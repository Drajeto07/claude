from fastapi import UploadFile

from app.ai.base import AIProvider
from app.ai.instruction_extraction import extract_formatting_rules
from app.formatting.engine import apply_formatting
from app.formatting.templates import get_template
from app.models.document import Document, FormattingRule
from app.services.ingestion_service import (
    build_document_from_docx,
    build_document_from_pdf,
    build_document_from_text,
    decode_text_upload,
)


class UnsupportedFileTypeError(Exception):
    def __init__(self, extension: str) -> None:
        super().__init__(f"Unsupported file type: {extension!r}")


class DocumentService:
    """In-memory store — the entire "database" for this phase.

    The spec (MVP scope) explicitly forbids assuming persistent storage:
    accounts and cloud document history are out of scope for the MVP, so
    documents only live as long as this process does.
    """

    def __init__(self) -> None:
        self._documents: dict[str, Document] = {}

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

    async def format_document(
        self,
        document_id: str,
        *,
        template_id: str | None,
        instructions_text: str,
        provider: AIProvider,
    ) -> Document | None:
        """Resolves a template (raises UnknownTemplateError if template_id is
        unrecognized) plus optional free-text instructions into concrete
        styles and applies them to the stored document in place. Returns None
        for an unknown document_id -- same convention as get() -- so the API
        layer handles the 404, while an unknown template is a 400 raised
        here and left to propagate."""
        document = self._documents.get(document_id)
        if document is None:
            return None

        template_rules: list[FormattingRule] = get_template(template_id).rules if template_id else []
        instruction_rules = await extract_formatting_rules(provider, instructions_text)

        return apply_formatting(
            document, template_id=template_id, template_rules=template_rules, instruction_rules=instruction_rules
        )


document_service = DocumentService()
