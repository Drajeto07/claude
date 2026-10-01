"""How undo steps are stored (PERF-004, services/version_history.py): compressed,
pictures as asset references only, bounded in bytes as well as in steps, and
read back exactly as before -- rows written before compression included."""

import asyncio
import base64
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.models import DocumentAsset, DocumentVersion, WorkspaceMember
from app.db.models import Document as DocumentRow
from app.main import app
from app.services.asset_cleanup import sweep_unused_assets
from app.services.usage_service import storage_bytes
from app.storage.local_provider import LocalStorageProvider

_FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "12-complex.docx"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def client(api_db):
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/register", json={"email": "owner@example.com", "password": "long enough password"}).status_code == 201
    return client


def _create(client) -> dict:
    response = client.post("/api/v1/documents", json={"text": "# Start\n\nThe original paragraph of text."})
    assert response.status_code == 201
    return response.json()


def _rename(client, document_id: str, title: str) -> dict:
    response = client.patch(f"/api/v1/documents/{document_id}", json={"title": title})
    assert response.status_code == 200
    return response.json()


def _numbers(client, document_id: str) -> list[int]:
    return [version["number"] for version in client.get(f"/api/v1/documents/{document_id}/versions").json()]


def _rows(api_db, document_id: str) -> list[DocumentVersion]:
    with OrmSession(api_db, expire_on_commit=False) as db:
        return list(
            db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(DocumentVersion.revision_number))
        )


def _png() -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (4, 4), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _picture(order: int) -> dict:
    return {"type": "image", "content": "", "order": order, "image": {"src": "data:image/png;base64," + base64.b64encode(_png()).decode()}}


def _as_legacy(api_db, document_id: str) -> None:
    """Rewrites the document's versions the way they were stored before PERF-004."""
    with OrmSession(api_db) as db:
        for version in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document_id)):
            data = version.data
            version.compressed_data, version.legacy_data = None, data
        db.commit()


def _without(document: dict, *keys: str) -> dict:
    document = json.loads(json.dumps(document))
    for key in keys:
        document.pop(key, None)
    document["metadata"].pop("updatedAt", None)
    return document


# --- compression --------------------------------------------------------------


def test_a_version_of_the_complex_fixture_is_stored_at_least_3x_smaller(api_db, client):
    imported = client.post("/api/v1/documents/upload", files={"file": ("complex.docx", _FIXTURE.read_bytes(), _DOCX)})
    assert imported.status_code == 201

    (version,) = _rows(api_db, imported.json()["id"])
    # What the row held before PERF-004: the JSON text the column stored.
    uncompressed = len(json.dumps(version.data))
    stored = version.stored_bytes

    assert version.legacy_data is None and stored == len(version.compressed_data)
    assert uncompressed / stored >= 3, (uncompressed, stored)
    # Numbers for docs/cloud-reports/PERF-004.md.
    print(f"\n12-complex.docx version: {uncompressed} bytes as JSON, {stored} bytes stored ({uncompressed / stored:.1f}x)")


