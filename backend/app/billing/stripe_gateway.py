"""Stripe, behind the four calls the app makes, so nothing else (tests included)
needs Stripe itself. A webhook is only read once its signature checks out, and
a subscription's state is always fetched fresh rather than taken from the event
that mentioned it: Stripe's events can arrive late, twice, or out of order."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

import stripe

from app.billing.errors import BillingProviderError, InvalidWebhookError

logger = logging.getLogger(__name__)


@dataclass
class StripeEvent:
    id: str
    type: str
    object: dict[str, Any]


@dataclass
class StripeSubscription:
    id: str
    customer_id: str
    status: str
    price_id: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    metadata: dict[str, str] = field(default_factory=dict)


class BillingGateway(Protocol):
    async def checkout_url(
        self, *, price_id: str, workspace_id: str, plan: str, customer_id: str | None, email: str, success_url: str, cancel_url: str
    ) -> str: ...

    async def portal_url(self, *, customer_id: str, return_url: str) -> str: ...

    def event(self, payload: bytes, signature: str) -> StripeEvent: ...

    async def subscription(self, subscription_id: str) -> StripeSubscription: ...


def _id(value: Any) -> str:
    """An id Stripe sends either as itself or as the expanded object."""
    return value if isinstance(value, str) else (value or {}).get("id", "")


def subscription_from(data: dict[str, Any]) -> StripeSubscription:
    """A Stripe subscription as the app needs it. Since Stripe's API version
    2025-03-31 the billing period is kept on each item, not the subscription."""
    items = (data.get("items") or {}).get("data") or []
    first = items[0] if items else {}
    period_end = first.get("current_period_end") or data.get("current_period_end")
    return StripeSubscription(
        id=data["id"],
        customer_id=_id(data.get("customer")),
        status=data.get("status") or "",
        price_id=_id(first.get("price")) or None,
        current_period_end=datetime.fromtimestamp(period_end, timezone.utc) if isinstance(period_end, int) else None,
        cancel_at_period_end=bool(data.get("cancel_at_period_end")) or data.get("cancel_at") is not None,
        metadata={key: str(value) for key, value in (data.get("metadata") or {}).items()},
    )


def event_subscription_id(event: StripeEvent) -> str:
    return _id(event.object.get("subscription")) if event.object.get("object") == "checkout.session" else _id(event.object)


class StripeGateway:
    def __init__(self, secret_key: str, webhook_secret: str) -> None:
        self._client = stripe.StripeClient(secret_key, http_client=stripe.HTTPXClient())
        self._webhook_secret = webhook_secret

    async def checkout_url(
        self, *, price_id: str, workspace_id: str, plan: str, customer_id: str | None, email: str, success_url: str, cancel_url: str
    ) -> str:
        # The workspace goes on the checkout and on the subscription it creates, so
        # every later event about that subscription says whose it is.
        metadata = {"workspace_id": workspace_id, "plan": plan}
        params: dict[str, Any] = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "client_reference_id": workspace_id,
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if customer_id:
            params["customer"] = customer_id
        else:
            params["customer_email"] = email
        try:
            session = await self._client.v1.checkout.sessions.create_async(params=params)
        except stripe.StripeError as exc:
            logger.warning("Stripe checkout failed: %s", exc)
            raise BillingProviderError("The payment page couldn't be opened. Please try again in a moment.") from exc
        return session.url or ""

    async def portal_url(self, *, customer_id: str, return_url: str) -> str:
        try:
            session = await self._client.v1.billing_portal.sessions.create_async(params={"customer": customer_id, "return_url": return_url})
        except stripe.StripeError as exc:
            logger.warning("Stripe billing portal failed: %s", exc)
            raise BillingProviderError("The billing portal couldn't be opened. Please try again in a moment.") from exc
        return session.url

    def event(self, payload: bytes, signature: str) -> StripeEvent:
        if not self._webhook_secret:
            raise InvalidWebhookError("Stripe webhooks aren't set up on this server (STRIPE_WEBHOOK_SECRET).")
        try:
            event = self._client.construct_event(payload, signature, self._webhook_secret)
        except (stripe.SignatureVerificationError, ValueError) as exc:
            raise InvalidWebhookError("The webhook's signature doesn't match.") from exc
        return StripeEvent(id=event.id, type=event.type, object=event.data.object.to_dict())

    async def subscription(self, subscription_id: str) -> StripeSubscription:
        try:
            found = await self._client.v1.subscriptions.retrieve_async(subscription_id)
        except stripe.StripeError as exc:
            logger.warning("Could not fetch Stripe subscription %s: %s", subscription_id, exc)
            raise BillingProviderError("Stripe couldn't be reached.") from exc
        return subscription_from(found.to_dict())
