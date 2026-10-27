import logging
from collections.abc import Iterable
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentAsset, WorkspaceMember
from app.models.document import WEB_IMAGE_TYPES
from app.storage.base import AssetNotFoundError, StorageProvider

logger = logging.getLogger(__name__)


class AssetService:
    """A DocumentAsset row plus its blob. The row is the source of truth: the
    blob is written before the row, so a row never points at bytes that were
    never stored. A blob with no row (e.g. a later rollback) is only garbage,
    never lost data."""

    def __init__(self, session: AsyncSession, storage: StorageProvider) -> None:
        self._session = session
        self._storage = storage

    async def store(
        self,
        workspace_id: str,
        data: bytes,
        content_type: str,
        *,
        document_id: str | None = None,
        original_filename: str | None = None,
    ) -> DocumentAsset:
        asset_id = str(uuid4())
        key = f"{workspace_id}/{asset_id}"
        await self._storage.put(key, data, content_type)
        asset = DocumentAsset(
            id=asset_id,
            workspace_id=workspace_id,
            document_id=document_id,
            storage_key=key,
            content_type=content_type,
            size_bytes=len(data),
            original_filename=original_filename,
        )
        self._session.add(asset)
        try:
            await self._session.flush()
        except Exception:
            await self._storage.delete(key)
            raise
        return asset

    async def total_size(self, workspace_id: str, asset_ids: Iterable[str]) -> int:
        """The stored bytes of those of `asset_ids` that are the workspace's (SEC-012)."""
        ids = set(asset_ids)
        if not ids:
            return 0
        total = select(func.coalesce(func.sum(DocumentAsset.size_bytes), 0)).where(
            DocumentAsset.workspace_id == workspace_id, DocumentAsset.id.in_(ids)
        )
        return int((await self._session.execute(total)).scalar_one())

    async def pictures_in(self, workspace_id: str, asset_ids: Iterable[str]) -> set[str]:
        """Those of `asset_ids` that are pictures of the workspace (S2-131a): what a document of it may show by id.
        A kept Word original is the workspace's too, but not a picture."""
        ids = set(asset_ids)
        if not ids:
            return set()
        found = select(DocumentAsset.id).where(
            DocumentAsset.workspace_id == workspace_id,
            DocumentAsset.id.in_(ids),
            DocumentAsset.content_type.in_(WEB_IMAGE_TYPES),
        )
        return set((await self._session.execute(found)).scalars().all())

    async def list_pictures(
        self, workspace_id: str, *, limit: int, before: str | None = None
    ) -> tuple[list[DocumentAsset], str | None] | None:
        """The workspace's pictures, newest first, `limit` at a time (S2-131a, the editor's Uploads panel): the
        pictures of all its documents, whichever document stored them. `before` is the id of the last picture of
        the page before (the cursor); the second value is the next page's, None after the last. None for a
        cursor that isn't one of the workspace's pictures. Rows only -- no picture's bytes are read."""
        query = select(DocumentAsset).where(
            DocumentAsset.workspace_id == workspace_id, DocumentAsset.content_type.in_(WEB_IMAGE_TYPES)
        )
        if before is not None:
            cursor = (await self._session.execute(query.where(DocumentAsset.id == before))).scalar_one_or_none()
            if cursor is None:
                return None
            query = query.where(
                or_(
                    DocumentAsset.created_at < cursor.created_at,
                    and_(DocumentAsset.created_at == cursor.created_at, DocumentAsset.id < cursor.id),
                )
            )
        rows = list(
            (
                await self._session.execute(
                    query.order_by(DocumentAsset.created_at.desc(), DocumentAsset.id.desc()).limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        page = rows[:limit]
        return page, (page[-1].id if len(rows) > limit else None)

    async def read(self, asset_id: str) -> tuple[DocumentAsset, bytes] | None:
        """Unscoped -- internal use only. Anything serving a user goes through
        read_for_user / read_many_for_user."""
        asset = await self._session.get(DocumentAsset, asset_id)
        if asset is None:
            return None
        return asset, await self._storage.get(asset.storage_key)

    def _accessible(self, user_id: str):
        return select(DocumentAsset).join(
            WorkspaceMember, WorkspaceMember.workspace_id == DocumentAsset.workspace_id
        ).where(WorkspaceMember.user_id == user_id)

    async def read_for_user(self, asset_id: str, user_id: str) -> tuple[DocumentAsset, bytes] | None:
        """None both for a missing asset and for one in a workspace the user
        isn't a member of -- same no-existence-leak rule as documents."""
        asset = (
            await self._session.execute(self._accessible(user_id).where(DocumentAsset.id == asset_id))
        ).scalar_one_or_none()
        if asset is None:
            return None
        return asset, await self._storage.get(asset.storage_key)

    async def read_many_for_user(self, asset_ids: Iterable[str], user_id: str) -> dict[str, bytes]:
        """For exports: ids the user can't access are simply absent, so a foreign
        assetId planted in a document exports as a missing image, not a leak."""
        ids = set(asset_ids)
        if not ids:
            return {}
        rows = (
            (await self._session.execute(self._accessible(user_id).where(DocumentAsset.id.in_(ids))))
            .scalars()
            .all()
        )
        found: dict[str, bytes] = {}
        for asset in rows:
            try:
                found[asset.id] = await self._storage.get(asset.storage_key)
            except AssetNotFoundError:
                logger.warning("Asset %s has a row but no stored blob -- exporting without it", asset.id)
        return found
