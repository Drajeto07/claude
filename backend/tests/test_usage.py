"""Usage metering (корекции.docx §36): documents created, jobs, exports and AI
calls are counted on the backend as they happen, per workspace and month."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.ai.schemas import AIFormattingRule, AIInstructionExtractionResponse
from app.db.models import UsageRecord, WorkspaceMember
from app.main import app
from app.services.usage_service import AI_OPERATIONS, MeteredAIProvider, month_of
from tests.fakes import FakeAIProvider

client = TestClient(app, base_url="https://testserver")
_MARKDOWN = "# Usage\n\nA paragraph that makes this a real document."


@pytest.fixture(autouse=True)
def signed_in(api_db):
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "usage@example.com", "password": "long enough password"}).status_code == 201
    yield
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)


def _usage() -> dict:
    return client.get("/api/v1/usage").json()


def test_a_new_workspace_has_used_nothing():
    usage = _usage()

    assert {key: usage[key] for key in ("documentsCreated", "exports", "aiOperations", "processingJobs", "documents", "storageBytes")} == {
        "documentsCreated": 0,
        "exports": 0,
        "aiOperations": 0,
        "processingJobs": 0,
        "documents": 0,
        "storageBytes": 0,
    }
    start, end = datetime.fromisoformat(usage["periodStart"]), datetime.fromisoformat(usage["periodEnd"])
    assert start.day == 1 and end.day == 1 and start < datetime.now(timezone.utc) < end


def test_jobs_documents_and_exports_are_counted():
    job = client.post("/api/v1/jobs/import-text", json={"text": _MARKDOWN}).json()
    document_id = job["result"]["documentId"]
    client.post("/api/v1/jobs/export", json={"documentId": document_id, "format": "pdf"})
    client.get(f"/api/v1/documents/{document_id}/export/docx")  # the direct endpoint counts too

    usage = _usage()

    assert (usage["documentsCreated"], usage["processingJobs"], usage["exports"], usage["documents"]) == (1, 2, 2, 1)
    assert usage["storageBytes"] > 0


def test_only_ai_calls_that_completed_are_counted():
    job = client.post("/api/v1/jobs/import-text", json={"text": _MARKDOWN}).json()
    document_id = job["result"]["documentId"]
    answer = AIInstructionExtractionResponse(rules=[AIFormattingRule(target="Paragraph", property="bold", value="true")])
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([answer])
    client.post("/api/v1/jobs/format", data={"documentId": document_id, "instructionsText": "make the text bold"})
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([AIStructuredOutputError("down")] * 3)
    client.post("/api/v1/jobs/format", data={"documentId": document_id, "instructionsText": "make it blue"})

    assert _usage()["aiOperations"] == 1


def test_earlier_months_and_other_workspaces_dont_count(api_db):
    client.post("/api/v1/documents", json={"text": _MARKDOWN})
    with OrmSession(api_db) as session:
        workspace_id = session.scalars(select(WorkspaceMember.workspace_id)).one()
        last_month = datetime.now(timezone.utc).replace(day=1) - timedelta(days=3)
        start, end = month_of(last_month)
        session.add(UsageRecord(workspace_id=workspace_id, metric="exports", quantity=5, period_start=start, period_end=end, created_at=last_month))
        session.commit()

    assert (_usage()["documentsCreated"], _usage()["exports"]) == (1, 0)

    client.cookies.clear()
    client.post("/api/v1/auth/register", json={"email": "other@example.com", "password": "long enough password"})
    assert (_usage()["documentsCreated"], _usage()["documents"]) == (0, 0)


async def test_the_metered_provider_counts_completed_calls_only():
    counted: list[str] = []
    provider = MeteredAIProvider(
        FakeAIProvider([AIInstructionExtractionResponse(rules=[]), AIStructuredOutputError("no")]), lambda: counted.append(AI_OPERATIONS)
    )

    await provider.complete_structured("first", response_model=AIInstructionExtractionResponse)
    with pytest.raises(AIStructuredOutputError):
        await provider.complete_structured("second", response_model=AIInstructionExtractionResponse)

    assert counted == [AI_OPERATIONS] and provider.provider_name() == "fake"


def test_month_of_is_the_calendar_month_in_utc():
    assert month_of(datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)) == (
        datetime(2026, 12, 1, tzinfo=timezone.utc),
        datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
