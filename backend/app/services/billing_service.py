"""Subscriptions (корекции.docx §35): what the billing page shows, Stripe
Checkout to subscribe, Stripe's billing portal to change plan, pay or cancel,
and the webhooks that keep each workspace's subscription row -- the one thing
its entitlements are read from -- in step with Stripe."""

import logging
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.billing.errors import AlreadySubscribedError, BillingNotConfiguredError, NoBillingAccountError, PlanNotAvailableError
from app.billing.plans import FREE, PLANS, Entitlements
from app.billing.stripe_gateway import BillingGateway, StripeEvent, StripeSubscription, event_subscription_id, invoice_subscription_id
from app.config import get_settings
from app.db.models import Subscription, Workspace
from app.models.base import ApiModel
from app.services.entitlements_service import ENTITLED_STATUSES, EntitlementsService, effective, hold_workspace
from app.services.usage_service import month_of, storage_bytes

logger = logging.getLogger(__name__)

# The events that can change a subscription; any other is acknowledged and ignored.
SUBSCRIPTION_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "customer.subscription.resumed",
    # A delayed payment method (a bank debit) settling or failing after the checkout.
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
}
# Recorded in the audit log for the owner to act on in Stripe; no plan changes with them.
_NOTED_EVENTS = {"invoice.payment_failed", "charge.refunded", "charge.dispute.created", "charge.dispute.closed"}
_MB = 1024 * 1024


class UsageLimit(ApiModel):
    used: int
    # None = unlimited.
    limit: int | None


class PlanUsageOut(ApiModel):
    documents: UsageLimit
    templates: UsageLimit
    # This calendar month (UTC): they renew when it ends (usagePeriodEnd).
    aiOperations: UsageLimit
    storageBytes: UsageLimit


class PlanOut(ApiModel):
    key: str
    name: str
    priceLabel: str | None
    entitlements: Entitlements
    # Can be subscribed to from here: Stripe and the plan's price are set up.
    available: bool


class BillingOut(ApiModel):
    plan: PlanOut
    # The subscription's status as Stripe says it ("active", "past_due", ...);
    # None without a subscription.
    status: str | None
    currentPeriodEnd: datetime | None
    cancelAtPeriodEnd: bool
    usage: PlanUsageOut
    usagePeriodEnd: datetime
    plans: list[PlanOut]
    # Stripe is set up on this server: plans can be subscribed to.
    billingEnabled: bool
    # There's a Stripe customer, so the billing portal has something to show.
    canManageBilling: bool


class CheckoutRequest(ApiModel):
    plan: str


class RedirectOut(ApiModel):
    """Where to send the browser next (a Stripe-hosted page)."""

    url: str


def _utc(at: datetime | None) -> datetime | None:
    """In UTC, whichever database it came from (SQLite drops the zone Postgres keeps)."""
    return at.replace(tzinfo=timezone.utc) if at is not None and at.tzinfo is None else at


def _note(event: StripeEvent) -> None:
    obj = event.object
    if event.type == "invoice.payment_failed":
        audit("billing.payment_failed", invoice=obj.get("id"), subscription=invoice_subscription_id(obj) or None, attempt=obj.get("attempt_count"))
    elif event.type == "charge.refunded":
        audit("billing.charge_refunded", charge=obj.get("id"), amount=obj.get("amount_refunded"), currency=obj.get("currency"))
    else:
        audit("billing.dispute", dispute=obj.get("id"), charge=obj.get("charge"), status=obj.get("status"), reason=obj.get("reason"), amount=obj.get("amount"))


def price_ids() -> dict[str, str]:
    """Each paid plan's Stripe price (STRIPE_PRICE_<PLAN KEY>), where one is set."""
    settings = get_settings()
    return {key: price for key in PLANS if key != FREE and (price := getattr(settings, f"stripe_price_{key}", ""))}


