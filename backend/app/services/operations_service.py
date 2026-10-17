"""Operations data for whoever runs the service (tracker OBS-003, brief §51/§98): what failed, what
spiked, what is stored and what was refused, across every workspace -- the questions the per-
process metrics (app/observability.py) can't answer, read from the database, next to this
process' own counters.

Only counts, ids, types, short codes and times: never a title, a file name, an e-mail address, a
job's error message or anything else that came from a user or a document."""

from collections import Counter as Tally
from datetime import datetime, timedelta, timezone

from pydantic import Field
from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import observability
from app.db.models import Document as DocumentRow
from app.db.models import DocumentAsset, DocumentVersion, ProcessingJob, UsageRecord, User
from app.db.types import octet_length
from app.jobs import policy
from app.models.base import ApiModel

# A metric is called a spike when the window's use is at least SPIKE_FACTOR times the window
# before's (or there was none before), and at least SPIKE_MINIMUM -- so a workspace going from 1
# export to 3 isn't one.
SPIKE_FACTOR = 3
SPIKE_MINIMUM = 20
TOP = 10  # rows in each "largest" / "most" list
RECENT_FAILURES = 20
# Jobs whose work is processing a document (import, formatting, reading a reference, translating),
# as against exporting one.
_PROCESSING_TYPES = ("import_text", "import_file", "format", "extract_reference", "translate")


class JobFailure(ApiModel):
    id: str
    workspace_id: str
    job_type: str
    failure_reason: str | None = None  # a short code (e.g. "transient:ConnectionError"), never document text
    dead_letter: bool
    attempts: int
    finished_at: datetime | None = None


class JobsSummary(ApiModel):
    by_status: dict[str, dict[str, int]] = Field(description="Jobs created in the window: type -> status -> count.")
    failed_by_reason: dict[str, int] = Field(description="Failed jobs finished in the window, by type and failure code.")
    dead_letters: int = Field(description="Failed jobs kept after their last attempt (all time, never swept).")
    stuck: list[str] = Field(description="Ids of jobs still running past their deadline -- their worker is gone.")
    pending_oldest_seconds: float | None = Field(default=None, description="How long the oldest job has waited to start.")
    recent_failures: list[JobFailure]


class FailureRates(ApiModel):
    finished: int
    failed: int


class UsageSpike(ApiModel):
    workspace_id: str
    metric: str
    window: int
    previous_window: int


class WorkspaceStorage(ApiModel):
    workspace_id: str
    bytes: int


class StorageSummary(ApiModel):
    documents: int
    document_bytes: int
    version_bytes: int
    asset_bytes: int
    total_bytes: int
    largest_workspaces: list[WorkspaceStorage]


class WorkspaceCount(ApiModel):
    workspace_id: str
    count: int


class AbuseSignals(ApiModel):
    accounts_created: int = Field(description="Accounts made in the window.")
    most_jobs: list[WorkspaceCount] = Field(description="The workspaces that queued the most jobs in the window.")
    refusals: dict[str, int] = Field(
        description="This process' refused and failed security events since it started (rate limits, plan limits, "
        "refused files, failed sign-ins, cross-site writes ...), by audit event and its reason."
    )


class ThisProcess(ApiModel):
    """This process' counters since it started -- each API process and the worker keep their own."""

    jobs: dict[str, int]
    ai_calls: dict[str, int]
    exports: dict[str, int]


class OperationsOut(ApiModel):
    generated_at: datetime
    window_hours: int
    jobs: JobsSummary
    processing: FailureRates = Field(description="Imports, formatting, reference reading and translation finished in the window.")
    exports: FailureRates = Field(description="Export jobs finished in the window.")
    usage_spikes: list[UsageSpike]
    storage: StorageSummary
    abuse: AbuseSignals
    this_process: ThisProcess


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(at: datetime | None) -> datetime | None:
    return at if at is None or at.tzinfo else at.replace(tzinfo=timezone.utc)


def _flat(counter: observability.Counter) -> dict[str, int]:
    """A counter's values keyed by their labels joined with "/" (e.g. "export/failed")."""
    return {"/".join(key) or "total": int(value) for key, value in sorted(counter.snapshot().items())}


class OperationsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summary(self, hours: int = 24, now: datetime | None = None) -> OperationsOut:
        now = now or _now()
        since = now - timedelta(hours=hours)
        return OperationsOut(
            generated_at=now,
            window_hours=hours,
            jobs=await self._jobs(since, now),
            processing=await self._rates(since, _PROCESSING_TYPES),
            exports=await self._rates(since, ("export",)),
            usage_spikes=await self._spikes(now - timedelta(hours=2 * hours), since, now),
            storage=await self._storage(),
            abuse=await self._abuse(since),
            this_process=ThisProcess(
                jobs=_flat(observability.JOBS), ai_calls=_flat(observability.AI_CALLS), exports=_flat(observability.EXPORTS)
            ),
        )

    async def _jobs(self, since: datetime, now: datetime) -> JobsSummary:
        db = self._session
        by_status: dict[str, dict[str, int]] = {}
        rows = await db.execute(
            select(ProcessingJob.job_type, ProcessingJob.status, func.count())
            .where(ProcessingJob.created_at >= since)
            .group_by(ProcessingJob.job_type, ProcessingJob.status)
        )
        for job_type, status, count in rows:
            by_status.setdefault(job_type, {})[status] = count
        failed = ProcessingJob.status == "failed"
        rows = await db.execute(
            select(ProcessingJob.job_type, ProcessingJob.failure_reason, func.count())
            .where(failed, ProcessingJob.finished_at >= since)
            .group_by(ProcessingJob.job_type, ProcessingJob.failure_reason)
        )
        failed_by_reason = {f"{job_type}/{reason or 'error'}": count for job_type, reason, count in rows}
        dead_letters = await db.scalar(select(func.count()).select_from(ProcessingJob).where(ProcessingJob.dead_letter.is_(True)))
        running = (await db.scalars(select(ProcessingJob).where(ProcessingJob.status == "running"))).all()
        stuck = [job.id for job in running if policy.is_stuck(job, now)]
        oldest = _aware(await db.scalar(select(func.min(ProcessingJob.created_at)).where(ProcessingJob.status == "pending")))
        recent = await db.scalars(
            select(ProcessingJob).where(failed).order_by(ProcessingJob.finished_at.desc()).limit(RECENT_FAILURES)
        )
        return JobsSummary(
            by_status=by_status,
            failed_by_reason=failed_by_reason,
            dead_letters=dead_letters or 0,
            stuck=stuck,
            pending_oldest_seconds=(now - oldest).total_seconds() if oldest else None,
            recent_failures=[
                JobFailure(
                    id=job.id,
                    workspace_id=job.workspace_id,
                    job_type=job.job_type,
                    failure_reason=job.failure_reason,
                    dead_letter=job.dead_letter,
                    attempts=job.attempts,
                    finished_at=_aware(job.finished_at),
                )
                for job in recent
            ],
        )

    async def _rates(self, since: datetime, job_types: tuple[str, ...]) -> FailureRates:
        rows = await self._session.execute(
            select(ProcessingJob.status, func.count())
            .where(ProcessingJob.job_type.in_(job_types), ProcessingJob.finished_at >= since)
            .group_by(ProcessingJob.status)
        )
        counts = dict(rows.all())
        return FailureRates(finished=sum(counts.values()), failed=counts.get("failed", 0))

    async def _usage(self, start: datetime, end: datetime) -> dict[tuple[str, str], int]:
        rows = await self._session.execute(
            select(UsageRecord.workspace_id, UsageRecord.metric, func.sum(UsageRecord.quantity))
            .where(UsageRecord.created_at >= start, UsageRecord.created_at < end)
            .group_by(UsageRecord.workspace_id, UsageRecord.metric)
        )
        return {(workspace_id, metric): int(total or 0) for workspace_id, metric, total in rows}

    async def _spikes(self, before: datetime, since: datetime, now: datetime) -> list[UsageSpike]:
        window, previous = await self._usage(since, now), await self._usage(before, since)
        spikes = [
            UsageSpike(workspace_id=workspace_id, metric=metric, window=used, previous_window=previous.get((workspace_id, metric), 0))
            for (workspace_id, metric), used in window.items()
            if used >= SPIKE_MINIMUM and used >= SPIKE_FACTOR * previous.get((workspace_id, metric), 0)
        ]
        return sorted(spikes, key=lambda spike: spike.window, reverse=True)

    async def _storage(self) -> StorageSummary:
        db = self._session
        per_workspace: Tally[str] = Tally()
        documents = 0
        sums: dict[str, int] = {}
        for name, query in (
            (
                "document",
                select(DocumentRow.workspace_id, func.sum(octet_length(cast(DocumentRow.data, Text))), func.count()).group_by(
                    DocumentRow.workspace_id
                ),
            ),
            (
                "version",
                select(DocumentRow.workspace_id, func.sum(DocumentVersion.stored_bytes), func.count())
                .join(DocumentRow, DocumentRow.id == DocumentVersion.document_id)
                .group_by(DocumentRow.workspace_id),
            ),
            ("asset", select(DocumentAsset.workspace_id, func.sum(DocumentAsset.size_bytes), func.count()).group_by(DocumentAsset.workspace_id)),
        ):
            total = 0
            for workspace_id, size, count in await db.execute(query):
                per_workspace[workspace_id] += int(size or 0)
                total += int(size or 0)
                if name == "document":
                    documents += count
            sums[name] = total
        return StorageSummary(
            documents=documents,
            document_bytes=sums["document"],
            version_bytes=sums["version"],
            asset_bytes=sums["asset"],
            total_bytes=sum(sums.values()),
            largest_workspaces=[WorkspaceStorage(workspace_id=key, bytes=size) for key, size in per_workspace.most_common(TOP)],
        )

    async def _abuse(self, since: datetime) -> AbuseSignals:
        db = self._session
        accounts = await db.scalar(select(func.count()).select_from(User).where(User.created_at >= since))
        rows = await db.execute(
            select(ProcessingJob.workspace_id, func.count().label("jobs"))
            .where(ProcessingJob.created_at >= since)
            .group_by(ProcessingJob.workspace_id)
            .order_by(func.count().desc())
            .limit(TOP)
        )
        return AbuseSignals(
            accounts_created=accounts or 0,
            most_jobs=[WorkspaceCount(workspace_id=workspace_id, count=count) for workspace_id, count in rows],
            refusals=_flat(observability.SECURITY_EVENTS),
        )
