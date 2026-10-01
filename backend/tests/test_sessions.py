"""A user's sessions (tracker ACCT-006): the browsers signed in to the account, each
signed out on its own or all but this one; and the hourly sweep of what accounts leave
behind -- ended sessions, used or expired account tokens, browsers long unused."""

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app import worker
from app.config import get_settings
from app.db.mixins import now_utc
from app.db.models import AccountToken, KnownBrowser, Session, User
from app.jobs import queue as queue_module
from app.main import app
from app.services.account_cleanup import sweep_account_records
from app.services.browsers import UNKNOWN, browser_name
from tests.helpers import error_body

pytestmark = pytest.mark.security  # the security regression suite (TEST-030)

_PASSWORD = "long enough password"
_FIREFOX = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0"
_SAFARI = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1"


def _client(user_agent: str = "testclient") -> TestClient:
    return TestClient(app, base_url="https://testserver", headers={"User-Agent": user_agent})


@pytest.fixture
def heidi(api_db) -> TestClient:
    client = _client(_FIREFOX)
    assert client.post("/api/v1/auth/register", json={"email": "heidi@example.com", "password": _PASSWORD}).status_code == 201
    return client


def _sign_in(user_agent: str) -> TestClient:
    client = _client(user_agent)
    assert client.post("/api/v1/auth/login", json={"email": "heidi@example.com", "password": _PASSWORD}).status_code == 200
    return client


def test_the_list_names_each_browser_and_marks_this_one_without_its_address(heidi):
    phone = _sign_in(_SAFARI)

    sessions = heidi.get("/api/v1/auth/sessions").json()

    assert [(entry["browser"], entry["current"]) for entry in sessions] == [("Safari on iPhone", False), ("Firefox on Windows", True)]
    assert all(set(entry) == {"id", "browser", "createdAt", "lastUsedAt", "current"} for entry in sessions)
    assert all(entry["createdAt"].endswith(("Z", "+00:00")) and entry["lastUsedAt"] for entry in sessions)
    assert "testclient" not in str(sessions)  # the address it signed in from isn't there
    assert [entry["current"] for entry in phone.get("/api/v1/auth/sessions").json()] == [True, False]


def test_signing_out_every_other_browser_keeps_this_one(heidi):
    phone, laptop = _sign_in(_SAFARI), _sign_in(_FIREFOX)

    assert heidi.post("/api/v1/auth/sessions/sign-out-others").status_code == 204

    assert phone.get("/api/v1/auth/me").status_code == laptop.get("/api/v1/auth/me").status_code == 401
    assert heidi.get("/api/v1/auth/me").status_code == 200
    assert [entry["current"] for entry in heidi.get("/api/v1/auth/sessions").json()] == [True]


def test_signing_out_one_browser(heidi):
    phone, laptop = _sign_in(_SAFARI), _sign_in(_FIREFOX)
    [phone_session] = [entry for entry in heidi.get("/api/v1/auth/sessions").json() if entry["browser"] == "Safari on iPhone"]

    assert heidi.delete(f"/api/v1/auth/sessions/{phone_session['id']}").status_code == 204

    assert phone.get("/api/v1/auth/me").status_code == 401
    assert laptop.get("/api/v1/auth/me").status_code == heidi.get("/api/v1/auth/me").status_code == 200
    gone = heidi.delete(f"/api/v1/auth/sessions/{phone_session['id']}")  # an ended one is not found
    assert (gone.status_code, error_body(gone)["code"]) == (404, "not_found")


def test_signing_out_this_browser_from_the_list_clears_its_cookie(heidi):
    [this] = heidi.get("/api/v1/auth/sessions").json()

    signed_out = heidi.delete(f"/api/v1/auth/sessions/{this['id']}")

    assert signed_out.status_code == 204 and 'smartdoc_session=""' in signed_out.headers["set-cookie"]
    assert heidi.get("/api/v1/auth/me").status_code == 401


def test_last_used_is_written_every_few_minutes_not_every_request(heidi, api_db):
    def last_used():
        with api_db.connect() as connection:
            return connection.scalar(select(Session.last_used_at))

    def set_last_used(minutes_ago: int):
        with api_db.begin() as connection:
            connection.execute(update(Session).values(last_used_at=now_utc() - timedelta(minutes=minutes_ago)))

    set_last_used(2)
    recent = last_used()
    assert heidi.get("/api/v1/auth/me").status_code == 200
    assert last_used() == recent

    set_last_used(6)
    assert heidi.get("/api/v1/auth/me").status_code == 200
    assert last_used() > recent