class BillingService:
    def __init__(self, session: AsyncSession, gateway: BillingGateway | None) -> None:
        self._session = session
        self._gateway = gateway
        self._plans = EntitlementsService(session)

    def _require_gateway(self) -> BillingGateway:
        if self._gateway is None:
            raise BillingNotConfiguredError("Paid plans aren't available yet.")
        return self._gateway

    def _plan_out(self, key: str) -> PlanOut:
        plan = PLANS[key]
        return PlanOut(
            key=key,
            name=plan.name,
            priceLabel=plan.priceLabel,
            entitlements=effective(plan.entitlements),
            available=self._gateway is not None and key in price_ids(),
        )

    async def summary(self, workspace_id: str) -> BillingOut:
        subscription = await self._plans.subscription(workspace_id)
        plan = await self._plans.plan(workspace_id)
        entitlements = effective(plan.entitlements)
        storage_limit = entitlements.maxStorageMb * _MB if entitlements.maxStorageMb is not None else None
        return BillingOut(
            plan=self._plan_out(plan.key),
            status=subscription.status if subscription else None,
            currentPeriodEnd=_utc(subscription.current_period_end) if subscription else None,
            cancelAtPeriodEnd=bool(subscription and subscription.cancel_at_period_end),
            usage=PlanUsageOut(
                documents=UsageLimit(used=await self._plans.documents(workspace_id), limit=entitlements.maxDocuments),
                templates=UsageLimit(used=await self._plans.templates(workspace_id), limit=entitlements.maxTemplates),
                aiOperations=UsageLimit(used=await self._plans.ai_operations_this_month(workspace_id), limit=entitlements.maxAiOperations),
                storageBytes=UsageLimit(used=await storage_bytes(self._session, workspace_id), limit=storage_limit),
            ),
            usagePeriodEnd=month_of(datetime.now(timezone.utc))[1],
            plans=[self._plan_out(key) for key in PLANS],
            billingEnabled=self._gateway is not None,
            canManageBilling=self._gateway is not None and bool(subscription and subscription.stripe_customer_id),
        )

    async def checkout(self, workspace_id: str, email: str, plan_key: str) -> str:
        """A Stripe Checkout page for subscribing to a paid plan."""
        gateway = self._require_gateway()
        price = price_ids().get(plan_key)
        if price is None:
            raise PlanNotAvailableError("That plan can't be subscribed to.")
        subscription = await self._plans.subscription(workspace_id)
        if subscription is not None and subscription.stripe_subscription_id and subscription.status in ENTITLED_STATUSES:
            raise AlreadySubscribedError("You already have a subscription: change your plan in the billing portal.")
        frontend = get_settings().frontend_url.rstrip("/")
        audit("billing.checkout_started", workspace_id=workspace_id, plan=plan_key)
        return await gateway.checkout_url(
            price_id=price,
            workspace_id=workspace_id,
            plan=plan_key,
            customer_id=subscription.stripe_customer_id if subscription else None,
            email=email,
            success_url=f"{frontend}/settings/billing?checkout=success",
            cancel_url=f"{frontend}/settings/billing?checkout=cancelled",
        )

    async def portal(self, workspace_id: str) -> str:
        """Stripe's billing portal: change plan, update the card, see invoices, cancel."""
        gateway = self._require_gateway()
        subscription = await self._plans.subscription(workspace_id)
        if subscription is None or not subscription.stripe_customer_id:
            raise NoBillingAccountError("There's no billing account yet: it's made with your first subscription.")
        audit("billing.portal_opened", workspace_id=workspace_id)
        return await gateway.portal_url(
            customer_id=subscription.stripe_customer_id, return_url=f"{get_settings().frontend_url.rstrip('/')}/settings/billing"
        )

    def verify(self, payload: bytes, signature: str) -> StripeEvent:
        return self._require_gateway().event(payload, signature)

    async def handle(self, event: StripeEvent) -> None:
        """A (verified) webhook. A subscription's event has the subscription it is
        about fetched from Stripe as it is now and written to its workspace's row, so
        what the row says never depends on the order events arrive in, and one
        handled again (Stripe repeats events) changes nothing. Payment trouble,
        refunds and disputes are only recorded: whether one ends a subscription is
        decided in Stripe, and arrives as the subscription's own event."""
        if event.type in _NOTED_EVENTS:
            _note(event)
            return
        if event.type not in SUBSCRIPTION_EVENTS:
            return
        is_checkout = event.type.startswith("checkout.session.")
        if is_checkout and event.object.get("mode") != "subscription":
            return
        subscription_id = event_subscription_id(event)
        if not subscription_id:
            return
        hint = event.object.get("client_reference_id") if is_checkout else None
        read_at = datetime.now(timezone.utc)  # before the read: what it saw is at least this fresh
        found = await self._require_gateway().subscription(subscription_id)
        if found is None:
            return  # nothing to write, and a retry would find the same
        await self.sync(found, workspace_hint=hint, read_at=read_at)

    async def sync(
        self, stripe_subscription: StripeSubscription, *, workspace_hint: str | None = None, read_at: datetime | None = None
    ) -> Subscription | None:
        """Writes a subscription, as Stripe said it was at `read_at`, to its
        workspace's row -- unless the row already holds a later read: webhooks
        handled at the same moment can write in either order."""
        read_at = read_at or datetime.now(timezone.utc)
        workspace_id = stripe_subscription.metadata.get("workspace_id") or workspace_hint
        if not workspace_id:
            # Made outside this app's checkout (e.g. in Stripe's dashboard) for a customer it knows.
            known = await self._known_row(stripe_subscription)
            workspace_id = known.workspace_id if known else None
        if not workspace_id:
            logger.warning("Stripe subscription %s belongs to no workspace here; ignored", stripe_subscription.id)
            return None
        # One webhook at a time per workspace: two first events (the checkout's and the
        # subscription's) can't both make the row, and the later read is the one kept.
        await hold_workspace(self._session, workspace_id)
        if await self._session.get(Workspace, workspace_id) is None:
            logger.warning("Stripe subscription %s belongs to no workspace here; ignored", stripe_subscription.id)
            await self._session.commit()  # nothing changed: ends the hold
            return None
        row = await self._session.scalar(
            select(Subscription).where(Subscription.workspace_id == workspace_id).execution_options(populate_existing=True)
        )
        if row is None:
            row = Subscription(workspace_id=workspace_id, plan=FREE, status=stripe_subscription.status)
            self._session.add(row)
        elif row.stripe_synced_at is not None and _utc(row.stripe_synced_at) > read_at:
            await self._session.commit()  # nothing changed: ends the hold
            return row  # a later read of Stripe is already stored
        replaced = row.stripe_subscription_id not in (None, stripe_subscription.id)
        if replaced and stripe_subscription.status not in ENTITLED_STATUSES:
            await self._session.commit()  # nothing changed: ends the hold
            return row  # news about an older subscription the workspace has since replaced
        if replaced and row.status in ENTITLED_STATUSES and stripe_subscription.status in ENTITLED_STATUSES:
            # Two subscriptions at once (two checkouts open together): both bill, and the row can follow only one.
            logger.warning("Workspace %s has two live Stripe subscriptions: %s and %s", workspace_id, row.stripe_subscription_id, stripe_subscription.id)
            audit("billing.duplicate_subscription", workspace_id=workspace_id, subscription=stripe_subscription.id, replaced=row.stripe_subscription_id)
        row.plan = self._plan_of(stripe_subscription) or row.plan
        row.status = stripe_subscription.status
        row.stripe_customer_id = stripe_subscription.customer_id or row.stripe_customer_id
        row.stripe_subscription_id = stripe_subscription.id
        row.current_period_end = stripe_subscription.current_period_end
        row.cancel_at_period_end = stripe_subscription.cancel_at_period_end
        row.stripe_synced_at = read_at
        await self._session.commit()
        audit("billing.subscription_synced", workspace_id=row.workspace_id, plan=row.plan, status=row.status, subscription=stripe_subscription.id)
        return row

    async def _known_row(self, stripe_subscription: StripeSubscription) -> Subscription | None:
        known = [Subscription.stripe_subscription_id == stripe_subscription.id]
        if stripe_subscription.customer_id:
            known.append(Subscription.stripe_customer_id == stripe_subscription.customer_id)
        return await self._session.scalar(select(Subscription).where(or_(*known)).limit(1))

    @staticmethod
    def _plan_of(stripe_subscription: StripeSubscription) -> str | None:
        by_price = {price: key for key, price in price_ids().items()}
        if stripe_subscription.price_id in by_price:
            return by_price[stripe_subscription.price_id]
        logger.warning("Stripe price %s is no plan's (STRIPE_PRICE_*); going by the subscription's metadata", stripe_subscription.price_id)
        named = stripe_subscription.metadata.get("plan")
        return named if named in PLANS else None
