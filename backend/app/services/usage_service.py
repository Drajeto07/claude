"""Usage metering (корекции.docx §36): what each workspace used, counted on the
backend as it happens -- never taken from the frontend. One usage_records row
per event, stamped with the calendar month (UTC) it falls in; Phase 14's plan
limits read the same rows.

- documents_created: every new document (DocumentService.create)
- processing_jobs: every job queued (JobService.create)
- exports: every finished DOCX/PDF export
- ai_operations: every completed call to the AI provider (MeteredAIProvider)
- storage: not an event -- measured when asked (stored images plus documents)"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.db.models import Document as DocumentRow
from app.db.models import DocumentAsset, UsageRecord
from app.models.base import ApiModel

DOCUMENTS_CREATED = "documents_created"
PROCESSING_JOBS = "processing_jobs"
EXPORTS = "exports"
AI_OPERATIONS = "ai_operations"

T = TypeVar("T", bound=BaseModel)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def month_of(at: datetime) -> tuple[datetime, datetime]:
    """The calendar month (UTC) `at` falls in, as [start, end)."""
    start = at.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, (start + timedelta(days=32)).replace(day=1)


def usage_row(workspace_id: str, metric: str, quantity: int = 1, at: datetime | None = None) -> UsageRecord:
    """One usage event, for the caller to add to its session (it counts once committed)."""
    at = at or _now()
    start, end = month_of(at)
    return UsageRecord(workspace_id=workspace_id, metric=metric, quantity=quantity, period_start=start, period_end=end, created_at=at)


class MeteredAIProvider(AIProvider):
    """Counts each AI call that completes (a refused or failed one gives the
    user nothing and isn't counted); `on_call` records it. `before_call`, when
    given, runs first and may refuse the call by raising (the plan's monthly
    allowance: services/entitlements_service.py)."""

    def __init__(
        self, inner: AIProvider, on_call: Callable[[], None], before_call: Callable[[], Awaitable[None]] | None = None
    ) -> None:
        self._inner = inner
        self._on_call = on_call
        self._before_call = before_call

    def provider_name(self) -> str:
        return self._inner.provider_name()

    async def complete(self, prompt: str, *, max_tokens: int = 256) -> str:
        if self._before_call is not None:
            await self._before_call()
        result = await self._inner.complete(prompt, max_tokens=max_tokens)
        self._on_call()
        return result

    async def complete_structured(self, prompt: str, *, response_model: type[T], max_tokens: int = 8192) -> T:
        if self._before_call is not None:
            await self._before_call()
        result = await self._inner.complete_structured(prompt, response_model=response_model, max_tokens=max_tokens)
        self._on_call()
        return result


class UsageOut(ApiModel):
    """A workspace's usage this month, and what it stores now."""

    periodStart: datetime
    periodEnd: datetime
    documentsCreated: int
    exports: int
    aiOperations: int
    processingJobs: int
    documents: int
    storageBytes: int


async def storage_bytes(session: AsyncSession, workspace_id: str) -> int:
    """What a workspace stores: its documents (as saved) and their images."""
    document_bytes = await session.scalar(
        select(func.coalesce(func.sum(func.length(cast(DocumentRow.data, Text))), 0)).where(DocumentRow.workspace_id == workspace_id)
    )
    asset_bytes = await session.scalar(select(func.coalesce(func.sum(DocumentAsset.size_bytes), 0)).where(DocumentAsset.workspace_id == workspace_id))
    return int(document_bytes or 0) + int(asset_bytes or 0)


class UsageService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summary(self, workspace_id: str, at: datetime | None = None) -> UsageOut:
        start, end = month_of(at or _now())
        counted = dict(
            (
                await self._session.execute(
                    select(UsageRecord.metric, func.sum(UsageRecord.quantity))
                    .where(UsageRecord.workspace_id == workspace_id, UsageRecord.created_at >= start, UsageRecord.created_at < end)
                    .group_by(UsageRecord.metric)
                )
            ).all()
        )
        documents = await self._session.scalar(select(func.count(DocumentRow.id)).where(DocumentRow.workspace_id == workspace_id))
        return UsageOut(
            periodStart=start,
            periodEnd=end,
            documentsCreated=int(counted.get(DOCUMENTS_CREATED, 0)),
            exports=int(counted.get(EXPORTS, 0)),
            aiOperations=int(counted.get(AI_OPERATIONS, 0)),
            processingJobs=int(counted.get(PROCESSING_JOBS, 0)),
            documents=int(documents or 0),
            storageBytes=await storage_bytes(self._session, workspace_id),
        )
