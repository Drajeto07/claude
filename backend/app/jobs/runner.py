"""The work each kind of background job does, and the runner that records it.

A job runs in one database session from start to end. As each real step
finishes, its stage and progress are written to its processing_jobs row and
committed, so whoever polls sees what is actually happening -- never a timer
(корекции.docx §52/§53). The same code runs in this process, in an arq worker
(app/worker.py) and inside the request in tests (queue.py)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import AIProvider
from app.db.models import JobStatus, JobType, ProcessingJob
from app.export.docx_export import build_docx
from app.export.filenames import safe_filename
from app.export.pdf_export import build_pdf
from app.formatting.engine import InvalidOperationError
from app.formatting.templates import UnknownTemplateError
from app.models.document import FormattingProperty
from app.parsers.docx import DocxParseError
from app.parsers.pdf import PdfParseError
from app.schemas.templates import ReferenceStyleOut
from app.services.document_service import DocumentService, FormattingConflictsError, RevisionConflictError
from app.services.ingestion_service import UnsupportedFileTypeError, build_document_from_text
from app.services.reference_service import extract_from_docx, suggested_name
from app.services.template_service import TemplateService
from app.storage.base import StorageProvider

logger = logging.getLogger(__name__)

IMPORT_TEXT = JobType.IMPORT_TEXT.value
IMPORT_FILE = JobType.IMPORT_FILE.value
FORMAT = JobType.FORMAT.value
EXPORT = JobType.EXPORT.value
EXTRACT_REFERENCE = JobType.EXTRACT_REFERENCE.value

EXPORT_TYPES = {
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", build_docx),
    "pdf": ("application/pdf", build_pdf),
}

_FINISHED = (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value)
_UNEXPECTED = "Something went wrong while processing this. Please try again."
# Payload fields that hold the user's own text: needed to do the job, dropped
# once it has finished (the text now lives in the document, or nowhere).
_TEXT_INPUTS = ("text", "instructionsText")


def without_text_inputs(payload: dict | None) -> dict | None:
    return {key: value for key, value in payload.items() if key not in _TEXT_INPUTS} if payload else payload


class JobError(Exception):
    """A failure the user is told about as it is."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class JobContext:
    job_id: str
    user_id: str
    document_id: str | None
    payload: dict[str, Any]
    input_key: str | None
    session: AsyncSession
    storage: StorageProvider
    provider: AIProvider

    async def report(self, stage: str, progress: int) -> None:
        """A real step reached: written and committed at once, for the poller to see."""
        job = await self.session.get(ProcessingJob, self.job_id)
        if job is not None:
            job.stage, job.progress = stage, max(0, min(99, progress))
            await self.session.commit()

    def documents(self, expected_revision: int | None = None) -> DocumentService:
        return DocumentService(self.session, user_id=self.user_id, storage=self.storage, expected_revision=expected_revision)


async def _import_text(ctx: JobContext) -> dict:
    await ctx.report("analyzing", 15)
    document = await build_document_from_text(ctx.payload["text"], ctx.payload.get("title"), ctx.provider)
    await ctx.report("finalizing", 85)
    created = await ctx.documents().create(document)
    return {"documentId": created.id}


async def _import_file(ctx: JobContext) -> dict:
    data = await ctx.storage.get(ctx.input_key or "")
    try:
        created = await ctx.documents().create_from_bytes(
            data, ctx.payload["filename"], ctx.payload.get("title"), ctx.provider, ctx.report
        )
    except (UnsupportedFileTypeError, DocxParseError, PdfParseError) as exc:
        raise JobError(str(exc)) from exc
    return {"documentId": created.id}


async def _format(ctx: JobContext) -> dict:
    payload = ctx.payload
    instructions = payload.get("instructionsText") or ""
    await ctx.report("analyzing" if instructions.strip() else "formatting", 10 if instructions.strip() else 40)
    resolutions = payload.get("resolutions")
    drop_overrides = (
        [(item["elementId"], FormattingProperty(item["property"])) for item in resolutions if item["resolution"] == "apply_recommended"]
        if resolutions is not None
        else None
    )
    try:
        result = await ctx.documents(payload.get("expectedRevision")).format_document(
            ctx.document_id or "",
            template_id=payload.get("templateId"),
            instructions_text=instructions,
            provider=ctx.provider,
            drop_overrides=drop_overrides,
            report=ctx.report if instructions.strip() else None,
        )
    except FormattingConflictsError as exc:
        return {"status": "conflicts", "conflicts": [conflict.model_dump(mode="json") for conflict in exc.conflicts]}
    except (UnknownTemplateError, InvalidOperationError) as exc:
        raise JobError(str(exc)) from exc
    except RevisionConflictError as exc:
        raise JobError("This document was changed in another tab or window. Reload it and try again.") from exc
    if result is None:
        raise JobError("The document no longer exists.")
    document, ai_unavailable, edit_count = result
    return {"status": "applied", "aiUnavailable": ai_unavailable, "instructionEditCount": edit_count, "revision": document.revision}


