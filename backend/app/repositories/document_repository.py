from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document as DocumentRow
from app.db.models import WorkspaceMember
from app.formatting.engine import recompute_styles
from app.models.document import Document as DocumentModel


def dump_document(document: DocumentModel) -> dict:
    """The JSON stored in documents.data and document_versions.data. `revision`
    lives only in its own column, so a stale copy can never ride along in `data`;
    `mode="json"` because the driver's JSON encoder knows neither datetimes nor enums."""
    return document.model_dump(mode="json", exclude={"revision"})


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
        document = DocumentModel.model_validate({**row.data, "revision": row.revision})
        recompute_styles(document)
        return document

    @staticmethod
    def apply(row: DocumentRow, document: DocumentModel) -> None:
        row.title = document.metadata.title
        row.document_type = document.documentType
        row.schema_version = document.schemaVersion
        row.data = dump_document(document)

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

    async def get_for_user(self, document_id: str, user_id: str) -> DocumentModel | None:
        row = await self.get_row_for_user(document_id, user_id)
        return self.to_model(row) if row else None

    async def workspace_id_of(self, document_id: str) -> str | None:
        return (
            await self._session.execute(select(DocumentRow.workspace_id).where(DocumentRow.id == document_id))
        ).scalar_one_or_none()

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
