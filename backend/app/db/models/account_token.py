from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin, now_utc


class AccountToken(UUIDPrimaryKeyMixin, Base):
    """A single-use token the app e-mails a user (ACCT-002, ACCT-003): to choose a new
    password, or to confirm an address. Only its SHA-256 is stored, so a leaked table
    resets nothing. `email` is the address it was sent to: once the account's
    address is another, the token is void. Used or not, it goes when its user does."""

    __tablename__ = "account_tokens"
    __table_args__ = (Index("ix_account_tokens_user_id_purpose", "user_id", "purpose"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # "password_reset" or "email_verification".
    purpose: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
