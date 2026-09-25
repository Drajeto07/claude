"""The daily sweep of images no document uses (services/asset_cleanup.py): an
asset is only deleted when nothing in its workspace can show it again."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import DocumentAsset, DocumentVersion, Workspace
from app.db.models import Document as DocumentRow
from app.models.document import Document, DocumentMetadata, Element, ElementType, ImageContent
from app.repositories.document_repository import DocumentRepository, dump_document
from app.services.asset_cleanup import sweep_unused_assets
from app.storage.local_provider import LocalStorageProvider

_OLD = datetime.now(timezone.utc) - timedelta(days=3)


def _with_image(asset_id: str | None, title: str = "Report") -> Document:
    elements = [Element(type=ElementType.PARAGRAPH, content="Text", order=0)]
    if asset_id:
        elements.append(Element(type=ElementType.IMAGE, content="", image=ImageContent(src="", assetId=asset_id), order=1))
    return Document(metadata=DocumentMetadata(title=title), elements=elements)


async def _workspace(session, slug: str) -> str:
    workspace = Workspace(name=slug, slug=slug)
    session.add(workspace)
    await session.flush()
    return workspace.id


async def _asset(session, storage, workspace_id: str, document_id: str | None, *, created_at: datetime = _OLD) -> str:
    asset = DocumentAsset(workspace_id=workspace_id, document_id=document_id, storage_key="", content_type="image/png", size_bytes=3, created_at=created_at)
    session.add(asset)
    await session.flush()
    asset.storage_key = f"{workspace_id}/{asset.id}"
    await storage.put(asset.storage_key, b"PNG", "image/png")
    return asset.id


async def test_only_images_nothing_can_show_again_are_deleted(db_session_factory, tmp_path):
    storage = LocalStorageProvider(tmp_path)
    async with db_session_factory() as session:
        repo = DocumentRepository(session)
        workspace = await _workspace(session, "acme")
        other_workspace = await _workspace(session, "other")

        in_use = _with_image(None)
        await repo.create(workspace, in_use)
        shown = await _asset(session, storage, workspace, in_use.id)
        in_history = await _asset(session, storage, workspace, in_use.id)
        unused = await _asset(session, storage, workspace, in_use.id)
        just_stored = await _asset(session, storage, workspace, in_use.id, created_at=datetime.now(timezone.utc))
        # Its document was deleted, but a copy of the image lives on in another document.
        copied = await _asset(session, storage, workspace, None)
        # Referenced only from another workspace, which can't use it.
        foreign = await _asset(session, storage, workspace, None)

        in_use.elements.append(Element(type=ElementType.IMAGE, content="", image=ImageContent(src="", assetId=shown), order=1))
        await session.execute(
            DocumentRow.__table__.update().where(DocumentRow.id == in_use.id).values(data=dump_document(in_use))
        )
        session.add(DocumentVersion(document_id=in_use.id, revision_number=1, data=dump_document(_with_image(in_history))))
        await repo.create(workspace, _with_image(copied, "Copy"))
        await repo.create(other_workspace, _with_image(foreign, "Elsewhere"))
        await session.commit()

    assert await sweep_unused_assets(db_session_factory, storage) == 2

    async with db_session_factory() as session:
        kept = set((await session.scalars(select(DocumentAsset.id))).all())
    assert kept == {shown, in_history, just_stored, copied}
    assert not (tmp_path / workspace / unused).exists() and not (tmp_path / workspace / foreign).exists()
    assert all((tmp_path / workspace / asset_id).exists() for asset_id in kept)


async def test_a_workspace_without_documents_loses_its_old_images(db_session_factory, tmp_path):
    storage = LocalStorageProvider(tmp_path)
    async with db_session_factory() as session:
        workspace = await _workspace(session, "empty")
        orphan = await _asset(session, storage, workspace, None)
        await session.commit()

    assert await sweep_unused_assets(db_session_factory, storage) == 1
    assert not (tmp_path / workspace / orphan).exists()
