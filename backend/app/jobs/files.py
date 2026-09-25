"""What background jobs leave in storage, and when it goes.

An upload waits at jobs/{id}/input until its job has run (the runner deletes
it). A finished export's file waits at jobs/{id}/output for JOB_FILE_TTL_HOURS
so it can be downloaded, then goes -- at once if its document is deleted. Job
rows themselves are kept for JOB_RETENTION_DAYS. sweep_job_files does the
timed part: hourly, in the arq worker or (in-process jobs) in the API."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import JobStatus, JobType, ProcessingJob
from app.storage.base import StorageProvider

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 3600


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _delete(storage: StorageProvider, key: str) -> None:
    try:
        await storage.delete(key)
    except Exception:  # noqa: BLE001 -- logged, not raised: a file left behind is garbage, never lost data
        logger.warning("Could not delete the job file %s", key)


async def discard_export_files(session: AsyncSession, storage: StorageProvider, *where) -> int:
    """Deletes the files of the finished exports matching `where`; their jobs then
    say "expired". The caller commits."""
    statement = select(ProcessingJob).where(
        ProcessingJob.job_type == JobType.EXPORT.value, ProcessingJob.status == JobStatus.SUCCEEDED.value, *where
    )
    discarded = 0
    for job in (await session.scalars(statement)).all():
        result = dict(job.result or {})
        key = result.pop("key", None)
        if key:
            await _delete(storage, key)
            job.result = {**result, "expired": True}
            discarded += 1
    return discarded


def export_cutoff() -> datetime:
    """Exports that finished before this have been kept long enough."""
    return _now() - timedelta(hours=get_settings().job_file_ttl_hours)


async def sweep_job_files(session_factory: async_sessionmaker[AsyncSession], storage: StorageProvider) -> tuple[int, int]:
    """Every workspace's expired export files (and any whose document is gone,
    however it went), then the job rows past their retention with anything they
    still hold in storage. Returns how many of each."""
    async with session_factory() as session:
        expired = await discard_export_files(
            session, storage, or_(ProcessingJob.finished_at < export_cutoff(), ProcessingJob.document_id.is_(None))
        )
        retention_cutoff = _now() - timedelta(days=get_settings().job_retention_days)
        old = (await session.scalars(select(ProcessingJob).where(ProcessingJob.created_at < retention_cutoff))).all()
        for job in old:
            for key in (job.input_key, (job.result or {}).get("key")):
                if key:
                    await _delete(storage, key)
            await session.delete(job)
        await session.commit()
        return expired, len(old)
