from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.db.models import ProcessingJob


class JobOut(BaseModel):
    """A background job as the frontend polls it (корекции.docx §52): its real
    stage (queued, uploading, parsing, analyzing, formatting, rendering,
    finalizing, then complete or failed) and progress, and what it produced."""

    id: str
    type: str
    status: Literal["pending", "running", "succeeded", "failed"]
    stage: str | None
    progress: int
    documentId: str | None
    # import: {"documentId"}; format: {"status": "applied"|"conflicts", ...};
    # export: {"filename", "contentType", "size", "expired"?}; extract_reference:
    # the ReferenceStyleOut.
    result: dict | None
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


class ImportTextJobRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2_000_000)
    title: str | None = Field(default=None, max_length=500)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class ExportJobRequest(BaseModel):
    documentId: str
    format: Literal["docx", "pdf"]
    includeHeaders: bool = True
    includePageNumbers: bool = True
    includePageBreaks: bool = True