@pytest.mark.parametrize(
    ("user_agent", "name"),
    [
        (_FIREFOX, "Firefox on Windows"),
        (_SAFARI, "Safari on iPhone"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36", "Chrome on macOS"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0", "Edge on Windows"),
        ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36", "Chrome on Android"),
        ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/129.0.0.0 Safari/537.36", "Chrome on Linux"),
        ("curl/8.5.0", UNKNOWN),
        (None, UNKNOWN),
        ("<script>alert(1)</script>", UNKNOWN),
    ],
)
def test_a_browser_is_named_by_its_family_and_system_only(user_agent, name):
    assert browser_name(user_agent) == name


async def test_the_sweep_deletes_what_has_ended_past_its_retention_and_keeps_the_rest(db_session_factory):
    settings, now = get_settings(), now_utc()
    days = timedelta(days=1)
    sessions_kept = settings.session_retention_days - 1
    async with db_session_factory() as session:
        user = User(email="ivan@example.com", hashed_password="x")
        session.add(user)
        await session.flush()

        def a_session(name: str, *, expires: timedelta, revoked: timedelta | None = None) -> Session:
            return Session(user_id=user.id, token_hash=name, expires_at=now + expires, revoked_at=now + revoked if revoked else None)

        def a_token(name: str, *, expires: timedelta, used: timedelta | None = None) -> AccountToken:
            return AccountToken(user_id=user.id, purpose="password_reset", token_hash=name, email=user.email, expires_at=now + expires, used_at=now + used if used else None)

        session.add_all(
            [
                a_session("active", expires=10 * days),
                a_session("expired-long-ago", expires=-(settings.session_retention_days + 1) * days),
                a_session("expired-lately", expires=-sessions_kept * days),
                a_session("revoked-long-ago", expires=10 * days, revoked=-(settings.session_retention_days + 1) * days),
                a_session("revoked-lately", expires=10 * days, revoked=-sessions_kept * days),
                a_token("unused", expires=timedelta(hours=1)),
                a_token("used-long-ago", expires=-(settings.account_token_retention_days + 2) * days, used=-(settings.account_token_retention_days + 1) * days),
                a_token("used-lately", expires=timedelta(hours=1), used=-days),
                a_token("expired-long-ago", expires=-(settings.account_token_retention_days + 1) * days),
                KnownBrowser(user_id=user.id, device_hash="in-use", last_used_at=now - days),
                KnownBrowser(user_id=user.id, device_hash="unused", last_used_at=now - (settings.known_browser_retention_days + 1) * days),
            ]
        )
        await session.commit()

    swept = await sweep_account_records(db_session_factory)

    assert (swept.sessions, swept.account_tokens, swept.browsers) == (2, 2, 1)
    async with db_session_factory() as session:
        assert sorted(await session.scalars(select(Session.token_hash))) == ["active", "expired-lately", "revoked-lately"]
        assert sorted(await session.scalars(select(AccountToken.token_hash))) == ["unused", "used-lately"]
        assert list(await session.scalars(select(KnownBrowser.device_hash))) == ["in-use"]
    assert not await sweep_account_records(db_session_factory)


async def test_the_sweep_runs_hourly_in_this_process_and_in_the_worker(db_session_factory, monkeypatch, tmp_path):
    swept = []

    async def record(session_factory):
        swept.append(session_factory)

    async def stop(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(queue_module, "sweep_account_records", record)
    monkeypatch.setattr(queue_module.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        await queue_module.sweep_forever(db_session_factory, None)
    assert swept == [db_session_factory]

    monkeypatch.setattr(worker, "sweep_account_records", record)
    monkeypatch.setattr(worker, "get_session_factory", lambda: "the worker's sessions")
    await worker.sweep_accounts({})
    assert swept[-1] == "the worker's sessions"
    [cron] = [job for job in worker.WorkerSettings.cron_jobs if job.coroutine is worker.sweep_accounts]
    assert (cron.minute, cron.hour) == (47, None)  # hourly
