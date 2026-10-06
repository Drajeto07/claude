"""What is stored, how long, and how it is served (STOR-001, brief §70; the table is in
docs/security/README.md): pictures, the kept original, a job's upload and an export file.
Retention is tested with the periods lowered, on small synthetic files."""

import base64
import io
from datetime import datetime, timedelta, timezone

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from app.config import get_settings
from app.db.models import DocumentAsset, JobStatus, JobType, ProcessingJob
from app.jobs import runner as runner_module
from app.jobs.files import sweep_job_files
from app.jobs.runner import JobRunner
from app.main import app
from app.models.document import DOCX_CONTENT_TYPE, Document, DocumentMetadata, SourcePackage
from app.repositories.document_repository import DocumentRepository
from app.security.serving import OPAQUE_TYPE, file_response
from app.services.asset_cleanup import sweep_unused_assets
from app.services.auth_service import AuthService
from app.services.document_service import DocumentService
from app.storage.base import StorageProvider
from app.storage.local_provider import LocalStorageProvider
from tests.fakes import FakeAIProvider

client = TestClient(app, base_url="https://testserver")
_PASSWORD = "long enough password"
_LONG_AGO = datetime.now(timezone.utc) - timedelta(days=40)


# -- how a file is served ---------------------------------------------------------------


def test_every_file_goes_out_with_nosniff_a_sandbox_and_a_disposition():
    served = file_response(b"x", "application/pdf", filename="Отчет.pdf")

    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert served.headers["content-disposition"].startswith("attachment;") and "filename*=UTF-8''" in served.headers["content-disposition"]
    assert served.headers["cache-control"] == "private, no-store"
    assert served.media_type == "application/pdf"


def test_a_picture_is_shown_in_place_and_the_rest_is_a_download():
    assert file_response(b"x", "image/png").headers["content-disposition"] == "inline"
    assert file_response(b"x", DOCX_CONTENT_TYPE).headers["content-disposition"] == "attachment"


@pytest.mark.parametrize("claimed", ["text/html", "image/svg+xml", "application/javascript", "text/html; charset=utf-8", ""])
def test_a_type_the_app_never_stores_is_sent_as_opaque_bytes_to_download(claimed):
    served = file_response(b"<script>alert(1)</script>", claimed)

    assert served.media_type == OPAQUE_TYPE
    assert served.headers["content-disposition"] == "attachment"
    assert served.headers["x-content-type-options"] == "nosniff"


def _png() -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (4, 4), "green").save(buffer, format="PNG")
    return buffer.getvalue()


def _word_file() -> bytes:
    doc = DocxDocument()
    doc.add_heading("Report", level=1)
    doc.add_paragraph("A paragraph long enough to be a real document.")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def signed_in(api_db):
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "storage@example.com", "password": _PASSWORD}).status_code == 201
    yield
    client.cookies.clear()


def test_a_stored_picture_is_served_in_place_and_the_kept_original_as_a_download(signed_in):
    document = client.post("/api/v1/documents", json={"text": "# Pictures\n\nSome text."}).json()
    picture = {"type": "image", "content": "", "order": 5, "image": {"src": "data:image/png;base64," + base64.b64encode(_png()).decode()}}
    saved = client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": document["elements"] + [picture]}).json()
    picture_id = next(element["image"]["assetId"] for element in saved["elements"] if element["type"] == "image")
    original = client.post("/api/v1/documents/upload", files={"file": ("report.docx", _word_file(), DOCX_CONTENT_TYPE)}).json()

    shown = client.get(f"/api/v1/assets/{picture_id}")
    kept = client.get(f"/api/v1/assets/{original['sourcePackage']['assetId']}")

    assert shown.headers["content-type"] == "image/png" and shown.headers["content-disposition"] == "inline"
    assert kept.headers["content-type"] == DOCX_CONTENT_TYPE
    assert kept.headers["content-disposition"].startswith('attachment; filename="report.docx"')
    for served in (shown, kept):
        assert served.headers["x-content-type-options"] == "nosniff"
        assert served.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert served.headers["cache-control"] == "private, max-age=31536000, immutable"


