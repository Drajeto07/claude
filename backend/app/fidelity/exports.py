"""The export report (brief §17): what an export approximated or left out, and
whether the exported file holds every word of the document -- checked by
reading the file back (a Word file with the same independent reader the import
check uses; a PDF by its extracted text, which may add list numbers, running
headers and page numbers of its own)."""

import io
import re
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from lxml import etree
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.fidelity.content import compare_words, document_words, hidden_words, words
from app.fidelity.docx_source import read_docx_source
from app.fidelity.imports import WORD_ONLY
from app.fidelity.report import FidelityItem, FidelityPolicy, FidelityReport, FidelityStage, ReportBuilder
from app.models.document import Document, MarkType, inline_runs, walk_elements

# The collector of the export being built, if its caller asked for a report.
_CURRENT: ContextVar[ReportBuilder | None] = ContextVar("export_report", default=None)


@contextmanager
def collecting(report: ReportBuilder | None) -> Iterator[None]:
    token = _CURRENT.set(report)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def note(
    feature: str, policy: FidelityPolicy, reason: str, *, element_id: str | None = None, content_changed: bool = False, count: int = 1
) -> None:
    """For the exporters: record what this export approximates or leaves out."""
    report = _CURRENT.get()
    if report is not None:
        report.add(feature, policy, reason, element_id=element_id, content_changed=content_changed, count=count)


# Scripts the PDF renderer can't lay out yet (no shaping, no bidi, no fonts for them).
_UNSHAPED_SCRIPTS = (
    ("Arabic", re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")),
    ("Hebrew", re.compile(r"[֐-׿יִ-ﭏ]")),
    ("Devanagari", re.compile(r"[ऀ-ॿ]")),
    ("Thai", re.compile(r"[฀-๿]")),
    ("Chinese, Japanese or Korean", re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")),
    ("emoji", re.compile(r"[\U0001f300-\U0001faff☀-➿]")),
)
_KEPT_IN_PDF = {
    "equation": (FidelityPolicy.LOSSY, "Equations are shown as linear text in the PDF."),
    "field": (FidelityPolicy.LOSSY, "Fields show the text they last had in the PDF."),
    "link": (FidelityPolicy.LOSSY, "Links to places inside the document aren't clickable in the PDF."),
    "comment": (FidelityPolicy.UNSUPPORTED, "Comments aren't included in a PDF."),
}


def pdf_document_notes(document: Document) -> None:
    """What any PDF of this document can't carry, known before it is drawn."""
    text = "\n".join(element.content for element in walk_elements(document.elements))
    unshaped = [name for name, pattern in _UNSHAPED_SCRIPTS if pattern.search(text)]
    if unshaped:
        note(
            "export.pdf.script",
            FidelityPolicy.LOSSY,
            f"Text in {', '.join(unshaped)} isn't laid out correctly in PDF exports yet; export to Word keeps it.",
            content_changed=True,
        )
    kinds = {
        fragment.get("kind")
        for element in walk_elements(document.elements)
        for fragment in ((element.preservedAttributes or {}).get("ooxml") or [])
        if isinstance(fragment, dict)
    }
    for kind, (policy, reason) in _KEPT_IN_PDF.items():
        if kind in kinds:
            note(f"export.pdf.{kind}", policy, reason)
    if hidden := hidden_words(document.elements):
        note(
            "export.pdf.hidden_text",
            FidelityPolicy.DETECTED_PRESERVED,
            f"Hidden text ({hidden} {'word' if hidden == 1 else 'words'}) isn't printed in the PDF, as Word leaves it out of "
            "printing; a Word export keeps it hidden.",
        )
    looks = [document.resolvedStyles.get(element.styleRef or "", {}) for element in walk_elements(document.elements)]
    if any(css.get("--tab-stops") for css in looks):
        note(
            "export.pdf.tab_stops",
            FidelityPolicy.LOSSY,
            "Tab stops aren't in the PDF: each tab is a gap of four spaces; a Word export keeps them.",
        )
    if any(_side_border_only(css) for css in looks):
        note(
            "export.pdf.paragraph_borders",
            FidelityPolicy.LOSSY,
            "A border on the left or right of a paragraph alone isn't drawn in the PDF (a box and lines above or below "
            "are); a Word export keeps it.",
        )
    runs = [run for element in document.elements for run in inline_runs(element)]
    styles = [mark for run in runs for mark in run.marks if mark.type == MarkType.TEXT_STYLE]
    if any(mark.letterSpacingPt for mark in styles):
        note(
            "export.pdf.character_spacing",
            FidelityPolicy.LOSSY,
            "Character spacing isn't in the PDF: that text is set with its font's own spacing; a Word export keeps it.",
        )
    if any(mark.type == MarkType.UNDERLINE and mark.lineStyle in ("dotted", "dashed", "wavy") for run in runs for mark in run.marks):
        note(
            "export.pdf.underline_style",
            FidelityPolicy.LOSSY,
            "Dotted, dashed and wavy underlines are drawn as plain lines in the PDF; a Word export keeps them.",
        )
    if any(element.image and element.image.alt for element in walk_elements(document.elements)):
        note("export.pdf.alt_text", FidelityPolicy.LOSSY, "Pictures' alt text isn't carried into the PDF (it isn't a tagged PDF yet).")
    if document.sourcePackage is not None and document.importReport is not None:
        word_only = [
            item
            for item in document.importReport.items
            if item.policy == FidelityPolicy.DETECTED_NOT_EDITABLE and item.feature in WORD_ONLY
        ]
        if word_only:
            note(
                "export.pdf.word_only",
                FidelityPolicy.LOSSY,
                "What the original Word file has that isn't shown here -- pictures in headers and footers, a watermark, "
                "content controls, page borders, custom properties, tracked changes -- is kept in a Word export only, not "
                "in a PDF.",
            )


def _side_border_only(css: dict[str, str]) -> bool:
    sides = {side: css.get(f"border-{side}") not in (None, "none") for side in ("top", "bottom", "left", "right")}
    return (sides["left"] or sides["right"]) and not all(sides.values())


def _pdf_text(content: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


def export_report(document: Document, content: bytes, file_format: str, items: list[FidelityItem]) -> FidelityReport:
    expected = document_words(document.elements)
    check = None
    try:
        if file_format == "docx":
            check = compare_words(expected, words(read_docx_source(content).body), method="docx-export")
        elif file_format == "pdf":  # hidden text isn't printed (DOCX-025)
            visible = document_words(document.elements, visible_only=True)
            check = compare_words(visible, words(_pdf_text(content)), method="pdf-export", allow_additions=True)
    except (zipfile.BadZipFile, KeyError, ValueError, etree.LxmlError, PdfReadError):
        check = None  # the file couldn't be read back: nothing is claimed
    return FidelityReport(stage=FidelityStage.EXPORT, sourceType=file_format, items=items, content=check)
