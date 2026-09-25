from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.db.models import JobType, ProcessingJob
from app.formatting.engine import FormattingConflict
from app.models.base import ApiModel
from app.schemas.templates import ReferenceStyleOut


class ImportJobResult(ApiModel):
    """What an import made: the new document."""

    documentId: str


class FormatAppliedResult(ApiModel):
    status: Literal["applied"]
    aiUnavailable: bool
    instructionEditCount: int
    revision: int


class FormatConflictsResult(ApiModel):
    """Nothing was applied: these values set by hand would change. Format again
    with a resolution for each."""

    status: Literal["conflicts"]
    conflicts: list[FormattingConflict]


class ExportJobResult(ApiModel):
    """The file, downloadable from GET /api/jobs/{id}/file until it has expired."""

    filename: str
    contentType: str
    size: int
    expired: bool = False


class JobOut(ApiModel):
    """A background job as the frontend polls it (корекции.docx §52): its real
    stage (queued, uploading, parsing, analyzing, formatting, rendering,
    finalizing, then complete or failed) and progress, and what it produced:
    an import's document, a formatting outcome, an export's file or a reference
    document's style, by its type."""

    id: str
    type: JobType
    status: Literal["pending", "running", "succeeded", "failed"]
    stage: str | None
    progress: int
    documentId: str | None
    result: ImportJobResult | FormatAppliedResult | FormatConflictsResult | ExportJobResult | ReferenceStyleOut | None
    error: str | None
    createdAt: datetime
    startedAt: datetime | None
    finishedAt: datetime | None

    @classmethod
    def of(cls, job: ProcessingJob) -> "JobOut":
        result = {key: value for key, value in job.result.items() if key != "key"} if job.result is not None else None
        return cls(
            id=job.id,
            type=job.job_type,
            status=job.status,
            stage=job.stage,
            progress=job.progress,
            documentId=job.document_id,
            result=result,
            error=job.error_message,
            createdAt=job.created_at,
            startedAt=job.started_at,
            finishedAt=job.finished_at,
        )


class ImportTextJobRequest(ApiModel):
    text: str = Field(..., min_length=1, max_length=2_000_000)
    title: str | None = Field(default=None, max_length=500)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class ExportJobRequest(ApiModel):
    documentId: str
    format: Literal["docx", "pdf"]
    includeHeaders: bool = True
    includePageNumbers: bool = True
    includePageBreaks: bool = True