def test_an_export_file_is_a_private_download_of_its_own_type(signed_in):
    document = client.post("/api/v1/documents", json={"text": "# Export\n\nSome text."}).json()
    job = client.post("/api/v1/jobs/export", json={"documentId": document["id"], "format": "pdf"}).json()

    served = client.get(f"/api/v1/jobs/{job['id']}/file")

    assert served.status_code == 200 and served.headers["content-type"] == "application/pdf"
    assert served.headers["content-disposition"].startswith("attachment;")
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["cache-control"] == "private, no-store"
    for kind, media in (("docx", DOCX_CONTENT_TYPE), ("pdf", "application/pdf")):
        direct = client.get(f"/api/v1/documents/{document['id']}/export/{kind}")
        assert direct.headers["content-type"] == media and direct.headers["content-disposition"].startswith("attachment;")
        assert direct.headers["x-content-type-options"] == "nosniff" and direct.headers["cache-control"] == "private, no-store"


def test_an_export_whose_recorded_type_is_not_one_the_app_makes_is_not_served_as_that_type(signed_in, api_db):
    document = client.post("/api/v1/documents", json={"text": "# Export\n\nSome text."}).json()
    job = client.post("/api/v1/jobs/export", json={"documentId": document["id"], "format": "pdf"}).json()
    with OrmSession(api_db) as session:
        row = session.get(ProcessingJob, job["id"])
        row.result = {**row.result, "contentType": "text/html"}
        session.commit()

    served = client.get(f"/api/v1/jobs/{job['id']}/file")

    assert served.headers["content-type"] == OPAQUE_TYPE and served.headers["content-disposition"].startswith("attachment;")


# -- an export is never kept for good ---------------------------------------------------


def test_an_export_past_its_time_cannot_be_downloaded_even_before_the_sweep_deletes_it(signed_in, api_db):
    document = client.post("/api/v1/documents", json={"text": "# Export\n\nSome text."}).json()
    job = client.post("/api/v1/jobs/export", json={"documentId": document["id"], "format": "pdf"}).json()
    ttl = timedelta(hours=get_settings().job_file_ttl_hours)

    def finished(ago: timedelta) -> None:
        with OrmSession(api_db) as session:
            session.execute(update(ProcessingJob).where(ProcessingJob.id == job["id"]).values(finished_at=datetime.now(timezone.utc) - ago))
            session.commit()

    finished(ttl - timedelta(minutes=30))
    assert client.get(f"/api/v1/jobs/{job['id']}/file").status_code == 200
    finished(ttl + timedelta(minutes=30))
    assert client.get(f"/api/v1/jobs/{job['id']}/file").status_code == 404


async def test_the_sweep_ends_an_export_with_the_time_lowered(db_session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "job_file_ttl_hours", 1)
    storage = LocalStorageProvider(tmp_path)
    user_id, workspace_id, document_id = await _user_and_document(db_session_factory)
    now = datetime.now(timezone.utc)
    jobs = {}
    for name, age in {"fresh": timedelta(minutes=20), "stale": timedelta(minutes=90)}.items():
        await storage.put(f"jobs/{name}/output", b"PK", "application/pdf")
        jobs[name] = await _add(
            db_session_factory,
            user_id,
            workspace_id,
            document_id=document_id,
            job_type=JobType.EXPORT.value,
            status=JobStatus.SUCCEEDED.value,
            result={"key": f"jobs/{name}/output", "filename": "a.pdf"},
            finished_at=now - age,
        )

    assert await sweep_job_files(db_session_factory, storage) == (1, 0)

    assert (tmp_path / "jobs" / "fresh" / "output").exists() and not (tmp_path / "jobs" / "stale" / "output").exists()
    assert (await _load(db_session_factory, jobs["stale"])).result == {"filename": "a.pdf", "expired": True}


async def test_an_export_file_a_failed_job_wrote_but_never_recorded_goes_with_its_job_row(db_session_factory, tmp_path):
    storage = LocalStorageProvider(tmp_path)
    user_id, workspace_id, _ = await _user_and_document(db_session_factory)
    job_id = await _add(
        db_session_factory, user_id, workspace_id, job_type=JobType.EXPORT.value, status=JobStatus.FAILED.value, created_at=_LONG_AGO
    )
    await storage.put(f"jobs/{job_id}/output", b"PK", "application/pdf")

    assert await sweep_job_files(db_session_factory, storage) == (0, 1)

    assert not (tmp_path / "jobs" / job_id / "output").exists()


