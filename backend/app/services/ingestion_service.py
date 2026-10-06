import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from functools import partial

from app.ai.base import AIProvider
from app.ai.structure_analysis import analyze_structure
from app.fidelity.content import words
from app.fidelity.imports import docx_import_report, text_import_report
from app.fidelity.pdf_conversion import conversion_items, conversion_summary
from app.fidelity.pdf_inspection import inspect_pdf, page_kind_items
from app.fidelity.report import FidelityItem, FidelityPolicy
from app.fidelity.text_sources import markdown_words, pdf_image_count
from app.models.base import NOT_XML, xml_text
from app.models.document import Document
from app.models.pdf_inspection import PdfInspection
from app.parsers.detection import looks_like_markdown
from app.parsers.docx import parse_docx, unreadable
from app.parsers.docx_inline import UNSAFE_LINKS_NOTE
from app.parsers.markdown import parse_markdown
from app.parsers.pdf import PdfText, extract_pdf_text, read_pdf
from app.parsers.pdf_geometry import PdfPage
from app.parsers.pdf_pictures import decode_pictures
from app.parsers.pdf_structure import PageLines, PdfStructure, build_pdf_document, page_lines, picture_plan
from app.parsers.trace import where
from app.security.package import Cleaned

_TEXT_DECODE_CHAIN = ("utf-8", "utf-8-sig", "cp1251", "latin-1")

logger = logging.getLogger(__name__)

# The layout read may miss this share of the text read's words (ligatures, words the
# two read apart differently) before the structure it rebuilt isn't used (P2E-002).
PDF_LAYOUT_SHORTFALL = 0.05
# The text read's words the layout read didn't find, quoted in the report at most.
_MISSED_SHOWN = 8

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


def _note_pdf_limits(document: Document, images: int | None, *, damaged: bool = False, rebuilt: bool = False, confidence: float = 1.0) -> None:
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
            reason=(
                "The PDF's structure was rebuilt from where its text sits -- headings, paragraphs, lists, columns, each "
                "block with how sure the rebuild is. Its tables came in as a paragraph a row, and the pages aren't laid "
                "out as they were."
                if rebuilt
                else "Only the PDF's text was imported: its layout, columns and tables aren't kept."
            ),
            confidence=confidence if rebuilt else 1.0,
        )
    )
    if rebuilt:
        return  # the reconstruction says which pictures went in and which didn't (P2E-003)
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


def _read_pdf_layout(file_bytes: bytes) -> tuple[PdfInspection, list[PageLines] | None]:
    """The PDF inspection and, from the same read, each page's lines in reading order --
    None when they can't all be had (a page the read couldn't take, a read stopped short,
    a failure making them)."""
    lines: list[PageLines] = []
    failed = False

    def keep(page: PdfPage, kind: str) -> None:
        nonlocal failed
        if failed:
            return
        try:
            lines.append(page_lines(page, kind))
        except Exception as exc:  # noqa: BLE001 -- the text read still makes the document
            failed = True
            logger.warning("A PDF page's lines couldn't be made: %s at %s", type(exc).__name__, where(exc))

    inspection = inspect_pdf(file_bytes, on_page=keep)
    whole = inspection.pageCount > 0 and inspection.stopped is None and not inspection.notRead
    return inspection, (lines if whole and not failed else None)


NOT_REBUILT_PARTLY = "Not all of this PDF's pages could be read for where their text sits, so only its text was imported."
NOT_REBUILT_SHORT = "Reading where this PDF's text sits found less of it than reading the text itself, so only its text was imported."
NOT_REBUILT_FAILED = "This PDF's structure couldn't be rebuilt, so only its text was imported."


