import asyncio
from datetime import timedelta

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.config import get_settings
from app.db.mixins import now_utc
from app.db.models import Document as DocumentRow
from app.db.models import DocumentVersion, User
from app.db.models.document import pack_snapshot

# How many undo steps are kept, and how many bytes they may take, are
# Settings.document_history_max_steps and document_history_max_bytes (see _trim).
# Autosave fires every ~1.2 s while typing; saves within this window of the
# step's start merge into it, so undo removes a burst of typing, not one tick.
CONTENT_MERGE_WINDOW = timedelta(seconds=60)
# The document as it was created or imported: never trimmed, so it can always be
# viewed, restored and compared with (корекции.docx §31, §39 "before/after").
ORIGINAL = 1


class VersionHistory:
    """Persisted, bounded, linear undo/redo. Each DocumentVersion holds the full
    document state after one step (compressed, pictures as asset references), and
    says what the step did; `documents.current_version` points at the step the
    document currently shows. Undo/redo move the pointer; a new change after an
    undo drops the steps above it, as in any editor. Beyond the last
    `document_history_max_steps` steps, or past `document_history_max_bytes`,
    only the original is kept (_trim)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def start(self, row: DocumentRow, data: dict, description: str) -> None:
        self._session.add(
            DocumentVersion(
                document_id=row.id, revision_number=ORIGINAL, kind="created", data=data, description=description, created_by=row.created_by
            )
        )
        row.current_version = ORIGINAL

    async def record(self, row: DocumentRow, *, before: dict, after: dict, kind: str, user_id: str, description: str) -> None:
        """Adds the step `after` (or merges it into the current one). The JSON and zlib
        work of packing a state is done in a thread, on the dict alone (PERF-008)."""
        if await self.needs_base(row):
            # Document predates version history: its pre-change state becomes the base step.
            self._session.add(
                DocumentVersion(
                    document_id=row.id,
                    revision_number=row.current_version,
                    kind="created",
                    compressed_data=await asyncio.to_thread(pack_snapshot, before),
                    description="Before version history began",
                )
            )

        packed = await asyncio.to_thread(pack_snapshot, after)
        at_tip = not await self._session.scalar(
            select(
                exists().where(
                    DocumentVersion.document_id == row.id, DocumentVersion.revision_number > row.current_version
                )
            )
        )
        if kind == "content" and at_tip:
            # Time compared in SQL: SQLite hands datetimes back naive, Postgres aware.
            mergeable = (
                await self._session.execute(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id == row.id,
                        DocumentVersion.revision_number == row.current_version,
                        DocumentVersion.kind == "content",
                        DocumentVersion.created_at > now_utc() - CONTENT_MERGE_WINDOW,
                    )
                )
            ).scalar_one_or_none()
            if mergeable is not None:
                mergeable.compressed_data, mergeable.legacy_data = packed, None
                await self._trim(row, mergeable)
                return

        await self._session.execute(
            delete(DocumentVersion).where(
                DocumentVersion.document_id == row.id, DocumentVersion.revision_number > row.current_version
            )
        )
        number = row.current_version + 1
        newest = DocumentVersion(
            document_id=row.id,
            revision_number=number,
            kind=kind,
            compressed_data=packed,
            description=description,
            created_by=user_id,
        )
        self._session.add(newest)
        row.current_version = number
        await self._trim(row, newest)

    async def _trim(self, row: DocumentRow, current: DocumentVersion) -> None:
        """The retention rule (PERF-004). Always kept: the original, the step the
        document shows (`current`), the one just below it (so the last change, a
        restore included, can always be undone) and any above it (redo; record()
        only gets here once those are gone). Below that, undo steps are kept
        newest first while there are fewer than `document_history_max_steps` steps
        and they, the original and the current step fit in
        `document_history_max_bytes`; everything older goes. Undo walks
        consecutive steps down from the current one, so the history is cut in one
        place and never left with a gap that would end undo early. A restore has
        read its version before it gets here."""
        settings = get_settings()
        # Sizes as stored, without loading any state. `current` is still unflushed,
        # so its size is taken from the object.
        below = (
            await self._session.execute(
                select(DocumentVersion.revision_number, DocumentVersion.stored_bytes)
                .where(DocumentVersion.document_id == row.id, DocumentVersion.revision_number < current.revision_number)
                .order_by(DocumentVersion.revision_number.desc())
            )
        ).all()
        kept_bytes = current.stored_bytes + sum(size for number, size in below if number == ORIGINAL)
        steps = 0
        for number, size in below:
            if number == ORIGINAL:
                continue
            steps += 1
            kept_bytes += size
            if steps >= settings.document_history_max_steps or (steps > 1 and kept_bytes > settings.document_history_max_bytes):
                await self._session.execute(
                    delete(DocumentVersion).where(
                        DocumentVersion.document_id == row.id,
                        DocumentVersion.revision_number <= number,
                        DocumentVersion.revision_number != ORIGINAL,
                    )
                )
                return

    async def needs_base(self, row: DocumentRow) -> bool:
        """Whether record() will keep the pre-change state as the base step: the
        document predates version history. Asked without reading the step: its state is
        the biggest thing in the table (PERF-008)."""
        return not await self._session.scalar(
            select(exists().where(DocumentVersion.document_id == row.id, DocumentVersion.revision_number == row.current_version))
        )

    async def undo(self, row: DocumentRow) -> dict | None:
        """The state to restore, or None if there is nothing older to go back to."""
        previous = await self._version(row.id, row.current_version - 1)
        if previous is None:
            return None
        row.current_version -= 1
        return previous.data

    async def redo(self, row: DocumentRow) -> dict | None:
        following = await self._version(row.id, row.current_version + 1)
        if following is None:
            return None
        row.current_version += 1
        return following.data

    async def listing(self, row: DocumentRow) -> list[tuple[DocumentVersion, str | None]]:
        """Every kept version, newest first, with who made it (name, else email;
        None once that account is gone). Their data isn't loaded."""
        result = await self._session.execute(
            select(DocumentVersion, func.coalesce(User.full_name, User.email))
            .options(defer(DocumentVersion.compressed_data), defer(DocumentVersion.legacy_data))
            .outerjoin(User, User.id == DocumentVersion.created_by)
            .where(DocumentVersion.document_id == row.id)
            .order_by(DocumentVersion.revision_number.desc())
        )
        return [(version, author) for version, author in result.all()]

    async def get(self, row: DocumentRow, number: int) -> DocumentVersion | None:
        return await self._version(row.id, number)

    async def _version(self, document_id: str, number: int) -> DocumentVersion | None:
        return (
            await self._session.execute(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document_id, DocumentVersion.revision_number == number
                )
            )
        ).scalar_one_or_none()
