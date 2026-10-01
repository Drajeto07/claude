"""Billing (корекции.docx §35): the billing page's summary, Stripe Checkout and
the billing portal, and the webhooks that put a workspace on its plan. Webhooks
go through the real Stripe signature check; only Stripe's API itself is stood
in for, so nothing here needs the network or a Stripe account."""

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.api.billing import get_billing_gateway
from app.billing.errors import BillingProviderError
from app.billing.plans import FREE, PLANS
from app.billing.stripe_gateway import StripeGateway, subscription_from
from app.config import get_settings
from app.db.models import Subscription, Workspace, WorkspaceMember
from app.main import app
from app.services.billing_service import BillingService
from app.services.entitlements_service import EntitlementsService

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
        self.fetched: list[str] = []
        self.unreachable = False

    async def checkout_url(self, **kwargs) -> str:
        self.checkouts.append(kwargs)
        return "https://checkout.stripe.test/c/session"

    async def portal_url(self, **kwargs) -> str:
        self.portals.append(kwargs)
        return "https://billing.stripe.test/p/session"

    async def subscription(self, subscription_id: str):
        self.fetched.append(subscription_id)
        if self.unreachable:
            raise BillingProviderError("Stripe couldn't be reached.")
        found = self.subscriptions.get(subscription_id)
        return subscription_from(found) if found else None  # None: Stripe has no such subscription


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
    assert client.post("/api/v1/auth/register", json={"email": "billing@example.com", "password": "long enough password"}).status_code == 201
    yield
    client.cookies.clear()
    app.dependency_overrides.pop(get_billing_gateway, None)


def _workspace_id(api_db) -> str:
    with OrmSession(api_db) as session:
        return session.scalars(select(WorkspaceMember.workspace_id)).one()


def _subscription(api_db) -> Subscription | None:
    with OrmSession(api_db) as session:
        return session.scalars(select(Subscription)).one_or_none()


def _stripe_subscription(sub_id="sub_1", *, workspace_id=None, status="active", price="price_pro", cancel=False, period_end=_PERIOD_END, cancel_at=None) -> dict:
    return {
        "id": sub_id,
        "object": "subscription",
        "customer": "cus_1",
        "status": status,
        "cancel_at_period_end": cancel,
        "cancel_at": cancel_at,
        "items": {
            "object": "list",
            "data": [{"id": "si_1", "object": "subscription_item", "current_period_end": period_end, "price": {"id": price, "object": "price"}}],
        },
        "metadata": {"workspace_id": workspace_id, "plan": "pro"} if workspace_id else {},
    }


def _webhook(event_type: str, obj: dict, *, secret: str = _WEBHOOK_SECRET, tamper: bool = False, event_id: str = "evt_1"):
    payload = json.dumps({"id": event_id, "object": "event", "type": event_type, "data": {"object": obj}}).encode()
    return _send(payload, secret=secret, tamper=tamper)


def _send(payload: bytes, *, secret: str = _WEBHOOK_SECRET, tamper: bool = False, age: int = 0):
    """A webhook body signed the way Stripe signs it (`age` seconds ago)."""
    timestamp = int(time.time()) - age
    signature = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    sent = payload.replace(b"price_pro", b"price_business") if tamper else payload
    return client.post(
        "/api/v1/billing/webhook", content=sent, headers={"Stripe-Signature": f"t={timestamp},v1={signature}", "Content-Type": "application/json"}
    )


def _subscription_event(gateway: OfflineStripe, api_db, event_type="customer.subscription.updated", *, event_id="evt_1", **changes):
    stripe_subscription = _stripe_subscription(workspace_id=_workspace_id(api_db), **changes)
    gateway.subscriptions[stripe_subscription["id"]] = stripe_subscription
    return _webhook(event_type, stripe_subscription, event_id=event_id)


