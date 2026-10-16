"""Usage metering (корекции.docx §36): what each workspace used, counted on the
backend as it happens -- never taken from the frontend. One usage_records row
per event, stamped with the calendar month (UTC) it falls in; the plan limits
read the same rows. The units and their limits are billing/units.py's.

- documents_created: every new document (DocumentService.create)
- processing_jobs: every job queued (JobService.create)
- exports: every finished DOCX/PDF export, reserved before it is built (UsageReservations)
- pdf_pages: every page of an imported PDF, with the document it became
- ai_operations: every completed call to the AI provider, reserved before the call (MeteredAIProvider)
- ocr_pages, translation_characters, batch_jobs: named; counted once those features exist
- storage: not an event -- measured when asked (storage_bytes)"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, TypeVar

from pydantic import BaseModel
from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.billing.units import AI_OPERATIONS, DOCUMENTS_CREATED, EXPORTS, PDF_PAGES, PROCESSING_JOBS  # noqa: F401 -- where they were
from app.db.models import Document as DocumentRow
from app.db.models import DocumentAsset, DocumentVersion, UsageRecord
from app.db.types import octet_length
from app.models.base import ApiModel

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
    allowance: services/entitlements_service.py). What it returns is the call's
    reservation: `release` gets it back when the call fails or is interrupted
    (a timeout, a cancel), so only completed calls stay counted (PLAN-003)."""

    def __init__(
        self,
        inner: AIProvider,
        on_call: Callable[[], None],
        before_call: Callable[[], Awaitable[Any]] | None = None,
        release: Callable[[Any], Awaitable[None]] | None = None,
    ) -> None:
        self._inner = inner
        self._on_call = on_call
        self._before_call = before_call
        self._release = release

    def provider_name(self) -> str:
        return self._inner.provider_name()

    async def _metered(self, call: Callable[[], Awaitable[T]]) -> T:
        reservation = await self._before_call() if self._before_call is not None else None
        try:
            result = await call()
        except BaseException:  # a CancelledError too: the call was cut off and gave nothing
            if self._release is not None and reservation is not None:
                await self._release(reservation)
            raise
        self._on_call()
        return result

    async def complete(self, prompt: str, *, max_tokens: int = 256, system: str | None = None) -> str:
        return await self._metered(lambda: self._inner.complete(prompt, max_tokens=max_tokens, system=system))

    async def complete_structured(
        self, prompt: str, *, response_model: type[T], max_tokens: int = 8192, system: str | None = None
    ) -> T:
        return await self._metered(
            lambda: self._inner.complete_structured(prompt, response_model=response_model, max_tokens=max_tokens, system=system)
        )


class UnitUsageOut(ApiModel):
    """One usage unit (billing/units.py): how much is used and the plan's limit."""

    key: str
    label: str
    used: int
    # None = unlimited.
    limit: int | None
    # "month": counted this calendar month (UTC), renews when it ends; "now": what the workspace holds.
    period: Literal["month", "now"]
    measure: Literal["count", "bytes"]
    # False: named, but the feature that uses it doesn't exist yet, so nothing counts it.
    available: bool


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
    # Every usage unit with the plan's limit for it, in billing/units.py's order.
    units: list[UnitUsageOut]


async def storage_bytes(session: AsyncSession, workspace_id: str) -> int:
    """What a workspace stores, in bytes (PLAN-005): its documents (their JSON as
    saved), their kept versions (as stored: compressed, PERF-004) and their assets
    -- pictures and the Word files imports were made from (kept originals). Not a
    job's upload (removed when the job ends) or an export's file (kept for the job's
    7 days, JOB_RETENTION_DAYS): neither is something the workspace keeps."""
    document_bytes = await session.scalar(
        select(func.coalesce(func.sum(octet_length(cast(DocumentRow.data, Text))), 0)).where(DocumentRow.workspace_id == workspace_id)
    )
    version_bytes = await session.scalar(
        select(func.coalesce(func.sum(DocumentVersion.stored_bytes), 0))
        .join(DocumentRow, DocumentRow.id == DocumentVersion.document_id)
        .where(DocumentRow.workspace_id == workspace_id)
    )
    asset_bytes = await session.scalar(select(func.coalesce(func.sum(DocumentAsset.size_bytes), 0)).where(DocumentAsset.workspace_id == workspace_id))
    return int(document_bytes or 0) + int(version_bytes or 0) + int(asset_bytes or 0)


class UsageService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summary(self, workspace_id: str, at: datetime | None = None) -> UsageOut:
        from app.services.entitlements_service import EntitlementsService  # it imports this module

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
            units=await EntitlementsService(self._session).unit_usage(workspace_id),
        )
