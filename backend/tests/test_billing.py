"""Billing (корекции.docx §35): the billing page's summary, Stripe Checkout and
the billing portal, and the webhooks that put a workspace on its plan. Webhooks
go through the real Stripe signature check; only Stripe's API itself is stood
in for, so nothing here needs the network or a Stripe account."""

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.api.billing import get_billing_gateway
from app.billing.plans import FREE, PLANS
from app.billing.stripe_gateway import StripeGateway, subscription_from
from app.config import get_settings
from app.db.models import Subscription, WorkspaceMember
from app.main import app

client = TestClient(app, base_url="https://testserver")
_WEBHOOK_SECRET = "whsec_test_only"
_PERIOD_END = 1_793_000_000  # 2026-10-26, as Stripe sends it


class OfflineStripe(StripeGateway):
    """The real gateway -- real webhook signature checks -- with Stripe's API
    answered from here."""

    def __init__(self) -> None:
        super().__init__("sk_test_offline", _WEBHOOK_SECRET)
        self.subscriptions: dict[str, dict] = {}
        self.checkouts: list[dict] = []
        self.portals: list[dict] = []

    async def checkout_url(self, **kwargs) -> str:
        self.checkouts.append(kwargs)
        return "https://checkout.stripe.test/c/session"

    async def portal_url(self, **kwargs) -> str:
        self.portals.append(kwargs)
        return "https://billing.stripe.test/p/session"

    async def subscription(self, subscription_id: str):
        return subscription_from(self.subscriptions[subscription_id])


@pytest.fixture
def stripe_setup(monkeypatch):
    settings = get_settings()
    for name, value in {
        "stripe_price_pro": "price_pro",
        "stripe_price_business": "price_business",
        "frontend_url": "https://app.example",
    }.items():
        monkeypatch.setattr(settings, name, value)
    gateway = OfflineStripe()
    app.dependency_overrides[get_billing_gateway] = lambda: gateway
    yield gateway
    app.dependency_overrides.pop(get_billing_gateway, None)


@pytest.fixture(autouse=True)
def signed_in(api_db):
    client.cookies.clear()
    assert client.post("/api/auth/register", json={"email": "billing@example.com", "password": "long enough password"}).status_code == 201
    yield
    client.cookies.clear()
    app.dependency_overrides.pop(get_billing_gateway, None)


def _workspace_id(api_db) -> str:
    with OrmSession(api_db) as session:
        return session.scalars(select(WorkspaceMember.workspace_id)).one()


def _subscription(api_db) -> Subscription | None:
    with OrmSession(api_db) as session:
        return session.scalars(select(Subscription)).one_or_none()


def _stripe_subscription(sub_id="sub_1", *, workspace_id=None, status="active", price="price_pro", cancel=False) -> dict:
    return {
        "id": sub_id,
        "object": "subscription",
        "customer": "cus_1",
        "status": status,
        "cancel_at_period_end": cancel,
        "cancel_at": None,
        "items": {
            "object": "list",
            "data": [{"id": "si_1", "object": "subscription_item", "current_period_end": _PERIOD_END, "price": {"id": price, "object": "price"}}],
        },
        "metadata": {"workspace_id": workspace_id, "plan": "pro"} if workspace_id else {},
    }


def _webhook(event_type: str, obj: dict, *, secret: str = _WEBHOOK_SECRET, tamper: bool = False):
    payload = json.dumps({"id": "evt_1", "object": "event", "type": event_type, "data": {"object": obj}}).encode()
    timestamp = int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    sent = payload.replace(b"price_pro", b"price_business") if tamper else payload
    return client.post(
        "/api/billing/webhook", content=sent, headers={"Stripe-Signature": f"t={timestamp},v1={signature}", "Content-Type": "application/json"}
    )


def _subscription_event(gateway: OfflineStripe, api_db, event_type="customer.subscription.updated", **changes):
    stripe_subscription = _stripe_subscription(workspace_id=_workspace_id(api_db), **changes)
    gateway.subscriptions[stripe_subscription["id"]] = stripe_subscription
    return _webhook(event_type, stripe_subscription)


