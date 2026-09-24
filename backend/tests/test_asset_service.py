import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Workspace
from app.services.asset_service import AssetService
from app.storage.local_provider import LocalStorageProvider

_PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256))


async def _workspace_id(db_session) -> str:
    workspace = Workspace(name="Acme", slug="acme")
    db_session.add(workspace)
    await db_session.flush()
    return workspace.id


async def test_store_then_read_round_trips_bytes_and_metadata(db_session, tmp_path):
    workspace_id = await _workspace_id(db_session)
    service = AssetService(db_session, LocalStorageProvider(tmp_path))

    asset = await service.store(workspace_id, _PNG, "image/png", original_filename="logo.png")
    await db_session.commit()
    db_session.expunge_all()

    stored = await service.read(asset.id)
    assert stored is not None
    row, data = stored
    assert data == _PNG
    assert (row.content_type, row.size_bytes, row.original_filename) == ("image/png", len(_PNG), "logo.png")
    assert row.storage_key == f"{workspace_id}/{asset.id}"


async def test_read_unknown_asset_returns_none(db_session, tmp_path):
    assert await AssetService(db_session, LocalStorageProvider(tmp_path)).read("does-not-exist") is None


async def test_failed_row_insert_removes_the_already_written_blob(db_session, tmp_path):
    service = AssetService(db_session, LocalStorageProvider(tmp_path))

    with pytest.raises(IntegrityError):
        await service.store("no-such-workspace", _PNG, "image/png")

    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []
