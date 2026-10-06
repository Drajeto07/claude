"""The signed-in user's background jobs (app/jobs): queuing one, reading it back,
and letting a finished export's file go once it has expired. A job is its
starter's: nobody else can see it, its result or its file."""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobStatus, ProcessingJob
from app.jobs.files import discard_export_files, export_cutoff
from app.jobs.runner import EXPORT, without_text_inputs
from app.services.auth_service import AuthService
from app.services.usage_service import PROCESSING_JOBS, usage_row
from app.storage.base import StorageProvider


class IdempotencyKeyReusedError(Exception):
    """The Idempotency-Key was used for another request: answering with that job
    would hand the caller a result for something they didn't ask for."""


def request_fingerprint(job_type: str, document_id: str | None, payload: dict | None, input_bytes: bytes | None) -> str:
    """What a job-creating request asked for, as a hash: its type, document, options and the
    file's bytes. The same key is only ever answered with a job made from the same request."""
    body = {"type": job_type, "document": document_id, "payload": payload or {}, "input": hashlib.sha256(input_bytes).hexdigest() if input_bytes is not None else None}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class JobService:
    def __init__(self, session: AsyncSession, *, user_id: str, storage: StorageProvider) -> None:
        self._session = session
        self._user_id = user_id
        self._storage = storage

    async def find_replay(
        self,
        key: str,
        job_type: str,
        *,
        document_id: str | None = None,
        payload: dict | None = None,
        input_bytes: bytes | None = None,
        input_content_type: str | None = None,
    ) -> ProcessingJob | None:
        """The user's job made under this Idempotency-Key, if any -- and
        IdempotencyKeyReusedError if it was made from a different request."""
        statement = (
            select(ProcessingJob)
            .where(ProcessingJob.created_by == self._user_id, ProcessingJob.idempotency_key == key)
            .execution_options(populate_existing=True)
        )
        job = (await self._session.scalars(statement)).first()
        if job is not None and job.request_fingerprint != request_fingerprint(job_type, document_id, payload, input_bytes):
            raise IdempotencyKeyReusedError
        return job

    async def create(
        self,
        job_type: str,
        *,
        document_id: str | None = None,
        payload: dict | None = None,
        input_bytes: bytes | None = None,
        input_content_type: str = "application/octet-stream",
        idempotency_key: str | None = None,
    ) -> tuple[ProcessingJob, bool]:
        """A pending job in the user's workspace; an uploaded file waits in storage
        until the job has used it. With an Idempotency-Key that already made a job
        (found by the unique index, so even a concurrent duplicate), that job
        comes back instead, with False."""
        workspace_id = await AuthService(self._session).default_workspace_id(self._user_id)
        job = ProcessingJob(
            workspace_id=workspace_id,
            document_id=document_id,
            created_by=self._user_id,
            job_type=job_type,
            payload=payload or {},
            stage="queued",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint(job_type, document_id, payload, input_bytes) if idempotency_key else None,
        )
        self._session.add(job)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            existing = (
                await self.find_replay(
                    idempotency_key, job_type, document_id=document_id, payload=payload, input_bytes=input_bytes
                )
                if idempotency_key
                else None
            )
            if existing is None:
                raise
            return existing, False
        if input_bytes is not None:
            job.input_key = f"jobs/{job.id}/input"
            await self._storage.put(job.input_key, input_bytes, input_content_type)
        self._session.add(usage_row(workspace_id, PROCESSING_JOBS))
        await self._session.commit()
        return job, True

    async def get(self, job_id: str) -> ProcessingJob | None:
        # populate_existing: a job run in another session (eager or in-process) moved on since.
        statement = (
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.created_by == self._user_id)
            .execution_options(populate_existing=True)
        )
        return (await self._session.scalars(statement)).first()

    async def cancel(self, job_id: str) -> ProcessingJob | None:
        """Cancels the user's job while it is pending or running; one already finished
        (succeeded, failed or cancelled) is returned as it is, not an error. A running
        job notices at its next check (JobContext.report) and stops without writing a
        result. None when the job isn't theirs. A waiting job's upload and text input go now."""
        job = await self.get(job_id)
        if job is None:
            return None
        input_key = job.input_key if job.status == JobStatus.PENDING.value else None  # a running job deletes its own
        cancelled = await self._session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]))
            .values(
                status=JobStatus.CANCELLED.value,
                stage="cancelled",
                payload=without_text_inputs(job.payload),
                finished_at=datetime.now(timezone.utc),
            )
        )
        await self._session.commit()
        if cancelled.rowcount and input_key:
            await self._storage.delete(input_key)
        return await self.get(job_id)

    async def recent(
        self, *, job_type: str | None, status: str | None, limit: int, dead_letter: bool | None = None
    ) -> list[ProcessingJob]:
        """This user's latest jobs, newest first."""
        statement = select(ProcessingJob).where(ProcessingJob.created_by == self._user_id)
        if dead_letter is not None:
            statement = statement.where(ProcessingJob.dead_letter.is_(dead_letter))
        if job_type:
            statement = statement.where(ProcessingJob.job_type == job_type)
        if status:
            statement = statement.where(ProcessingJob.status == status)
        return list((await self._session.scalars(statement.order_by(ProcessingJob.created_at.desc()).limit(limit))).all())

    async def export_file(self, job: ProcessingJob) -> tuple[bytes, dict] | None:
        """A finished export's bytes and description, while it hasn't expired. The hourly
        sweep deletes the file; until it has, an export past JOB_FILE_TTL_HOURS is
        already gone as far as anyone can download it (STOR-001)."""
        result = job.result or {}
        if job.job_type != EXPORT or job.status != JobStatus.SUCCEEDED.value or not result.get("key"):
            return None
        finished = job.finished_at
        if finished is not None and finished.replace(tzinfo=finished.tzinfo or timezone.utc) < export_cutoff():
            return None
        return await self._storage.get(result["key"]), result

    async def expire_old_exports(self) -> None:
        """This user's export files past JOB_FILE_TTL_HOURS go before anything new
        is queued (the hourly sweep in app/jobs/files.py does it for everyone)."""
        if await discard_export_files(
            self._session, self._storage, ProcessingJob.created_by == self._user_id, ProcessingJob.finished_at < export_cutoff()
        ):
            await self._session.commit()

    async def fail(self, job: ProcessingJob, message: str) -> None:
        """A job that couldn't be handed to its queue, so nobody waits for it."""
        job.status, job.stage, job.error_message = JobStatus.FAILED.value, "failed", message
        job.failure_reason = "queue_unavailable"
        job.payload, job.finished_at = without_text_inputs(job.payload), datetime.now(timezone.utc)
        if job.input_key:
            await self._storage.delete(job.input_key)
        await self._session.commit()
