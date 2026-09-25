from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin, now_utc


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per workspace (doc §35, Phase 14) -- the `Entitlements` service
    reads `plan`/`status` from here; it is never checked as scattered
    `if plan == "pro"` conditionals elsewhere."""

    __tablename__ = "subscriptions"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(50), default="free")
    # Stripe's ids, filled in by its webhooks (services/billing_service.py), which look rows up by them.
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Cancelled in the billing portal: the plan ends at current_period_end instead of renewing.
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class UsageRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "usage_records"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