def test_without_stripe_every_workspace_is_on_its_plan_and_nobody_can_subscribe(api_db):
    app.dependency_overrides[get_billing_gateway] = lambda: None
    client.post("/api/v1/documents", json={"text": "# Billed\n\nA paragraph."})

    billing = client.get("/api/v1/billing").json()

    assert (billing["plan"]["key"], billing["status"], billing["billingEnabled"], billing["canManageBilling"]) == (FREE, None, False, False)
    assert [plan["key"] for plan in billing["plans"]] == list(PLANS)
    assert not any(plan["available"] for plan in billing["plans"])
    free = PLANS[FREE].entitlements
    assert billing["usage"]["documents"] == {"used": 1, "limit": free.maxDocuments}
    assert billing["usage"]["aiOperations"] == {"used": 0, "limit": free.maxAiOperations}
    assert billing["usage"]["storageBytes"]["used"] > 0
    assert datetime.fromisoformat(billing["usagePeriodEnd"]).day == 1
    for response in (client.post("/api/v1/billing/checkout", json={"plan": "pro"}), client.post("/api/v1/billing/portal")):
        assert (response.status_code, response.json()["code"]) == (503, "billing_not_configured")


def test_checkout_opens_stripe_for_a_paid_plan_with_the_workspace_on_it(stripe_setup, api_db):
    response = client.post("/api/v1/billing/checkout", json={"plan": "pro"})

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
    available = {plan["key"]: plan["available"] for plan in client.get("/api/v1/billing").json()["plans"]}
    assert available == {FREE: False, "pro": True, "business": True}


def test_only_a_paid_plan_with_a_price_can_be_checked_out(stripe_setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "stripe_price_business", "")

    for plan in (FREE, "business", "enterprise"):
        response = client.post("/api/v1/billing/checkout", json={"plan": plan})
        assert (response.status_code, response.json()["code"]) == (400, "plan_not_available"), plan
    assert stripe_setup.checkouts == []


def test_a_completed_checkout_puts_the_workspace_on_its_plan(stripe_setup, api_db):
    workspace_id = _workspace_id(api_db)
    stripe_setup.subscriptions["sub_1"] = _stripe_subscription(workspace_id=workspace_id)
    session = {"id": "cs_1", "object": "checkout.session", "mode": "subscription", "subscription": "sub_1", "client_reference_id": workspace_id}

    assert _webhook("checkout.session.completed", session).status_code == 200
    assert _webhook("checkout.session.completed", session).status_code == 200  # Stripe may send it twice

    billing = client.get("/api/v1/billing").json()
    assert (billing["plan"]["key"], billing["status"], billing["cancelAtPeriodEnd"], billing["canManageBilling"]) == ("pro", "active", False, True)
    assert datetime.fromisoformat(billing["currentPeriodEnd"]) == datetime.fromtimestamp(_PERIOD_END, timezone.utc)
    assert billing["usage"]["documents"]["limit"] == PLANS["pro"].entitlements.maxDocuments
    with OrmSession(api_db) as db:
        assert db.scalar(select(func.count(Subscription.id))) == 1
    row = _subscription(api_db)
    assert (row.stripe_customer_id, row.stripe_subscription_id) == ("cus_1", "sub_1")


def test_a_subscribed_workspace_manages_its_plan_in_the_billing_portal(stripe_setup, api_db):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created")

    response = client.post("/api/v1/billing/portal")

    assert response.json() == {"url": "https://billing.stripe.test/p/session"}
    assert stripe_setup.portals == [{"customer_id": "cus_1", "return_url": "https://app.example/settings/billing"}]
    again = client.post("/api/v1/billing/checkout", json={"plan": "business"})
    assert (again.status_code, again.json()["code"]) == (409, "already_subscribed")


def test_the_billing_portal_needs_a_first_subscription(stripe_setup):
    response = client.post("/api/v1/billing/portal")

    assert (response.status_code, response.json()["code"]) == (409, "no_billing_account")


def test_a_webhook_whose_signature_doesnt_match_is_refused_and_changes_nothing(stripe_setup, api_db):
    stripe_setup.subscriptions["sub_1"] = _stripe_subscription(workspace_id=_workspace_id(api_db))
    obj = stripe_setup.subscriptions["sub_1"]

    for response in (
        _webhook("customer.subscription.updated", obj, tamper=True),
        _webhook("customer.subscription.updated", obj, secret="whsec_someone_else"),
        client.post("/api/v1/billing/webhook", content=json.dumps({"type": "customer.subscription.updated"})),
    ):
        assert (response.status_code, response.json()["code"]) == (400, "invalid_webhook")
    assert _subscription(api_db) is None


