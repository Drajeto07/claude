"""What a workspace's plan allows, and the checks that enforce it (корекции.docx
§35). Every limit is checked here, on the backend, against the plan's
entitlements (billing/plans.json) -- never against a plan's name -- so a
subscription change reaches every check by changing the plan alone. Which
entitlement limits which use is billing/units.py's.

A check that counts and the use it allows are one step (PLAN-003): the check
that comes right before the use holds the workspace (`hold=True`) until the
transaction that makes the use ends, so two requests at once can't both pass a
limit with room for one. Earlier checks that only refuse early (before a file
is read) don't hold anything. A use that happens outside any transaction -- an
AI call, an export being built -- is reserved instead (UsageReservations): taken
under the hold in a short transaction of its own before the work, and given back
if the work doesn't happen."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.base import AIStructuredOutputError
from app.billing import units
from app.billing.plans import DEFAULT_PLAN, PLANS, Entitlements, Plan
from app.billing.units import UsageUnit
from app.config import get_settings
from app.db.models import Document as DocumentRow
from app.db.models import Subscription, UsageRecord
from app.db.models import Template as TemplateRow
from app.db.models import Workspace
from app.ai.base import AIProvider
from app.services.usage_service import MeteredAIProvider, UnitUsageOut, month_of, storage_bytes, usage_row

logger = logging.getLogger(__name__)

# A subscription in these states grants its plan; anything else is the free plan.
ENTITLED_STATUSES = {"active", "trialing", "past_due"}
_MB = units.MB


class PlanLimitError(Exception):
    """Something the workspace's plan doesn't allow; the message says what and
    how to go on. The API answers 402 with code "plan_limit"."""

    def __init__(self, entitlement: str, message: str, *, limit: int | None = None, used: int | None = None) -> None:
        super().__init__(message)
        self.entitlement = entitlement
        self.limit = limit
        self.used = used


class AILimitReachedError(AIStructuredOutputError):
    """The month's AI operations are used up. An AIStructuredOutputError, so every
    AI step falls back exactly as when the AI is unavailable."""


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


async def hold_workspace(session: AsyncSession, workspace_id: str) -> None:
    """Holds the workspace until this transaction ends: anyone else holding it waits
    till then, and then counts what this one added. An UPDATE that changes nothing,
    not SELECT ... FOR UPDATE, so it is the same statement everywhere: PostgreSQL
    takes the row's lock for it, SQLite (tests, development) its write lock. It goes
    before the transaction reads anything, where it can: SQLite can't wait for a
    write lock in a transaction that has read."""
    await session.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(updated_at=Workspace.updated_at)
        .execution_options(synchronize_session=False)
    )


def effective(entitlements: Entitlements) -> Entitlements:
    """A plan's entitlements as this server honours them: no plan takes a file
    over the server's own upload cap (MAX_UPLOAD_SIZE_MB), whatever it promises."""
    ceiling = get_settings().max_upload_size_mb
    if entitlements.maxDocumentSizeMb <= ceiling:
        return entitlements
    return entitlements.model_copy(update={"maxDocumentSizeMb": ceiling})


class EntitlementsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def subscription(self, workspace_id: str) -> Subscription | None:
        return await self._session.scalar(select(Subscription).where(Subscription.workspace_id == workspace_id))

    async def plan(self, workspace_id: str) -> Plan:
        subscription = await self.subscription(workspace_id)
        if subscription is not None and subscription.status in ENTITLED_STATUSES and subscription.plan in PLANS:
            return PLANS[subscription.plan]
        return PLANS[DEFAULT_PLAN]

    async def entitlements(self, workspace_id: str) -> Entitlements:
        return effective((await self.plan(workspace_id)).entitlements)

    async def documents(self, workspace_id: str) -> int:
        return int(await self._session.scalar(select(func.count(DocumentRow.id)).where(DocumentRow.workspace_id == workspace_id)) or 0)

    async def templates(self, workspace_id: str) -> int:
        return int(await self._session.scalar(select(func.count(TemplateRow.id)).where(TemplateRow.workspace_id == workspace_id)) or 0)

    async def used_this_month(self, workspace_id: str, metric: str) -> int:
        """What the workspace used of a counted unit this calendar month (UTC)."""
        start, end = month_of(datetime.now(timezone.utc))
        used = await self._session.scalar(
            select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
                UsageRecord.workspace_id == workspace_id,
                UsageRecord.metric == metric,
                UsageRecord.created_at >= start,
                UsageRecord.created_at < end,
            )
        )
        return int(used or 0)

    async def ai_operations_this_month(self, workspace_id: str) -> int:
        return await self.used_this_month(workspace_id, units.AI_OPERATIONS)

    async def used(self, workspace_id: str, unit: UsageUnit) -> int:
        """How much of a unit the workspace uses: this month's count, or what it holds now."""
        if unit.metric is not None:
            return await self.used_this_month(workspace_id, unit.metric)
        if unit is units.DOCUMENTS:
            return await self.documents(workspace_id)
        if unit is units.TEMPLATES:
            return await self.templates(workspace_id)
        if unit is units.STORAGE:
            return await storage_bytes(self._session, workspace_id)
        raise ValueError(f"No way to measure {unit.key}")

    async def unit_usage(self, workspace_id: str) -> list[UnitUsageOut]:
        """Every usage unit, what is used of it and the plan's limit (GET /usage, GET /billing)."""
        entitlements = await self.entitlements(workspace_id)
        return [
            UnitUsageOut(
                key=unit.key,
                label=unit.label,
                used=await self.used(workspace_id, unit),
                limit=unit.limit(entitlements),
                period="month" if unit.per_month else "now",
                measure=unit.measure,
                available=unit.counted,
            )
            for unit in units.UNITS
        ]

    async def check_monthly(self, workspace_id: str, unit: UsageUnit, quantity: int = 1, *, hold: bool = False) -> None:
        """Refuses `quantity` more of a counted unit when this month's use would go over the plan's limit."""
        if hold:
            await hold_workspace(self._session, workspace_id)
        limit = unit.limit(await self.entitlements(workspace_id))
        if limit is None:
            return
        used = await self.used_this_month(workspace_id, unit.metric or "")
        if used + quantity > limit:
            raise PlanLimitError(unit.entitlement, _over_monthly(unit, limit, used, quantity), limit=limit, used=used)

    async def check_new_document(self, workspace_id: str, *, hold: bool = False) -> None:
        if hold:
            await hold_workspace(self._session, workspace_id)
        limit = (await self.entitlements(workspace_id)).maxDocuments
        if limit is None:
            return
        used = await self.documents(workspace_id)
        if used >= limit:
            raise PlanLimitError(
                "maxDocuments",
                f"Your plan allows {_plural(limit, 'document')}. Delete one you no longer need, or upgrade your plan.",
                limit=limit,
                used=used,
            )

    async def check_file_size(self, workspace_id: str, size_bytes: int) -> None:
        limit_mb = (await self.entitlements(workspace_id)).maxDocumentSizeMb
        if size_bytes > limit_mb * _MB:
            raise PlanLimitError("maxDocumentSizeMb", f"Your plan takes files of up to {limit_mb} MB.", limit=limit_mb, used=-(-size_bytes // _MB))

    async def check_export(self, workspace_id: str, file_format: str) -> None:
        entitlements = await self.entitlements(workspace_id)
        allowed = entitlements.canExportDocx if file_format == "docx" else entitlements.canExportPdf
        if not allowed:
            raise PlanLimitError(
                "canExportDocx" if file_format == "docx" else "canExportPdf",
                f"Your plan doesn't include {file_format.upper()} export. Upgrade your plan to export as {file_format.upper()}.",
            )
        # Early, before anything is built; the export's own reservation is what counts it.
        await self.check_monthly(workspace_id, units.EXPORT)

    async def ai_remaining(self, workspace_id: str) -> int | None:
        """AI operations left this month; None = unlimited."""
        limit = units.AI.limit(await self.entitlements(workspace_id))
        if limit is None:
            return None
        return max(0, limit - await self.ai_operations_this_month(workspace_id))

    async def check_ai(self, workspace_id: str) -> None:
        """Before work whose point is the AI (instructions): refused once used up."""
        if await self.ai_remaining(workspace_id) == 0:
            limit = (await self.entitlements(workspace_id)).maxAiOperations or 0
            raise PlanLimitError(
                "maxAiOperations",
                f"You've used all {_plural(limit, 'AI operation')} of your plan this month. They renew on the 1st, or upgrade your plan.",
                limit=limit,
                used=limit,
            )

    async def check_new_template(self, workspace_id: str, *, hold: bool = False) -> None:
        if hold:
            await hold_workspace(self._session, workspace_id)
        limit = (await self.entitlements(workspace_id)).maxTemplates
        if limit is None:
            return
        used = await self.templates(workspace_id)
        if used >= limit:
            raise PlanLimitError(
                "maxTemplates",
                f"Your plan allows {_plural(limit, 'template')}. Delete one you no longer need, or upgrade your plan.",
                limit=limit,
                used=used,
            )

    async def check_storage(self, workspace_id: str, adding_bytes: int, *, hold: bool = False) -> None:
        if hold:
            await hold_workspace(self._session, workspace_id)
        limit_mb = (await self.entitlements(workspace_id)).maxStorageMb
        if limit_mb is None:
            return
        used = await storage_bytes(self._session, workspace_id)
        if used + adding_bytes > limit_mb * _MB:
            raise PlanLimitError(
                "maxStorageMb",
                f"This would go over your plan's {limit_mb} MB of storage. Delete documents you no longer need, or upgrade your plan.",
                limit=limit_mb,
                used=-(-used // _MB),
            )


def _over_monthly(unit: UsageUnit, limit: int, used: int, quantity: int) -> str:
    """Why a monthly limit refuses, and how to go on."""
    first, _, rest = unit.label.partition(" ")
    what = " ".join(filter(None, (first if first.isupper() else first.lower(), rest)))  # "PDF pages", "exports"
    if quantity > 1 and used < limit:
        return (
            f"This needs {quantity:,} {what}, and your plan has {limit - used:,} of its {limit:,} left this month. "
            "They renew on the 1st, or upgrade your plan."
        )
    return f"You've used all {limit:,} {what} of your plan this month. They renew on the 1st, or upgrade your plan."


class UsageReservations:
    """Monthly usage taken before the work that uses it (PLAN-003): the count and
    the taking are one short transaction of their own, holding the workspace and
    committed before the work starts. So two jobs at once can't both take the last
    of the month, and the work's own transaction -- long, and rolled back when it
    fails -- neither holds the workspace meanwhile nor takes the count with it.
    What the work didn't use is given back: a reservation is the usage_records row
    that counts the use, deleted again.

    A process that dies between the two leaves its reservation counted: a use
    that may have happened is counted, never one given away."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], workspace_id: str) -> None:
        self._sessions = sessions
        self._workspace_id = workspace_id

    async def take(self, unit: UsageUnit, quantity: int = 1) -> str:
        """Reserves `quantity` of the unit, or raises PlanLimitError when the month has no room for it."""
        async with self._sessions() as session:
            plans = EntitlementsService(session)
            await plans.check_monthly(self._workspace_id, unit, quantity, hold=True)
            row = usage_row(self._workspace_id, unit.metric or "", quantity)
            session.add(row)
            await session.commit()
            return row.id

    @asynccontextmanager
    async def held(self, unit: UsageUnit, quantity: int = 1) -> AsyncIterator[str]:
        """Reserved for the block's work; given back if the block fails."""
        reservation = await self.take(unit, quantity)
        try:
            yield reservation
        except BaseException:
            await self.give_back(reservation)
            raise

    async def give_back(self, reservation: str) -> None:
        """The reserved use didn't happen: it no longer counts. If that can't be
        written, it stays counted (logged), never the other way round."""
        try:
            async with self._sessions() as session:
                await session.execute(delete(UsageRecord).where(UsageRecord.id == reservation))
                await session.commit()
        except Exception:  # noqa: BLE001 -- the use stays counted; the work's own outcome stands
            logger.warning("Could not give back the usage reserved as %s", reservation)


def metered(provider: AIProvider, reservations: UsageReservations, on_call: Callable[[], None] = lambda: None) -> AIProvider:
    """`provider` with each call's AI operation reserved before it (refused, as
    AILimitReachedError, once the month's are used up -- the AI step then falls
    back) and given back if the call fails or is cut off (PLAN-003)."""

    async def reserve() -> str:
        try:
            return await reservations.take(units.AI)
        except PlanLimitError as exc:
            raise AILimitReachedError("The plan's AI operations for this month are used up.") from exc

    return MeteredAIProvider(provider, on_call, reserve, reservations.give_back)
