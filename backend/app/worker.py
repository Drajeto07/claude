"""The arq worker for background jobs, the production setup (корекции.docx §52):

    arq app.worker.WorkerSettings

with REDIS_URL set here and on the API servers, and JOB_BACKEND=arq on the API
servers so they queue jobs instead of running them. It runs the same JobRunner
as the in-process backend (app/jobs), against the same processing_jobs rows.
A worker that dies mid-job leaves the job to arq's retry; the runner itself
never runs a finished job twice. It also tidies up: job files and old job rows
hourly (app/jobs/files.py), images no document uses daily
(services/asset_cleanup.py)."""

import logging

from arq import Retry, cron
from arq.connections import RedisSettings

from app.ai.factory import get_ai_provider
from app.config import get_settings
from app.db.session import get_session_factory
from app.jobs.files import sweep_job_files
from app.jobs.policy import JOB_TIMEOUTS, STUCK_GRACE_SECONDS
from app.jobs.recovery import recover_stuck_jobs
from app.jobs.runner import JobRunner
from app.services.asset_cleanup import sweep_unused_assets
from app.storage.factory import get_storage_provider

logger = logging.getLogger(__name__)


async def startup(ctx: dict) -> None:
    ctx["runner"] = JobRunner(get_session_factory(), get_storage_provider(), get_ai_provider())


async def run_job(ctx: dict, job_id: str) -> None:
    wait = await ctx["runner"].run(job_id)
    if wait is not None:  # a transient failure with attempts left: arq runs it again after the backoff
        raise Retry(defer=wait)


async def recover(ctx: dict) -> None:
    async def requeue(job_id: str, retry: int) -> None:
        # A new arq job id per retry: the first one's key may still be in Redis.
        await ctx["redis"].enqueue_job("run_job", job_id, _job_id=f"{job_id}:retry{retry}")

    queued, failed = await recover_stuck_jobs(get_session_factory(), get_storage_provider(), requeue)
    if queued or failed:
        logger.warning("Stuck jobs: %d queued again, %d failed", queued, failed)


async def sweep(ctx: dict) -> None:
    expired, removed = await sweep_job_files(get_session_factory(), get_storage_provider())
    if expired or removed:
        logger.info("Job sweep: %d export file(s) expired, %d old job(s) removed", expired, removed)


async def sweep_assets(ctx: dict) -> None:
    if deleted := await sweep_unused_assets(get_session_factory(), get_storage_provider()):
        logger.info("Asset sweep: %d unused image(s) deleted", deleted)


class WorkerSettings:
    functions = [run_job]
    # Each runs on one worker at a time (arq cron jobs are unique across workers).
    cron_jobs = [cron(sweep, minute=17), cron(sweep_assets, hour=3, minute=37), cron(recover)]  # recover: every minute
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379")
    # arq counts a crashed worker's retry and each of the runner's own retries (JOB_MAX_ATTEMPTS,
    # default 3) as tries; the runner is the one that gives up, so arq's limit stays above it.
    max_tries = get_settings().job_max_attempts + 3
    # Above the longest job type's own timeout, which fires first with a message for people.
    job_timeout = max(JOB_TIMEOUTS.values()) + STUCK_GRACE_SECONDS
    keep_result = 3600
