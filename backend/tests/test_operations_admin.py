"""Operations data for whoever runs the service (tracker OBS-003): failed and stuck jobs,
processing and export failures, usage spikes, storage and refusals across every workspace, at
GET /api/v1/admin/operations -- only for ADMIN_TOKEN's holder, and with nothing of any document or
account in it."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as OrmSession

from app import main, observability
from app.db.mixins import now_utc
from app.db.models import DocumentAsset, ProcessingJob, User
from app.services.usage_service import usage_row

client = TestClient(main.app, base_url="https://testserver")
SECRET = "Merger plans nobody may read 4417"
TOKEN = "operator-secret"


def _get(hours: int | None = None, token: str | None = TOKEN):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/api/v1/admin/operations", params={"hours": hours} if hours is not None else None, headers=headers)


def _sign_up(email: str) -> str:
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": email, "password": "long enough password"}).status_code == 201
    assert client.post("/api/v1/documents", json={"text": f"# {SECRET}\n\n{SECRET}."}).status_code in (200, 201)
    workspace = client.get("/api/v1/auth/me").json()["workspaceId"]
    client.cookies.clear()
    return workspace


@pytest.fixture
def operator(monkeypatch):
    monkeypatch.setattr(main.settings, "admin_token", TOKEN)


def test_only_the_token_holder_gets_it_and_a_wrong_token_is_counted(api_db, monkeypatch):
    monkeypatch.setattr(main.settings, "admin_token", None)
    assert _get().status_code == 404  # unset: not there at all
    monkeypatch.setattr(main.settings, "admin_token", TOKEN)
    refused = observability.SECURITY_EVENTS.value(event="admin.token_refused", reason="-")
    assert _get(token=None).status_code == 401
    assert _get(token="guess").status_code == 401
    assert observability.SECURITY_EVENTS.value(event="admin.token_refused", reason="-") == refused + 2
    client.cookies.clear()
    _sign_up("ops-user@example.com")
    client.post("/api/v1/auth/login", json={"email": "ops-user@example.com", "password": "long enough password"})
    assert _get(token="not-it").status_code == 401  # a signed-in user is no operator
    client.cookies.clear()
    assert _get().status_code == 200
    assert _get(hours=0).status_code == 422 and _get(hours=24 * 32).status_code == 422
    assert "/api/v1/admin/operations" not in main.app.openapi()["paths"]


def test_failures_stuck_jobs_spikes_storage_and_busy_workspaces(api_db, operator):
    busy, quiet = _sign_up("busy@example.com"), _sign_up("quiet@example.com")
    now = now_utc()
    with OrmSession(api_db) as session:
        session.add_all([
            ProcessingJob(id="dead-export", workspace_id=busy, job_type="export", status="failed", failure_reason="transient:ConnectionError",
                          dead_letter=True, attempts=3, error_message=SECRET, finished_at=now - timedelta(hours=1), created_at=now - timedelta(hours=2)),
            ProcessingJob(id="failed-format", workspace_id=busy, job_type="format", status="failed", error_message=SECRET,
                          finished_at=now - timedelta(minutes=5), created_at=now - timedelta(minutes=6)),
            ProcessingJob(workspace_id=busy, job_type="import_text", status="succeeded", finished_at=now, created_at=now - timedelta(minutes=1)),
            ProcessingJob(workspace_id=quiet, job_type="export", status="succeeded", finished_at=now, created_at=now - timedelta(minutes=1)),
            ProcessingJob(id="stuck", workspace_id=quiet, job_type="export", status="running", started_at=now - timedelta(days=1), created_at=now - timedelta(days=1)),
            ProcessingJob(workspace_id=busy, job_type="format", status="running", started_at=now, created_at=now),  # running, within its time
            ProcessingJob(id="old-failure", workspace_id=quiet, job_type="export", status="failed", finished_at=now - timedelta(days=3), created_at=now - timedelta(days=3)),
            ProcessingJob(workspace_id=quiet, job_type="format", status="pending", created_at=now - timedelta(minutes=10)),
            usage_row(busy, "exports", 30, at=now - timedelta(hours=1)),  # 30 against 5 the day before: a spike
            usage_row(busy, "exports", 5, at=now - timedelta(hours=30)),
            usage_row(quiet, "exports", 25, at=now - timedelta(hours=1)),  # 25 against 10: not three times
            usage_row(quiet, "exports", 10, at=now - timedelta(hours=30)),
            usage_row(quiet, "ai_operations", 10, at=now - timedelta(hours=1)),  # new, but too few to matter
            DocumentAsset(workspace_id=busy, storage_key="busy/picture", content_type="image/png", size_bytes=50_000, original_filename=f"{SECRET}.png"),
            User(email="long-ago@example.com", hashed_password="x", created_at=now - timedelta(days=40)),  # not new
        ])
        session.commit()

    response = _get()

    assert response.status_code == 200
    data = response.json()
    assert SECRET not in response.text and "@example.com" not in response.text  # counts and ids, nothing of a document or account
    jobs = data["jobs"]
    assert jobs["by_status"]["export"] == {"failed": 1, "succeeded": 1}  # the 3-day-old one is outside the window
    assert jobs["failed_by_reason"] == {"export/transient:ConnectionError": 1, "format/error": 1}
    assert jobs["dead_letters"] == 1 and jobs["stuck"] == ["stuck"]
    assert 590 <= jobs["pending_oldest_seconds"] < 3600
    assert [failure["id"] for failure in jobs["recent_failures"]] == ["failed-format", "dead-export", "old-failure"]
    assert data["processing"] == {"finished": 2, "failed": 1} and data["exports"] == {"finished": 2, "failed": 1}
    assert data["usage_spikes"] == [{"workspace_id": busy, "metric": "exports", "window": 30, "previous_window": 5}]
    storage = data["storage"]
    assert storage["documents"] == 2 and storage["asset_bytes"] == 50_000
    assert storage["total_bytes"] == storage["document_bytes"] + storage["version_bytes"] + 50_000
    assert storage["largest_workspaces"][0]["workspace_id"] == busy
    abuse = data["abuse"]
    assert abuse["accounts_created"] == 2
    assert abuse["most_jobs"] == [{"workspace_id": busy, "count": 4}, {"workspace_id": quiet, "count": 2}]
    # A week back, the old failure is in it too.
    assert _get(hours=24 * 7).json()["jobs"]["by_status"]["export"] == {"failed": 2, "succeeded": 1, "running": 1}


def test_refusals_and_this_process_counters_are_reported(api_db, operator):
    _sign_up("refused@example.com")
    failed = observability.SECURITY_EVENTS.value(event="auth.login_failed", reason="-")
    assert client.post("/api/v1/auth/login", json={"email": "refused@example.com", "password": "not the password"}).status_code == 401
    data = _get().json()
    assert data["abuse"]["refusals"]["auth.login_failed/-"] == failed + 1
    assert set(data["this_process"]) == {"jobs", "ai_calls", "exports"}


def test_a_refusal_is_labelled_by_its_scope_never_by_free_text():
    from app.audit import audit

    before = observability.SECURITY_EVENTS.value(event="limit.rate_refused", reason="login_ip")
    audit("limit.rate_refused", scope="login_ip", ip="203.0.113.9", path="/api/v1/auth/login")
    audit("file.refused", reason=SECRET, ip="203.0.113.9")  # a refused file's reason is its error message
    audit("document.deleted", document_id="d1")  # not a refusal
    assert observability.SECURITY_EVENTS.value(event="limit.rate_refused", reason="login_ip") == before + 1
    assert "Merger" not in observability.render()  # not even with its spaces made safe
    assert "document.deleted" not in observability.render()
