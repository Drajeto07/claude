import inspect
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.ai.base import AIProvider
from app.ai.instruction_extraction import extract_document_edits
from app.db.models import Document as DocumentRow
from app.db.models import ProcessingJob
from app.formatting.engine import (
    FormattingConflict,
    apply_formatting,
    apply_operations,
    clear_document_setting,
    clear_element_override,
    detect_conflicts,
    insert_element,
    insert_page_break,
    prune_dangling_element_rules,
    recompute_styles,
    set_document_setting,
    set_element_override,
    validate_operations,
)
from app.jobs.files import discard_export_files
from app.models.document import Document, Element, ElementType, FormattingProperty, FormattingRule
from app.repositories.document_repository import DocumentRepository, dump_document
from app.services.asset_service import AssetService
from app.services.auth_service import AuthService
from app.services.image_assets import externalize_inline_images
from app.services.ingestion_service import (
    ProgressReport,
    UnsupportedFileTypeError,
    build_document_from_text,
    build_document_from_upload,
)
from app.services.template_service import TemplateService
from app.services.version_history import VersionHistory
from app.storage.base import StorageProvider


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FormattingConflictsError(Exception):
    """Raised instead of applying anything when detect_conflicts() finds
    conflicts and the caller hasn't supplied resolutions yet (spec §7.10) --
    the API layer turns this into a 409 carrying the conflict list."""

    def __init__(self, conflicts: list[FormattingConflict]) -> None:
        self.conflicts = conflicts
        super().__init__(f"{len(conflicts)} formatting conflict(s) require resolution")


class NothingToUndoError(Exception):
    def __init__(self, document_id: str) -> None:
        super().__init__(f"Nothing to undo for document {document_id!r}")


class NothingToRedoError(Exception):
    def __init__(self, document_id: str) -> None:
        super().__init__(f"Nothing to redo for document {document_id!r}")


class RevisionConflictError(Exception):
    """The caller's copy is stale: the document changed after they loaded it
    (another tab, device or user). Nothing was written. The API answers 412."""

    def __init__(self, current_revision: int | None) -> None:
        self.current_revision = current_revision
        super().__init__("The document was changed elsewhere since it was loaded.")


