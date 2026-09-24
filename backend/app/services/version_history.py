from datetime import timedelta

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.mixins import now_utc
from app.db.models import Document as DocumentRow
from app.db.models import DocumentVersion

# How many undo steps are kept is Settings.document_history_max_steps.
# Autosave fires every ~1.2 s while typing; saves within this window of the
# step's start merge into it, so undo removes a burst of typing, not one tick.
CONTENT_MERGE_WINDOW = timedelta(seconds=60)


class VersionHistory:
    """Persisted, bounded, linear undo/redo. Each DocumentVersion holds the full
    document state after one step; `documents.current_version` points at the
    step the document currently shows. Undo/redo move the pointer; a new change
    after an undo drops the steps above it, as in any editor."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def start(self, row: DocumentRow, data: dict) -> None:
        self._session.add(
            DocumentVersion(document_id=row.id, revision_number=1, kind="created", data=data, created_by=row.created_by)
        )
        row.current_version = 1

    async def record(self, row: DocumentRow, *, before: dict, after: dict, kind: str, user_id: str) -> None:
        if await self._version(row.id, row.current_version) is None:
            # Document predates version history: its pre-change state becomes the base step.
            self._session.add(
                DocumentVersion(document_id=row.id, revision_number=row.current_version, kind="created", data=before)
            )

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
                mergeable.data = after
                return

        await self._session.execute(
            delete(DocumentVersion).where(
                DocumentVersion.document_id == row.id, DocumentVersion.revision_number > row.current_version
            )
        )
        number = row.current_version + 1
        self._session.add(
            DocumentVersion(document_id=row.id, revision_number=number, kind=kind, data=after, created_by=user_id)
        )
        row.current_version = number
        max_steps = get_settings().document_history_max_steps
        await self._session.execute(
            delete(DocumentVersion).where(
                DocumentVersion.document_id == row.id, DocumentVersion.revision_number <= number - max_steps
            )
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

    async def _version(self, document_id: str, number: int) -> DocumentVersion | None:
        return (
            await self._session.execute(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document_id, DocumentVersion.revision_number == number
                )
            )
        ).scalar_one_or_none()
