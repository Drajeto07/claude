from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import UUIDPrimaryKeyMixin, now_utc
from app.db.types import JSONVariant


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, enum.Enum):
    IMPORT_TEXT = "import_text"
    IMPORT_FILE = "import_file"
    FORMAT = "format"
    EXPORT = "export"
    EXTRACT_REFERENCE = "extract_reference"


class ProcessingJob(UUIDPrimaryKeyMixin, Base):
    """One piece of heavy work done off the request (корекции.docx §52): an
    import (parsing, AI structure analysis), formatting with instructions (AI),
    an export (DOCX/PDF rendering) or reading a reference document. The row is
    the job's durable state, so the frontend polls real stages and progress
    whether the work runs in this process or in an arq worker (app/jobs)."""

    __tablename__ = "processing_jobs"
    __table_args__ = (
        # One job per user and Idempotency-Key; the database, not the code, is what
        # stops two concurrent duplicates (NULL keys never collide).
        Index("uq_processing_jobs_created_by_idempotency_key", "created_by", "idempotency_key", unique=True),
    )

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), default=None, index=True
    )
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True)
    job_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.PENDING.value)
    # What it is doing now (uploading, parsing, analyzing, formatting, rendering,
    # finalizing) and how far along, 0-100 -- only ever set as real steps finish.
    stage: Mapped[str | None] = mapped_column(String(30), default=None)
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # The job's input (text, options) and, for an uploaded file, where its bytes
    # wait in storage; its result (a new document's id, an export file, ...).
    payload: Mapped[dict | None] = mapped_column(JSONVariant, default=None)
    input_key: Mapped[str | None] = mapped_column(String(500), default=None)
    result: Mapped[dict | None] = mapped_column(JSONVariant, default=None)
    # Times it was started, and how many of those were retries after a transient
    # failure or a stuck run (app/jobs/retry.py).
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(String(2000), default=None)
    # Failed after its last attempt (transient errors that never cleared, or a run
    # that never ended): kept, never swept, with failure_reason -- a short code for
    # operators (e.g. "transient:ConnectionError"), never text from the document.
    dead_letter: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    failure_reason: Mapped[str | None] = mapped_column(String(200), default=None)
    # The client's Idempotency-Key and a hash of what it asked for, so the same key
    # with another request is refused instead of answered with this job.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), default=None)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