def _rebuilt(
    file_bytes: bytes, read: PdfText, inspection: PdfInspection, lines: list[PageLines] | None, title: str | None
) -> tuple[PdfStructure | None, str | None]:
    """The document rebuilt from the PDF's layout, its pictures in place (P2E-003), or None
    and why the text alone is used: the layout read must have had every page and found
    (nearly) all the text read's words."""
    if lines is None:
        return None, NOT_REBUILT_PARTLY if inspection.pageCount > 0 else None
    try:
        wanted, _ = picture_plan(lines)
        structure = build_pdf_document(lines, title, decode_pictures(file_bytes, wanted) if wanted else {})
    except Exception as exc:  # noqa: BLE001 -- the text read still makes the document
        logger.warning("A PDF's structure couldn't be rebuilt: %s at %s", type(exc).__name__, where(exc))
        return None, NOT_REBUILT_FAILED
    text_words = words(read.text)
    missed = Counter(text_words) - structure.line_words
    if not structure.document.elements or sum(missed.values()) > max(3, PDF_LAYOUT_SHORTFALL * len(text_words)):
        return None, NOT_REBUILT_SHORT
    return structure, None


def _note_missed_words(document: Document, read: PdfText, structure: PdfStructure) -> None:
    """Words the text read found that the layout read didn't (within PDF_LAYOUT_SHORTFALL):
    said, never dropped silently."""
    missed = Counter(words(read.text)) - structure.line_words
    count = sum(missed.values())
    if not count or document.importReport is None:
        return
    shown = ", ".join(f"“{word}”" for word in list(missed)[:_MISSED_SHOWN])
    plural = count != 1
    document.importReport.items.append(
        FidelityItem(
            feature="pdf.text_reads_differ",
            policy=FidelityPolicy.LOSSY,
            reason=f"{count} word{'s' if plural else ''} in the PDF's text {'were' if plural else 'was'} not found where its text "
            f"sits, so {'they are' if plural else 'it is'} missing here: {shown}.",
            count=count,
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
        read = await asyncio.to_thread(read_pdf, file_bytes)
        # Only once the text read has accepted the file, so what it refuses stays refused
        # as before; the inspection never refuses an import itself (PDF-012). The same
        # read of the pages gives the structure reconstruction its lines (P2E-002).
        inspection, lines = await asyncio.to_thread(_read_pdf_layout, file_bytes)
        await step("analyzing", 35)
        structure, why_not = await asyncio.to_thread(_rebuilt, file_bytes, read, inspection, lines, title)
        if structure is not None:
            document = structure.document
            document.importReport = text_import_report(document, structure.source_words, source_type="pdf", method="pdf-layout")
            document.importReport.items.extend(structure.items)
            _note_missed_words(document, read, structure)
        else:
            # The text alone, as before the reconstruction: it takes the same Markdown sniff
            # as pasted text, so a PDF of a Markdown document gets the deterministic path.
            document = await build_document_from_text(read.text, title, provider, source_type="pdf", method="pdf-extracted-text")
            if why_not is not None and document.importReport is not None:
                document.importReport.items.append(FidelityItem(feature="pdf.structure_not_rebuilt", policy=FidelityPolicy.LOSSY, reason=why_not))
        document.metadata.sourceType = "uploaded_pdf"
        document.metadata.originalFilename = filename
        document.pdfInspection = inspection
        rebuilt = structure is not None
        if document.importReport is not None:
            document.importReport.items.extend(conversion_items(inspection, rebuilt=rebuilt))
        document.pdfConversion = conversion_summary(document, structure, inspection)  # how sure it is (P2E-005)
        _note_pdf_limits(
            document, await asyncio.to_thread(pdf_image_count, file_bytes), damaged=read.damaged, rebuilt=rebuilt, confidence=document.pdfConversion.confidence
        )
        if document.importReport is not None:
            document.importReport.items.extend(page_kind_items(inspection))
        return document
    if extension == "txt":
        await step("analyzing", 25)
        document = await build_document_from_text(decode_text_upload(file_bytes), title, provider, source_type="txt")
        document.metadata.sourceType = "uploaded_txt"
        document.metadata.originalFilename = filename
        return document
    raise UnsupportedFileTypeError(extension)
