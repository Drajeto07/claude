from fastapi import UploadFile

from app.ai.base import AIProvider
from app.ai.instruction_extraction import extract_formatting_rules
from app.formatting.engine import (
    FormattingConflict,
    apply_formatting,
    clear_element_override,
    detect_conflicts,
    set_element_override,
)
from app.formatting.templates import get_template
from app.models.document import Document, FormattingProperty, FormattingRule
from app.services.ingestion_service import (
    build_document_from_docx,
    build_document_from_pdf,
    build_document_from_text,
    decode_text_upload,
)


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
    """In-memory store — the entire "database" for this phase.

    The spec (MVP scope) explicitly forbids assuming persistent storage:
    accounts and cloud document history are out of scope for the MVP, so
    documents only live as long as this process does.
    """

    def __init__(self) -> None:
        self._documents: dict[str, Document] = {}
        # Formatting/structural undo-redo only -- a separate track from
        # Tiptap's own text-edit history, which never touches the backend.
        # Full snapshots, not diffs: documents are small and fully in-memory
        # already, so this is simple and obviously correct rather than a
        # command log earning its complexity.
        self._undo_stacks: dict[str, list[Document]] = {}
        self._redo_stacks: dict[str, list[Document]] = {}

    async def create_from_text(self, text: str, title: str | None, provider: AIProvider) -> Document:
        document = await build_document_from_text(text, title, provider)
        self._documents[document.id] = document
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
        return next_state

    async def format_document(
        self,
        document_id: str,
        *,
        template_id: str | None,
        instructions_text: str,
        provider: AIProvider,
        drop_overrides: list[tuple[str, FormattingProperty]] | None = None,
    ) -> Document | None:
        """Resolves a template (raises UnknownTemplateError if template_id is
        unrecognized) plus optional free-text instructions into concrete
        styles and applies them to the stored document in place. Returns None
        for an unknown document_id -- same convention as get() -- so the API
        layer handles the 404, while an unknown template is a 400 raised
        here and left to propagate.

        When `drop_overrides` is None (no conflict resolutions supplied
        yet), conflicting live overrides are detected first and raised as
        FormattingConflictsError *without mutating anything* -- the caller
        is expected to re-call with resolutions once the user has chosen.
        Supplying `drop_overrides` (even an empty list, meaning every
        conflict was resolved as "keep current") skips re-detection
        entirely and applies directly, trusting the caller already showed
        the user everything it was told about."""
        document = self._documents.get(document_id)
        if document is None:
            return None

        template_rules: list[FormattingRule] = get_template(template_id).rules if template_id else []
        instruction_rules = await extract_formatting_rules(provider, instructions_text)

        if drop_overrides is None:
            conflicts = detect_conflicts(document, template_rules, instruction_rules)
            if conflicts:
                raise FormattingConflictsError(conflicts)

        self._push_undo_snapshot(document_id)
        return apply_formatting(
            document,
            template_id=template_id,
            template_rules=template_rules,
            instruction_rules=instruction_rules,
            drop_overrides=drop_overrides,
        )

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
        return set_element_override(document, element_id=element_id, property=property, value=value, unit=unit)

    def clear_element_style(self, document_id: str, *, element_id: str, property: FormattingProperty) -> Document | None:
        document = self._documents.get(document_id)
        if document is None:
            return None
        self._push_undo_snapshot(document_id)
        return clear_element_override(document, element_id=element_id, property=property)


document_service = DocumentService()
