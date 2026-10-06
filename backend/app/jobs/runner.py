"""The work each kind of background job does, and the runner that records it.

A job runs in one database session from start to end. As each real step
finishes, its stage and progress are written to its processing_jobs row and
committed, so whoever polls sees what is actually happening -- never a timer
(корекции.docx §52/§53). The same code runs in this process, in an arq worker
(app/worker.py) and inside the request in tests (queue.py)."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import AIProvider
from app.billing import units
from app.ai.budget import BudgetedAIProvider
from app.audit import audit
from app.config import get_settings
from app.db.models import JobStatus, JobType, ProcessingJob
from app.export.docx_export import build_docx
from app.export.filenames import safe_filename
from app.export.pdf_export import build_pdf
from app.fidelity.exports import export_report
from app.fidelity.report import FidelityPolicy, ReportBuilder
from app.formatting.engine import InvalidOperationError
from app.formatting.templates import UnknownTemplateError
from app.jobs.files import output_key
from app.jobs.policy import backoff_seconds, gave_up_message, is_stuck, is_transient, timeout_for, timeout_message
from app.models.document import FormattingProperty
from app.parsers.docx import DocxParseError
from app.parsers.pdf import PdfParseError
from app.schemas.templates import ReferenceStyleOut
from app.services.document_service import DocumentService, FormattingConflictsError, RevisionConflictError
from app.services.entitlements_service import PlanLimitError, UsageReservations, metered
from app.services.ingestion_service import UnsupportedFileTypeError, build_document_from_text
from app.services.reference_service import extract_from_docx, suggested_name
from app.services.template_service import TemplateService
from app.services.usage_service import usage_row
from app.storage.base import StorageProvider

logger = logging.getLogger(__name__)

IMPORT_TEXT = JobType.IMPORT_TEXT.value
IMPORT_FILE = JobType.IMPORT_FILE.value
FORMAT = JobType.FORMAT.value
EXPORT = JobType.EXPORT.value
EXTRACT_REFERENCE = JobType.EXTRACT_REFERENCE.value
TRANSLATE = JobType.TRANSLATE.value

EXPORT_TYPES = {
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", build_docx),
    "pdf": ("application/pdf", build_pdf),
}

_FINISHED = (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value)
_WAITING = (JobStatus.PENDING.value, JobStatus.RUNNING.value)
_UNEXPECTED = "Something went wrong while processing this. Please try again."
# Payload fields that hold the user's own text: needed to do the job, dropped
# once it has finished (the text now lives in the document, or nowhere).
_TEXT_INPUTS = ("text", "instructionsText")


def without_text_inputs(payload: dict | None) -> dict | None:
    return {key: value for key, value in payload.items() if key not in _TEXT_INPUTS} if payload else payload


class JobError(Exception):
    """A failure the user is told about as it is."""


class JobCancelled(BaseException):
    """Raised at a job's next check once its owner has cancelled it. Not an
    Exception, so no `except Exception` in the work being done can swallow it."""


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
    # Reserves each AI call's operation before it, committed at once (refused once
    # the plan's AI operations for the month are used up: the AI step then falls
    # back), and gives it back if the call fails. A call that completed stays
    # counted whatever becomes of the job: it happened.
    provider: AIProvider
    # Usage events (services/usage_service.py) not yet written, written with the
    # job's outcome, whatever it is.
    usage: list[str] = field(default_factory=list)
    # The workspace's monthly usage, reserved before the work (PLAN-003).
    reservations: UsageReservations | None = None
    # What was reserved for the job's result (an export): kept only if the result
    # is written, given back on every other outcome -- a failure, a retry (which
    # reserves again), a cancel -- so a job counts once however often it runs.
    held: list[str] = field(default_factory=list)

    async def reserve_for_result(self, unit: units.UsageUnit, quantity: int = 1) -> None:
        if self.reservations is not None:
            self.held.append(await self.reservations.take(unit, quantity))

    async def report(self, stage: str, progress: int) -> None:
        """A real step reached: written and committed at once, for the poller to see."""
        # Written only while the job isn't cancelled -- one statement, so a cancel
        # can't slip in between a check and the write. No row to write is a stop too.
        written = await self.session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == self.job_id, ProcessingJob.status != JobStatus.CANCELLED.value)
            .values(stage=stage, progress=max(0, min(99, progress)))
        )
        await self.session.commit()
        if written.rowcount == 0:
            raise JobCancelled

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
            data,
            ctx.payload["filename"],
            ctx.payload.get("title"),
            ctx.provider,
            ctx.report,
            autolink=bool(ctx.payload.get("autolink")),
            pdf_mode="layout" if ctx.payload.get("pdf_mode") == "layout" else "editable",
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
    document, ai_unavailable, edit_count, proposal_count = result
    return {
        "status": "applied",
        "aiUnavailable": ai_unavailable,
        "instructionEditCount": edit_count,
        "proposalCount": proposal_count,
        "revision": document.revision,
    }


async def _export(ctx: JobContext) -> dict:
    extension = ctx.payload["format"]
    content_type, build = EXPORT_TYPES[extension]
    # Before anything is built: an export the month has no room for isn't made.
    await ctx.reserve_for_result(units.EXPORT)
    await ctx.report("rendering", 10)
    service = ctx.documents()
    document = await service.get(ctx.document_id or "")
    if document is None:
        raise JobError("The document no longer exists.")
    assets = await service.export_assets(document)
    noted = ReportBuilder()
    word: dict = {}
    if extension == "docx":
        # A Word export is written into the Word file the document came from (DOCX-011).
        word["source"], problem = await service.source_package(document)
        if problem:
            noted.add(
                "export.docx.source_missing",
                FidelityPolicy.LOSSY,
                f"{problem} This export was built without it: its styles, headers and footers and properties aren't kept.",
            )
    content = await asyncio.to_thread(
        build,
        document,
        assets=assets,
        **word,
        include_headers=ctx.payload.get("includeHeaders", True),
        include_page_numbers=ctx.payload.get("includePageNumbers", True),
        include_page_breaks=ctx.payload.get("includePageBreaks", True),
        report=noted,
    )
    await ctx.report("finalizing", 80)
    # The file read back: does it hold every word of the document?
    fidelity = await asyncio.to_thread(export_report, document, content, extension, noted.items())
    await ctx.report("finalizing", 90)
    key = output_key(ctx.job_id)
    await ctx.storage.put(key, content, content_type)
    audit("document.exported", document_id=document.id, user_id=ctx.user_id, format=extension, bytes=len(content), job_id=ctx.job_id)
    return {
        "key": key,
        "filename": f"{safe_filename(document.metadata.title)}.{extension}",
        "contentType": content_type,
        "size": len(content),
        "fidelity": fidelity.model_dump(mode="json"),
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


async def _translate(ctx: JobContext) -> dict:
    """A translated version of a document (TRAN-006): a new document, the original untouched."""
    from app.api.deps import get_translation_provider
    from app.ai.factory import get_ai_provider
    from app.services.translation_service import TranslationService
    from app.translation.providers import TranslationUnavailable

    await ctx.report("translating", 10)
    try:
        created = await TranslationService(ctx.documents(), ctx.reservations).translated_version(
            ctx.document_id or "",
            target=ctx.payload["targetLanguage"],
            source=ctx.payload.get("sourceLanguage"),
            provider=get_translation_provider(get_ai_provider()),
            user_id=ctx.user_id,
        )
    except TranslationUnavailable as exc:
        raise JobError(str(exc)) from exc
    if created is None:
        raise JobError("The document no longer exists.")
    await ctx.report("finalizing", 95)
    return {"documentId": created.id}


KINDS: dict[str, Callable[[JobContext], Awaitable[dict]]] = {
    IMPORT_TEXT: _import_text,
    IMPORT_FILE: _import_file,
    FORMAT: _format,
    EXPORT: _export,
    EXTRACT_REFERENCE: _extract_reference,
    TRANSLATE: _translate,
}


class JobRunner:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], storage: StorageProvider, provider: AIProvider
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._provider = provider

    async def run(self, job_id: str) -> float | None:
        """Does the job, once: one already finished (or taken by another worker's
        retry after it finished) is left alone. Returns the seconds to wait before
        running it again when it failed for a transient reason and has attempts
        left (the queue does the waiting, app/jobs/queue.py), else None."""
        settings = get_settings()
        async with self._session_factory() as session:
            job = await session.get(ProcessingJob, job_id, populate_existing=True)
            if job is None or job.status in _FINISHED:
                return None
            if job.created_by is None or job.job_type not in KINDS:
                await self._finish(session, job_id, error="This job can't be run.", reason="invalid")
                return None
            retries = job.retry_count
            if job.status == JobStatus.RUNNING.value:
                # Running, so another worker has it -- unless it is past its deadline: then
                # that worker is gone (a crash, a restart) and this is its retry.
                if not is_stuck(job, _now()):
                    return None
                if job.attempts >= settings.job_max_attempts:
                    await self._finish(session, job_id, error=gave_up_message(job.attempts), reason="stuck", dead_letter=True)
                    await self._discard(job.input_key, job_id)
                    return None
                retries += 1
            # Taken by compare-and-set on the attempt count: of two workers that both
            # see this job waiting, only one gets it.
            taken = await session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id, ProcessingJob.status == job.status, ProcessingJob.attempts == job.attempts)
                .values(status=JobStatus.RUNNING.value, started_at=_now(), attempts=job.attempts + 1, retry_count=retries)
            )
            await session.commit()
            if taken.rowcount == 0:
                return None
            await session.refresh(job)
            usage: list[str] = []
            ai_calls: list[None] = []
            # Each in a short transaction of its own, never the job's (PLAN-003).
            reservations = UsageReservations(self._session_factory, job.workspace_id)
            context = JobContext(
                job_id=job.id,
                user_id=job.created_by,
                document_id=job.document_id,
                payload=dict(job.payload or {}),
                input_key=job.input_key,
                session=session,
                storage=self._storage,
                provider=BudgetedAIProvider(
                    metered(self._provider, reservations, lambda: ai_calls.append(None)),
                    calls=get_settings().ai_calls_per_job,
                    seconds=get_settings().ai_seconds_per_job,
                ),
                usage=usage,
                reservations=reservations,
            )
            kind, input_key = KINDS[job.job_type], job.input_key
            job_type, attempt, started = job.job_type, job.attempts, time.perf_counter()
            # Until an outcome is known: a run cut off from outside (a worker shutting down) is "interrupted".
            outcome, retry_in = "interrupted", None
            try:
                # The job's own time allowance. A thread already started (an export's
                # rendering) can't be stopped, but its result is no longer waited for.
                async with asyncio.timeout(timeout_for(job_type)) as allowance:
                    result = await kind(context)
            except JobCancelled:
                outcome = "cancelled"  # the cancel already recorded it; no result is written
                await self._finish(session, job_id, usage=usage, cancelled=True)
            except (JobError, PlanLimitError) as exc:
                outcome = f"failed:{type(exc).__name__}"
                await self._finish(session, job_id, error=str(exc), reason=f"user:{type(exc).__name__}", usage=usage)
            except Exception as exc:  # noqa: BLE001 -- recorded on the job; never the document's content in the log
                if allowance.expired():
                    outcome = "failed:timeout"
                    await self._finish(session, job_id, error=timeout_message(job_type), reason="timeout", usage=usage)
                elif is_transient(exc):
                    reason = f"transient:{type(exc).__name__}"
                    logger.warning("Job %s (%s) hit a transient error (%s), attempt %d", job_id, kind.__name__, type(exc).__name__, attempt)
                    if attempt < settings.job_max_attempts:
                        outcome = "retry"
                        retry_in = await self._retry(session, job_id, retries, reason, usage)
                    else:
                        outcome = "failed:dead_letter"
                        await self._finish(session, job_id, error=gave_up_message(attempt), reason=reason, dead_letter=True, usage=usage)
                else:
                    outcome = "failed:unexpected"
                    logger.exception("Job %s (%s) failed", job_id, kind.__name__)
                    await self._finish(session, job_id, error=_UNEXPECTED, reason=f"unexpected:{type(exc).__name__}", usage=usage)
            else:
                outcome = "succeeded"
                if not await self._finish(session, job_id, result=result, usage=usage):
                    outcome = "cancelled"  # cancelled after its last check: the result is dropped
                    await self._discard(result.get("key"), job_id)
            finally:
                # Processing status and duration (корекции.docx §51), without anything of the content.
                logger.info(
                    "job.finished",
                    extra={
                        "job_id": job_id,
                        "job_type": job_type,
                        "outcome": outcome,
                        "attempt": attempt,
                        "duration_ms": round((time.perf_counter() - started) * 1000),
                        "ai_calls": len(ai_calls),
                    },
                )
                if outcome != "succeeded":
                    for reservation in context.held:
                        await reservations.give_back(reservation)
                # A job waiting for its retry still needs its upload.
                if outcome != "retry":
                    await self._discard(input_key, job_id)
                    if outcome != "succeeded" and job_type == EXPORT:
                        # The file may already be written (a failure after it, a timeout, a cancel):
                        # nothing will ever record its key, so it goes by where it is written.
                        await self._discard(output_key(job_id), job_id)
            return retry_in

    async def _discard(self, key: str | None, job_id: str) -> None:
        if key:
            try:
                await self._storage.delete(key)
            except Exception:  # noqa: BLE001 -- a leftover file is harmless; the job's outcome stands
                logger.warning("Could not delete a file of job %s", job_id)

    @staticmethod
    async def _retry(session: AsyncSession, job_id: str, retries: int, reason: str, usage: Sequence[str]) -> float | None:
        """Back to pending, to run again after the backoff; None when it was cancelled meanwhile."""
        await session.rollback()  # whatever the failed attempt left half-done
        job = await session.get(ProcessingJob, job_id, populate_existing=True)
        if job is None:
            return None
        for metric in usage:  # the calls made happened, whether or not the attempt finished
            session.add(usage_row(job.workspace_id, metric))
        waiting = await session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.status == JobStatus.RUNNING.value)
            .values(status=JobStatus.PENDING.value, stage="retrying", progress=0, retry_count=retries + 1, failure_reason=reason)
        )
        await session.commit()
        return backoff_seconds(retries) if waiting.rowcount else None

    @staticmethod
    async def _finish(
        session: AsyncSession,
        job_id: str,
        *,
        result: dict | None = None,
        error: str | None = None,
        reason: str | None = None,
        dead_letter: bool = False,
        cancelled: bool = False,
        usage: Sequence[str] = (),
    ) -> bool:
        """Writes the outcome -- unless the job was cancelled first: a cancel stands, and
        a result that arrives after it is dropped (False). `cancelled`: only the usage."""
        await session.rollback()  # whatever a failed step left half-done
        job = await session.get(ProcessingJob, job_id, populate_existing=True)
        if job is None:
            return False
        for metric in usage:
            session.add(usage_row(job.workspace_id, metric))
        written = False
        if not cancelled:
            finished = await session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job_id, ProcessingJob.status.in_(_WAITING))
                .values(
                    status=JobStatus.FAILED.value if error else JobStatus.SUCCEEDED.value,
                    stage="failed" if error else "complete",
                    progress=job.progress if error else 100,
                    result=result,
                    error_message=error[:2000] if error else None,
                    failure_reason=reason,
                    dead_letter=dead_letter,
                    payload=without_text_inputs(job.payload),
                    finished_at=_now(),
                )
            )
            written = finished.rowcount == 1
        await session.commit()
        return written
