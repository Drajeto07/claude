"""The operator's API (tracker OBS-003): operations data across every workspace -- failed and
stuck jobs, processing and export failure counts, usage spikes, storage, refusals.

Not for users: there is no admin role. It answers only to ADMIN_TOKEN as the bearer token (as
GET /api/metrics does to METRICS_TOKEN), and isn't there at all while that is unset. What it
returns is counts, ids, types and short codes -- nothing of any document or account."""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.deps import DbSession, client_address
from app.audit import audit
from app.config import get_settings
from app.services.operations_service import OperationsOut, OperationsService

router = APIRouter()


def require_admin_token(request: Request) -> None:
    token = get_settings().admin_token
    if not token:
        raise HTTPException(status_code=404, detail="Not Found")
    sent = request.headers.get("Authorization", "")
    if not hmac.compare_digest(sent.encode(), f"Bearer {token}".encode()):
        audit("admin.token_refused", ip=client_address(request))
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


@router.get("/operations", response_model=OperationsOut, dependencies=[Depends(require_admin_token)])
async def operations(db: DbSession, hours: Annotated[int, Query(ge=1, le=24 * 31)] = 24) -> OperationsOut:
    """What happened in the last `hours` (24 by default): failed jobs by type and code, stuck and
    dead-lettered jobs, processing and export failures, usage spikes against the window before,
    storage by workspace, new accounts, the busiest workspaces, and this process' refusals."""
    return await OperationsService(db).summary(hours)
