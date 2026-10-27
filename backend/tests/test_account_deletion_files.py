"""What deleting an account leaves in storage (B-040): every file derived from the deleted workspaces' documents goes
-- the project thumbnails and their revision markers, pictures, kept originals, job files, unfinished uploads -- and
nothing of a workspace that stays (another user's, or a shared one the user only leaves). Files go only after the rows
are committed; one that can't be deleted doesn't stop the others."""

import io
import logging
import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.db.models import Document as DocumentRow
from app.db.models import User, WorkspaceMember, WorkspaceRole
from app.jobs import uploads
from app.main import app
from app.services.account_deletion import delete_files
from app.services.document_service import thumbnail_keys
from app.storage.local_provider import LocalStorageProvider

pytestmark = pytest.mark.security

_PASSWORD = "long enough password"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _register(email: str) -> tuple[TestClient, dict]:
    client = _client()
    me = client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    assert me.status_code == 201
    return client, me.json()


def _document_with_thumbnail(client: TestClient, title: str) -> str:
    document = client.post("/api/v1/documents", json={"text": f"# {title}\n\nA private paragraph of {title}."}).json()
    assert client.get(f"/api/v1/documents/{document['id']}/thumbnail?v=1").status_code == 200
    return document["id"]


def _docx() -> bytes:
    doc = DocxDocument()
    doc.add_paragraph("A kept original.")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _thumbnail_files(root, document_id: str) -> list:
    return [root / key for key in thumbnail_keys(document_id)]


def _delete(client: TestClient):
    return client.request("DELETE", "/api/v1/auth/account", json={"password": _PASSWORD})


@pytest.fixture
def root(api_db, tmp_path):
    return tmp_path / "assets"


def test_the_thumbnails_and_their_markers_of_every_deleted_document_go_and_others_stay(api_db, root):
    frank, _ = _register("frank@example.com")
    grace, _ = _register("grace@example.com")
    franks = [_document_with_thumbnail(frank, f"Frank {n}") for n in range(3)]
    graces = [_document_with_thumbnail(grace, "Grace")]
    for document_id in franks + graces:
        assert all(path.exists() for path in _thumbnail_files(root, document_id))  # the drawing and its revision marker

    assert _delete(frank).status_code == 204

    for document_id in franks:
        assert not [path for path in _thumbnail_files(root, document_id) if path.exists()], document_id
    assert all(path.exists() for path in _thumbnail_files(root, graces[0]))
    assert grace.get(f"/api/v1/documents/{graces[0]}/thumbnail?v=1").status_code == 200


def test_pictures_kept_originals_and_job_files_still_go_with_the_thumbnails(api_db, root):
    frank, me = _register("frank@example.com")
    document_id = _document_with_thumbnail(frank, "Frank")
    imported = frank.post("/api/v1/jobs/import-file", files={"file": ("report.docx", _docx(), _DOCX)}).json()
    exported = frank.post("/api/v1/jobs/export", json={"documentId": document_id, "format": "docx"}).json()
    assert imported["status"] == exported["status"] == "succeeded"
    workspace_files = [path for path in (root / me["workspaceId"]).rglob("*") if path.is_file()]
    job_files = [path for path in (root / "jobs").rglob("*") if path.is_file()] if (root / "jobs").exists() else []
    assert workspace_files  # the kept original (and any picture) under the workspace

    assert _delete(frank).status_code == 204

    assert not [path for path in workspace_files + job_files if path.exists()]
    assert not [path for path in _thumbnail_files(root, document_id) if path.exists()]


def test_an_account_without_thumbnails_or_documents_is_deleted_as_before(api_db, root):
    frank, _ = _register("frank@example.com")
    frank.post("/api/v1/documents", json={"text": "# Never drawn\n\nNo thumbnail was ever asked for."})

    assert _delete(frank).status_code == 204
    assert frank.get("/api/v1/auth/me").status_code == 401


def test_a_shared_workspace_the_user_only_leaves_keeps_its_documents_thumbnails(api_db, root):
    """Frank is a member of Grace's workspace: his own workspace goes, hers -- and the thumbnail of the document he made
    there -- stays."""
    from sqlalchemy.orm import Session as OrmSession

    frank, frank_me = _register("frank@example.com")
    grace, grace_me = _register("grace@example.com")
    franks_own = _document_with_thumbnail(frank, "Frank's own")
    in_shared = _document_with_thumbnail(frank, "Made in Grace's workspace")
    with OrmSession(api_db) as db:
        db.add(WorkspaceMember(workspace_id=grace_me["workspaceId"], user_id=frank_me["id"], role=WorkspaceRole.MEMBER.value))
        db.execute(update(DocumentRow).where(DocumentRow.id == in_shared).values(workspace_id=grace_me["workspaceId"]))
        db.commit()

    assert _delete(frank).status_code == 204

    assert not [path for path in _thumbnail_files(root, franks_own) if path.exists()]
    assert all(path.exists() for path in _thumbnail_files(root, in_shared))
    assert grace.get(f"/api/v1/documents/{in_shared}/thumbnail?v=1").status_code == 200


