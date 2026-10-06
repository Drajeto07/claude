"""Deleting images nothing uses any more (the half of Phase 4's asset storage that
waited for a sweep; корекции.docx §72).

An asset goes once no document in its workspace refers to it, neither in its
current content nor anywhere in its undo history (undo could bring the image
back), and it is more than a day old, so an image stored a moment ago is never
taken from under an edit still being saved. A document's own assets aren't the
only ones it can use: an image copied from another document of the workspace
keeps pointing at that document's asset, which is why the whole workspace is
checked, and why deleting a document leaves its assets to this sweep.

The row is deleted and committed first, the blob after: a failure in between
leaves a blob nobody points at (garbage), never a row pointing at nothing. A
blob whose row was never committed can't be found this way; the storage
providers can't list their contents yet.

The Word file kept as a document's original is an asset too, and its document
refers to it, so the rule above keeps it as long as the document is there. When
the owner sets KEPT_ORIGINAL_RETENTION_DAYS, it goes after that many days instead,
whatever refers to it (STOR-001); the export then reports it as no longer stored."""

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Document, DocumentAsset, DocumentVersion
from app.db.models.document import unpack_snapshot
from app.models.document import DOCX_CONTENT_TYPE
from app.storage.base import StorageProvider

logger = logging.getLogger(__name__)

GRACE_PERIOD = timedelta(days=1)
SWEEP_INTERVAL_SECONDS = 24 * 3600

# Anything shaped like an id counts as a reference, wherever it sits in the
# document (an image's assetId, an old /api/assets/... src): a false match only
# keeps an asset, it can never delete one that is used.
_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _ids_in(data: object) -> set[str]:
    return set(_ID.findall(json.dumps(data).lower()))


async def _ids_used_in_workspace(session: AsyncSession, workspace_id: str) -> set[str]:
    used: set[str] = set()
    documents = await session.stream_scalars(select(Document.data).where(Document.workspace_id == workspace_id))
    async for data in documents:
        used |= _ids_in(data)
    # Versions are stored compressed (PERF-004), older ones uncompressed: each is
    # read back to its JSON, or an image only a version uses would look unused.
    versions = await session.stream(
        select(DocumentVersion.compressed_data, DocumentVersion.legacy_data)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.workspace_id == workspace_id)
    )
    async for compressed, legacy in versions:
        used |= _ids_in(unpack_snapshot(compressed, legacy))
    return used


async def sweep_unused_assets(session_factory: async_sessionmaker[AsyncSession], storage: StorageProvider) -> int:
    """Deletes every workspace's unused assets older than GRACE_PERIOD, and the kept
    originals past their retention when one is set; returns how many."""
    now = datetime.now(timezone.utc)
    cutoff = now - GRACE_PERIOD
    unused_keys: list[str] = []
    async with session_factory() as session:
        if retention_days := get_settings().kept_original_retention_days:
            expired = await session.scalars(
                select(DocumentAsset).where(
                    DocumentAsset.content_type == DOCX_CONTENT_TYPE, DocumentAsset.created_at < now - timedelta(days=retention_days)
                )
            )
            for original in expired.all():
                unused_keys.append(original.storage_key)
                await session.delete(original)
        candidates = (await session.scalars(select(DocumentAsset).where(DocumentAsset.created_at < cutoff))).all()
        by_workspace: dict[str, list[DocumentAsset]] = defaultdict(list)
        for asset in candidates:
            by_workspace[asset.workspace_id].append(asset)
        for workspace_id, assets in by_workspace.items():
            used = await _ids_used_in_workspace(session, workspace_id)
            for asset in assets:
                if asset.id not in used:
                    unused_keys.append(asset.storage_key)
                    await session.delete(asset)
        await session.commit()
    for key in unused_keys:
        try:
            await storage.delete(key)
        except Exception:  # noqa: BLE001 -- logged, not raised: the row is gone, so this blob is only garbage
            logger.warning("Could not delete the unused asset blob %s", key)
    return len(unused_keys)
