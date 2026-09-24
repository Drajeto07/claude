from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin, now_utc
from app.db.types import JSONVariant


class Template(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "templates"

    # NULL workspace_id == a global/built-in template (today's formatting/templates.py
    # built-ins); a real workspace_id is a workspace-owned custom template.
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), default=None, index=True
    )
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100), default="general")
    description: Mapped[str] = mapped_column(String(2000), default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)

    versions: Mapped[list["TemplateVersion"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class TemplateVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version_number"),)

    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONVariant)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    template: Mapped["Template"] = relationship(back_populates="versions")


class FormattingProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reusable style profile -- either saved by a user or extracted by
    Format by Example (doc §17, Phase 8). Same JSON-rules shape either way."""

    __tablename__ = "formatting_profiles"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    rules: Mapped[dict] = mapped_column(JSONVariant)
