from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import CurrentUser, DbSession, Storage, WorkspaceId
from app.export.filenames import safe_filename
from app.models.base import ApiModel
from app.repositories.document_repository import DocumentRepository
from app.security.serving import IMAGE_TYPES, file_response
from app.services.asset_service import AssetService
from app.storage.base import AssetNotFoundError

router = APIRouter()


class PictureOut(ApiModel):
    """One of the workspace's pictures: shown from GET /assets/{id}, put in a document by its id."""

    id: str
    contentType: str
    sizeBytes: int
    createdAt: datetime


class PicturePage(ApiModel):
    items: list[PictureOut]
    # The `before` of the next page; null after the last.
    next: str | None


@router.get("", response_model=PicturePage)
async def list_pictures(
    user: CurrentUser,
    workspace_id: WorkspaceId,
    db: DbSession,
    storage: Storage,
    limit: Annotated[int, Query(ge=1, le=48)] = 24,
    before: Annotated[str | None, Query(max_length=64, description="The last id of the page before")] = None,
    document_id: Annotated[
        str | None, Query(alias="documentId", max_length=64, description="List the pictures of this document's workspace")
    ] = None,
) -> PicturePage:
    """The pictures of a workspace, newest first, a page at a time (S2-131a, the editor's Uploads panel): every
    picture its documents hold, put in again by its id -- never stored twice. The workspace of `documentId` (the
    document being edited: what a save of it accepts), else the signed-in user's own. 404 for a document the user
    can't open, as everywhere."""
    if document_id is not None:
        found = await DocumentRepository(db).workspace_id_for_user(document_id, user.id)
        if found is None:
            raise HTTPException(status_code=404, detail="Document not found")
        workspace_id = found
    listed = await AssetService(db, storage).list_pictures(workspace_id, limit=limit, before=before)
    if listed is None:
        raise HTTPException(status_code=400, detail="That isn't a page of your pictures.")
    rows, following = listed
    items = [PictureOut(id=row.id, contentType=row.content_type, sizeBytes=row.size_bytes, createdAt=row.created_at) for row in rows]
    return PicturePage(items=items, next=following)


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
