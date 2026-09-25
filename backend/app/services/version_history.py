from datetime import timedelta

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.config import get_settings
from app.db.mixins import now_utc
from app.db.models import Document as DocumentRow
from app.db.models import DocumentVersion, User

# How many undo steps are kept is Settings.document_history_max_steps.
# Autosave fires every ~1.2 s while typing; saves within this window of the
# step's start merge into it, so undo removes a burst of typing, not one tick.
CONTENT_MERGE_WINDOW = timedelta(seconds=60)
# The document as it was created or imported: never trimmed, so it can always be
# viewed, restored and compared with (корекции.docx §31, §39 "before/after").
ORIGINAL = 1


class VersionHistory:
    """Persisted, bounded, linear undo/redo. Each DocumentVersion holds the full
    document state after one step, and says what the step did; `documents.
    current_version` points at the step the document currently shows. Undo/redo
    move the pointer; a new change after an undo drops the steps above it, as in
    any editor. Beyond the last `document_history_max_steps` only the original
    is kept."""

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
        if await self._version(row.id, row.current_version) is None:
            # Document predates version history: its pre-change state becomes the base step.
            self._session.add(
                DocumentVersion(
                    document_id=row.id,
                    revision_number=row.current_version,
                    kind="created",
                    data=before,
                    description="Before version history began",
                )
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
            DocumentVersion(
                document_id=row.id, revision_number=number, kind=kind, data=after, description=description, created_by=user_id
            )
        )
        row.current_version = number
        max_steps = get_settings().document_history_max_steps
        await self._session.execute(
            delete(DocumentVersion).where(
                DocumentVersion.document_id == row.id,
                DocumentVersion.revision_number <= number - max_steps,
                DocumentVersion.revision_number != ORIGINAL,
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

    async def listing(self, row: DocumentRow) -> list[tuple[DocumentVersion, str | None]]:
        """Every kept version, newest first, with who made it (name, else email;
        None once that account is gone). Their data isn't loaded."""
        result = await self._session.execute(
            select(DocumentVersion, func.coalesce(User.full_name, User.email))
            .options(defer(DocumentVersion.data))
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
