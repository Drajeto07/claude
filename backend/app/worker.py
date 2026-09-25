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

from arq import cron
from arq.connections import RedisSettings

from app.ai.factory import get_ai_provider
from app.config import get_settings
from app.db.session import get_session_factory
from app.jobs.files import sweep_job_files
from app.jobs.runner import JobRunner
from app.services.asset_cleanup import sweep_unused_assets
from app.storage.factory import get_storage_provider

logger = logging.getLogger(__name__)


async def startup(ctx: dict) -> None:
    ctx["runner"] = JobRunner(get_session_factory(), get_storage_provider(), get_ai_provider())


async def run_job(ctx: dict, job_id: str) -> None:
    await ctx["runner"].run(job_id)


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
    cron_jobs = [cron(sweep, minute=17), cron(sweep_assets, hour=3, minute=37)]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379")
    max_tries = 3
    job_timeout = 600  # seconds: the longest AI call or export
    keep_result = 3600
