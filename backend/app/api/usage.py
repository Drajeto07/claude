from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.services.auth_service import AuthService
from app.services.usage_service import UsageOut, UsageService

router = APIRouter()


@router.get("", response_model=UsageOut)
async def get_usage(user: CurrentUser, db: DbSession) -> UsageOut:
    """This month's usage of the user's workspace (корекции.docx §36), counted on
    the backend as it happened, and what the workspace stores now."""
    workspace_id = await AuthService(db).default_workspace_id(user.id)
    return await UsageService(db).summary(workspace_id)