async def _export(ctx: JobContext) -> dict:
    extension = ctx.payload["format"]
    content_type, build = EXPORT_TYPES[extension]
    await ctx.report("rendering", 10)
    service = ctx.documents()
    document = await service.get(ctx.document_id or "")
    if document is None:
        raise JobError("The document no longer exists.")
    assets = await service.export_assets(document)
    content = await asyncio.to_thread(
        build,
        document,
        assets=assets,
        include_headers=ctx.payload.get("includeHeaders", True),
        include_page_numbers=ctx.payload.get("includePageNumbers", True),
        include_page_breaks=ctx.payload.get("includePageBreaks", True),
    )
    await ctx.report("finalizing", 90)
    key = f"jobs/{ctx.job_id}/output"
    await ctx.storage.put(key, content, content_type)
    return {
        "key": key,
        "filename": f"{safe_filename(document.metadata.title)}.{extension}",
        "contentType": content_type,
        "size": len(content),
    }


async def _extract_reference(ctx: JobContext) -> dict:
    data = await ctx.storage.get(ctx.input_key or "")
    filename = ctx.payload["filename"]
    try:
        reference = await extract_from_docx(data, filename, ctx.provider, ctx.report)
    except DocxParseError as exc:
        raise JobError(str(exc)) from exc
    await ctx.report("finalizing", 90)
    taken = {view.name for view in await TemplateService(ctx.session, user_id=ctx.user_id).list_visible()}
    return ReferenceStyleOut.of(reference, suggested_name(filename, taken)).model_dump(mode="json")


KINDS: dict[str, Callable[[JobContext], Awaitable[dict]]] = {
    IMPORT_TEXT: _import_text,
    IMPORT_FILE: _import_file,
    FORMAT: _format,
    EXPORT: _export,
    EXTRACT_REFERENCE: _extract_reference,
}


class JobRunner:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], storage: StorageProvider, provider: AIProvider
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._provider = provider

    async def run(self, job_id: str) -> None:
        """Does the job, once: one already finished (or taken by another worker's
        retry after it finished) is left alone."""
        async with self._session_factory() as session:
            job = await session.get(ProcessingJob, job_id)
            if job is None or job.status in _FINISHED:
                return
            if job.created_by is None or job.job_type not in KINDS:
                await self._finish(session, job_id, error="This job can't be run.")
                return
            job.status, job.started_at, job.attempts = JobStatus.RUNNING.value, _now(), job.attempts + 1
            await session.commit()
            context = JobContext(
                job_id=job.id,
                user_id=job.created_by,
                document_id=job.document_id,
                payload=dict(job.payload or {}),
                input_key=job.input_key,
                session=session,
                storage=self._storage,
                provider=self._provider,
            )
            kind, input_key = KINDS[job.job_type], job.input_key
            try:
                result = await kind(context)
            except JobError as exc:
                await self._finish(session, job_id, error=str(exc))
            except Exception:  # noqa: BLE001 -- recorded on the job; never the document's content in the log
                logger.exception("Job %s (%s) failed", job_id, kind.__name__)
                await self._finish(session, job_id, error=_UNEXPECTED)
            else:
                await self._finish(session, job_id, result=result)
            finally:
                if input_key:
                    try:
                        await self._storage.delete(input_key)
                    except Exception:  # noqa: BLE001 -- a leftover upload is harmless; the job's outcome stands
                        logger.warning("Could not delete the input of job %s", job_id)

    @staticmethod
    async def _finish(session: AsyncSession, job_id: str, *, result: dict | None = None, error: str | None = None) -> None:
        await session.rollback()  # whatever a failed step left half-done
        job = await session.get(ProcessingJob, job_id)
        if job is None:
            return
        job.status = JobStatus.FAILED.value if error else JobStatus.SUCCEEDED.value
        job.stage = "failed" if error else "complete"
        job.progress = job.progress if error else 100
        job.result, job.error_message = result, error[:2000] if error else None
        job.payload = without_text_inputs(job.payload)
        job.finished_at = _now()
        await session.commit()