async def test_an_export_that_fails_after_writing_its_file_leaves_none_behind(db_session_factory, tmp_path, monkeypatch):
    storage = LocalStorageProvider(tmp_path)
    user_id, workspace_id, _ = await _user_and_document(db_session_factory)
    job_id = await _add(db_session_factory, user_id, workspace_id, job_type=JobType.EXPORT.value)

    async def kind(ctx):
        await ctx.storage.put(f"jobs/{ctx.job_id}/output", b"PK", "application/pdf")
        raise RuntimeError("something after the write")

    monkeypatch.setitem(runner_module.KINDS, JobType.EXPORT.value, kind)

    await JobRunner(db_session_factory, storage, FakeAIProvider([])).run(job_id)

    job = await _load(db_session_factory, job_id)
    assert job.status == JobStatus.FAILED.value and job.result is None
    assert not (tmp_path / "jobs" / job_id / "output").exists()


# -- a job's upload never outlives the job ----------------------------------------------


class _FailingDeletes(LocalStorageProvider):
    """A storage that can't delete (an outage) until `working` is set."""

    working = False

    async def delete(self, key: str) -> None:
        if not self.working:
            raise ConnectionError("storage is down")
        await super().delete(key)


@pytest.mark.parametrize(
    "fields",
    [
        {"status": JobStatus.SUCCEEDED.value},
        {"status": JobStatus.FAILED.value},
        {"status": JobStatus.CANCELLED.value},
        {"status": JobStatus.FAILED.value, "dead_letter": True, "failure_reason": "stuck"},
        {"status": JobStatus.FAILED.value, "dead_letter": True, "created_at": _LONG_AGO},  # retention never removes a dead letter
    ],
    ids=["succeeded", "failed", "cancelled", "dead-letter", "old-dead-letter"],
)
async def test_the_upload_of_a_finished_job_is_deleted_again_if_it_was_left_behind(db_session_factory, tmp_path, fields):
    storage = _FailingDeletes(tmp_path)
    user_id, workspace_id, _ = await _user_and_document(db_session_factory)
    await storage.put("jobs/left/input", b"the user's file", "application/octet-stream")
    job_id = await _add(db_session_factory, user_id, workspace_id, input_key="jobs/left/input", **fields)

    await sweep_job_files(db_session_factory, storage)  # the delete fails: the file is still there, and still recorded
    assert (tmp_path / "jobs" / "left" / "input").exists()
    assert (await _load(db_session_factory, job_id)).input_key == "jobs/left/input"

    storage.working = True
    await sweep_job_files(db_session_factory, storage)

    assert not (tmp_path / "jobs" / "left" / "input").exists()
    job = await _load(db_session_factory, job_id)
    assert job is not None and job.input_key is None  # nothing refers to a file that is gone


async def test_the_upload_of_a_job_that_has_not_finished_is_left_alone(db_session_factory, tmp_path):
    storage = LocalStorageProvider(tmp_path)
    user_id, workspace_id, _ = await _user_and_document(db_session_factory)
    for status in (JobStatus.PENDING.value, JobStatus.RUNNING.value):
        await storage.put(f"jobs/{status}/input", b"file", "application/octet-stream")
        await _add(db_session_factory, user_id, workspace_id, status=status, input_key=f"jobs/{status}/input")

    await sweep_job_files(db_session_factory, storage)

    assert (tmp_path / "jobs" / "pending" / "input").exists() and (tmp_path / "jobs" / "running" / "input").exists()


# -- the original Word file: as long as the document, unless the owner sets a time ---------


