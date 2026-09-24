from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPrimaryKeyMixin:
    """String(36) rather than a dialect-native UUID type -- matches the id
    format `models/document.py` already uses (`str(uuid4())`), so a row
    migrated from an existing JSON document keeps the same id, and the same
    column type works identically on SQLite (tests) and Postgres (prod)."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))


class TimestampMixin:
    """Application-generated timestamps (not DB server_default/onupdate) --
    matches the existing Pydantic models' `_now()` convention and behaves
    identically across SQLite and Postgres."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
