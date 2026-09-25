from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.models import Base, DocumentVersion
from app.db.models import Document as DocumentRow
from app.main import app
from app.models.document import Document, DocumentMetadata
from app.services import document_service as document_service_module
from app.services import version_history
from app.services.auth_service import AuthService
from app.services.document_service import DocumentService, RevisionConflictError
from app.storage.local_provider import LocalStorageProvider
from tests.conftest import _enable_sqlite_fk


@pytest.fixture
def client(api_db):
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/auth/register", json={"email": "owner@example.com", "password": "long enough password"}).status_code == 201
    return client


def _create(client) -> dict:
    response = client.post("/api/documents", json={"text": "# Start\n\nThe original paragraph of text."})
    assert response.status_code == 201
    return response.json()


def _rename(client, document_id: str, title: str, if_match=None):
    headers = {"If-Match": str(if_match)} if if_match is not None else {}
    return client.patch(f"/api/documents/{document_id}", json={"title": title}, headers=headers)


def _versions_in_db(api_db, document_id: str) -> int:
    with OrmSession(api_db) as db:
        return db.execute(
            select(func.count()).select_from(DocumentVersion).where(DocumentVersion.document_id == document_id)
        ).scalar_one()


def test_every_write_bumps_the_revision_and_every_read_reports_it(client):
    document = _create(client)
    assert document["revision"] == 1

    renamed = _rename(client, document["id"], "Renamed").json()

    assert renamed["revision"] == 2
    assert client.get(f"/api/documents/{document['id']}").json()["revision"] == 2


def test_a_stale_if_match_is_rejected_and_nothing_is_written(client):
    document = _create(client)
    assert _rename(client, document["id"], "First edit", if_match=1).status_code == 200

    stale = _rename(client, document["id"], "Edit from an outdated tab", if_match=1)

    assert stale.status_code == 412
    assert stale.json()["details"]["currentRevision"] == 2
    assert client.get(f"/api/documents/{document['id']}").json()["metadata"]["title"] == "First edit"


@pytest.mark.parametrize("header", ['"1"', 'W/"1"', "1"])
def test_if_match_accepts_plain_quoted_and_weak_etag_forms(client, header):
    document = _create(client)

    response = client.patch(f"/api/documents/{document['id']}", json={"title": "x"}, headers={"If-Match": header})

    assert response.status_code == 200


def test_malformed_if_match_is_a_bad_request(client):
    document = _create(client)

    assert _rename(client, document["id"], "x", if_match="yesterday").status_code == 400


def test_undo_history_lives_in_the_database(api_db, client):
    document = _create(client)
    _rename(client, document["id"], "Second")
    _rename(client, document["id"], "Third")

    assert _versions_in_db(api_db, document["id"]) == 3  # created + two changes
    undone = client.post(f"/api/documents/{document['id']}/undo").json()
    assert undone["metadata"]["title"] == "Second"


def test_a_burst_of_autosaves_is_one_undo_step(client):
    document = _create(client)
    elements = document["elements"]
    for text in ("The original paragraph of text. More", "The original paragraph of text. More words", "The original paragraph of text. More words here"):
        elements[1]["content"] = text
        elements[1]["inline"] = [{"text": text, "marks": []}]
        assert client.put(f"/api/documents/{document['id']}/content", json={"elements": elements}).status_code == 200

    undone = client.post(f"/api/documents/{document['id']}/undo").json()

    assert undone["elements"][1]["content"] == "The original paragraph of text."


def test_autosaves_outside_the_merge_window_are_separate_steps(client, monkeypatch):
    monkeypatch.setattr(version_history, "CONTENT_MERGE_WINDOW", timedelta(0))
    document = _create(client)
    elements = document["elements"]
    for text in ("First draft sentence.", "Second draft sentence."):
        elements[1]["content"] = text
        elements[1]["inline"] = [{"text": text, "marks": []}]
        client.put(f"/api/documents/{document['id']}/content", json={"elements": elements})

    undone = client.post(f"/api/documents/{document['id']}/undo").json()

    assert undone["elements"][1]["content"] == "First draft sentence."


def test_history_depth_is_the_configured_one_plus_the_original(api_db, client, monkeypatch):
    monkeypatch.setattr(get_settings(), "document_history_max_steps", 3)
    document = _create(client)
    for index in range(5):
        _rename(client, document["id"], f"Title {index}")

    # The last 3 steps, and the original (never trimmed, for before/after).
    assert _versions_in_db(api_db, document["id"]) == 3 + 1
    assert [version["number"] for version in client.get(f"/api/documents/{document['id']}/versions").json()] == [6, 5, 4, 1]
    assert client.post(f"/api/documents/{document['id']}/undo").status_code == 200
    assert client.post(f"/api/documents/{document['id']}/undo").status_code == 200
    # Undo walks back through consecutive steps only; the original is reached by restoring it.
    assert client.post(f"/api/documents/{document['id']}/undo").status_code == 400


def test_a_new_change_after_undo_drops_the_redo_branch(client):
    document = _create(client)
    _rename(client, document["id"], "A")
    _rename(client, document["id"], "B")
    client.post(f"/api/documents/{document['id']}/undo")

    _rename(client, document["id"], "C")

    assert client.post(f"/api/documents/{document['id']}/redo").status_code == 400
    assert client.post(f"/api/documents/{document['id']}/undo").json()["metadata"]["title"] == "A"


def test_a_document_from_before_version_history_can_still_be_undone(api_db, client):
    document = _create(client)
    with OrmSession(api_db) as db:  # simulate a row written before history existed
        db.query(DocumentVersion).delete()
        db.commit()

    _rename(client, document["id"], "Changed")

    assert client.post(f"/api/documents/{document['id']}/undo").json()["metadata"]["title"] == document["metadata"]["title"]


async def test_two_writes_racing_on_the_same_revision_cannot_both_win(tmp_path, monkeypatch):
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'race.db'}"
    sync_engine = create_engine(db_url.replace("+aiosqlite", ""))
    Base.metadata.create_all(sync_engine)
    engine = create_async_engine(db_url, poolclass=NullPool)
    event.listen(engine.sync_engine, "connect", _enable_sqlite_fk)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    storage = LocalStorageProvider(tmp_path / "assets")

    async with sessions() as setup:
        user = await AuthService(setup).register("racer@example.com", "long enough password", None)
        document = await DocumentService(setup, user_id=user.id, storage=storage).create(
            Document(metadata=DocumentMetadata(title="Original"))
        )

    async with sessions() as first, sessions() as second:
        winner = DocumentService(first, user_id=user.id, storage=storage)
        loser = DocumentService(second, user_id=user.id, storage=storage)

        # Commit the winner's write *inside* the loser's load-to-write window: the
        # loser has already loaded revision 1 when this runs (a step update_content
        # awaits mid-change), exactly like two requests interleaving on a server.
        real_step = document_service_module.externalize_inline_images

        async def winner_commits_first(*args, **kwargs):
            await winner.rename(document.id, title="Winner")
            return await real_step(*args, **kwargs)

        monkeypatch.setattr(document_service_module, "externalize_inline_images", winner_commits_first)
        with pytest.raises(RevisionConflictError):
            await loser.update_content(document.id, elements=[])

    async with sessions() as check:
        row = await check.get(DocumentRow, document.id)
        assert row.data["metadata"]["title"] == "Winner"
        assert row.revision == 2
    await engine.dispose()
    sync_engine.dispose()
