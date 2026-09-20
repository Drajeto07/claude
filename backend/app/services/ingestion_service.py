from app.ai.base import AIProvider
from app.ai.structure_analysis import analyze_structure
from app.models.document import Document
from app.parsers.detection import looks_like_markdown
from app.parsers.docx import parse_docx
from app.parsers.markdown import parse_markdown
from app.parsers.pdf import extract_pdf_text

_TEXT_DECODE_CHAIN = ("utf-8", "utf-8-sig", "cp1251", "latin-1")


async def build_document_from_text(text: str, title: str | None, provider: AIProvider) -> Document:
    """Route by source characteristics: Markdown-looking text gets free,
    deterministic, perfectly-reliable parsing; only genuinely unstructured
    prose reaches the AI. See docs/spec.md's Phase 2/3 design notes."""
    if looks_like_markdown(text):
        return parse_markdown(text, title=title)
    return await analyze_structure(provider, text, title=title)


def build_document_from_docx(file_bytes: bytes, filename: str, title: str | None) -> Document:
    """DOCX carries real, deterministic structure (Word paragraph styles,
    list/table XML) -- extracting it directly is strictly more accurate than
    re-inferring via AI from a flattened text dump. No AI call on this path."""
    return parse_docx(file_bytes, filename, title=title)


async def build_document_from_pdf(file_bytes: bytes, title: str | None, provider: AIProvider) -> Document:
    """PDF text extraction has no reliable embedded structure of its own, so
    the extracted text is routed through the same Markdown-sniff gate as
    pasted text -- a PDF rendering of a Markdown document still gets the
    free, deterministic path."""
    text = extract_pdf_text(file_bytes)
    return await build_document_from_text(text, title, provider)


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
