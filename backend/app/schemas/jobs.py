from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.db.models import JobType, ProcessingJob
from app.fidelity.report import FidelityReport
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
    # Changes to the content the instructions asked for, waiting for the user's review.
    proposalCount: int = 0


class FormatConflictsResult(ApiModel):
    """Nothing was applied: these values set by hand would change. Format again
    with a resolution for each."""

    status: Literal["conflicts"]
    conflicts: list[FormattingConflict]


class ExportPart(ApiModel):
    """One document of a batch export (FEAT-002): its file in the ZIP, and whether that file, read
    back, holds every word of the document; `missing` -- deleted since the batch was asked for."""

    documentId: str
    filename: str | None
    verified: bool
    missing: bool = False


class ExportJobResult(ApiModel):
    """The file, downloadable from GET /api/jobs/{id}/file until it has expired."""

    filename: str
    contentType: str
    size: int
    expired: bool = False
    # What the export approximated or left out, and whether the file, read back,
    # holds every word of the document (app/fidelity/exports.py).
    fidelity: FidelityReport | None = None
    # A batch export's documents, one file each in the ZIP (FEAT-002).
    parts: list[ExportPart] | None = None


# The most documents one batch takes (FEAT-001): each is a job of its own.
MAX_BATCH_DOCUMENTS = 50


class BatchFormatRequest(ApiModel):
    """One template applied to many documents (FEAT-001): a format job for each."""

    documentIds: list[str] = Field(min_length=1, max_length=MAX_BATCH_DOCUMENTS)
    templateId: str = Field(min_length=1, max_length=100)


class JobOut(ApiModel):
    """A background job as the frontend polls it (корекции.docx §52): its real
    stage (queued, uploading, parsing, analyzing, formatting, rendering,
    finalizing, then complete, failed or cancelled; retrying while it waits to be
    tried again) and progress, and what it produced:
    an import's document, a formatting outcome, an export's file or a reference
    document's style, by its type."""

    id: str
    type: JobType
    status: Literal["pending", "running", "succeeded", "failed", "cancelled"]
    stage: str | None
    progress: int
    # Times it was tried again after a transient failure; whether it failed for good
    # after its last attempt (a dead letter: `error` then says it gave up).
    retryCount: int
    deadLetter: bool
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
            retryCount=job.retry_count,
            deadLetter=job.dead_letter,
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


class TranslateDocumentJobRequest(ApiModel):
    """A translated version of a document (TRAN-006): a new document; the original stays as it is."""

    documentId: str
    targetLanguage: str = Field(max_length=35, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
    sourceLanguage: str | None = Field(default=None, max_length=35, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")


class BatchTranslateRequest(ApiModel):
    """Many documents translated into one language (FEAT-003): a translated version of each."""

    documentIds: list[str] = Field(min_length=1, max_length=MAX_BATCH_DOCUMENTS)
    targetLanguage: str = Field(max_length=35, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
    sourceLanguage: str | None = Field(default=None, max_length=35, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")


class BatchExportRequest(ApiModel):
    """Many documents exported into one ZIP (FEAT-002), with a single export's options."""

    documentIds: list[str] = Field(min_length=1, max_length=MAX_BATCH_DOCUMENTS)
    format: Literal["docx", "pdf"]
    includeHeaders: bool = True
    includePageNumbers: bool = True
    includePageBreaks: bool = True


class ExportJobRequest(ApiModel):
    documentId: str
    format: Literal["docx", "pdf"]
    includeHeaders: bool = True
    includePageNumbers: bool = True
    includePageBreaks: bool = True


class BatchOut(ApiModel):
    """A batch (FEAT-001): its jobs, one per document, and how far they have got. `conflicts`:
    documents the template's rules conflict with -- each waits for its own resolution (its job's
    result lists them); the others are formatted."""

    id: str
    jobs: list[JobOut]
    total: int
    done: int
    failed: int
    conflicts: int

    @classmethod
    def of(cls, batch_id: str, jobs: list[JobOut]) -> "BatchOut":
        return cls(id=batch_id, jobs=jobs, **batch_counts(jobs))


def batch_counts(jobs) -> dict[str, int]:
    """How far a batch's jobs have got: finished (done), failed or cancelled, waiting for their
    conflicts to be resolved (a format job that finished with conflicts)."""
    return {
        "total": len(jobs),
        "done": sum(1 for job in jobs if job.status in ("succeeded", "failed", "cancelled")),
        "failed": sum(1 for job in jobs if job.status in ("failed", "cancelled")),
        "conflicts": sum(1 for job in jobs if job.status == "succeeded" and getattr(job.result, "status", None) == "conflicts"),
    }
