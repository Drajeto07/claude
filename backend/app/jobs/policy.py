"""The rules a background job lives by when something goes wrong (JOB-001).

- **Attempts and backoff.** A job is started at most settings.job_max_attempts
  times. Only a transient failure (below) is tried again, after 5 s, then 10 s,
  then 20 s ... (doubling, capped). Anything about the user's file, text or plan,
  and any bug, fails at once: running it again would fail the same way.
- **Timeout.** Each job type has a time allowed (JOB_TIMEOUTS). A job past it is
  stopped and fails with a message for people. It is not retried: the same input
  would take as long again.
- **Stuck.** A job still "running" TIMEOUT + STUCK_GRACE_SECONDS after it started
  lost its worker (a crash, a deploy, a dropped connection): its own timeout never
  got to fire. It is started again while attempts remain, else it is a dead letter.
- **Dead letter.** A job that failed after its last attempt (transient errors that
  never cleared, or a run that never ended) keeps dead_letter = true and a
  failure_reason. The sweep never deletes one."""

from datetime import datetime, timedelta, timezone

import anthropic
from botocore import exceptions as botocore_exceptions
from sqlalchemy import exc as sqlalchemy_exc

from app.config import get_settings
from app.db.models import JobType, ProcessingJob
from app.parsers.docx import DocxParseError
from app.parsers.pdf import PdfParseError
from app.security.files import UnsafeFileError
from app.services.entitlements_service import PlanLimitError
from app.services.ingestion_service import UnsupportedFileTypeError

# Seconds a job of each type may run. An AI step is held to settings.ai_seconds_per_job
# as well (the arq worker's own limit is a little above the longest of these).
JOB_TIMEOUTS: dict[str, float] = {
    JobType.IMPORT_TEXT.value: 300,
    JobType.IMPORT_FILE.value: 600,
    JobType.FORMAT.value: 600,
    JobType.EXPORT.value: 300,
    JobType.EXTRACT_REFERENCE.value: 300,
    JobType.TRANSLATE.value: 900,
}
_NOUNS = {
    JobType.IMPORT_TEXT.value: "import",
    JobType.IMPORT_FILE.value: "import",
    JobType.FORMAT.value: "formatting",
    JobType.EXPORT.value: "export",
    JobType.EXTRACT_REFERENCE.value: "reading of the reference document",
    JobType.TRANSLATE.value: "translation",
}
# A job that outlives its timeout by this much has lost its worker.
STUCK_GRACE_SECONDS = 60

# Never retried, whatever they inherit from: what the user sent is the problem.
PERMANENT_ERRORS: tuple[type[BaseException], ...] = (
    DocxParseError,
    PdfParseError,
    UnsafeFileError,
    UnsupportedFileTypeError,
    PlanLimitError,
)
# Retried: the network, the database connection, a provider that is busy or briefly
# down. The same call can succeed a moment later.
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    sqlalchemy_exc.OperationalError,
    sqlalchemy_exc.InterfaceError,
    anthropic.APIConnectionError,  # includes its timeouts
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    botocore_exceptions.ConnectionError,
    botocore_exceptions.ConnectTimeoutError,
    botocore_exceptions.ReadTimeoutError,
)


def is_transient(exc: BaseException) -> bool:
    return not isinstance(exc, PERMANENT_ERRORS) and isinstance(exc, TRANSIENT_ERRORS)


def timeout_for(job_type: str) -> float:
    return JOB_TIMEOUTS.get(job_type, max(JOB_TIMEOUTS.values()))


def _duration(seconds: float) -> str:
    return f"{round(seconds / 60)} minutes" if seconds >= 90 else f"{round(seconds)} seconds"


def timeout_message(job_type: str) -> str:
    return (
        f"This {_NOUNS.get(job_type, 'job')} took longer than {_duration(timeout_for(job_type))}, so it was stopped. "
        "Please try again; if it keeps happening, try a smaller document."
    )


def gave_up_message(attempts: int) -> str:
    return f"This couldn't be finished after {attempts} tries. Please try again in a few minutes."


def backoff_seconds(retries_done: int) -> float:
    """The wait before the next retry: `retries_done` is how many were made already."""
    settings = get_settings()
    return min(settings.job_retry_base_seconds * 2**retries_done, settings.job_retry_max_seconds)


def deadline(job: ProcessingJob) -> datetime | None:
    """When a running job is given up on, or None before it has started."""
    if job.started_at is None:
        return None
    started = job.started_at if job.started_at.tzinfo else job.started_at.replace(tzinfo=timezone.utc)
    return started + timedelta(seconds=timeout_for(job.job_type) + STUCK_GRACE_SECONDS)


def is_stuck(job: ProcessingJob, now: datetime) -> bool:
    limit = deadline(job)
    return job.status == "running" and limit is not None and limit < now