async def _kept_originals(session_factory, storage: StorageProvider):
    """A workspace with a document whose original is 40 days old, one whose original is
    10 days old, and a picture of 40 days that a document shows."""
    async with session_factory() as session:
        auth = AuthService(session)
        user = await auth.register("owner@example.com", _PASSWORD, None)
        workspace_id = await auth.default_workspace_id(user.id)
        ids = {}
        for name, age in {"old": timedelta(days=40), "recent": timedelta(days=10)}.items():
            asset = DocumentAsset(
                workspace_id=workspace_id, storage_key="", content_type=DOCX_CONTENT_TYPE, size_bytes=4,
                original_filename=f"{name}.docx", created_at=datetime.now(timezone.utc) - age,
            )
            session.add(asset)
            await session.flush()
            asset.storage_key = f"{workspace_id}/{asset.id}"
            await storage.put(asset.storage_key, b"DOCX", DOCX_CONTENT_TYPE)
            document = Document(metadata=DocumentMetadata(title=name), sourcePackage=SourcePackage(assetId=asset.id, sha256="0" * 64, size=4))
            await DocumentRepository(session).create(workspace_id, document)
            ids[name] = (asset.id, document)
        await session.commit()
        return user.id, workspace_id, ids


async def test_by_default_the_original_stays_as_long_as_its_document(db_session_factory, tmp_path):
    storage = LocalStorageProvider(tmp_path)
    _, workspace_id, ids = await _kept_originals(db_session_factory, storage)
    assert get_settings().kept_original_retention_days == 0

    assert await sweep_unused_assets(db_session_factory, storage) == 0

    assert all((tmp_path / workspace_id / asset_id).exists() for asset_id, _ in ids.values())


async def test_with_a_time_set_an_older_original_goes_and_its_export_says_so(db_session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "kept_original_retention_days", 30)
    storage = LocalStorageProvider(tmp_path)
    user_id, workspace_id, ids = await _kept_originals(db_session_factory, storage)
    (old_id, old_document), (recent_id, recent_document) = ids["old"], ids["recent"]

    assert await sweep_unused_assets(db_session_factory, storage) == 1

    assert not (tmp_path / workspace_id / old_id).exists() and (tmp_path / workspace_id / recent_id).exists()
    async with db_session_factory() as session:
        remaining = set((await session.scalars(select(DocumentAsset.id))).all())
        assert remaining == {recent_id}
        service = DocumentService(session, user_id=user_id, storage=storage)
        # The document stays; the export is written without the original and says why.
        assert (await service.source_package(old_document)) == (None, "The original Word file this document came from is no longer stored.")
        assert (await service.source_package(recent_document))[1] != "The original Word file this document came from is no longer stored."


async def test_a_picture_is_never_taken_by_the_time_set_for_originals(db_session_factory, tmp_path, monkeypatch):
    from app.models.document import Element, ElementType, ImageContent

    monkeypatch.setattr(get_settings(), "kept_original_retention_days", 30)
    storage = LocalStorageProvider(tmp_path)
    user_id, workspace_id, _ = await _user_and_document(db_session_factory)
    async with db_session_factory() as session:
        picture = DocumentAsset(
            workspace_id=workspace_id, storage_key="", content_type="image/png", size_bytes=3, created_at=_LONG_AGO
        )
        session.add(picture)
        await session.flush()
        picture.storage_key = f"{workspace_id}/{picture.id}"
        await storage.put(picture.storage_key, b"PNG", "image/png")
        shown = Document(
            metadata=DocumentMetadata(title="Shown"),
            elements=[Element(type=ElementType.IMAGE, content="", image=ImageContent(src="", assetId=picture.id), order=0)],
        )
        await DocumentRepository(session).create(workspace_id, shown)
        await session.commit()

    assert await sweep_unused_assets(db_session_factory, storage) == 0

    assert (tmp_path / workspace_id / picture.id).exists()


# -- helpers -------------------------------------------------------------------------------


async def _user_and_document(factory) -> tuple[str, str, str]:
    async with factory() as session:
        auth = AuthService(session)
        user = await auth.register("jobs@example.com", _PASSWORD, None)
        workspace_id = await auth.default_workspace_id(user.id)
        document = Document(metadata=DocumentMetadata(title="Kept"))
        await DocumentRepository(session).create(workspace_id, document)
        await session.commit()
        return user.id, workspace_id, document.id


async def _add(factory, user_id: str, workspace_id: str, **fields) -> str:
    async with factory() as session:
        row = ProcessingJob(**{"workspace_id": workspace_id, "created_by": user_id, "job_type": JobType.IMPORT_FILE.value, "payload": {}} | fields)
        session.add(row)
        await session.commit()
        return row.id


async def _load(factory, job_id: str) -> ProcessingJob | None:
    async with factory() as session:
        return await session.get(ProcessingJob, job_id)