def test_without_stripe_every_workspace_is_on_its_plan_and_nobody_can_subscribe(api_db):
    app.dependency_overrides[get_billing_gateway] = lambda: None
    client.post("/api/documents", json={"text": "# Billed\n\nA paragraph."})

    billing = client.get("/api/billing").json()

    assert (billing["plan"]["key"], billing["status"], billing["billingEnabled"], billing["canManageBilling"]) == (FREE, None, False, False)
    assert [plan["key"] for plan in billing["plans"]] == list(PLANS)
    assert not any(plan["available"] for plan in billing["plans"])
    free = PLANS[FREE].entitlements
    assert billing["usage"]["documents"] == {"used": 1, "limit": free.maxDocuments}
    assert billing["usage"]["aiOperations"] == {"used": 0, "limit": free.maxAiOperations}
    assert billing["usage"]["storageBytes"]["used"] > 0
    assert datetime.fromisoformat(billing["usagePeriodEnd"]).day == 1
    for response in (client.post("/api/billing/checkout", json={"plan": "pro"}), client.post("/api/billing/portal")):
        assert (response.status_code, response.json()["code"]) == (503, "billing_not_configured")


def test_checkout_opens_stripe_for_a_paid_plan_with_the_workspace_on_it(stripe_setup, api_db):
    response = client.post("/api/billing/checkout", json={"plan": "pro"})

    assert response.status_code == 200 and response.json() == {"url": "https://checkout.stripe.test/c/session"}
    assert stripe_setup.checkouts == [
        {
            "price_id": "price_pro",
            "workspace_id": _workspace_id(api_db),
            "plan": "pro",
            "customer_id": None,
            "email": "billing@example.com",
            "success_url": "https://app.example/settings/billing?checkout=success",
            "cancel_url": "https://app.example/settings/billing?checkout=cancelled",
        }
    ]
    assert _subscription(api_db) is None  # nothing changes until Stripe's webhook says so
    available = {plan["key"]: plan["available"] for plan in client.get("/api/billing").json()["plans"]}
    assert available == {FREE: False, "pro": True, "business": True}


