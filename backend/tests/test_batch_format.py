"""Batch formatting (tracker FEAT-001, brief §61): one template over many documents, a format job
for each, followed as one batch. Counted once against the plan's batch jobs a month; every
document and the template checked before anything is queued."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.billing.plans import FREE, PLANS
from app.db.models import ProcessingJob, UsageRecord
from app.main import app

client = TestClient(app, base_url="https://testserver")


def _plan(monkeypatch, **limits) -> None:
    free = PLANS[FREE]
    monkeypatch.setitem(PLANS, FREE, free.model_copy(update={"entitlements": free.entitlements.model_copy(update=limits)}))


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "batch@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()


def _documents(count: int) -> list[str]:
    return [client.post("/api/v1/documents", json={"text": f"# Report {n}\n\nA paragraph of report {n}."}).json()["id"] for n in range(count)]


def test_one_template_over_many_documents_as_jobs_followed_as_one_batch(signed_in, monkeypatch):
    _plan(monkeypatch, maxBatchJobs=5)
    ids = _documents(3)

    response = client.post("/api/v1/jobs/batch-format", json={"documentIds": [*ids, ids[0]], "templateId": "academic-default"})

    assert response.status_code == 202, response.text
    batch = response.json()
    assert batch["total"] == 3 and [job["documentId"] for job in batch["jobs"]] == ids  # each once, in order
    followed = client.get(f"/api/v1/jobs/batches/{batch['id']}").json()
    assert followed["done"] == 3 and followed["failed"] == 0
    assert all(job["type"] == "format" and job["status"] == "succeeded" for job in followed["jobs"])
    for document_id in ids:
        document = client.get(f"/api/v1/documents/{document_id}").json()
        assert document["templateId"] == "academic-default"
    with OrmSession(signed_in) as session:
        assert session.scalar(select(func.count()).select_from(UsageRecord).where(UsageRecord.metric == "batch_jobs")) == 1
    usage = {unit["key"]: unit for unit in client.get("/api/v1/usage").json()["units"]}
    assert usage["batchJobs"]["used"] == 1


def test_nothing_is_queued_for_a_missing_document_or_template(signed_in, monkeypatch):
    _plan(monkeypatch, maxBatchJobs=5)
    ids = _documents(2)
    missing = client.post("/api/v1/jobs/batch-format", json={"documentIds": [ids[0], "00000000-0000-0000-0000-000000000000"], "templateId": "academic-default"})
    no_template = client.post("/api/v1/jobs/batch-format", json={"documentIds": ids, "templateId": "no-such-template"})
    assert missing.status_code == 404 and no_template.status_code == 404
    with OrmSession(signed_in) as session:
        assert session.scalar(select(func.count()).select_from(ProcessingJob).where(ProcessingJob.job_type == "format")) == 0
    assert client.get("/api/v1/jobs/batches/not-a-batch").status_code == 404


def test_the_plans_batch_jobs_limit_refuses_one_more(signed_in, monkeypatch):
    _plan(monkeypatch, maxBatchJobs=1)
    ids = _documents(1)
    assert client.post("/api/v1/jobs/batch-format", json={"documentIds": ids, "templateId": "academic-default"}).status_code == 202
    refused = client.post("/api/v1/jobs/batch-format", json={"documentIds": ids, "templateId": "academic-default"})
    assert refused.status_code == 402, refused.text
    body = refused.json()
    assert (body["code"], body["details"]["entitlement"], body["details"]["limit"], body["details"]["used"]) == ("plan_limit", "maxBatchJobs", 1, 1)


def test_free_plans_have_no_batches_and_too_many_documents_are_refused(signed_in):
    ids = _documents(1)
    free = client.post("/api/v1/jobs/batch-format", json={"documentIds": ids, "templateId": "academic-default"})
    assert free.status_code == 402 and free.json()["details"]["entitlement"] == "maxBatchJobs"
    too_many = client.post("/api/v1/jobs/batch-format", json={"documentIds": [f"id-{n}" for n in range(51)], "templateId": "academic-default"})
    assert too_many.status_code == 422


def test_another_users_batch_looks_missing(signed_in, monkeypatch):
    _plan(monkeypatch, maxBatchJobs=5)
    batch = client.post("/api/v1/jobs/batch-format", json={"documentIds": _documents(1), "templateId": "academic-default"}).json()
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "other@example.com", "password": "long enough password"}).status_code == 201
    assert client.get(f"/api/v1/jobs/batches/{batch['id']}").status_code == 404


def test_a_batch_holds_its_own_jobs_only(signed_in, monkeypatch):
    _plan(monkeypatch, maxBatchJobs=5)
    ids = _documents(3)
    first = client.post("/api/v1/jobs/batch-format", json={"documentIds": ids[:2], "templateId": "academic-default"}).json()
    second = client.post("/api/v1/jobs/batch-format", json={"documentIds": ids[2:], "templateId": "academic-default"}).json()
    client.post("/api/v1/jobs/format", data={"documentId": ids[0], "templateId": "academic-default"})  # not a batch's
    assert [job["documentId"] for job in client.get(f"/api/v1/jobs/batches/{first['id']}").json()["jobs"]] == ids[:2]
    assert [job["documentId"] for job in client.get(f"/api/v1/jobs/batches/{second['id']}").json()["jobs"]] == ids[2:]


def test_a_batch_counts_what_failed_and_what_waits_for_its_conflicts():
    from types import SimpleNamespace

    from app.schemas.jobs import batch_counts

    jobs = [
        SimpleNamespace(status="succeeded", result=SimpleNamespace(status="applied")),
        SimpleNamespace(status="succeeded", result=SimpleNamespace(status="conflicts")),
        SimpleNamespace(status="failed", result=None),
        SimpleNamespace(status="cancelled", result=None),
        SimpleNamespace(status="running", result=None),
    ]
    assert batch_counts(jobs) == {"total": 5, "done": 4, "failed": 2, "conflicts": 1}