def test_a_refused_deletion_deletes_no_file(api_db, root):
    """The policy refuses (an owner leaving others in a workspace without an owner): nothing is deleted, rows or files."""
    from sqlalchemy.orm import Session as OrmSession

    frank, frank_me = _register("frank@example.com")
    _, grace_me = _register("grace@example.com")
    document_id = _document_with_thumbnail(frank, "Frank")
    with OrmSession(api_db) as db:
        db.add(WorkspaceMember(workspace_id=frank_me["workspaceId"], user_id=grace_me["id"], role=WorkspaceRole.MEMBER.value))
        db.commit()

    refused = _delete(frank)

    assert refused.status_code == 409 and refused.json()["code"] == "workspace_has_members"
    assert all(path.exists() for path in _thumbnail_files(root, document_id))
    assert frank.get("/api/v1/auth/me").status_code == 200


def test_no_file_is_deleted_when_the_rows_can_t_be(api_db, root, monkeypatch):
    """Files go only after the commit: a deletion whose transaction fails part-way (here: deleting the user row, after
    the workspace's rows) is rolled back whole and leaves every file in place."""
    import app.services.account_deletion as account_deletion

    frank, _ = _register("frank@example.com")
    document_id = _document_with_thumbnail(frank, "Frank")
    deleted_keys: list[str] = []
    real_delete, real_statement = LocalStorageProvider.delete, account_deletion.delete

    async def recording_delete(self, key: str) -> None:
        deleted_keys.append(key)
        await real_delete(self, key)

    def failing_statement(table):
        if table is User:
            raise RuntimeError("database unavailable")
        return real_statement(table)

    monkeypatch.setattr(LocalStorageProvider, "delete", recording_delete)
    monkeypatch.setattr(account_deletion, "delete", failing_statement)

    assert _delete(frank).status_code == 500
    monkeypatch.undo()

    assert deleted_keys == []
    assert all(path.exists() for path in _thumbnail_files(root, document_id))
    assert frank.get("/api/v1/auth/me").status_code == 200
    assert frank.get(f"/api/v1/documents/{document_id}").status_code == 200


def test_an_unfinished_upload_of_the_deleted_workspace_goes_and_another_workspace_s_stays(api_db, root):
    import asyncio

    frank, frank_me = _register("frank@example.com")
    _, grace_me = _register("grace@example.com")
    storage = LocalStorageProvider(root)

    async def put() -> None:
        for workspace_id in (frank_me["workspaceId"], grace_me["workspaceId"]):
            await storage.put(f"{uploads.PREFIX}{workspace_id}/upload-1/session.json", b"{}", "application/json")
            await storage.put(f"{uploads.PREFIX}{workspace_id}/upload-1/part-00000", b"part", "application/octet-stream")

    asyncio.run(put())

    assert _delete(frank).status_code == 204

    franks_uploads = root / "uploads" / frank_me["workspaceId"]
    assert not [path for path in franks_uploads.rglob("*") if path.is_file()]
    assert (root / "uploads" / grace_me["workspaceId"] / "upload-1" / "part-00000").exists()


async def test_missing_and_failing_files_don_t_stop_the_rest_and_each_key_is_deleted_once(tmp_path, caplog):
    storage_root = tmp_path
    present = ["thumbnails/a.png", "thumbnails/a.rev", "ws/asset"]
    calls: list[str] = []

    class Flaky(LocalStorageProvider):
        async def delete(self, key: str) -> None:
            calls.append(key)
            if key == "thumbnails/a.rev":
                raise OSError("storage unreachable")
            await super().delete(key)

    storage = Flaky(storage_root)
    for key in present:
        await storage.put(key, b"x", "application/octet-stream")

    with caplog.at_level(logging.WARNING):
        deleted = await delete_files(storage, ["thumbnails/a.png", "thumbnails/a.rev", "thumbnails/gone.png", "ws/asset", "thumbnails/a.png"])

    assert sorted(calls) == sorted(["thumbnails/a.png", "thumbnails/a.rev", "thumbnails/gone.png", "ws/asset"])  # once each
    assert deleted == 3  # the missing one counts as deleted (deleting nothing is not an error); the failing one doesn't
    assert not (storage_root / "thumbnails" / "a.png").exists() and not (storage_root / "ws" / "asset").exists()
    assert (storage_root / "thumbnails" / "a.rev").exists()
    assert "thumbnails/a.rev" in caplog.text


