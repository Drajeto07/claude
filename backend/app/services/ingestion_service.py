import asyncio
from collections.abc import Awaitable, Callable
from functools import partial

from app.ai.base import AIProvider
from app.ai.structure_analysis import analyze_structure
from app.fidelity.content import words
from app.fidelity.imports import docx_import_report, text_import_report
from app.fidelity.report import FidelityItem, FidelityPolicy
from app.fidelity.text_sources import markdown_words, pdf_image_count
from app.models.base import NOT_XML, xml_text
from app.models.document import Document
from app.parsers.detection import looks_like_markdown
from app.parsers.docx import parse_docx, unreadable
from app.parsers.docx_inline import UNSAFE_LINKS_NOTE
from app.parsers.markdown import parse_markdown
from app.parsers.pdf import extract_pdf_text, read_pdf
from app.security.package import Cleaned

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
    report): an AI that dropped or changed a sentence shows up there. Control
    codes no document can hold are left out first, and said to be (SEC-023)."""
    control = len(NOT_XML.findall(text))
    text = xml_text(text)
    markdown = looks_like_markdown(text)
    document = parse_markdown(text, title=title) if markdown else await analyze_structure(provider, text, title=title)
    document.importReport = text_import_report(
        document,
        markdown_words(text) if markdown else words(text),
        source_type=source_type,
        method=method or ("markdown-text" if markdown else "source-text"),
    )
    if control:
        document.importReport.items.append(
            FidelityItem(
                feature="text.control_characters",
                policy=FidelityPolicy.UNSUPPORTED,
                reason=f"The text held {control} control code{'s' if control != 1 else ''}, which no document can hold: left out.",
                count=control,
            )
        )
    return document


def build_document_from_docx(file_bytes: bytes, filename: str, title: str | None, *, autolink: bool = False) -> Document:
    """DOCX carries real, deterministic structure (Word paragraph styles,
    list/table XML) -- extracting it directly is strictly more accurate than
    re-inferring via AI from a flattened text dump. No AI call on this path.
    The import report checks the result's words against the file's own text.
    `autolink`: turn web and e-mail addresses written as plain text into links (DOCX-026)."""
    document = parse_docx(file_bytes, filename, title=title, autolink=autolink)
    try:
        document.importReport = docx_import_report(document, file_bytes, autolink=autolink)
    except Exception as exc:  # noqa: BLE001 -- the file read, but a part of it can't be checked: damaged all the same (SEC-010)
        raise unreadable(exc) from exc
    return document


UNSAFE_FIELDS = (
    "Fields that could run a program or pull in outside content (DDE, INCLUDETEXT, INCLUDEPICTURE and the like) "
    "were kept as their last result, not as fields."
)


UNSAFE_LINKS = UNSAFE_LINKS_NOTE  # the importer's own words for them
UNSAFE_EXTERNAL = (
    "What the Word file would fetch from outside itself when opened -- a template, a linked picture or object, a "
    "mail-merge data source -- was taken out."
)


def note_cleaned(document: Document, cleaned: Cleaned) -> None:
    """What was made safe in the Word file before it was read and kept (SEC-015, SEC-016).
    Links keep the words the importer uses for them (docx.link.unsafe)."""
    for count, feature, reason in (
        (cleaned.fields, "docx.field.unsafe", UNSAFE_FIELDS),
        (cleaned.links, "docx.link.unsafe", UNSAFE_LINKS),
        (cleaned.external, "docx.external.unsafe", UNSAFE_EXTERNAL),
    ):
        if not count:
            continue
        if reason not in document.unsupportedFeatures:
            document.unsupportedFeatures.append(reason)
        if document.importReport is None:
            continue
        same = next((item for item in document.importReport.items if (item.feature, item.reason) == (feature, reason)), None)
        if same is not None:  # the importer noted some itself
            same.count += count
        else:
            document.importReport.items.append(FidelityItem(feature=feature, policy=FidelityPolicy.LOSSY, reason=reason, count=count))


def _note_pdf_limits(document: Document, images: int | None, *, damaged: bool = False) -> None:
    """What the PDF import doesn't keep, said in the report (its text is checked
    against what could be read -- which, from a damaged file, may not be all of it)."""
    if document.importReport is None:
        return
    if damaged:
        document.importReport.items.append(
            FidelityItem(
                feature="pdf.damaged",
                policy=FidelityPolicy.LOSSY,
                reason="Part of this PDF is damaged, so some of its text may be missing: check the document against the original.",
                contentChanged=True,
            )
        )
    document.importReport.items.append(
        FidelityItem(
            feature="pdf.layout",
            policy=FidelityPolicy.LOSSY,
            reason="Only the PDF's text was imported: its layout, columns and tables aren't kept.",
        )
    )
    if images is None:  # they couldn't be counted: not claimed to be none
        document.importReport.items.append(
            FidelityItem(
                feature="pdf.images",
                policy=FidelityPolicy.UNSUPPORTED,
                reason="Any pictures in the PDF weren't imported (they couldn't be counted).",
                contentChanged=True,
            )
        )
    elif images:
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
        # PDF text has no reliable structure of its own, so it takes the same Markdown
        # sniff as pasted text: a PDF of a Markdown document gets the deterministic path.
        await step("parsing", 15)
        read = await asyncio.to_thread(read_pdf, file_bytes)
        await step("analyzing", 35)
        document = await build_document_from_text(read.text, title, provider, source_type="pdf", method="pdf-extracted-text")
        _note_pdf_limits(document, await asyncio.to_thread(pdf_image_count, file_bytes), damaged=read.damaged)
        return document
    if extension == "txt":
        await step("analyzing", 25)
        document = await build_document_from_text(decode_text_upload(file_bytes), title, provider, source_type="txt")
        document.metadata.sourceType = "uploaded_txt"
        document.metadata.originalFilename = filename
        return document
    raise UnsupportedFileTypeError(extension)
