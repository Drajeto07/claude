from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import AuthService
from app.services.document_service import DocumentService
from app.storage.base import StorageProvider
from app.storage.factory import get_storage_provider

SESSION_COOKIE = "smartdoc_session"

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(request: Request, db: DbSession) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    user = await AuthService(db).resolve_session(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
Storage = Annotated[StorageProvider, Depends(get_storage_provider)]


def _expected_revision(request: Request) -> int | None:
    """If-Match carries the document revision the client last saw (plain, quoted
    or weak-ETag form). Absent or "*" means "don't check"."""
    raw = request.headers.get("if-match")
    if raw is None or raw.strip() == "*":
        return None
    value = raw.strip().removeprefix("W/").strip('"')
    if not value.isdigit():
        raise HTTPException(status_code=400, detail="If-Match must be a document revision number.")
    return int(value)


async def get_document_service(
    request: Request, user: CurrentUser, db: DbSession, storage: Storage
) -> DocumentService:
    return DocumentService(db, user_id=user.id, storage=storage, expected_revision=_expected_revision(request))


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]