def test_undo_redo_and_restore_give_back_exactly_the_states_that_were_saved(client):
    document = _create(client)
    states = [client.get(f"/api/v1/documents/{document['id']}").json()]
    states.append(_rename(client, document["id"], "Ünïcode and кирилица"))
    elements = json.loads(json.dumps(states[-1]["elements"]))
    elements[1]["content"] = elements[1]["inline"][0]["text"] = "Edited text."
    states.append(client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": elements}).json())

    for expected in reversed(states[:-1]):
        assert _without(client.post(f"/api/v1/documents/{document['id']}/undo").json(), "revision") == _without(expected, "revision")
    assert client.post(f"/api/v1/documents/{document['id']}/undo").status_code == 400
    for expected in states[1:]:
        assert _without(client.post(f"/api/v1/documents/{document['id']}/redo").json(), "revision") == _without(expected, "revision")
    assert client.post(f"/api/v1/documents/{document['id']}/redo").status_code == 400

    viewed = client.get(f"/api/v1/documents/{document['id']}/versions/2").json()
    assert _without(viewed, "revision") == _without(states[1], "revision")
    restored = client.post(f"/api/v1/documents/{document['id']}/versions/2/restore").json()
    assert _without(restored, "revision") == _without(states[1], "revision")
    assert _without(client.post(f"/api/v1/documents/{document['id']}/undo").json(), "revision") == _without(states[2], "revision")


# --- rows from before compression ---------------------------------------------


def test_versions_stored_before_compression_still_read_and_new_ones_are_compressed(api_db, client, monkeypatch):
    monkeypatch.setattr(get_settings(), "document_history_max_steps", 50)
    document = _create(client)
    _rename(client, document["id"], "Second")
    _rename(client, document["id"], "Third")
    _as_legacy(api_db, document["id"])
    assert all(row.compressed_data is None and row.legacy_data for row in _rows(api_db, document["id"]))

    assert client.get(f"/api/v1/documents/{document['id']}/versions/1").json()["metadata"]["title"] == document["metadata"]["title"]
    assert client.get(f"/api/v1/documents/{document['id']}/compare", params={"from": 1}).status_code == 200
    assert client.post(f"/api/v1/documents/{document['id']}/undo").json()["metadata"]["title"] == "Second"
    assert client.post(f"/api/v1/documents/{document['id']}/redo").json()["metadata"]["title"] == "Third"
    assert client.post(f"/api/v1/documents/{document['id']}/versions/1/restore").json()["metadata"]["title"] == document["metadata"]["title"]

    rows = _rows(api_db, document["id"])
    assert [row.compressed_data is not None for row in rows] == [False, False, False, True]
    assert client.post(f"/api/v1/documents/{document['id']}/undo").json()["metadata"]["title"] == "Third"


def test_an_autosave_merged_into_an_uncompressed_step_rewrites_it_compressed(api_db, client):
    document = _create(client)
    elements = document["elements"]
    elements[1]["content"] = elements[1]["inline"][0]["text"] = "First words."
    client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": elements})
    _as_legacy(api_db, document["id"])

    elements[1]["content"] = elements[1]["inline"][0]["text"] = "First words, and more."
    client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": elements})

    merged = _rows(api_db, document["id"])[-1]
    assert merged.legacy_data is None and merged.data["elements"][1]["content"] == "First words, and more."


# --- the bound ----------------------------------------------------------------


def test_with_no_room_the_original_the_current_step_and_the_one_below_it_stay(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "document_history_max_bytes", 0)
    document = _create(client)
    for index in range(5):
        _rename(client, document["id"], f"Title {index}")

    assert _numbers(client, document["id"]) == [6, 5, 1]
    # The last change can still be undone and redone, and the original restored.
    assert client.post(f"/api/v1/documents/{document['id']}/undo").json()["metadata"]["title"] == "Title 3"
    assert client.post(f"/api/v1/documents/{document['id']}/undo").status_code == 400
    assert client.post(f"/api/v1/documents/{document['id']}/redo").json()["metadata"]["title"] == "Title 4"
    restored = client.post(f"/api/v1/documents/{document['id']}/versions/1/restore").json()
    assert restored["metadata"]["title"] == document["metadata"]["title"]
    # ... and that restore can be undone.
    assert client.post(f"/api/v1/documents/{document['id']}/undo").json()["metadata"]["title"] == "Title 4"


def test_an_autosave_merging_into_the_current_step_keeps_the_one_below_it(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "document_history_max_bytes", 0)
    document = _create(client)
    _rename(client, document["id"], "Renamed")
    elements = document["elements"]
    for text in ("Typing.", "Typing, merged into the same step."):
        elements[1]["content"] = elements[1]["inline"][0]["text"] = text
        assert client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": elements}).status_code == 200

    assert _numbers(client, document["id"]) == [3, 2, 1]
    assert client.post(f"/api/v1/documents/{document['id']}/undo").json()["metadata"]["title"] == "Renamed"


def test_an_autosave_growing_the_current_step_past_the_bytes_trims_the_oldest(api_db, client, monkeypatch):
    document = _create(client)
    for index in range(3):
        _rename(client, document["id"], f"Title {index}")
    elements = document["elements"]
    elements[1]["content"] = elements[1]["inline"][0]["text"] = "Short."
    client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": elements})
    assert _numbers(client, document["id"]) == [5, 4, 3, 2, 1]
    monkeypatch.setattr(get_settings(), "document_history_max_bytes", sum(row.stored_bytes for row in _rows(api_db, document["id"])) + 1000)

    # Random text hardly compresses: the merged step grows by far more than the room left.
    long = base64.b64encode(os.urandom(6000)).decode()
    elements[1]["content"] = elements[1]["inline"][0]["text"] = long
    client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": elements})

    assert _numbers(client, document["id"]) == [5, 4, 1]


def test_history_past_its_bytes_loses_its_oldest_steps_in_one_cut(api_db, client, monkeypatch):
    document = _create(client)
    _rename(client, document["id"], "Title 0")
    step = _rows(api_db, document["id"])[-1].stored_bytes
    original = _rows(api_db, document["id"])[0].stored_bytes
    # Room for the original and about four steps.
    monkeypatch.setattr(get_settings(), "document_history_max_bytes", original + 4 * step + step // 2)
    for index in range(1, 9):
        _rename(client, document["id"], f"Title {index}")

    rows = _rows(api_db, document["id"])
    numbers = [row.revision_number for row in rows]
    assert numbers[0] == 1 and numbers[-1] == 10
    kept_steps = numbers[1:]
    assert kept_steps == list(range(kept_steps[0], 11))  # no gap: undo walks all of them
    assert 3 <= len(kept_steps) <= 5
    assert sum(row.stored_bytes for row in rows) <= get_settings().document_history_max_bytes
    for _ in range(len(kept_steps) - 1):
        assert client.post(f"/api/v1/documents/{document['id']}/undo").status_code == 200
    assert client.post(f"/api/v1/documents/{document['id']}/undo").status_code == 400


def test_undo_and_redo_never_trim_the_history(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "document_history_max_bytes", 0)
    document = _create(client)
    for index in range(3):
        _rename(client, document["id"], f"Title {index}")
    before = _numbers(client, document["id"])

    client.post(f"/api/v1/documents/{document['id']}/undo")
    client.post(f"/api/v1/documents/{document['id']}/redo")
    client.post(f"/api/v1/documents/{document['id']}/undo")

    assert _numbers(client, document["id"]) == before
    assert client.post(f"/api/v1/documents/{document['id']}/redo").json()["metadata"]["title"] == "Title 2"


def test_by_default_a_real_documents_history_is_bounded_by_steps_not_bytes(api_db, client):
    imported = client.post("/api/v1/documents/upload", files={"file": ("complex.docx", _FIXTURE.read_bytes(), _DOCX)}).json()
    for index in range(10):
        _rename(client, imported["id"], f"Title {index}")

    assert len(_rows(api_db, imported["id"])) == 11


# --- pictures -----------------------------------------------------------------


def test_a_picture_still_inline_in_an_old_document_reaches_no_version(api_db, client):
    document = _create(client)
    with OrmSession(api_db) as db:  # a document saved before pictures (nested ones too) moved into storage
        row = db.get(DocumentRow, document["id"])
        data = json.loads(json.dumps(row.data))
        data["elements"].append(_picture(len(data["elements"])))
        data["elements"][0]["children"] = [_picture(0)]
        db.execute(update(DocumentRow).where(DocumentRow.id == document["id"]).values(data=data))
        db.query(DocumentVersion).delete()  # and from before version history: its base step is that state
        db.commit()

    _rename(client, document["id"], "Renamed")

    rows = _rows(api_db, document["id"])
    assert len(rows) == 2
    assert not any("data:image" in json.dumps(row.data) for row in rows)
    assert "data:image" not in client.get(f"/api/v1/documents/{document['id']}").text
    undone = client.post(f"/api/v1/documents/{document['id']}/undo").json()
    pictures = [undone["elements"][-1]["image"], undone["elements"][0]["children"][0]["image"]]
    assert all(picture["assetId"] and picture["src"] == "" for picture in pictures)
    with OrmSession(api_db) as db:
        assets = set(db.scalars(select(DocumentAsset.id)))
    assert {picture["assetId"] for picture in pictures} <= assets


def test_the_asset_sweep_keeps_a_picture_only_a_compressed_version_shows(api_db, client, tmp_path):
    document = _create(client)
    with_picture = client.put(
        f"/api/v1/documents/{document['id']}/content", json={"elements": document["elements"] + [_picture(len(document["elements"]))]}
    ).json()
    asset_id = with_picture["elements"][-1]["image"]["assetId"]
    client.patch(f"/api/v1/documents/{document['id']}", json={"title": "Separate step"})
    client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": with_picture["elements"][:-1]})
    with OrmSession(api_db) as db:
        db.execute(update(DocumentAsset).values(created_at=datetime.now(timezone.utc) - timedelta(days=3)))
        db.commit()
    rows = _rows(api_db, document["id"])
    assert any(asset_id in json.dumps(row.data) for row in rows)
    # Only a scan that decompresses the versions can see it.
    assert not any(asset_id.encode() in row.compressed_data for row in rows)

    async def sweep() -> int:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}", poolclass=NullPool)
        try:
            return await sweep_unused_assets(async_sessionmaker(engine, expire_on_commit=False), LocalStorageProvider(tmp_path / "assets"))
        finally:
            await engine.dispose()

    assert asyncio.run(sweep()) == 0
    assert client.post(f"/api/v1/documents/{document['id']}/undo").json()["elements"][-1]["image"]["assetId"] == asset_id
    assert client.get(f"/api/assets/{asset_id}").status_code == 200

    _as_legacy(api_db, document["id"])  # versions from before compression are scanned too
    assert asyncio.run(sweep()) == 0


# --- metering -----------------------------------------------------------------


def test_storage_counts_the_versions_as_they_are_stored(api_db, client):
    document = _create(client)
    for index in range(3):
        _rename(client, document["id"], f"Title {index}")
    rows = _rows(api_db, document["id"])
    with OrmSession(api_db) as db:
        workspace_id = db.scalars(select(WorkspaceMember.workspace_id)).one()
        document_text = len(json.dumps(db.get(DocumentRow, document["id"]).data))

    async def measured() -> int:
        engine = create_async_engine(f"sqlite+aiosqlite:///{api_db.url.database}", poolclass=NullPool)
        try:
            async with async_sessionmaker(engine)() as session:
                return await storage_bytes(session, workspace_id)
        finally:
            await engine.dispose()

    compressed = sum(len(row.compressed_data) for row in rows)
    assert asyncio.run(measured()) == document_text + compressed
    assert client.get("/api/v1/usage").json()["storageBytes"] == document_text + compressed
    # Counted as stored: a version from before compression counts as its JSON.
    _as_legacy(api_db, document["id"])
    assert asyncio.run(measured()) == document_text + sum(len(json.dumps(row.data)) for row in rows)
