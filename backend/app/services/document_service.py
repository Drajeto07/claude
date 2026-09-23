from datetime import datetime, timezone

from fastapi import UploadFile

from app.ai.base import AIProvider
from app.ai.instruction_extraction import extract_document_edits
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
from app.formatting.templates import get_template
from app.models.document import Document, Element, ElementType, FormattingProperty, FormattingRule
from app.services import persistence
from app.services.ingestion_service import (
    build_document_from_docx,
    build_document_from_pdf,
    build_document_from_text,
    decode_text_upload,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UnsupportedFileTypeError(Exception):
    def __init__(self, extension: str) -> None:
        super().__init__(f"Unsupported file type: {extension!r}")


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


class DocumentService:
    """File-backed store (see app/services/persistence.py) -- documents
    survive a restart, but this is still single-process/single-user: no
    concurrent-writer safety, no accounts, no cloud history (spec MVP scope
    for those still holds; only the "documents vanish on restart" line has
    moved, per Boril's explicit ask that reload/restart must not lose work).

    Undo/redo *history* stays in-memory-only and does not survive a restart
    -- only the current document state persists. An explicit, narrower scope
    line than "everything persists," not a silent gap: post-restart Undo
    correctly reports NothingToUndoError instead of misbehaving.
    """

    def __init__(self) -> None:
        self._documents: dict[str, Document] = persistence.load_all_documents()
        self._undo_stacks: dict[str, list[Document]] = {}
        self._redo_stacks: dict[str, list[Document]] = {}

    def _persist(self, document: Document) -> None:
        persistence.save_document(document)

    async def create_from_text(self, text: str, title: str | None, provider: AIProvider) -> Document:
        document = await build_document_from_text(text, title, provider)
        self._documents[document.id] = document
        self._persist(document)
        return document

    async def create_from_upload(self, file: UploadFile, title: str | None, provider: AIProvider) -> Document:
        filename = file.filename or "upload"
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        file_bytes = await file.read()

        if extension == "docx":
            document = build_document_from_docx(file_bytes, filename, title)
        elif extension == "pdf":
            document = await build_document_from_pdf(file_bytes, title, provider)
        elif extension == "txt":
            document = await build_document_from_text(decode_text_upload(file_bytes), title, provider)
            document.metadata.sourceType = "uploaded_txt"
            document.metadata.originalFilename = filename
        else:
            raise UnsupportedFileTypeError(extension)

        self._documents[document.id] = document
        self._persist(document)
        return document

    def get(self, document_id: str) -> Document | None:
        return self._documents.get(document_id)

    def _push_undo_snapshot(self, document_id: str) -> None:
        """Records the *current* (pre-mutation) state so it can be restored
        later, and clears the redo stack -- any new action invalidates old
        redo history, the standard undo/redo semantics."""
        document = self._documents.get(document_id)
        if document is None:
            return
        self._undo_stacks.setdefault(document_id, []).append(document.model_copy(deep=True))
        self._redo_stacks[document_id] = []

    def undo(self, document_id: str) -> Document | None:
        """None = unknown document (404); NothingToUndoError (400) when that
        document's undo stack is empty."""
        if document_id not in self._documents:
            return None
        stack = self._undo_stacks.get(document_id, [])
        if not stack:
            raise NothingToUndoError(document_id)
        previous = stack.pop()
        self._redo_stacks.setdefault(document_id, []).append(self._documents[document_id].model_copy(deep=True))
        self._documents[document_id] = previous
        self._persist(previous)
        return previous

    def redo(self, document_id: str) -> Document | None:
        if document_id not in self._documents:
            return None
        stack = self._redo_stacks.get(document_id, [])
        if not stack:
            raise NothingToRedoError(document_id)
        next_state = stack.pop()
        self._undo_stacks.setdefault(document_id, []).append(self._documents[document_id].model_copy(deep=True))
        self._documents[document_id] = next_state
        self._persist(next_state)
        return next_state

    async def format_document(
        self,
        document_id: str,
        *,
        template_id: str | None,
        instructions_text: str,
        provider: AIProvider,
        drop_overrides: list[tuple[str, FormattingProperty]] | None = None,
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
        document = self._documents.get(document_id)
        if document is None:
            return None

        template_rules: list[FormattingRule] = get_template(template_id).rules if template_id else []
        edits = await extract_document_edits(provider, instructions_text, document)

        if drop_overrides is None:
            conflicts = detect_conflicts(document, template_rules, edits.rules)
            if conflicts:
                raise FormattingConflictsError(conflicts)

        if edits.operations:
            validate_operations(document, edits.operations)

        self._push_undo_snapshot(document_id)
        if edits.operations:
            apply_operations(document, edits.operations)
        apply_formatting(
            document,
            template_id=template_id,
            template_rules=template_rules,
            instruction_rules=edits.rules,
            drop_overrides=drop_overrides,
        )
        self._persist(document)
        return document, edits.ai_unavailable, len(edits.rules) + len(edits.operations)

    def set_element_style(
        self, document_id: str, *, element_id: str, property: FormattingProperty, value: str, unit: str | None
    ) -> Document | None:
        """None = unknown document (404, same convention as get()/
        format_document()); UnknownElementError raised here propagates for
        the API layer to turn into its own 404."""
        document = self._documents.get(document_id)
        if document is None:
            return None
        self._push_undo_snapshot(document_id)
        result = set_element_override(document, element_id=element_id, property=property, value=value, unit=unit)
        self._persist(result)
        return result

    def clear_element_style(self, document_id: str, *, element_id: str, property: FormattingProperty) -> Document | None:
        document = self._documents.get(document_id)
        if document is None:
            return None
        self._push_undo_snapshot(document_id)
        result = clear_element_override(document, element_id=element_id, property=property)
        self._persist(result)
        return result

    def update_content(self, document_id: str, *, elements: list[Element]) -> Document | None:
        """Stage 0: reconciles live Tiptap edits back into the stored
        document -- the piece that was missing entirely before. The frontend
        (editor/tiptapToDocument.ts) has already done the id-matching
        (existing elements updated in place, new top-level blocks appended,
        removed ones dropped); this just accepts the result, re-derives
        `order`, prunes any per-element override that pointed at a since-
        removed element, and recomputes styles so new elements pick up a
        styleRef. No revision entry -- this fires on every autosave tick,
        and would otherwise spam the changelog Instructions relies on to
        prove something real happened."""
        document = self._documents.get(document_id)
        if document is None:
            return None
        self._push_undo_snapshot(document_id)
        for index, element in enumerate(elements):
            element.order = index
        document.elements = elements
        prune_dangling_element_rules(document)
        recompute_styles(document)
        document.metadata.updatedAt = _utcnow()
        self._persist(document)
        return document

    def add_page(self, document_id: str, *, after_element_id: str | None) -> Document | None:
        document = self._documents.get(document_id)
        if document is None:
            return None
        self._push_undo_snapshot(document_id)
        result = insert_page_break(document, after_element_id=after_element_id)
        self._persist(result)
        return result

    def add_element(self, document_id: str, *, element_type: ElementType, after_element_id: str | None, text: str) -> Document | None:
        document = self._documents.get(document_id)
        if document is None:
            return None
        self._push_undo_snapshot(document_id)
        result = insert_element(document, element_type=element_type, after_element_id=after_element_id, text=text)
        self._persist(result)
        return result

    def rename(self, document_id: str, *, title: str) -> Document | None:
        document = self._documents.get(document_id)
        if document is None:
            return None
        self._push_undo_snapshot(document_id)
        document.metadata.title = title
        document.metadata.updatedAt = _utcnow()
        self._persist(document)
        return document

    def set_page_setting(
        self, document_id: str, *, property: FormattingProperty, value: str, unit: str | None
    ) -> Document | None:
        document = self._documents.get(document_id)
        if document is None:
            return None
        self._push_undo_snapshot(document_id)
        result = set_document_setting(document, property=property, value=value, unit=unit)
        self._persist(result)
        return result

    def clear_page_setting(self, document_id: str, *, property: FormattingProperty) -> Document | None:
        document = self._documents.get(document_id)
        if document is None:
            return None
        self._push_undo_snapshot(document_id)
        result = clear_document_setting(document, property=property)
        self._persist(result)
        return result


document_service = DocumentService()
