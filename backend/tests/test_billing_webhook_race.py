"""Stripe webhooks handled at the same moment (PLAN-004). Stripe sends a
checkout's events within moments of each other, and each is handled by its own
request: two first events for one workspace must make one subscription row, and
whichever read Stripe later is the one kept, whichever request finishes last.

Run on two real connections to one SQLite file, and on PostgreSQL when
SMARTDOC_TEST_POSTGRES_URL names one (CI's migrations job), like
test_plan_limits_atomic.py, whose fixtures these are."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.billing.stripe_gateway import subscription_from
from app.db.models import Subscription
from app.services.billing_service import BillingService
from tests.test_plan_limits_atomic import race_database, two_connections  # noqa: F401  (fixtures)


def _read(workspace_id: str, status: str):
    return subscription_from(
        {
            "id": "sub_1",
            "customer": "cus_1",
            "status": status,
            "items": {"data": [{"current_period_end": 1_793_000_000, "price": {"id": "price_pro"}}]},
            "metadata": {"workspace_id": workspace_id, "plan": "pro"},
        }
    )


async def _sync(sessions, workspace_id: str, status: str, read_at: datetime) -> None:
    async with sessions() as session:
        await BillingService(session, None).sync(_read(workspace_id, status), read_at=read_at)


@pytest.mark.parametrize("older_starts_first", [True, False])
async def test_two_first_events_make_one_row_and_the_later_read_wins(two_connections, older_starts_first):
    sessions, workspace_id, _user_id = two_connections
    now = datetime.now(timezone.utc)
    older = _sync(sessions, workspace_id, "active", now - timedelta(seconds=2))
    newer = _sync(sessions, workspace_id, "past_due", now)

    await asyncio.wait_for(asyncio.gather(*((older, newer) if older_starts_first else (newer, older))), timeout=20)

    async with sessions() as session:
        assert await session.scalar(select(func.count(Subscription.id))) == 1
        assert (await session.scalar(select(Subscription.status))) == "past_due"