def test_plan_changes_and_cancellation_follow_the_subscription(stripe_setup, api_db):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created")
    _subscription_event(stripe_setup, api_db, price="price_business")
    assert client.get("/api/v1/billing").json()["plan"]["key"] == "business"

    _subscription_event(stripe_setup, api_db, price="price_business", cancel=True)
    billing = client.get("/api/v1/billing").json()
    assert (billing["plan"]["key"], billing["cancelAtPeriodEnd"]) == ("business", True)  # until the period ends

    _subscription_event(stripe_setup, api_db, "customer.subscription.deleted", price="price_business", status="canceled")
    billing = client.get("/api/v1/billing").json()
    assert (billing["plan"]["key"], billing["status"]) == (FREE, "canceled")
    assert client.post("/api/v1/billing/checkout", json={"plan": "pro"}).status_code == 200  # can subscribe again


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

    assert client.get("/api/v1/billing").json()["status"] == "past_due"


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


# -- Every flow, event by event (docs/billing/README.md lists them) -------------------------


def _summary() -> tuple[str, str | None, bool]:
    billing = client.get("/api/v1/billing").json()
    return billing["plan"]["key"], billing["status"], billing["cancelAtPeriodEnd"]


def _checkout_completed(api_db, sub_id="sub_1", *, event_id="evt_checkout", event_type="checkout.session.completed"):
    session = {
        "id": "cs_1",
        "object": "checkout.session",
        "mode": "subscription",
        "subscription": sub_id,
        "client_reference_id": _workspace_id(api_db),
    }
    return _webhook(event_type, session, event_id=event_id)


@pytest.fixture
def audit_log(caplog):
    caplog.set_level(logging.INFO, logger="app")
    return caplog


def _audited(caplog, event: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if getattr(record, "event", None) == event]


def test_a_downgrade_in_the_portal_changes_the_limits_and_deletes_nothing(stripe_setup, api_db, monkeypatch):
    for index in range(2):
        client.post("/api/v1/documents", json={"text": f"# Kept {index}\n\nA paragraph."})
    _subscription_event(stripe_setup, api_db, "customer.subscription.created", price="price_business")
    assert client.get("/api/v1/billing").json()["usage"]["documents"] == {"used": 2, "limit": None}

    _subscription_event(stripe_setup, api_db, price="price_pro")  # business -> pro, in the portal
    assert client.get("/api/v1/billing").json()["usage"]["documents"] == {"used": 2, "limit": PLANS["pro"].entitlements.maxDocuments}

    # Back to free, which allows fewer documents than there are: they all stay, and no new one is made.
    free = PLANS[FREE]
    monkeypatch.setitem(PLANS, FREE, free.model_copy(update={"entitlements": free.entitlements.model_copy(update={"maxDocuments": 1})}))
    _subscription_event(stripe_setup, api_db, "customer.subscription.deleted", status="canceled")
    assert client.get("/api/v1/billing").json()["usage"]["documents"] == {"used": 2, "limit": 1}
    assert len(client.get("/api/v1/documents").json()) == 2
    refused = client.post("/api/v1/documents", json={"text": "# One too many"})
    assert (refused.status_code, refused.json()["code"]) == (402, "plan_limit")


def test_cancelling_at_the_period_end_then_changing_ones_mind(stripe_setup, api_db):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created")

    _subscription_event(stripe_setup, api_db, cancel=True)
    assert _summary() == ("pro", "active", True)

    _subscription_event(stripe_setup, api_db, cancel=False)  # "Don't cancel" in the portal
    assert _summary() == ("pro", "active", False)

    # The portal can also end a plan on a date it names, not at the period's end.
    _subscription_event(stripe_setup, api_db, cancel_at=_PERIOD_END)
    assert _summary() == ("pro", "active", True)


def test_a_renewal_moves_the_period_and_keeps_the_plan(stripe_setup, api_db):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created")
    renewed = _PERIOD_END + 30 * 86400

    _subscription_event(stripe_setup, api_db, period_end=renewed)  # Stripe sends it when the new period starts
    paid = _webhook("invoice.paid", {"id": "in_1", "object": "invoice", "subscription": "sub_1"}, event_id="evt_paid")

    assert paid.status_code == 200 and _summary() == ("pro", "active", False)
    assert client.get("/api/v1/billing").json()["currentPeriodEnd"] is not None
    assert _subscription(api_db).current_period_end.replace(tzinfo=timezone.utc) == datetime.fromtimestamp(renewed, timezone.utc)


