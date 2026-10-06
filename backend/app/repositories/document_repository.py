import json
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.db.models import Document as DocumentRow
from app.db.models import WorkspaceMember
from app.db.types import EncodedJSON
from app.formatting.engine import recompute_styles
from app.models.document import Document as DocumentModel


class DocumentSummaryRow(NamedTuple):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    formatted_at: datetime | None
    source_type: str | None
    original_filename: str | None
    template_id: str | None


def dump_document(document: DocumentModel) -> dict:
    """The JSON stored in documents.data and document_versions.data. `revision`
    lives only in its own column, so a stale copy can never ride along in `data`;
    `mode="json"` because the driver's JSON encoder knows neither datetimes nor enums."""
    return document.model_dump(mode="json", exclude={"revision"})


def stored_form(document: DocumentModel) -> EncodedJSON:
    """What a save stores: the document's dump with its stored text, both made once so
    the row, the undo step and the answer share them (PERF-008). Plain data in, plain
    data out, so a thread can make it."""
    return EncodedJSON(dump_document(document))


def document_from_json(text: str, revision: int) -> DocumentModel:
    """`DocumentRepository.to_model` for a row's JSON as text, off the row: the whole of
    reading a document into its model (decode, validate, resolve its styles), on plain
    data, so a save can do it in a thread instead of on the event loop."""
    return _model({**json.loads(text), "revision": revision})


def _model(data: dict) -> DocumentModel:
    document = DocumentModel.model_validate(data)
    recompute_styles(document)
    return document


class DocumentRepository:
    """Postgres-backed persistence for `Document`: `data` holds the full Pydantic
    document verbatim (see dump_document)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def to_model(row: DocumentRow) -> DocumentModel:
        """The stored document, with its resolved styles worked out again: they are
        derived from its rules and the render specification, so a document saved
        before a default changed still opens and exports with the current look."""
        return _model({**row.data, "revision": row.revision})

    @staticmethod
    def apply(row: DocumentRow, document: DocumentModel, data: dict | None = None) -> None:
        """`data`: the document's dump, when the caller has made it (stored_form)."""
        row.title = document.metadata.title
        row.document_type = document.documentType
        row.schema_version = document.schemaVersion
        row.data = dump_document(document) if data is None else data

    async def get(self, document_id: str) -> DocumentModel | None:
        row = await self._session.get(DocumentRow, document_id)
        return self.to_model(row) if row else None

    async def get_row_for_user(self, document_id: str, user_id: str) -> DocumentRow | None:
        """None both when the document doesn't exist and when it belongs to a
        workspace the user isn't a member of, so callers can't tell the two apart."""
        return (
            await self._session.execute(
                select(DocumentRow)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == DocumentRow.workspace_id)
                .where(DocumentRow.id == document_id, WorkspaceMember.user_id == user_id)
            )
        ).scalar_one_or_none()

    async def get_row_with_json_for_user(self, document_id: str, user_id: str) -> tuple[DocumentRow, str] | None:
        """For a write: the row without its `data` loaded, and that JSON as the text the
        database holds, undecoded (PERF-008) -- decoding a big document is work for a
        thread, not for the query's result handling on the event loop. The row's `data`
        stays unloaded; a write sets it (apply), nobody reads it. None as get_row_for_user."""
        found = (
            await self._session.execute(
                select(DocumentRow, cast(DocumentRow.data, Text))
                .options(defer(DocumentRow.data))
                .join(WorkspaceMember, WorkspaceMember.workspace_id == DocumentRow.workspace_id)
                .where(DocumentRow.id == document_id, WorkspaceMember.user_id == user_id)
            )
        ).one_or_none()
        return (found[0], found[1]) if found else None

    async def get_for_user(self, document_id: str, user_id: str) -> DocumentModel | None:
        row = await self.get_row_for_user(document_id, user_id)
        return self.to_model(row) if row else None

    async def workspace_id_of(self, document_id: str) -> str | None:
        return (
            await self._session.execute(select(DocumentRow.workspace_id).where(DocumentRow.id == document_id))
        ).scalar_one_or_none()

    async def summaries_for_user(
        self, user_id: str, *, query: str | None, sort: str, limit: int, offset: int
    ) -> tuple[list[DocumentSummaryRow], int]:
        """One page of the documents a user can open, and how many there are in
        all. Only light columns and a few JSON fields are read, never whole documents."""
        visible = (
            select(DocumentRow.id)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == DocumentRow.workspace_id)
            .where(WorkspaceMember.user_id == user_id)
        )
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            visible = visible.where(DocumentRow.title.ilike(f"%{escaped}%", escape="\\"))
        total = await self._session.scalar(select(func.count()).select_from(visible.subquery()))
        order = {
            "title": (func.lower(DocumentRow.title).asc(), DocumentRow.id),
            "created": (DocumentRow.created_at.desc(), DocumentRow.id),
        }.get(sort, (DocumentRow.updated_at.desc(), DocumentRow.id))
        rows = await self._session.execute(
            select(
                DocumentRow.id,
                DocumentRow.title,
                DocumentRow.created_at,
                DocumentRow.updated_at,
                DocumentRow.formatted_at,
                DocumentRow.data["metadata"]["sourceType"].as_string(),
                DocumentRow.data["metadata"]["originalFilename"].as_string(),
                DocumentRow.data["templateId"].as_string(),
            )
            .where(DocumentRow.id.in_(visible))
            .order_by(*order)
            .limit(limit)
            .offset(offset)
        )
        return [DocumentSummaryRow(*row) for row in rows.all()], int(total or 0)

    async def list_for_workspace(self, workspace_id: str) -> list[DocumentModel]:
        rows = (
            (await self._session.execute(select(DocumentRow).where(DocumentRow.workspace_id == workspace_id)))
            .scalars()
            .all()
        )
        return [self.to_model(row) for row in rows]

    async def create(self, workspace_id: str, document: DocumentModel, created_by: str | None = None) -> DocumentRow:
        row = DocumentRow(id=document.id, workspace_id=workspace_id, created_by=created_by)
        self.apply(row, document)
        self._session.add(row)
        await self._session.flush()
        return row

    async def update(self, document: DocumentModel) -> bool:
        row = await self._session.get(DocumentRow, document.id)
        if row is None:
            return False
        self.apply(row, document)
        await self._session.flush()
        return True

    async def delete(self, document_id: str) -> bool:
        row = await self._session.get(DocumentRow, document_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True
