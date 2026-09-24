from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin, now_utc
from app.db.types import JSONVariant


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per document. `data` holds the full existing Pydantic Document
    payload verbatim (migration-plan.md's deliberate adapter choice) --
    normalizing elements/sections/formattingRules into their own tables is a
    separate, later migration, not bundled into standing up Postgres itself."""

    __tablename__ = "documents"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    template_id: Mapped[str | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"), default=None, index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    document_type: Mapped[str] = mapped_column(String(100), default="general")
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSONVariant)
    # Optimistic-concurrency token: bumped by every write (version_id_col below),
    # and an UPDATE only succeeds while it still matches what was loaded.
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    # The DocumentVersion.revision_number that `data` currently equals -- the undo pointer.
    current_version: Mapped[int] = mapped_column(Integer, server_default="1", default=1)

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    assets: Mapped[list["DocumentAsset"]] = relationship(back_populates="document")

    __mapper_args__ = {"version_id_col": revision}


class DocumentVersion(UUIDPrimaryKeyMixin, Base):
    """One undo step: the full document state after that step. See
    services/version_history.py for how steps are added, merged and trimmed."""

    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "revision_number"),)

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    # "created" | "content" (autosaved typing, merged within a time window) | "change"
    kind: Mapped[str] = mapped_column(String(20), server_default="change", default="change")
    data: Mapped[dict] = mapped_column(JSONVariant)
    description: Mapped[str | None] = mapped_column(String(1000), default=None)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    document: Mapped["Document"] = relationship(back_populates="versions")


class DocumentAsset(UUIDPrimaryKeyMixin, Base):
    """Metadata row for a `StorageProvider`-held blob (doc §72, Phase 4) --
    this table plus that abstraction is what image content migrates to,
    off base64-in-JSON."""

    __tablename__ = "document_assets"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), default=None, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(1024))
    content_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    original_filename: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    document: Mapped["Document | None"] = relationship(back_populates="assets")
