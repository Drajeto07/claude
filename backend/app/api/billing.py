"""The workspace's plan, its usage against the plan's limits, and subscribing
through Stripe (services/billing_service.py). Errors are mapped once, in
app/main.py."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentUser, DbSession, WorkspaceId, client_address
from app.audit import audit
from app.billing.errors import InvalidWebhookError
from app.billing.stripe_gateway import BillingGateway, StripeGateway
from app.config import get_settings
from app.services.billing_service import BillingOut, BillingService, CheckoutRequest, RedirectOut

router = APIRouter()


def get_billing_gateway() -> BillingGateway | None:
    """Stripe, when this server has a key for it."""
    settings = get_settings()
    secret_key = settings.stripe_secret_key.get_secret_value()
    return StripeGateway(secret_key, settings.stripe_webhook_secret.get_secret_value()) if secret_key else None


def get_billing_service(db: DbSession, gateway: Annotated[BillingGateway | None, Depends(get_billing_gateway)]) -> BillingService:
    return BillingService(db, gateway)


Billing = Annotated[BillingService, Depends(get_billing_service)]


@router.get("", response_model=BillingOut)
async def billing_summary(workspace_id: WorkspaceId, billing: Billing) -> BillingOut:
    """The plan the workspace is on, what it has used of it, and the plans there are."""
    return await billing.summary(workspace_id)


@router.post("/checkout", response_model=RedirectOut)
async def start_checkout(payload: CheckoutRequest, user: CurrentUser, workspace_id: WorkspaceId, billing: Billing) -> RedirectOut:
    """A Stripe Checkout page to subscribe to a paid plan; the plan changes once
    Stripe's webhook says the subscription exists, not when this answers."""
    return RedirectOut(url=await billing.checkout(workspace_id, user.email, payload.plan))


@router.post("/portal", response_model=RedirectOut)
async def open_billing_portal(workspace_id: WorkspaceId, billing: Billing) -> RedirectOut:
    """Stripe's billing portal, to change plan, update the card or cancel."""
    return RedirectOut(url=await billing.portal(workspace_id))


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, billing: Billing) -> dict[str, bool]:
    """Stripe's events. Not signed in -- the Stripe-Signature header is what makes
    one trusted, and one that fails the check is refused before it is read."""
    try:
        event = billing.verify(await request.body(), request.headers.get("stripe-signature", ""))
    except InvalidWebhookError:
        audit("billing.webhook_refused", ip=client_address(request))
        raise
    await billing.handle(event)
    return {"received": True}
