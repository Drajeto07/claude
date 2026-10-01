from __future__ import annotations

import json
import zlib
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, cast, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin, now_utc
from app.db.types import JSONVariant, dumps_in_pieces


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per document. `data` holds the full existing Pydantic Document
    payload verbatim (migration-plan.md's deliberate adapter choice) --
    normalizing elements/sections/formattingRules into their own tables is a
    separate, later migration, not bundled into standing up Postgres itself."""

    __tablename__ = "documents"
    # The document list and the dashboard: a workspace's documents, most recently changed first.
    __table_args__ = (Index("ix_documents_workspace_id_updated_at", "workspace_id", "updated_at"),)

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    # No template column: the template a document was formatted with is
    # data["templateId"], and the document keeps its own copy of that
    # template's rules, so it never depends on the template still existing.
    title: Mapped[str] = mapped_column(String(500))
    document_type: Mapped[str] = mapped_column(String(100), default="general")
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSONVariant)
    # Optimistic-concurrency token: bumped by every write (version_id_col below),
    # and an UPDATE only succeeds while it still matches what was loaded.
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    # The DocumentVersion.revision_number that `data` currently equals -- the undo pointer.
    current_version: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    # When a template or instructions were last applied; None = never formatted (a draft).
    formatted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    assets: Mapped[list["DocumentAsset"]] = relationship(back_populates="document")

    __mapper_args__ = {"version_id_col": revision}


# JSONVariant, but None is SQL NULL rather than JSON 'null', so a compressed row
# leaves it empty (ck_document_versions_one_copy).
_NULLABLE_JSON = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


def pack_snapshot(data: dict) -> bytes:
    """A version's document state as stored: compact JSON (UTF-8, so Cyrillic isn't
    tripled by \\u escapes), zlib-compressed. See DocumentVersion.compressed_data."""
    return zlib.compress(dumps_in_pieces(data, separators=(",", ":"), ensure_ascii=False).encode(), 6)


def unpack_snapshot(compressed: bytes | None, legacy: dict | None) -> dict:
    """A version's document state from whichever copy the row holds."""
    if compressed is not None:
        return json.loads(zlib.decompress(compressed))
    if legacy is None:  # ck_document_versions_one_copy rules this out
        raise ValueError("A document version holds no state")
    return legacy


class DocumentVersion(UUIDPrimaryKeyMixin, Base):
    """One undo step: the full document state after that step. See
    services/version_history.py for how steps are added, merged and trimmed."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "revision_number"),
        # Exactly one copy of the state: compressed, or uncompressed from before PERF-004.
        CheckConstraint("(data IS NULL) <> (compressed_data IS NULL)", name="one_copy"),
    )

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    # "created" | "content" (autosaved typing, merged within a time window) | "change"
    kind: Mapped[str] = mapped_column(String(20), server_default="change", default="change")
    # The state, zlib-compressed JSON (PERF-004): about 5x smaller than the JSON, read
    # back in one step for undo/redo/restore. Postgres's own TOAST compression (pglz)
    # would only cover values over ~2 KB, compresses less, and its bytes aren't what
    # storage metering can see. Pictures are asset references, never inline bytes.
    compressed_data: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    # Rows written before PERF-004 keep their state uncompressed here and are read as
    # they are; new and merged steps always go to compressed_data. Use `data`.
    legacy_data: Mapped[dict | None] = mapped_column("data", _NULLABLE_JSON, default=None)
    description: Mapped[str | None] = mapped_column(String(1000), default=None)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    document: Mapped["Document"] = relationship(back_populates="versions")

    @property
    def data(self) -> dict:
        return unpack_snapshot(self.compressed_data, self.legacy_data)

    @data.setter
    def data(self, value: dict) -> None:
        self.compressed_data, self.legacy_data = pack_snapshot(value), None

    @hybrid_property
    def stored_bytes(self) -> int:
        """What the row's state takes in the database (version retention and storage metering)."""
        if self.compressed_data is not None:
            return len(self.compressed_data)
        return len(json.dumps(self.legacy_data))

    @stored_bytes.inplace.expression
    @classmethod
    def _stored_bytes_expression(cls):
        # length() of a BLOB/bytea is its bytes; a legacy row counts as its JSON text,
        # the way storage_bytes counts documents.data.
        return func.coalesce(func.length(cls.compressed_data), func.length(cast(cls.legacy_data, Text)))


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