def test_a_failed_payment_runs_through_past_due_and_unpaid_and_back_to_active(stripe_setup, api_db, audit_log):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created")

    failed = {"id": "in_1", "object": "invoice", "subscription": "sub_1", "customer": "cus_1", "attempt_count": 1}
    assert _webhook("invoice.payment_failed", failed, event_id="evt_failed").status_code == 200
    _subscription_event(stripe_setup, api_db, status="past_due", event_id="evt_past_due")
    assert _summary()[:2] == ("pro", "past_due")  # Stripe is still retrying the card: the plan stays
    assert client.post("/api/v1/billing/checkout", json={"plan": "business"}).json()["code"] == "already_subscribed"

    _subscription_event(stripe_setup, api_db, status="unpaid", event_id="evt_unpaid")
    assert _summary()[:2] == (FREE, "unpaid")  # the retries ran out: back on the free plan

    _subscription_event(stripe_setup, api_db, status="active", event_id="evt_paid_again")  # the card was fixed and the invoice paid
    assert _summary()[:2] == ("pro", "active")
    assert [record.status for record in _audited(audit_log, "billing.subscription_synced")] == ["active", "past_due", "unpaid", "active"]
    [failure] = _audited(audit_log, "billing.payment_failed")
    assert (failure.subscription, failure.attempt) == ("sub_1", 1)


def test_a_failed_payment_names_its_subscription_in_either_api_version(stripe_setup, api_db, audit_log):
    new_style = {"id": "in_2", "object": "invoice", "parent": {"subscription_details": {"subscription": "sub_1"}}, "attempt_count": 2}

    assert _webhook("invoice.payment_failed", new_style, event_id="evt_failed").status_code == 200

    [failure] = _audited(audit_log, "billing.payment_failed")
    assert (failure.invoice, failure.subscription, failure.attempt) == ("in_2", "sub_1", 2)


def test_a_workspace_with_an_unpaid_subscription_can_subscribe_again(stripe_setup, api_db):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created", status="unpaid")

    response = client.post("/api/v1/billing/checkout", json={"plan": "pro"})

    assert response.status_code == 200
    assert stripe_setup.checkouts[0]["customer_id"] == "cus_1"  # on the customer it already has


def test_a_paused_subscription_gives_no_plan_until_it_is_resumed(stripe_setup, api_db):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created")

    _subscription_event(stripe_setup, api_db, "customer.subscription.paused", status="paused")
    assert _summary()[:2] == (FREE, "paused")
    _subscription_event(stripe_setup, api_db, "customer.subscription.resumed", status="active")
    assert _summary()[:2] == ("pro", "active")


def test_a_checkout_that_is_not_paid_yet_gives_no_plan(stripe_setup, api_db):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created", status="incomplete")
    assert _summary()[:2] == (FREE, "incomplete")  # 3-D Secure not finished
    assert client.post("/api/v1/billing/checkout", json={"plan": "pro"}).status_code == 200  # can try again

    _subscription_event(stripe_setup, api_db, status="incomplete_expired")
    assert _summary()[:2] == (FREE, "incomplete_expired")


def test_a_delayed_payment_method_settling_after_the_checkout_gives_the_plan(stripe_setup, api_db):
    stripe_setup.subscriptions["sub_1"] = _stripe_subscription(workspace_id=_workspace_id(api_db), status="incomplete")
    assert _checkout_completed(api_db).status_code == 200
    assert _summary()[:2] == (FREE, "incomplete")

    stripe_setup.subscriptions["sub_1"] = _stripe_subscription(workspace_id=_workspace_id(api_db))  # the debit went through
    assert _checkout_completed(api_db, event_id="evt_settled", event_type="checkout.session.async_payment_succeeded").status_code == 200

    assert _summary()[:2] == ("pro", "active")


