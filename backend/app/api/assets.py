from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession, Storage
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
    return Response(
        content=data,
        media_type=asset.content_type,
        headers={
            # A new upload always gets a new id, so a stored asset never changes.
            "Cache-Control": "private, max-age=31536000, immutable",
            # Served from the API origin: never let a browser reinterpret the bytes
            # as HTML/script, whatever they actually contain.
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
