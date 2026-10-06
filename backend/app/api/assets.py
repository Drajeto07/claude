from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession, Storage
from app.export.filenames import safe_filename
from app.security.serving import IMAGE_TYPES, file_response
from app.services.asset_service import AssetService
from app.storage.base import AssetNotFoundError

router = APIRouter()


@router.get("/{asset_id}")
async def get_asset(asset_id: str, user: CurrentUser, db: DbSession, storage: Storage) -> Response:
    try:
        found = await AssetService(db, storage).read_for_user(asset_id, user.id)
    except AssetNotFoundError:
        found = None
    if found is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    asset, data = found
    # A new upload always gets a new id, so a stored asset never changes. A picture is
    # shown in place; the Word file kept as the original is only ever a download.
    filename = None if asset.content_type in IMAGE_TYPES else safe_filename(asset.original_filename or "document.docx")
    return file_response(data, asset.content_type, filename=filename, cache="private, max-age=31536000, immutable")