def test_a_refund_or_a_dispute_is_recorded_and_changes_no_plan(stripe_setup, api_db, audit_log):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created")
    refund = {"id": "ch_1", "object": "charge", "customer": "cus_1", "amount_refunded": 900, "currency": "eur", "refunded": True}
    dispute = {"id": "dp_1", "object": "dispute", "charge": "ch_1", "amount": 900, "currency": "eur", "reason": "fraudulent", "status": "needs_response"}

    for event_type, obj in (("charge.refunded", refund), ("charge.dispute.created", dispute), ("charge.dispute.closed", {**dispute, "status": "lost"})):
        assert _webhook(event_type, obj, event_id=f"evt_{event_type}").status_code == 200

    assert _summary() == ("pro", "active", False)  # ending the subscription is the owner's call, in Stripe
    assert [record.charge for record in _audited(audit_log, "billing.charge_refunded")] == ["ch_1"]
    assert [(record.dispute, record.status) for record in _audited(audit_log, "billing.dispute")] == [("dp_1", "needs_response"), ("dp_1", "lost")]

    # ... and once the owner ends the subscription over it, the workspace is on the free plan.
    _subscription_event(stripe_setup, api_db, "customer.subscription.deleted", status="canceled", event_id="evt_ended")
    assert _summary()[:2] == (FREE, "canceled")


def test_a_price_that_is_no_plans_goes_by_the_subscriptions_plan_or_changes_nothing(stripe_setup, api_db):
    _subscription_event(stripe_setup, api_db, "customer.subscription.created", price="price_business")
    unknown = {**_stripe_subscription(workspace_id=_workspace_id(api_db), price="price_new_unknown"), "metadata": {"workspace_id": _workspace_id(api_db), "plan": "pro"}}
    stripe_setup.subscriptions["sub_1"] = unknown
    _webhook("customer.subscription.updated", unknown, event_id="evt_2")
    assert _summary()[0] == "pro"  # its metadata says pro

    nameless = {**unknown, "metadata": {"workspace_id": _workspace_id(api_db)}}
    stripe_setup.subscriptions["sub_1"] = nameless
    _webhook("customer.subscription.updated", nameless, event_id="evt_3")
    assert _summary()[0] == "pro"  # nothing says which: the plan it had stays


# -- Webhooks that arrive twice, late or out of order ---------------------------------------


def test_the_same_event_delivered_twice_changes_nothing_the_second_time(stripe_setup, api_db):
    first = _subscription_event(stripe_setup, api_db, "customer.subscription.created", event_id="evt_same")
    row = _subscription(api_db)
    again = _subscription_event(stripe_setup, api_db, "customer.subscription.created", event_id="evt_same")

    assert first.status_code == again.status_code == 200
    after = _subscription(api_db)
    assert (after.id, after.plan, after.status, after.stripe_subscription_id, after.current_period_end) == (
        row.id,
        row.plan,
        row.status,
        row.stripe_subscription_id,
        row.current_period_end,
    )


def test_a_subscription_update_before_the_checkout_completed_event_is_the_same_as_after(stripe_setup, api_db):
    stripe_setup.subscriptions["sub_1"] = _stripe_subscription(workspace_id=_workspace_id(api_db))

    assert _webhook("customer.subscription.updated", stripe_setup.subscriptions["sub_1"], event_id="evt_2").status_code == 200
    assert _summary() == ("pro", "active", False)
    assert _checkout_completed(api_db, event_id="evt_1").status_code == 200

    assert _summary() == ("pro", "active", False)
    with OrmSession(api_db) as db:
        assert db.scalar(select(func.count(Subscription.id))) == 1


def test_a_late_event_does_not_bring_back_a_subscription_that_has_ended(stripe_setup, api_db):
    created = _stripe_subscription(workspace_id=_workspace_id(api_db))
    stripe_setup.subscriptions["sub_1"] = created
    _webhook("customer.subscription.created", created, event_id="evt_1")
    stripe_setup.subscriptions["sub_1"] = {**created, "status": "canceled"}
    _webhook("customer.subscription.deleted", stripe_setup.subscriptions["sub_1"], event_id="evt_3")

    _webhook("customer.subscription.updated", created, event_id="evt_2")  # sent before the cancellation, arrives after it

    assert _summary()[:2] == (FREE, "canceled")


def test_two_live_subscriptions_are_audited_and_the_newer_one_is_followed(stripe_setup, api_db, audit_log):
    workspace_id = _workspace_id(api_db)
    stripe_setup.subscriptions["sub_a"] = _stripe_subscription("sub_a", workspace_id=workspace_id)
    stripe_setup.subscriptions["sub_b"] = _stripe_subscription("sub_b", workspace_id=workspace_id, price="price_business")

    _webhook("customer.subscription.created", stripe_setup.subscriptions["sub_a"], event_id="evt_a")
    _webhook("customer.subscription.created", stripe_setup.subscriptions["sub_b"], event_id="evt_b")

    row = _subscription(api_db)
    assert (row.stripe_subscription_id, row.plan) == ("sub_b", "business")
    [duplicate] = _audited(audit_log, "billing.duplicate_subscription")
    assert (duplicate.subscription, duplicate.replaced) == ("sub_b", "sub_a")


