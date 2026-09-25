"""What a workspace's plan allows, and the checks that enforce it (корекции.docx
§35). Every limit is checked here, on the backend, against the plan's
entitlements (billing/plans.json) -- never against a plan's name -- so a
subscription change reaches every check by changing the plan alone."""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIStructuredOutputError
from app.billing.plans import FREE, PLANS, Entitlements, Plan
from app.config import get_settings
from app.db.models import Document as DocumentRow
from app.db.models import Subscription, UsageRecord
from app.db.models import Template as TemplateRow
from app.services.usage_service import AI_OPERATIONS, month_of, storage_bytes

# A subscription in these states grants its plan; anything else is the free plan.
ENTITLED_STATUSES = {"active", "trialing", "past_due"}
_MB = 1024 * 1024


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
        return PLANS[FREE]

    async def entitlements(self, workspace_id: str) -> Entitlements:
        return effective((await self.plan(workspace_id)).entitlements)

    async def documents(self, workspace_id: str) -> int:
        return int(await self._session.scalar(select(func.count(DocumentRow.id)).where(DocumentRow.workspace_id == workspace_id)) or 0)

    async def templates(self, workspace_id: str) -> int:
        return int(await self._session.scalar(select(func.count(TemplateRow.id)).where(TemplateRow.workspace_id == workspace_id)) or 0)

    async def ai_operations_this_month(self, workspace_id: str) -> int:
        start, end = month_of(datetime.now(timezone.utc))
        used = await self._session.scalar(
            select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
                UsageRecord.workspace_id == workspace_id,
                UsageRecord.metric == AI_OPERATIONS,
                UsageRecord.created_at >= start,
                UsageRecord.created_at < end,
            )
        )
        return int(used or 0)

    async def check_new_document(self, workspace_id: str) -> None:
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

    async def ai_remaining(self, workspace_id: str) -> int | None:
        """AI operations left this month; None = unlimited."""
        limit = (await self.entitlements(workspace_id)).maxAiOperations
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

    async def check_new_template(self, workspace_id: str) -> None:
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

    async def check_storage(self, workspace_id: str, adding_bytes: int) -> None:
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
