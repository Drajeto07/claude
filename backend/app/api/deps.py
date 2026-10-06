from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import AIProvider
from app.ai.budget import BudgetedAIProvider
from app.ai.factory import get_ai_provider
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.jobs.queue import get_job_session_factory
from app.mail import EmailSender, get_email_sender
from app.security.rate_limit import enforce
from app.services.auth_service import AuthService
from app.services.document_service import DocumentService
from app.services.entitlements_service import EntitlementsService, UsageReservations, metered
from app.storage.base import StorageProvider
from app.storage.factory import get_storage_provider
from app.translation.providers import TranslationProvider

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

# The app's e-mail (app/mail): a test puts an in-memory sender in.
Mail = Annotated[EmailSender, Depends(get_email_sender)]
# Sessions for work done after the answer (a background task), which the request's own session doesn't outlive.
BackgroundSessions = Annotated[async_sessionmaker[AsyncSession], Depends(get_job_session_factory)]


def get_usage_reservations(workspace_id: WorkspaceId, db: DbSession) -> UsageReservations:
    """Reservations of the user's workspace's monthly usage, each in a short
    transaction of its own on the request's database (a session apart from the
    request's, whose own change isn't committed with it)."""
    return UsageReservations(async_sessionmaker(db.bind, expire_on_commit=False), workspace_id)


Reservations = Annotated[UsageReservations, Depends(get_usage_reservations)]


async def get_metered_ai_provider(
    reservations: Reservations, provider: Annotated[AIProvider, Depends(get_ai_provider)]
) -> AIProvider:
    """The AI provider for a request that calls it directly: each completed call
    counts into the user's usage, reserved and committed before the call whatever
    becomes of the request, and calls are refused once the plan's monthly AI
    operations are used up."""
    settings = get_settings()
    return BudgetedAIProvider(metered(provider, reservations), calls=settings.ai_calls_per_job, seconds=settings.ai_seconds_per_job)


MeteredAI = Annotated[AIProvider, Depends(get_metered_ai_provider)]


def get_translation_provider(provider: Annotated[AIProvider, Depends(get_ai_provider)]) -> TranslationProvider:
    """Who translates (TRANSLATION_PROVIDER), within the AI's call and time budget. Metered by
    the characters sent (TRAN-009), not as AI operations: a translation counts once."""
    from app.translation.service import provider_for

    settings = get_settings()
    return provider_for(BudgetedAIProvider(provider, calls=settings.ai_calls_per_job, seconds=settings.ai_seconds_per_job))


Translator = Annotated[TranslationProvider, Depends(get_translation_provider)]


def client_address(request: Request) -> str:
    """The caller's address. Behind a proxy it is the real client's only when the
    server trusts the proxy's X-Forwarded-For (uvicorn --proxy-headers)."""
    return request.client.host if request.client else "unknown"


def rate_limited(scope: str):
    """A route dependency counting the request against `scope`'s allowance
    (security/rate_limit.py), per signed-in user; 429 once it is used up."""

    async def check(user: CurrentUser) -> None:
        await enforce(scope, f"user:{user.id}")

    return Depends(check)