async def _workspace(session) -> str:
    workspace = Workspace(name="Acme", slug="acme")
    session.add(workspace)
    await session.commit()
    return workspace.id


def _read(workspace_id: str, status: str, **changes):
    return subscription_from(_stripe_subscription(workspace_id=workspace_id, status=status, **changes))


async def test_an_older_read_of_a_subscription_never_overwrites_a_newer_one(db_session, stripe_setup):
    # Two webhooks handled at once each read the subscription from Stripe, and the
    # one that read first can write last: what was read when decides, not who wrote last.
    workspace_id = await _workspace(db_session)
    billing = BillingService(db_session, None)
    now = datetime.now(timezone.utc)

    await billing.sync(_read(workspace_id, "past_due"), read_at=now)
    await billing.sync(_read(workspace_id, "active"), read_at=now - timedelta(seconds=5))
    row = await EntitlementsService(db_session).subscription(workspace_id)
    assert (row.status, _utc_of(row.stripe_synced_at)) == ("past_due", now)

    await billing.sync(_read(workspace_id, "unpaid"), read_at=now + timedelta(seconds=5))
    assert (await EntitlementsService(db_session).subscription(workspace_id)).status == "unpaid"


def _utc_of(at: datetime) -> datetime:
    return at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at


# -- What Stripe or a caller can send that isn't expected -------------------------------


def test_a_webhook_for_a_subscription_stripe_no_longer_has_is_acknowledged(stripe_setup, api_db):
    gone = _stripe_subscription("sub_gone", workspace_id=_workspace_id(api_db))  # not in the stand-in: Stripe answers "no such subscription"

    response = _webhook("customer.subscription.updated", gone)

    assert (response.status_code, response.json()) == (200, {"received": True})  # a retry would only find the same
    assert stripe_setup.fetched == ["sub_gone"] and _subscription(api_db) is None


def test_a_webhook_while_stripe_cant_be_reached_is_refused_so_stripe_sends_it_again(stripe_setup, api_db):
    stripe_setup.unreachable = True
    event = _subscription_event(stripe_setup, api_db, "customer.subscription.created")
    assert (event.status_code, event.json()["code"]) == (502, "billing_provider_error")
    assert _subscription(api_db) is None

    stripe_setup.unreachable = False
    assert _subscription_event(stripe_setup, api_db, "customer.subscription.created").status_code == 200  # the retry
    assert _summary()[:2] == ("pro", "active")


_NOT_EVENTS = [
    b"",
    b"not json",
    b"\xff\xfe",
    b"[]",
    b"null",
    b'"text"',
    b"{}",
    b'{"id": "evt_1", "type": "customer.subscription.updated"}',
    b'{"id": "evt_1", "type": "customer.subscription.updated", "data": null}',
    b'{"id": "evt_1", "type": "customer.subscription.updated", "data": {"object": "sub_1"}}',
    b'{"id": "evt_1", "type": "customer.subscription.updated", "data": {"object": null}}',
    b'{"id": "evt_1", "type": "customer.subscription.updated", "data": {"object": [1]}}',
    b'{"type": "customer.subscription.updated", "data": {"object": {}}}',
    b'{"id": "evt_1", "type": 5, "data": {"object": {}}}',
]


@pytest.mark.parametrize("body", _NOT_EVENTS)
def test_a_signed_body_that_is_no_event_is_refused_without_a_crash_or_a_trace(stripe_setup, api_db, body):
    response = _send(body)

    assert (response.status_code, response.json()["code"]) == (400, "invalid_webhook")
    assert "Traceback" not in response.text and "Error" not in response.text
    assert _subscription(api_db) is None


