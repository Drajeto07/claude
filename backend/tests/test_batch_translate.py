"""Batch translation (tracker FEAT-003, brief §61): the documents ticked in the list translated into
one language at once -- a translated version of each, linked to its original, which is never
changed -- as a batch of translation jobs followed until each is done; all of it checked before
anything is queued: the documents, the plan's batches, room for the new documents and the
characters they would send."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.ai.base import AIStructuredOutputError
from app.ai.factory import get_ai_provider
from app.api import deps
from app.api.deps import get_translation_provider
from app.billing.plans import FREE, PLANS
from app.db.models import UsageRecord
from app.main import app
from app.translation.providers import PseudoTranslator
from tests.fakes import FakeAIProvider

client = TestClient(app, base_url="https://testserver")


def _plan(monkeypatch, **limits) -> None:
    free = PLANS[FREE]
    monkeypatch.setitem(PLANS, FREE, free.model_copy(update={"entitlements": free.entitlements.model_copy(update=limits)}))


def _sign_up(email: str) -> None:
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": email, "password": "long enough password"}).status_code == 201


@pytest.fixture
def signed_in(api_db, monkeypatch):
    translator = PseudoTranslator()
    app.dependency_overrides[get_ai_provider] = lambda: FakeAIProvider([AIStructuredOutputError("no AI in tests")] * 20)
    app.dependency_overrides[get_translation_provider] = lambda: translator
    monkeypatch.setattr(deps, "get_translation_provider", lambda ai: translator)  # the job asks for it itself
    _sign_up("batch-translate@example.com")
    yield api_db
    client.cookies.clear()
    app.dependency_overrides.pop(get_ai_provider, None)
    app.dependency_overrides.pop(get_translation_provider, None)


def _documents(*texts: str) -> list[dict]:
    return [client.post("/api/v1/documents", json={"text": text}).json() for text in texts]


def _count(api_db, metric: str) -> int:
    with OrmSession(api_db) as session:
        return session.scalar(select(func.sum(UsageRecord.quantity)).where(UsageRecord.metric == metric)) or 0


def test_each_document_gets_a_translated_version_and_the_originals_stay(signed_in, monkeypatch):
    _plan(monkeypatch, maxBatchJobs=5)
    originals = _documents("# Report one\n\nThe first report.", "# Report two\n\nThe second report.")
    before = [client.get(f"/api/v1/documents/{document['id']}").json() for document in originals]

    batch = client.post("/api/v1/jobs/batch-translate", json={"documentIds": [document["id"] for document in originals] * 2, "targetLanguage": "bg", "sourceLanguage": "en"})

    assert batch.status_code == 202, batch.text
    body = batch.json()
    assert (body["total"], body["done"], body["failed"]) == (2, 2, 0)  # each document once
    followed = client.get(f"/api/v1/jobs/batches/{body['id']}").json()
    assert [job["documentId"] for job in followed["jobs"]] == [document["id"] for document in originals]
    for job, original in zip(followed["jobs"], before):
        assert (job["type"], job["status"]) == ("translate", "succeeded"), job
        version = client.get(f"/api/v1/documents/{job['result']['documentId']}").json()
        assert version["metadata"]["translatedFrom"]["documentId"] == original["id"]
        assert version["metadata"]["language"] == "bg" and version["elements"][0]["content"] != original["elements"][0]["content"]
        assert client.get(f"/api/v1/documents/{original['id']}").json()["elements"] == original["elements"]  # untouched
    assert _count(signed_in, "batch_jobs") == 1 and _count(signed_in, "translation_characters") > 0


def test_checked_before_anything_is_queued(signed_in, monkeypatch):
    [one, two] = _documents("# One\n\nA short text.", "# Two\n\nAnother short text.")
    ids = [one["id"], two["id"]]
    request = {"documentIds": ids, "targetLanguage": "bg"}

    free = client.post("/api/v1/jobs/batch-translate", json=request)
    assert free.status_code == 402 and free.json()["details"]["entitlement"] == "maxBatchJobs"

    _plan(monkeypatch, maxBatchJobs=5, maxDocuments=3)  # two documents and room for one more: not for two
    no_room = client.post("/api/v1/jobs/batch-translate", json=request)
    assert no_room.status_code == 402 and no_room.json()["details"]["entitlement"] == "maxDocuments"

    _plan(monkeypatch, maxBatchJobs=5, maxDocuments=None, maxTranslationCharacters=10)  # their text is longer than that together
    too_long = client.post("/api/v1/jobs/batch-translate", json=request)
    assert too_long.status_code == 402 and too_long.json()["details"]["entitlement"] == "maxTranslationCharacters"

    _plan(monkeypatch, maxBatchJobs=5, maxTranslationCharacters=None)
    missing = client.post("/api/v1/jobs/batch-translate", json={"documentIds": [ids[0], "no-such-document"], "targetLanguage": "bg"})
    assert missing.status_code == 404
    invalid = client.post("/api/v1/jobs/batch-translate", json={"documentIds": ids, "targetLanguage": "not a language"})
    assert invalid.status_code == 422
    assert _count(signed_in, "batch_jobs") == 0
    assert client.get("/api/v1/jobs", params={"type": "translate"}).json() == []  # nothing queued


def test_someone_elses_documents_are_not_found(signed_in, monkeypatch):
    _plan(monkeypatch, maxBatchJobs=5)
    [mine] = _documents("# Mine\n\nMy text.")
    _sign_up("someone-else@example.com")

    refused = client.post("/api/v1/jobs/batch-translate", json={"documentIds": [mine["id"]], "targetLanguage": "bg"})

    assert refused.status_code == 404