def test_only_a_paid_plan_with_a_price_can_be_checked_out(stripe_setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_price_business", "")

    for plan in (FREE, "business", "enterprise"):
        response = client.post("/api/billing/checkout", json={"plan": plan})
        assert (response.status_code, response.json()["code"]) == (400, "plan_not_available"), plan
    assert stripe_setup.checkouts == []


def test_a_completed_checkout_puts_the_workspace_on_its_plan(stripe_setup, api_db):
    workspace_id = _workspace_id(api_db)
    stripe_setup.subscriptions["sub_1"] = _stripe_subscription(workspace_id=workspace_id)
    session = {"id": "cs_1", "object": "checkout.session", "mode": "subscription", "subscription": "sub_1", "client_reference_id": workspace_id}

    assert _webhook("checkout.session.completed", session).status_code == 200
    assert _webhook("checkout.session.completed", session).status_code == 200  # Stripe may send it twice

    billing = client.get("/api/billing").json()
    assert (billing["plan"]["key"], billing["status"], billing["cancelAtPeriodEnd"], billing["canManageBilling"]) == ("pro", "active", False, True)
    assert datetime.fromisoformat(billing["currentPeriodEnd"]) == datetime.fromtimestamp(_PERIOD_END, timezone.utc)
    assert billing["usage"]["documents"]["limit"] == PLANS["pro"].entitlements.maxDocuments
    with OrmSession(api_db) as db:
        assert db.scalar(select(func.count(Subscription.id))) == 1
    row = _subscription(api_db)
    assert (row.stripe_customer_id, row.stripe_subscription_id) == ("cus_1", "sub_1")


def test_a_subscribed_workspace_manages_its_plan_in_the_billing_portal(stripe_setup, api_db):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created")

    response = client.post("/api/billing/portal")

    assert response.json() == {"url": "https://billing.stripe.test/p/session"}
    assert stripe_setup.portals == [{"customer_id": "cus_1", "return_url": "https://app.example/settings/billing"}]
    again = client.post("/api/billing/checkout", json={"plan": "business"})
    assert (again.status_code, again.json()["code"]) == (409, "already_subscribed")


def test_the_billing_portal_needs_a_first_subscription(stripe_setup):
    response = client.post("/api/billing/portal")

    assert (response.status_code, response.json()["code"]) == (409, "no_billing_account")


def test_a_webhook_whose_signature_doesnt_match_is_refused_and_changes_nothing(stripe_setup, api_db):
    stripe_setup.subscriptions["sub_1"] = _stripe_subscription(workspace_id=_workspace_id(api_db))
    obj = stripe_setup.subscriptions["sub_1"]

    for response in (
        _webhook("customer.subscription.updated", obj, tamper=True),
        _webhook("customer.subscription.updated", obj, secret="whsec_someone_else"),
        client.post("/api/billing/webhook", content=json.dumps({"type": "customer.subscription.updated"})),
    ):
        assert (response.status_code, response.json()["code"]) == (400, "invalid_webhook")
    assert _subscription(api_db) is None


def test_plan_changes_and_cancellation_follow_the_subscription(stripe_setup, api_db):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created")
    _subscription_event(stripe_setup, api_db, price="price_business")
    assert client.get("/api/billing").json()["plan"]["key"] == "business"

    _subscription_event(stripe_setup, api_db, price="price_business", cancel=True)
    billing = client.get("/api/billing").json()
    assert (billing["plan"]["key"], billing["cancelAtPeriodEnd"]) == ("business", True)  # until the period ends

    _subscription_event(stripe_setup, api_db, "customer.subscription.deleted", price="price_business", status="canceled")
    billing = client.get("/api/billing").json()
    assert (billing["plan"]["key"], billing["status"]) == (FREE, "canceled")
    assert client.post("/api/billing/checkout", json={"plan": "pro"}).status_code == 200  # can subscribe again


def test_late_news_about_a_replaced_subscription_is_ignored(stripe_setup, api_db):
    workspace_id = _workspace_id(api_db)
    stripe_setup.subscriptions["sub_new"] = _stripe_subscription("sub_new", workspace_id=workspace_id)
    stripe_setup.subscriptions["sub_old"] = _stripe_subscription("sub_old", workspace_id=workspace_id, status="canceled")

    _webhook("customer.subscription.created", stripe_setup.subscriptions["sub_new"])
    _webhook("customer.subscription.deleted", stripe_setup.subscriptions["sub_old"])

    row = _subscription(api_db)
    assert (row.stripe_subscription_id, row.status, row.plan) == ("sub_new", "active", "pro")


def test_the_subscription_is_read_from_stripe_not_from_the_event(stripe_setup, api_db):
    # The event is stale ("active"); Stripe's own answer now is "past_due".
    stale = _stripe_subscription(workspace_id=_workspace_id(api_db))
    stripe_setup.subscriptions["sub_1"] = {**stale, "status": "past_due"}

    _webhook("customer.subscription.updated", stale)

    assert client.get("/api/billing").json()["status"] == "past_due"


def test_events_about_nothing_here_are_acknowledged_and_ignored(stripe_setup, api_db):
    stripe_setup.subscriptions["sub_x"] = _stripe_subscription("sub_x", workspace_id="no-such-workspace")

    for response in (
        _webhook("invoice.paid", {"id": "in_1", "object": "invoice"}),
        _webhook("checkout.session.completed", {"id": "cs_1", "object": "checkout.session", "mode": "payment"}),
        _webhook("customer.subscription.updated", stripe_setup.subscriptions["sub_x"]),
    ):
        assert response.status_code == 200 and response.json() == {"received": True}
    assert _subscription(api_db) is None


def test_a_subscription_made_in_stripes_dashboard_is_found_by_its_customer(stripe_setup, api_db):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created")
    no_metadata = {**_stripe_subscription("sub_2", price="price_business"), "metadata": {}}
    stripe_setup.subscriptions["sub_2"] = no_metadata

    _webhook("customer.subscription.created", no_metadata)

    row = _subscription(api_db)
    assert (row.stripe_subscription_id, row.plan) == ("sub_2", "business")


def test_subscription_from_reads_the_period_from_the_items_and_expanded_ids():
    expanded = {
        "id": "sub_9",
        "customer": {"id": "cus_9", "object": "customer"},
        "status": "trialing",
        "cancel_at": 1_800_000_000,
        "items": {"data": [{"current_period_end": _PERIOD_END, "price": {"id": "price_pro"}}]},
    }
    legacy = {"id": "sub_8", "customer": "cus_8", "status": "active", "current_period_end": _PERIOD_END, "items": {"data": []}}

    parsed = subscription_from(expanded)
    assert (parsed.customer_id, parsed.price_id, parsed.cancel_at_period_end, parsed.metadata) == ("cus_9", "price_pro", True, {})
    assert parsed.current_period_end == datetime.fromtimestamp(_PERIOD_END, timezone.utc)
    assert (subscription_from(legacy).current_period_end, subscription_from(legacy).price_id) == (parsed.current_period_end, None)
