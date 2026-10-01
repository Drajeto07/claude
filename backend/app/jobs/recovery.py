"""Stuck-job detection (JOB-001): a job still "running" past its deadline
(policy.deadline: its type's timeout plus a minute) has lost its worker.

- attempts left: it goes back to pending and is queued again at once;
- no attempts left: it fails as a dead letter, with its reason, and its upload goes.

Runs every minute: in the arq worker as a cron job (app/worker.py), in the API
process (in-process jobs) as recover_forever. A worker that restarts the job by
itself (arq retries a crashed one) and this sweep can both reach the same job; the
runner takes a job by compare-and-set, so only one of them runs it."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import JobStatus, ProcessingJob
from app.jobs.policy import gave_up_message, is_stuck
from app.jobs.runner import without_text_inputs
from app.storage.base import StorageProvider

logger = logging.getLogger(__name__)

RECOVER_INTERVAL_SECONDS = 60

# Called with the job's id and its retry number (arq needs a fresh id per retry).
Requeue = Callable[[str, int], Awaitable[None]]


async def recover_stuck_jobs(session_factory: async_sessionmaker[AsyncSession], storage: StorageProvider, requeue: Requeue) -> tuple[int, int]:
    """Returns how many stuck jobs were queued again and how many were failed."""
    now = datetime.now(timezone.utc)
    queued = failed = 0
    async with session_factory() as session:
        running = (await session.scalars(select(ProcessingJob).where(ProcessingJob.status == JobStatus.RUNNING.value))).all()
        for job in (job for job in running if is_stuck(job, now)):
            if job.attempts < get_settings().job_max_attempts:
                if await _queue_again(session, job, requeue):
                    queued += 1
                continue
            gave_up = await session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == job.id, ProcessingJob.status == JobStatus.RUNNING.value)
                .values(
                    status=JobStatus.FAILED.value,
                    stage="failed",
                    error_message=gave_up_message(job.attempts),
                    failure_reason="stuck",
                    dead_letter=True,
                    payload=without_text_inputs(job.payload),
                    finished_at=now,
                )
            )
            await session.commit()
            if gave_up.rowcount:
                failed += 1
                if job.input_key:
                    try:
                        await storage.delete(job.input_key)
                    except Exception:  # noqa: BLE001 -- a leftover file is harmless; the job's outcome stands
                        logger.warning("Could not delete the input of job %s", job.id)
    return queued, failed


async def _queue_again(session: AsyncSession, job: ProcessingJob, requeue: Requeue) -> bool:
    # Pending first (one sweep wins, the others find it no longer running), then queued.
    retries, attempts = job.retry_count, job.attempts  # the update below changes the object too
    pending = await session.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job.id, ProcessingJob.status == JobStatus.RUNNING.value, ProcessingJob.attempts == attempts)
        .values(status=JobStatus.PENDING.value, stage="retrying", retry_count=retries + 1, failure_reason="stuck")
    )
    await session.commit()
    if not pending.rowcount:
        return False
    try:
        await requeue(job.id, retries + 1)
    except Exception:  # noqa: BLE001 -- put back as it was, so the next sweep tries again
        logger.exception("Could not queue the stuck job %s again", job.id)
        await session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job.id, ProcessingJob.status == JobStatus.PENDING.value)
            .values(status=JobStatus.RUNNING.value, retry_count=retries)
        )
        await session.commit()
        return False
    return True


async def recover_forever(session_factory: async_sessionmaker[AsyncSession], storage: StorageProvider, requeue: Requeue) -> None:
    while True:
        try:
            queued, failed = await recover_stuck_jobs(session_factory, storage, requeue)
            if queued or failed:
                logger.warning("Stuck jobs: %d queued again, %d failed", queued, failed)
        except Exception:  # noqa: BLE001 -- the next round tries again
            logger.exception("The stuck-job check failed")
        await asyncio.sleep(RECOVER_INTERVAL_SECONDS)