class DocumentService:
    """One instance per request, acting for one signed-in user. Every read goes
    through DocumentRepository's user-scoped lookups, so a document outside the
    user's workspaces behaves exactly like one that doesn't exist (None -> 404).

    Every write: load the row, check the caller's `expected_revision` (the If-Match
    they sent; None skips the check), apply, record an undo step
    (services/version_history.py), commit. Two writes racing between load and
    commit are caught by the row's version counter and reported the same way."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        storage: StorageProvider,
        expected_revision: int | None = None,
    ) -> None:
        self._session = session
        self._storage = storage
        self._repo = DocumentRepository(session)
        self._assets = AssetService(session, storage)
        self._versions = VersionHistory(session)
        self._user_id = user_id
        self._expected_revision = expected_revision

    async def create(self, document: Document) -> Document:
        """Stores an already-built document in the user's workspace: the one path
        every new document takes (images become assets, version history starts)."""
        recompute_styles(document)  # parsed text has no resolved look yet; the render specification's defaults apply
        workspace_id = await AuthService(self._session).default_workspace_id(self._user_id)
        # The row has to exist before its images can be stored as assets pointing
        # at it; the base64 version is replaced within the same transaction, so it
        # is never committed.
        row = await self._repo.create(workspace_id, document, created_by=self._user_id)
        if await externalize_inline_images(document, self._assets, workspace_id):
            self._repo.apply(row, document)
        self._versions.start(row, dump_document(document))
        await self._session.commit()
        document.revision = row.revision
        return document

    async def _load_for_write(self, document_id: str) -> tuple[DocumentRow, Document] | None:
        row = await self._repo.get_row_for_user(document_id, self._user_id)
        if row is None:
            return None
        if self._expected_revision is not None and row.revision != self._expected_revision:
            raise RevisionConflictError(row.revision)
        return row, self._repo.to_model(row)

    async def _write(self, row: DocumentRow, document: Document, *, before: dict | None, kind: str) -> Document:
        """Stores `document` into `row`, records the undo step (skipped for undo/
        redo themselves, which only move the pointer: before=None), commits."""
        try:
            # One flush for the whole write: an autoflush triggered by the history
            # queries would UPDATE the row twice and bump its revision by two.
            with self._session.no_autoflush:
                self._repo.apply(row, document)
                if before is not None:
                    await self._versions.record(
                        row, before=before, after=dump_document(document), kind=kind, user_id=self._user_id
                    )
            await self._session.commit()
        except StaleDataError as exc:
            await self._session.rollback()
            raise RevisionConflictError(None) from exc
        document.revision = row.revision
        return document

    async def _change(
        self, document_id: str, change: Callable[[Document], object], *, kind: str = "change"
    ) -> Document | None:
        """Applies `change` (sync or async) in place and saves. None = unknown (or
        inaccessible) document; an exception from `change` leaves nothing written."""
        loaded = await self._load_for_write(document_id)
        if loaded is None:
            return None
        row, document = loaded
        before = dump_document(document)
        result = change(document)
        if inspect.isawaitable(result):
            await result
        return await self._write(row, document, before=before, kind=kind)

    async def create_from_text(self, text: str, title: str | None, provider: AIProvider) -> Document:
        return await self.create(await build_document_from_text(text, title, provider))

    async def create_from_upload(self, file: UploadFile, title: str | None, provider: AIProvider) -> Document:
        return await self.create_from_bytes(await file.read(), file.filename or "upload", title, provider)

    async def create_from_bytes(
        self, file_bytes: bytes, filename: str, title: str | None, provider: AIProvider, report: ProgressReport | None = None
    ) -> Document:
        """An uploaded file as a new document (the upload endpoint and the import job).
        UnsupportedFileTypeError for anything but .docx, .pdf and .txt."""
        document = await build_document_from_upload(file_bytes, filename, title, provider, report)
        if report is not None:
            await report("finalizing", 85)
        return await self.create(document)

    async def get(self, document_id: str) -> Document | None:
        return await self._repo.get_for_user(document_id, self._user_id)

    async def export_assets(self, document: Document) -> dict[str, bytes]:
        """Image bytes for an export, limited to assets the user can access."""
        asset_ids = [e.image.assetId for e in document.elements if e.image and e.image.assetId]
        return await self._assets.read_many_for_user(asset_ids, self._user_id)

    async def delete(self, document_id: str) -> bool:
        """False if the document is unknown or inaccessible (the API layer turns
        that into a 404). Its version history goes with it (FK cascade), and so
        do the files of its exports, whoever made them."""
        loaded = await self._load_for_write(document_id)
        if loaded is None:
            return False
        try:
            await discard_export_files(self._session, self._storage, ProcessingJob.document_id == document_id)
            await self._session.delete(loaded[0])
            await self._session.commit()
        except StaleDataError as exc:
            await self._session.rollback()
            raise RevisionConflictError(None) from exc
        return True

    async def undo(self, document_id: str) -> Document | None:
        """None = unknown document (404); NothingToUndoError (400) when there is
        no older step (never recorded, or trimmed off the bounded history)."""
        loaded = await self._load_for_write(document_id)
        if loaded is None:
            return None
        row, _ = loaded
        data = await self._versions.undo(row)
        if data is None:
            raise NothingToUndoError(document_id)
        return await self._write(row, Document.model_validate(data), before=None, kind="change")

    async def redo(self, document_id: str) -> Document | None:
        loaded = await self._load_for_write(document_id)
        if loaded is None:
            return None
        row, _ = loaded
        data = await self._versions.redo(row)
        if data is None:
            raise NothingToRedoError(document_id)
        return await self._write(row, Document.model_validate(data), before=None, kind="change")

    async def format_document(
        self,
        document_id: str,
        *,
        template_id: str | None,
        instructions_text: str,
        provider: AIProvider,
        drop_overrides: list[tuple[str, FormattingProperty]] | None = None,
        report: ProgressReport | None = None,
    ) -> tuple[Document, bool, int] | None:
        """Resolves a template (raises UnknownTemplateError if template_id is
        unrecognized) plus optional free-text instructions into concrete
        styles/operations and applies them to the stored document in place.
        Returns `(document, ai_unavailable, instruction_edit_count)` -- the
        extra elements let the API layer tell the frontend "the AI call
        itself failed" apart from "it ran and found nothing to change"
        (spec AC-INSTRUCTION-11/12). Returns None for an unknown
        document_id -- same convention as get() -- so the API layer handles
        the 404, while an unknown template is a 400 raised here and left to
        propagate.

        When `drop_overrides` is None (no conflict resolutions supplied
        yet), conflicting live overrides are detected first and raised as
        FormattingConflictsError *without mutating anything* -- the caller
        is expected to re-call with resolutions once the user has chosen.
        Supplying `drop_overrides` (even an empty list, meaning every
        conflict was resolved as "keep current") skips re-detection
        entirely and applies directly, trusting the caller already showed
        the user everything it was told about.

        Structural/targeted-style operations extracted from instructions
        (delete/insert/move/add-page/targeted set_style) are validated
        against the document *before* anything is applied -- an invalid
        batch raises InvalidOperationError and changes nothing, including
        the template, so a bad instruction can never half-apply."""
        loaded = await self._load_for_write(document_id)
        if loaded is None:
            return None
        row, document = loaded

        template_rules: list[FormattingRule] = (
            await TemplateService(self._session, user_id=self._user_id).rules_for(template_id) if template_id else []
        )
        edits = await extract_document_edits(provider, instructions_text, document)
        if report is not None:
            await report("formatting", 70)

        if drop_overrides is None:
            conflicts = detect_conflicts(document, template_rules, edits.rules)
            if conflicts:
                raise FormattingConflictsError(conflicts)

        if edits.operations:
            validate_operations(document, edits.operations)

        before = dump_document(document)
        if edits.operations:
            apply_operations(document, edits.operations)
        apply_formatting(
            document,
            template_id=template_id,
            template_rules=template_rules,
            instruction_rules=edits.rules,
            drop_overrides=drop_overrides,
        )
        document = await self._write(row, document, before=before, kind="change")
        return document, edits.ai_unavailable, len(edits.rules) + len(edits.operations)

    async def set_element_style(
        self, document_id: str, *, element_id: str, property: FormattingProperty, value: str, unit: str | None
    ) -> Document | None:
        """None = unknown document (404); UnknownElementError raised by the
        engine propagates for the API layer to turn into its own 404."""
        return await self._change(
            document_id,
            lambda document: set_element_override(
                document, element_id=element_id, property=property, value=value, unit=unit
            ),
        )

    async def clear_element_style(
        self, document_id: str, *, element_id: str, property: FormattingProperty
    ) -> Document | None:
        return await self._change(
            document_id,
            lambda document: clear_element_override(document, element_id=element_id, property=property),
        )

    async def update_content(self, document_id: str, *, elements: list[Element]) -> Document | None:
        """Reconciles live Tiptap edits back into the stored document. The
        frontend (editor/tiptapToDocument.ts) has already done the id-matching
        (existing elements updated in place, new top-level blocks appended,
        removed ones dropped); this just accepts the result, re-derives
        `order`, prunes any per-element override that pointed at a since-
        removed element, and recomputes styles so new elements pick up a
        styleRef. No revision entry -- this fires on every autosave tick,
        and would otherwise spam the changelog Instructions relies on to
        prove something real happened. Consecutive autosaves merge into one
        undo step (kind="content", see version_history.py)."""

        async def replace_elements(document: Document) -> None:
            for index, element in enumerate(elements):
                element.order = index
            document.elements = elements
            # An image pasted into the editor arrives as a data: URI.
            workspace_id = await self._repo.workspace_id_of(document.id)
            await externalize_inline_images(document, self._assets, workspace_id)
            prune_dangling_element_rules(document)
            recompute_styles(document)
            document.metadata.updatedAt = _utcnow()

        return await self._change(document_id, replace_elements, kind="content")

    async def add_page(self, document_id: str, *, after_element_id: str | None) -> Document | None:
        return await self._change(
            document_id, lambda document: insert_page_break(document, after_element_id=after_element_id)
        )

    async def add_element(
        self, document_id: str, *, element_type: ElementType, after_element_id: str | None, text: str
    ) -> Document | None:
        return await self._change(
            document_id,
            lambda document: insert_element(
                document, element_type=element_type, after_element_id=after_element_id, text=text
            ),
        )

    async def rename(self, document_id: str, *, title: str) -> Document | None:
        def set_title(document: Document) -> None:
            document.metadata.title = title
            document.metadata.updatedAt = _utcnow()

        return await self._change(document_id, set_title)

    async def set_page_setting(
        self, document_id: str, *, property: FormattingProperty, value: str, unit: str | None
    ) -> Document | None:
        return await self._change(
            document_id,
            lambda document: set_document_setting(document, property=property, value=value, unit=unit),
        )

    async def clear_page_setting(self, document_id: str, *, property: FormattingProperty) -> Document | None:
        return await self._change(
            document_id, lambda document: clear_document_setting(document, property=property)
        )
