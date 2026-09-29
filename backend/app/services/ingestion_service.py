import asyncio
from collections.abc import Awaitable, Callable
from functools import partial

from app.ai.base import AIProvider
from app.ai.structure_analysis import analyze_structure
from app.fidelity.content import words
from app.fidelity.imports import docx_import_report, text_import_report
from app.fidelity.report import FidelityItem, FidelityPolicy
from app.fidelity.text_sources import markdown_words, pdf_image_count
from app.models.document import Document
from app.parsers.detection import looks_like_markdown
from app.parsers.docx import parse_docx
from app.parsers.markdown import parse_markdown
from app.parsers.pdf import extract_pdf_text

_TEXT_DECODE_CHAIN = ("utf-8", "utf-8-sig", "cp1251", "latin-1")

# Reports the stage a job has reached and its real progress, 0-100 (app/jobs).
ProgressReport = Callable[[str, int], Awaitable[None]]


class UnsupportedFileTypeError(Exception):
    def __init__(self, extension: str) -> None:
        super().__init__(f"Unsupported file type: {extension!r}")


async def build_document_from_text(
    text: str, title: str | None, provider: AIProvider, *, source_type: str = "paste", method: str | None = None
) -> Document:
    """Route by source characteristics: Markdown-looking text gets free,
    deterministic, perfectly-reliable parsing; only genuinely unstructured
    prose reaches the AI. See docs/spec.md's Phase 2/3 design notes.

    Either way the result's words are checked against the text's (the import
    report): an AI that dropped or changed a sentence shows up there."""
    markdown = looks_like_markdown(text)
    document = parse_markdown(text, title=title) if markdown else await analyze_structure(provider, text, title=title)
    document.importReport = text_import_report(
        document,
        markdown_words(text) if markdown else words(text),
        source_type=source_type,
        method=method or ("markdown-text" if markdown else "source-text"),
    )
    return document


def build_document_from_docx(file_bytes: bytes, filename: str, title: str | None, *, autolink: bool = False) -> Document:
    """DOCX carries real, deterministic structure (Word paragraph styles,
    list/table XML) -- extracting it directly is strictly more accurate than
    re-inferring via AI from a flattened text dump. No AI call on this path.
    The import report checks the result's words against the file's own text.
    `autolink`: turn web and e-mail addresses written as plain text into links (DOCX-026)."""
    document = parse_docx(file_bytes, filename, title=title, autolink=autolink)
    document.importReport = docx_import_report(document, file_bytes, autolink=autolink)
    return document


async def build_document_from_pdf(file_bytes: bytes, title: str | None, provider: AIProvider) -> Document:
    """PDF text extraction has no reliable embedded structure of its own, so
    the extracted text is routed through the same Markdown-sniff gate as
    pasted text -- a PDF rendering of a Markdown document still gets the
    free, deterministic path."""
    text = extract_pdf_text(file_bytes)
    document = await build_document_from_text(text, title, provider, source_type="pdf", method="pdf-extracted-text")
    _note_pdf_limits(document, pdf_image_count(file_bytes))
    return document


def _note_pdf_limits(document: Document, images: int) -> None:
    """What the PDF import doesn't keep, said in the report (its text is checked)."""
    if document.importReport is None:
        return
    document.importReport.items.append(
        FidelityItem(
            feature="pdf.layout",
            policy=FidelityPolicy.LOSSY,
            reason="Only the PDF's text was imported: its layout, columns and tables aren't kept.",
        )
    )
    if images:
        document.importReport.items.append(
            FidelityItem(
                feature="pdf.images",
                policy=FidelityPolicy.UNSUPPORTED,
                reason=f"The PDF's {images} picture{'s' if images != 1 else ''} weren't imported.",
                count=images,
                contentChanged=True,
            )
        )


def decode_text_upload(file_bytes: bytes) -> str:
    for encoding in _TEXT_DECODE_CHAIN:
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def extract_instructions_text(file_bytes: bytes, filename: str) -> str:
    """Instructions-file uploads (spec FR-IN-004) reuse the same decode/
    extraction helpers as document uploads. Only called with an
    already-extension-validated file -- see api/documents.py -- so only
    txt/pdf need handling here; DOCX instructions files aren't supported
    this phase (no plain-text DOCX extraction helper exists yet, and
    instructions files are the less common upload case)."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension == "pdf":
        return extract_pdf_text(file_bytes)
    return decode_text_upload(file_bytes)


async def build_document_from_upload(
    file_bytes: bytes,
    filename: str,
    title: str | None,
    provider: AIProvider,
    report: ProgressReport | None = None,
    *,
    autolink: bool = False,
) -> Document:
    """.docx, .pdf or .txt bytes as a document, reporting each real step to a job
    when one is watching. UnsupportedFileTypeError for anything else. `autolink`
    applies to a Word file (DOCX-026)."""

    async def step(stage: str, progress: int) -> None:
        if report is not None:
            await report(stage, progress)

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension == "docx":
        await step("parsing", 15)
        return await asyncio.to_thread(partial(build_document_from_docx, autolink=autolink), file_bytes, filename, title)
    if extension == "pdf":
        await step("parsing", 15)
        text = await asyncio.to_thread(extract_pdf_text, file_bytes)
        await step("analyzing", 35)
        document = await build_document_from_text(text, title, provider, source_type="pdf", method="pdf-extracted-text")
        _note_pdf_limits(document, await asyncio.to_thread(pdf_image_count, file_bytes))
        return document
    if extension == "txt":
        await step("analyzing", 25)
        document = await build_document_from_text(decode_text_upload(file_bytes), title, provider, source_type="txt")
        document.metadata.sourceType = "uploaded_txt"
        document.metadata.originalFilename = filename
        return document
    raise UnsupportedFileTypeError(extension)
