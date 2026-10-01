from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin, now_utc


class KnownBrowser(UUIDPrimaryKeyMixin, Base):
    """A browser a user has signed in from (ACCT-007), recognised by the long-lived
    random cookie it carries (`smartdoc_device`), never by its address. Only the
    cookie's SHA-256 is stored. A sign-in from a browser not listed here e-mails the
    owner. Forgotten after KNOWN_BROWSER_RETENTION_DAYS unused, and with its user."""

    __tablename__ = "known_browsers"
    __table_args__ = (UniqueConstraint("user_id", "device_hash"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    device_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
