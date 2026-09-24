from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin, now_utc
from app.db.types import JSONVariant


class TemplateVisibility(str, enum.Enum):
    WORKSPACE = "workspace"  # every member of the workspace can see and use it
    PRIVATE = "private"  # only the person who made it


class Template(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A template owned by a workspace. Built-in templates are not rows: they
    ship with the code (formatting/builtin_templates.json).

    `style_system` is what the template is (formatting/style_system.py);
    `rules` is what it compiled to when this version was saved, i.e. exactly
    the rules applying it puts on a document."""

    __tablename__ = "templates"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    # The document it was saved from, if any (корекции.docx §18).
    source_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), default=None, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100), default="general")
    description: Mapped[str] = mapped_column(String(2000), default="")
    visibility: Mapped[str] = mapped_column(
        String(20), default=TemplateVisibility.WORKSPACE.value, server_default=TemplateVisibility.WORKSPACE.value
    )
    style_system: Mapped[dict] = mapped_column(JSONVariant)
    rules: Mapped[list] = mapped_column(JSONVariant)
    # Bumped by every save (version_id_col below); saves carry the version they
    # started from, so one tab can't silently overwrite another's edit.
    version: Mapped[int] = mapped_column(Integer, server_default="1")

    versions: Mapped[list["TemplateVersion"]] = relationship(
        back_populates="template", cascade="all, delete-orphan", passive_deletes=True
    )

    __mapper_args__ = {"version_id_col": version}


class TemplateVersion(UUIDPrimaryKeyMixin, Base):
    """The template as it was saved at `version_number` (name, description,
    style system, compiled rules): its history, and what a restore copies back."""

    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version_number"),)

    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONVariant)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
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
