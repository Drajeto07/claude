"""The signed-in user's background jobs (app/jobs): queuing one, reading it back,
and letting a finished export's file go once it has expired. A job is its
starter's: nobody else can see it, its result or its file."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobStatus, ProcessingJob
from app.jobs.files import discard_export_files, export_cutoff
from app.jobs.runner import EXPORT, without_text_inputs
from app.services.auth_service import AuthService
from app.storage.base import StorageProvider


class JobService:
    def __init__(self, session: AsyncSession, *, user_id: str, storage: StorageProvider) -> None:
        self._session = session
        self._user_id = user_id
        self._storage = storage

    async def create(
        self,
        job_type: str,
        *,
        document_id: str | None = None,
        payload: dict | None = None,
        input_bytes: bytes | None = None,
        input_content_type: str = "application/octet-stream",
    ) -> ProcessingJob:
        """A pending job in the user's workspace; an uploaded file waits in storage
        until the job has used it."""
        workspace_id = await AuthService(self._session).default_workspace_id(self._user_id)
        job = ProcessingJob(
            workspace_id=workspace_id,
            document_id=document_id,
            created_by=self._user_id,
            job_type=job_type,
            payload=payload or {},
            stage="queued",
        )
        self._session.add(job)
        await self._session.flush()
        if input_bytes is not None:
            job.input_key = f"jobs/{job.id}/input"
            await self._storage.put(job.input_key, input_bytes, input_content_type)
        await self._session.commit()
        return job

    async def get(self, job_id: str) -> ProcessingJob | None:
        # populate_existing: a job run in another session (eager or in-process) moved on since.
        statement = (
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.created_by == self._user_id)
            .execution_options(populate_existing=True)
        )
        return (await self._session.scalars(statement)).first()

    async def export_file(self, job: ProcessingJob) -> tuple[bytes, dict] | None:
        """A finished export's bytes and description, while it hasn't expired."""
        result = job.result or {}
        if job.job_type != EXPORT or job.status != JobStatus.SUCCEEDED.value or not result.get("key"):
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
        job.payload, job.finished_at = without_text_inputs(job.payload), datetime.now(timezone.utc)
        if job.input_key:
            await self._storage.delete(job.input_key)
        await self._session.commit()
