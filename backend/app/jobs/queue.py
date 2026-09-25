"""Where background jobs run (settings.job_backend):

- "background": an asyncio task in this process, right after the request that
  queued it. For development; a restart fails the jobs it interrupts.
- "arq": an arq worker, through Redis (`arq app.worker.WorkerSettings`) -- the
  production setup: survives restarts, scales out, retries a crashed worker's job.
- "eager": inside the request, before it answers. For tests.

All three run the same JobRunner against the same processing_jobs rows, so the
API and the frontend can't tell them apart.

Priority processing (a plan entitlement, app/billing) matters only when jobs
wait: an arq worker takes the queued job with the oldest score first, so a
priority job is queued as if it had already waited PRIORITY_HEAD_START -- ahead
of the jobs queued since, with no second worker to deploy. In-process jobs never
wait, so there it changes nothing."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import AIProvider
from app.ai.factory import get_ai_provider
from app.config import get_settings
from app.db.models import JobStatus, ProcessingJob
from app.db.session import get_session_factory
from app.jobs.files import SWEEP_INTERVAL_SECONDS, sweep_job_files
from app.jobs.runner import JobRunner, without_text_inputs
from app.services.asset_cleanup import SWEEP_INTERVAL_SECONDS as ASSET_SWEEP_INTERVAL_SECONDS
from app.services.asset_cleanup import sweep_unused_assets
from app.storage.base import StorageProvider
from app.storage.factory import get_storage_provider

logger = logging.getLogger(__name__)

PRIORITY_HEAD_START = timedelta(minutes=10)


class JobQueue(Protocol):
    async def enqueue(self, job_id: str, *, priority: bool = False) -> None: ...


class EagerQueue:
    def __init__(self, runner: JobRunner) -> None:
        self._runner = runner

    async def enqueue(self, job_id: str, *, priority: bool = False) -> None:
        await self._runner.run(job_id)


# The asyncio tasks still running, so none is garbage-collected half-way.
_running: set[asyncio.Task] = set()


class BackgroundQueue:
    def __init__(self, runner: JobRunner) -> None:
        self._runner = runner

    async def enqueue(self, job_id: str, *, priority: bool = False) -> None:
        task = asyncio.create_task(self._runner.run(job_id))
        _running.add(task)
        task.add_done_callback(_running.discard)


_arq_pool = None


class ArqQueue:
    """Hands the job to an arq worker. The job's id doubles as arq's, so the same
    job is never queued twice."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    async def enqueue(self, job_id: str, *, priority: bool = False) -> None:
        global _arq_pool
        if _arq_pool is None:
            from arq import create_pool  # only the arq setup needs it
            from arq.connections import RedisSettings

            _arq_pool = await create_pool(RedisSettings.from_dsn(self._redis_url))
        head_start = {"_defer_until": datetime.now(timezone.utc) - PRIORITY_HEAD_START} if priority else {}
        await _arq_pool.enqueue_job("run_job", job_id, _job_id=job_id, **head_start)


def get_job_backend() -> str:
    return get_settings().job_backend


def get_job_session_factory() -> async_sessionmaker[AsyncSession]:
    return get_session_factory()


def get_job_queue(
    backend: Annotated[str, Depends(get_job_backend)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_job_session_factory)],
    storage: Annotated[StorageProvider, Depends(get_storage_provider)],
    provider: Annotated[AIProvider, Depends(get_ai_provider)],
) -> JobQueue:
    if backend == "arq":
        return ArqQueue(get_settings().redis_url)
    runner = JobRunner(session_factory, storage, provider)
    return EagerQueue(runner) if backend == "eager" else BackgroundQueue(runner)


Queue = Annotated[JobQueue, Depends(get_job_queue)]


async def fail_interrupted_jobs(session_factory: async_sessionmaker[AsyncSession], storage: StorageProvider) -> int:
    """With in-process jobs, a job still pending or running when this process
    starts was cut off by the restart: it is marked failed, so nobody waits for
    it forever, and its upload goes. (An arq worker keeps its own queue; this is
    never needed there.)"""
    async with session_factory() as session:
        jobs = (
            await session.scalars(
                select(ProcessingJob).where(ProcessingJob.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]))
            )
        ).all()
        for job in jobs:
            job.status, job.stage = JobStatus.FAILED.value, "failed"
            job.error_message = "The server restarted before this finished. Please try again."
            job.payload, job.finished_at = without_text_inputs(job.payload), datetime.now(timezone.utc)
            if job.input_key:
                await storage.delete(job.input_key)
        await session.commit()
        return len(jobs)


async def sweep_forever(session_factory: async_sessionmaker[AsyncSession], storage: StorageProvider) -> None:
    """In-process jobs: this process does the tidying an arq worker does as cron
    jobs (app/worker.py) -- job files and old jobs hourly, unused images daily."""
    hours = 0
    while True:
        try:
            expired, removed = await sweep_job_files(session_factory, storage)
            if expired or removed:
                logger.info("Job sweep: %d export file(s) expired, %d old job(s) removed", expired, removed)
            if hours % (ASSET_SWEEP_INTERVAL_SECONDS // SWEEP_INTERVAL_SECONDS) == 0:
                if deleted := await sweep_unused_assets(session_factory, storage):
                    logger.info("Asset sweep: %d unused image(s) deleted", deleted)
        except Exception:  # noqa: BLE001 -- the next round tries again
            logger.exception("The sweep failed")
        hours += 1
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
