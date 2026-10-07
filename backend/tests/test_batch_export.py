"""Batch export (tracker FEAT-002, brief §61): many documents exported into one ZIP -- one export
job building each document's file as a single export does, downloaded like any export, its
result naming each part and whether its words all came through."""

import io
import zipfile

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession

from app.billing.plans import FREE, PLANS
from app.db.models import UsageRecord
from app.main import app

client = TestClient(app, base_url="https://testserver")


def _plan(monkeypatch, **limits) -> None:
    free = PLANS[FREE]
    monkeypatch.setitem(PLANS, FREE, free.model_copy(update={"entitlements": free.entitlements.model_copy(update=limits)}))


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "zip@example.com", "password": "long enough password"}).status_code == 201
    yield api_db
    client.cookies.clear()


def _documents(*titles: str) -> list[str]:
    return [client.post("/api/v1/documents", json={"text": f"# {title}\n\nThe text of {title}."}).json()["id"] for title in titles]


def _count(api_db, metric: str) -> int:
    with OrmSession(api_db) as session:
        return session.scalar(select(func.sum(UsageRecord.quantity)).where(UsageRecord.metric == metric)) or 0


@pytest.mark.parametrize("file_format", ["docx", "pdf"])
def test_many_documents_into_one_zip_each_checked(signed_in, monkeypatch, file_format):
    _plan(monkeypatch, maxBatchJobs=5)
    ids = _documents("Alpha report", "Beta report", "Alpha report")  # two of the same title

    job = client.post("/api/v1/jobs/batch-export", json={"documentIds": ids, "format": file_format})

    assert job.status_code == 202, job.text
    done = client.get(f"/api/v1/jobs/{job.json()['id']}").json()
    assert done["status"] == "succeeded", done
    parts = done["result"]["parts"]
    assert [part["documentId"] for part in parts] == ids and all(part["verified"] for part in parts)
    names = [part["filename"] for part in parts]
    assert names == [f"Alpha report.{file_format}", f"Beta report.{file_format}", f"Alpha report (2).{file_format}"]
    download = client.get(f"/api/v1/jobs/{job.json()['id']}/file")
    assert download.status_code == 200 and download.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(download.content)) as package:
        assert package.namelist() == names
        data = package.read(names[1])
    text = DocxDocument(io.BytesIO(data)).paragraphs[1].text if file_format == "docx" else PdfReader(io.BytesIO(data)).pages[0].extract_text()
    assert "The text of Beta report." in text
    assert _count(signed_in, "exports") == 3 and _count(signed_in, "batch_jobs") == 1


def test_checked_before_anything_is_made(signed_in, monkeypatch):
    ids = _documents("Only one")
    free = client.post("/api/v1/jobs/batch-export", json={"documentIds": ids, "format": "docx"})
    assert free.status_code == 402 and free.json()["details"]["entitlement"] == "maxBatchJobs"
    _plan(monkeypatch, maxBatchJobs=5, maxExports=2)
    too_many = client.post("/api/v1/jobs/batch-export", json={"documentIds": _documents("Two", "Three", "Four"), "format": "docx"})
    assert too_many.status_code == 402 and too_many.json()["details"]["entitlement"] == "maxExports"
    missing = client.post("/api/v1/jobs/batch-export", json={"documentIds": [ids[0], "no-such-document"], "format": "docx"})
    assert missing.status_code == 404
    assert _count(signed_in, "batch_jobs") == 0


def test_a_document_deleted_meanwhile_is_left_out_and_said(signed_in, monkeypatch):
    """The parts the runner builds, when a document goes between the request and the job."""
    import asyncio

    from app.jobs import runner

    _plan(monkeypatch, maxBatchJobs=5)
    ids = _documents("Kept", "Deleted later")
    real = runner._batch_export

    async def deleting_first(ctx):
        client.delete(f"/api/v1/documents/{ids[1]}")
        return await real(ctx)

    monkeypatch.setattr(runner, "_batch_export", deleting_first)
    done = client.get(f"/api/v1/jobs/{client.post('/api/v1/jobs/batch-export', json={'documentIds': ids, 'format': 'docx'}).json()['id']}").json()
    assert done["status"] == "succeeded", done
    assert [(part["filename"], part["missing"]) for part in done["result"]["parts"]] == [("Kept.docx", False), (None, True)]
    assert asyncio.iscoroutinefunction(real)


def test_a_part_whose_words_didnt_all_come_through_is_said(signed_in, monkeypatch):
    from app.jobs import runner

    _plan(monkeypatch, maxBatchJobs=5)
    ids = _documents("Fine", "Short of words")
    real = runner.export_report

    def checked(document, content, file_format, items):
        report = real(document, content, file_format, items)
        if document.metadata.title.startswith("Short"):
            report.content.verified = False  # as if the file came back short of words
        return report

    monkeypatch.setattr(runner, "export_report", checked)
    done = client.get(f"/api/v1/jobs/{client.post('/api/v1/jobs/batch-export', json={'documentIds': ids, 'format': 'docx'}).json()['id']}").json()
    assert [part["verified"] for part in done["result"]["parts"]] == [True, False]
