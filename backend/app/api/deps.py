from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.ai.factory import get_ai_provider
from app.db.models import User
from app.db.session import get_db
from app.services.auth_service import AuthService
from app.services.document_service import DocumentService
from app.services.entitlements_service import AILimitReachedError, EntitlementsService
from app.services.usage_service import AI_OPERATIONS, MeteredAIProvider, usage_row
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


def if_match_number(request: Request) -> int | None:
    """If-Match carries the revision/version number the client last saw (plain,
    quoted or weak-ETag form). Absent or "*" means "don't check"."""
    raw = request.headers.get("if-match")
    if raw is None or raw.strip() == "*":
        return None
    value = raw.strip().removeprefix("W/").strip('"')
    if not value.isdigit():
        raise HTTPException(status_code=400, detail="If-Match must be a revision number.")
    return int(value)


async def get_document_service(
    request: Request, user: CurrentUser, db: DbSession, storage: Storage
) -> DocumentService:
    return DocumentService(db, user_id=user.id, storage=storage, expected_revision=if_match_number(request))


DocumentServiceDep = Annotated[DocumentService, Depends(get_document_service)]


async def get_workspace_id(user: CurrentUser, db: DbSession) -> str:
    """The signed-in user's own workspace: where what they create goes, and whose plan applies."""
    return await AuthService(db).default_workspace_id(user.id)


WorkspaceId = Annotated[str, Depends(get_workspace_id)]


def get_entitlements(db: DbSession) -> EntitlementsService:
    return EntitlementsService(db)


PlanChecks = Annotated[EntitlementsService, Depends(get_entitlements)]


async def get_metered_ai_provider(
    workspace_id: WorkspaceId, db: DbSession, entitlements: PlanChecks, provider: Annotated[AIProvider, Depends(get_ai_provider)]
) -> AIProvider:
    """The AI provider for a request that calls it directly, counting each
    completed call into the user's usage (committed with the request's own
    change; an endpoint that changes nothing commits it itself), and refusing
    calls once the plan's monthly AI operations are used up."""
    async def within_allowance() -> None:
        # This request's own calls are pending in the session, and flushed into the count by the query.
        if await entitlements.ai_remaining(workspace_id) == 0:
            raise AILimitReachedError("The plan's AI operations for this month are used up.")

    return MeteredAIProvider(provider, lambda: db.add(usage_row(workspace_id, AI_OPERATIONS)), within_allowance)


MeteredAI = Annotated[AIProvider, Depends(get_metered_ai_provider)]
