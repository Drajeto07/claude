"""Jobs on Vercel (RELEASE, REL-014): a job runs inside its request (JOB_BACKEND=eager), which
the platform ends at 300 s. JOB_TIME_LIMIT_SECONDS caps every job type below that, so a job
stops itself and says why; and a job whose request was cut off anyway is reported failed when
next looked at, since no worker will ever pick it up."""

from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.db.models import JobStatus, JobType, ProcessingJob
from app.jobs import policy
from app.services.auth_service import AuthService
from app.services.job_service import JobService
from app.storage.local_provider import LocalStorageProvider

_PASSWORD = "long enough password"


def _ago(seconds: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


async def _user(factory) -> tuple[str, str]:
    async with factory() as session:
        auth = AuthService(session)
        user = await auth.register("eager@example.com", _PASSWORD, None)
        return user.id, await auth.default_workspace_id(user.id)


async def _add(factory, user, **fields) -> str:
    async with factory() as session:
        row = ProcessingJob(**{"workspace_id": user[1], "created_by": user[0], "job_type": JobType.TRANSLATE.value, "payload": {"text": "a secret paragraph"}} | fields)
        session.add(row)
        await session.commit()
        return row.id


async def _read(factory, user, job_id, storage) -> ProcessingJob:
    async with factory() as session:
        return await JobService(session, user_id=user[0], storage=storage).get(job_id)


def test_the_host_limit_caps_every_job_type(monkeypatch):
    assert policy.timeout_for(JobType.TRANSLATE.value) == 900  # no host limit: the type's own
    monkeypatch.setattr(get_settings(), "job_time_limit_seconds", 270)

    assert policy.timeout_for(JobType.TRANSLATE.value) == 270
    assert policy.timeout_for(JobType.IMPORT_FILE.value) == 270
    assert policy.timeout_for(JobType.EXPORT.value) == 270
    assert "took longer than 4 minutes" in policy.timeout_message(JobType.TRANSLATE.value)  # what the person is told


async def test_an_eager_job_cut_off_with_its_request_is_reported_failed(db_session_factory, tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "job_backend", "eager")
    monkeypatch.setattr(settings, "job_time_limit_seconds", 270)
    storage = LocalStorageProvider(tmp_path)
    await storage.put("jobs/cut/input", b"upload", "text/plain")
    user = await _user(db_session_factory)
    cut_off = await _add(db_session_factory, user, status="running", attempts=1, input_key="jobs/cut/input", started_at=_ago(270 + policy.STUCK_GRACE_SECONDS + 5))
    running = await _add(db_session_factory, user, status="running", attempts=1, started_at=_ago(30))

    failed = await _read(db_session_factory, user, cut_off, storage)
    still_running = await _read(db_session_factory, user, running, storage)

    assert failed.status == JobStatus.FAILED.value and failed.failure_reason == "stuck" and failed.dead_letter
    assert "couldn't be finished" in failed.error_message
    assert "text" not in failed.payload  # the document's text isn't kept on a dead job
    assert not (tmp_path / "jobs" / "cut" / "input").exists()  # its upload is gone
    assert still_running.status == JobStatus.RUNNING.value


async def test_with_a_worker_a_stuck_job_is_left_to_recovery(db_session_factory, tmp_path, monkeypatch):
    # A worker (in-process or arq) retries a stuck job itself: reading it changes nothing.
    monkeypatch.setattr(get_settings(), "job_backend", "background")
    user = await _user(db_session_factory)
    stuck = await _add(db_session_factory, user, status="running", attempts=1, started_at=_ago(5000))

    assert (await _read(db_session_factory, user, stuck, LocalStorageProvider(tmp_path))).status == JobStatus.RUNNING.value


def test_the_vercel_image_stops_jobs_before_vercel_does():
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parent.parent / "Dockerfile.vercel").read_text(encoding="utf-8")
    env_block = dockerfile.split("ENV JOB_BACKEND=", 1)[1].split("\n\n", 1)[0]
    limit = next(int(line.strip(" \\").split("=", 1)[1]) for line in env_block.splitlines() if "JOB_TIME_LIMIT_SECONDS=" in line)
    assert 0 < limit <= 300 - 20  # at least 20 s left inside Vercel's 300 s to record the failure and answer


@pytest.fixture(autouse=True)
def _no_host_limit_leaks(monkeypatch):
    monkeypatch.setattr(get_settings(), "job_time_limit_seconds", 0)