async def test_cleanup_can_run_again_over_what_is_already_gone(tmp_path):
    storage = LocalStorageProvider(tmp_path)
    await storage.put("thumbnails/b.png", b"x", "image/png")
    keys = ["thumbnails/b.png", "thumbnails/b.rev"]

    assert await delete_files(storage, keys) == 2
    assert await delete_files(storage, keys) == 2  # a repeat (or a partial one finished later) is harmless
    assert not (tmp_path / "thumbnails" / "b.png").exists()


def test_the_cleanup_runs_after_the_answer_and_names_no_one(api_db, root, caplog):
    """The audit line counts the files; it names no person, document or key."""
    frank, frank_me = _register("frank@example.com")
    document_id = _document_with_thumbnail(frank, "Frank")

    with caplog.at_level(logging.INFO, logger="app.audit"):
        assert _delete(frank).status_code == 204

    [line] = [record for record in caplog.records if record.getMessage() == "auth.account_deleted"]
    text = " ".join(str(value) for value in vars(line).values())
    assert document_id not in text and frank_me["id"] not in text and "frank" not in text
    assert getattr(line, "files", 0) >= 2  # the thumbnail and its marker at least


def test_users_row_is_gone(api_db):
    from sqlalchemy.orm import Session as OrmSession

    frank, _ = _register("frank@example.com")
    _document_with_thumbnail(frank, "Frank")
    assert _delete(frank).status_code == 204
    with OrmSession(api_db) as db:
        assert db.scalar(select(User).where(User.email == "frank@example.com")) is None



async def test_only_one_workspace_s_uploads_folder_is_ever_listed(tmp_path, caplog):
    """The whole uploads folder, a deeper path or another folder is never listed or emptied, whatever is asked."""
    storage = LocalStorageProvider(tmp_path)
    for key in ("uploads/ws-a/u1/part-00000", "uploads/ws-ab/u1/part-00000", "uploads/ws-b/u1/part-00000", "thumbnails/x.png"):
        await storage.put(key, b"x", "application/octet-stream")
    asked: list[str] = []

    class Recording(LocalStorageProvider):
        async def list(self, prefix: str):
            asked.append(prefix)
            return await super().list(prefix)

    with caplog.at_level(logging.WARNING):
        deleted = await delete_files(Recording(tmp_path), [], ["uploads/", "uploads/ws-a", "thumbnails/", "uploads/ws-a/u1/", "uploads/ws-a/"])

    assert asked == ["uploads/ws-a/"]  # only the well-formed one
    assert deleted == 1
    assert not (tmp_path / "uploads" / "ws-a" / "u1" / "part-00000").exists()
    assert (tmp_path / "uploads" / "ws-ab" / "u1" / "part-00000").exists()  # a workspace whose id merely starts the same
    assert (tmp_path / "uploads" / "ws-b" / "u1" / "part-00000").exists()
    assert (tmp_path / "thumbnails" / "x.png").exists()
    assert "storage cleanup is incomplete: 1 deleted, 0 failed, 4 upload folders not listed" in caplog.text


async def test_keys_a_store_lists_outside_the_folder_are_never_deleted(tmp_path):
    storage = LocalStorageProvider(tmp_path)
    for key in ("uploads/ws-a/u1/part-00000", "uploads/ws-b/u1/part-00000"):
        await storage.put(key, b"x", "application/octet-stream")

    class Careless(LocalStorageProvider):
        async def list(self, prefix: str):
            return await super().list("uploads/")  # answers more than it was asked

    assert await delete_files(Careless(tmp_path), [], ["uploads/ws-a/"]) == 1
    assert (tmp_path / "uploads" / "ws-b" / "u1" / "part-00000").exists()


async def test_a_store_that_can_t_list_still_deletes_the_known_keys_and_says_the_cleanup_is_incomplete(tmp_path, caplog):
    from app.storage.base import StorageProvider

    class NoListing(StorageProvider):
        def __init__(self) -> None:
            self.deleted: list[str] = []

        async def put(self, key, data, content_type):
            pass

        async def get(self, key):
            raise AssertionError("not read")

        async def delete(self, key):
            self.deleted.append(key)

    storage = NoListing()
    with caplog.at_level(logging.WARNING):
        assert await delete_files(storage, ["thumbnails/a.png", "thumbnails/a.rev"], ["uploads/ws-a/"]) == 2

    assert storage.deleted == ["thumbnails/a.png", "thumbnails/a.rev"]
    assert "storage cleanup is incomplete: 2 deleted, 0 failed, 1 upload folders not listed" in caplog.text


async def test_a_complete_cleanup_logs_no_warning(tmp_path, caplog):
    storage = LocalStorageProvider(tmp_path)
    await storage.put("thumbnails/c.png", b"x", "image/png")
    with caplog.at_level(logging.WARNING):
        assert await delete_files(storage, ["thumbnails/c.png"], []) == 1
    assert "incomplete" not in caplog.text
