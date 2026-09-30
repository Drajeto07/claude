"""The import report: what the importer itself noted, plus the content check
against the source -- the Word file's own text, the pasted or uploaded text."""

import zipfile
from collections import Counter

from lxml import etree

from app.fidelity.content import compare_words, document_words, words
from app.fidelity.docx_detect import detect_docx_features, section_findings
from app.fidelity.docx_source import read_docx_source
from app.fidelity.report import FidelityItem, FidelityPolicy, FidelityReport, FidelityStage, ReportBuilder
from app.models.document import Document


def _importer_items(document: Document, source_type: str) -> ReportBuilder:
    builder = ReportBuilder()
    if document.importReport is not None:
        builder.extend(document.importReport.items)
    else:
        # Producers that only write human-readable notes (structure analysis, Markdown).
        for note in document.unsupportedFeatures:
            builder.add(f"{source_type}.note", FidelityPolicy.LOSSY, note)
    return builder


_TEXT_KEYS = ("header", "footer", "firstHeader", "firstFooter", "evenHeader", "evenFooter")


def header_footer_texts(document: Document) -> list[str]:
    """Every header and footer text the document holds: the last section's main ones
    (DocumentSettings), and each section's own, first-page and even-page ones (DOCX-015)."""
    sections = [element.sectionBreak for element in document.elements if element.sectionBreak is not None]
    if document.lastSection is not None:
        sections.append(document.lastSection)
    texts = [document.settings.header, document.settings.footer]
    texts += [getattr(section, key) for section in sections for key in _TEXT_KEYS]
    return [text for text in texts if text]


def docx_import_report(document: Document, file_bytes: bytes, *, autolink: bool = False) -> FidelityReport:
    builder = _importer_items(document, "docx")
    try:
        source = read_docx_source(file_bytes)
    except (zipfile.BadZipFile, KeyError, ValueError, etree.LxmlError):
        # The file couldn't be read a second time: nothing is claimed about its content.
        return FidelityReport(stage=FidelityStage.IMPORT, sourceType="docx", items=builder.items())
    content = compare_words(words(source.body), document_words(document.elements), method="docx-text")
    # What the importer changes or leaves out without saying so while it reads.
    builder.extend(detect_docx_features(file_bytes, autolink=autolink))

    # Every section's headers and footers are kept (DOCX-015); page numbers are fields.
    kept = Counter(words(" ".join(header_footer_texts(document))))
    lost = [word for word in _multiset_missing(words(source.header_footer), kept) if not word.isdigit()]
    if lost:
        builder.add(
            "docx.header_footer.text",
            FidelityPolicy.UNSUPPORTED,
            "Some header or footer text was left out.",
            source=" ".join(lost[:40]),
            content_changed=True,
            count=len(lost),
        )
    return FidelityReport(stage=FidelityStage.IMPORT, sourceType="docx", items=builder.items(), content=content)


# What a Word export written into the original file keeps (DOCX-011), and how the
# report says it once that file is kept: shown nowhere in the app, but not lost.
KEPT_IN_WORD = {
    "docx.header_footer.picture": "Pictures in the header or footer aren't shown here; the Word export keeps them.",
    "docx.watermark": "The watermark isn't shown here; the Word export keeps it.",
    "docx.metadata.custom_properties": "The document's custom properties aren't shown here; the Word export keeps them.",
    "docx.metadata.sensitivity_label": "The document's sensitivity label is kept in the Word export (a PDF has none): check it before sharing.",
}
# The last section's own properties, which that export keeps.
KEPT_SECTION = {
    "docx.sections.page_borders": "Page borders aren't shown here; the Word export keeps the last section's.",
    "docx.sections.line_numbers": "Line numbering isn't shown here; the Word export keeps the last section's.",
    "docx.sections.vertical_alignment": "Vertical alignment on the page isn't shown here; the Word export keeps the last section's.",
}
# Earlier sections' properties, headers and footers: the paragraph that ends a
# section holds them, and the Word export copies it as it is while it is
# unchanged (DOCX-028); changed, the export says the section was lost.
_WHILE_UNCHANGED = "while the paragraph that ends each section isn't changed or restyled here"
EARLIER_SECTIONS = {
    "docx.sections.page_borders": f"Page borders aren't shown here; the Word export keeps them {_WHILE_UNCHANGED}.",
    "docx.sections.line_numbers": f"Line numbering isn't shown here; the Word export keeps it {_WHILE_UNCHANGED}.",
    "docx.sections.vertical_alignment": f"Vertical alignment on the page isn't shown here; the Word export keeps it {_WHILE_UNCHANGED}.",
}
_EARLIER_HEADERS = f"Some header or footer text isn't shown here; the Word export keeps it {_WHILE_UNCHANGED}."
# What lives inside the body's blocks and a Word export copies with a block the
# document didn't change (DOCX-028): kept while unchanged; a block written anew
# loses it, and that export says so (export.docx.rewritten_blocks, FID-007).
KEPT_WHILE_UNCHANGED = frozenset(
    {
        "docx.content_control",
        "docx.text_box",
        "docx.drop_cap",
        "docx.empty_paragraph",
        "docx.underline_variant",
        "docx.character_scale",
        "docx.text_effects",
        "docx.rtl",
    }
)
_KEPT_WHILE_UNCHANGED = " A Word export keeps the original while the paragraph that holds it isn't changed or restyled here."
# Drawings a Word export puts back from the original even into a paragraph written anew
# (DOCX-019): shown nowhere in the app, but not lost.
KEPT_DRAWINGS = {
    "docx.chart": "Charts aren't shown here or in a PDF; a Word export keeps them.",
    "docx.smartart": "SmartArt graphics aren't shown here or in a PDF; a Word export keeps them.",
    "docx.shape": "Shapes (lines, arrows, drawn figures) aren't shown here or in a PDF; a Word export keeps them.",
    "docx.embedded_object": "Embedded objects aren't shown here or in a PDF; a Word export keeps them.",
}
# Tracked changes once the original file is kept (DOCX-022): shown as if accepted, and
# kept by a Word export in the blocks not changed here -- or all accepted, as chosen.
TRACKED_KEPT = (
    "Tracked changes are shown here as if accepted. A Word export keeps them in the blocks you don't change or "
    "restyle here; you can accept them all instead."
)
TRACKED_ACCEPTED = "Tracked changes were accepted, as you chose: insertions kept, deletions removed. No export has them."
# What only a Word export keeps: a PDF export says so.
WORD_ONLY = frozenset(
    {*KEPT_IN_WORD, *KEPT_SECTION, *EARLIER_SECTIONS, *KEPT_WHILE_UNCHANGED, *KEPT_DRAWINGS, "docx.header_footer.text", "docx.tracked_changes"}
)


