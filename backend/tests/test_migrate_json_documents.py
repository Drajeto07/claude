import base64

import pytest

from app.db.models import Document as DocumentRow
from app.models.document import Document, DocumentMetadata, Element, ElementType, ImageContent
from app.repositories.document_repository import DocumentRepository
from app.services import persistence
from app.services.asset_service import AssetService
from app.services.auth_service import AuthService
from app.storage.local_provider import LocalStorageProvider
from scripts.migrate_json_documents import migrate

_OWNER = "owner@example.com"


def _seed_json_document(title: str) -> Document:
    document = Document(metadata=DocumentMetadata(title=title))
    persistence.save_document(document)
    return document


async def _register_owner(session_factory) -> tuple[str, str]:
    async with session_factory() as session:
        service = AuthService(session)
        user = await service.register(_OWNER, "long enough password", None)
        return user.id, await service.default_workspace_id(user.id)


async def test_migrate_attaches_documents_to_the_owners_workspace(db_session_factory):
    user_id, workspace_id = await _register_owner(db_session_factory)
    doc_a = _seed_json_document("First")
    doc_b = _seed_json_document("Second")

    await migrate(owner_email="OWNER@example.com", dry_run=False, session_factory=db_session_factory)

    async with db_session_factory() as session:
        assert {d.id for d in await DocumentRepository(session).list_for_workspace(workspace_id)} == {doc_a.id, doc_b.id}
        assert (await session.get(DocumentRow, doc_a.id)).created_by == user_id
        # And the owner can actually open them through the same access check the API uses.
        assert (await DocumentRepository(session).get_for_user(doc_a.id, user_id)).id == doc_a.id

    # Source files must survive the migration untouched (doc §70).
    assert persistence.load_all_documents().keys() == {doc_a.id, doc_b.id}


async def test_migrate_is_idempotent_on_rerun(db_session_factory):
    _, workspace_id = await _register_owner(db_session_factory)
    document = _seed_json_document("Once")

    await migrate(owner_email=_OWNER, dry_run=False, session_factory=db_session_factory)
    await migrate(owner_email=_OWNER, dry_run=False, session_factory=db_session_factory)  # must not raise or duplicate

    async with db_session_factory() as session:
        assert [d.id for d in await DocumentRepository(session).list_for_workspace(workspace_id)] == [document.id]


async def test_dry_run_writes_nothing(db_session_factory):
    _, workspace_id = await _register_owner(db_session_factory)
    _seed_json_document("Not migrated yet")

    await migrate(owner_email=_OWNER, dry_run=True, session_factory=db_session_factory)

    async with db_session_factory() as session:
        assert await DocumentRepository(session).list_for_workspace(workspace_id) == []


async def test_legacy_inline_images_are_moved_into_asset_storage(db_session_factory, tmp_path):
    user_id, _ = await _register_owner(db_session_factory)
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(64))
    document = Document(
        metadata=DocumentMetadata(title="With a figure"),
        elements=[
            Element(
                type=ElementType.IMAGE,
                content="",
                order=0,
                image=ImageContent(src="data:image/png;base64," + base64.b64encode(png).decode()),
            )
        ],
    )
    persistence.save_document(document)
    storage = LocalStorageProvider(tmp_path / "assets")

    await migrate(owner_email=_OWNER, dry_run=False, session_factory=db_session_factory, storage=storage)

    async with db_session_factory() as session:
        migrated = await DocumentRepository(session).get_for_user(document.id, user_id)
        image = migrated.elements[0].image
        assert image.assetId and image.src == ""
        _, data = await AssetService(session, storage).read_for_user(image.assetId, user_id)
    assert data == png


async def test_unknown_owner_stops_before_writing_anything(db_session_factory):
    _seed_json_document("Orphan")

    with pytest.raises(SystemExit, match="register in the app first"):
        await migrate(owner_email="nobody@example.com", dry_run=False, session_factory=db_session_factory)