def test_events_that_name_no_subscription_in_any_shape_are_acknowledged(stripe_setup, api_db):
    for event_type, obj in (
        ("customer.subscription.updated", {"object": "subscription"}),  # no id
        ("customer.subscription.deleted", {"id": None, "object": "subscription"}),
        ("checkout.session.completed", {"object": "checkout.session", "mode": "subscription", "subscription": None}),
        ("checkout.session.completed", {"object": "checkout.session", "mode": "subscription", "subscription": ["x"]}),
        ("customer.created", {"id": "cus_9", "object": "customer"}),
        ("a.type.nobody.knows", {}),
    ):
        response = _webhook(event_type, obj)
        assert (response.status_code, response.json()) == (200, {"received": True}), event_type
    assert stripe_setup.fetched == [] and _subscription(api_db) is None


def test_a_webhook_signed_long_ago_is_refused(stripe_setup, api_db):
    obj = _stripe_subscription(workspace_id=_workspace_id(api_db))
    stripe_setup.subscriptions["sub_1"] = obj
    body = json.dumps({"id": "evt_1", "object": "event", "type": "customer.subscription.created", "data": {"object": obj}}).encode()

    assert _send(body).status_code == 200
    replayed = _send(body, age=3600)  # a captured, correctly signed request sent again an hour later

    assert (replayed.status_code, replayed.json()["code"]) == (400, "invalid_webhook")


def test_a_refused_webhook_says_nothing_about_why(stripe_setup, api_db):
    obj = _stripe_subscription(workspace_id=_workspace_id(api_db))

    answers = {
        _webhook("customer.subscription.updated", obj, tamper=True).json()["message"],
        _webhook("customer.subscription.updated", obj, secret="whsec_someone_else").json()["message"],
        client.post("/api/v1/billing/webhook", content=b"{}", headers={"Stripe-Signature": "t=1,v1=00"}).json()["message"],
        client.post("/api/v1/billing/webhook", content=b"{}").json()["message"],
    }

    assert len(answers) == 1  # the same answer whatever was wrong with it
    assert "whsec_" not in next(iter(answers))


def test_webhooks_without_a_webhook_secret_are_refused_not_trusted(monkeypatch, api_db):
    gateway = StripeGateway("sk_test_offline", "")  # a key, but no STRIPE_WEBHOOK_SECRET
    app.dependency_overrides[get_billing_gateway] = lambda: gateway
    obj = _stripe_subscription(workspace_id=_workspace_id(api_db))

    response = _webhook("customer.subscription.created", obj, secret="")

    assert (response.status_code, response.json()["code"]) == (400, "invalid_webhook")
    assert _subscription(api_db) is None


def test_a_webhook_on_a_server_without_stripe_is_answered_not_crashed(api_db):
    app.dependency_overrides[get_billing_gateway] = lambda: None

    response = _webhook("customer.subscription.created", _stripe_subscription())

    assert (response.status_code, response.json()["code"]) == (503, "billing_not_configured")


async def test_the_real_gateway_maps_stripes_answers(monkeypatch):
    import stripe

    gateway = StripeGateway("sk_test_offline", _WEBHOOK_SECRET)

    def fails(error):
        async def raise_it(*args, **kwargs):
            raise error

        return raise_it

    retrieve = gateway._client.v1.subscriptions
    monkeypatch.setattr(retrieve, "retrieve_async", fails(stripe.InvalidRequestError("No such subscription", "id", code="resource_missing")))
    assert await gateway.subscription("sub_gone") is None
    monkeypatch.setattr(retrieve, "retrieve_async", fails(stripe.InvalidRequestError("Bad request", "id", code="parameter_invalid_empty")))
    with pytest.raises(BillingProviderError):
        await gateway.subscription("sub_1")
    monkeypatch.setattr(retrieve, "retrieve_async", fails(stripe.APIConnectionError("no route")))
    with pytest.raises(BillingProviderError):
        await gateway.subscription("sub_1")
    monkeypatch.setattr(gateway._client.v1.checkout.sessions, "create_async", fails(stripe.APIConnectionError("no route")))
    with pytest.raises(BillingProviderError):
        await gateway.checkout_url(price_id="p", workspace_id="w", plan="pro", customer_id=None, email="a@b.c", success_url="https://x", cancel_url="https://x")
    monkeypatch.setattr(gateway._client.v1.billing_portal.sessions, "create_async", fails(stripe.APIConnectionError("no route")))
    with pytest.raises(BillingProviderError):
        await gateway.portal_url(customer_id="cus_1", return_url="https://x")