def _tracked(item: FidelityItem, choice: str) -> FidelityItem:
    if choice == "kept":
        return item.model_copy(update={"policy": FidelityPolicy.DETECTED_NOT_EDITABLE, "reason": TRACKED_KEPT, "contentChanged": False})
    return item.model_copy(update={"policy": FidelityPolicy.LOSSY, "reason": TRACKED_ACCEPTED, "contentChanged": True})


def with_tracked_changes(report: FidelityReport, choice: str) -> FidelityReport:
    """The import report once the file's tracked changes are kept for Word or accepted (DOCX-022)."""
    return report.model_copy(update={"items": [_tracked(item, choice) if item.feature == "docx.tracked_changes" else item for item in report.items]})


def with_source_kept(report: FidelityReport, file_bytes: bytes, document: Document) -> FidelityReport:
    """The import report once the original Word file is kept for exports: what the
    Word export keeps is no longer left out -- the last section's headers and
    footers of every kind, the watermark, custom properties, the sensitivity
    label, and earlier sections with their own page setup, headers and footers
    while the paragraphs ending them are unchanged (DOCX-028)."""
    builder = ReportBuilder()
    try:
        earlier, every = section_findings(file_bytes, last_too=False), section_findings(file_bytes, last_too=True)
    except (zipfile.BadZipFile, KeyError, ValueError, etree.LxmlError):
        earlier = every = None
    for item in report.items:
        if item.feature == "docx.header_footer.text":
            continue  # counted again below, against what the Word export keeps
        if earlier is not None and item.feature.startswith("docx.sections."):
            total = every.get(item.feature, 0)
            reason = (EARLIER_SECTIONS if earlier.get(item.feature) else KEPT_SECTION).get(item.feature)
            if reason and total:
                builder.add(item.feature, FidelityPolicy.DETECTED_NOT_EDITABLE, reason, source=item.sourceState, count=total)
            else:
                builder.extend([item])
            continue
        if item.feature == "docx.tracked_changes" and document.trackedChanges is not None:
            builder.extend([_tracked(item, document.trackedChanges)])
            continue
        if item.feature in KEPT_WHILE_UNCHANGED:
            builder.add(
                item.feature,
                FidelityPolicy.DETECTED_NOT_EDITABLE,
                item.reason.rstrip() + _KEPT_WHILE_UNCHANGED,
                source=item.sourceState,
                content_changed=item.contentChanged,
                count=item.count,
            )
            continue
        reason = KEPT_IN_WORD.get(item.feature) or KEPT_DRAWINGS.get(item.feature)
        if reason is None:
            builder.extend([item])
        else:
            builder.add(item.feature, FidelityPolicy.DETECTED_NOT_EDITABLE, reason, source=item.sourceState, count=item.count)
    try:
        source = read_docx_source(file_bytes)
    except (zipfile.BadZipFile, KeyError, ValueError, etree.LxmlError):
        builder.extend([item for item in report.items if item.feature == "docx.header_footer.text"])
        return report.model_copy(update={"items": builder.items()})
    kept = Counter(words(" ".join([*header_footer_texts(document), source.last_section_header_footer or ""])))
    lost = [word for word in _multiset_missing(words(source.header_footer), kept) if not word.isdigit()]
    if lost:
        builder.add("docx.header_footer.text", FidelityPolicy.DETECTED_NOT_EDITABLE, _EARLIER_HEADERS, source=" ".join(lost[:40]), count=len(lost))
    return report.model_copy(update={"items": builder.items()})


def _multiset_missing(source: list[str], kept: Counter) -> list[str]:
    remaining = Counter(kept)
    missing = []
    for word in source:
        if remaining[word] > 0:
            remaining[word] -= 1
        else:
            missing.append(word)
    return missing


def text_import_report(document: Document, source_words: list[str], *, source_type: str, method: str) -> FidelityReport:
    """Pasted text, a .txt file or a PDF's extracted text against the document made of it."""
    builder = _importer_items(document, source_type)
    # A source without words gives nothing to compare: nothing is claimed.
    content = compare_words(source_words, document_words(document.elements), method=method) if source_words else None
    return FidelityReport(stage=FidelityStage.IMPORT, sourceType=source_type, items=builder.items(), content=content)
