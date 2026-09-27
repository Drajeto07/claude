"""The import report: what the importer itself noted, plus the content check
against the source -- the Word file's own text, the pasted or uploaded text."""

import zipfile
from collections import Counter

from lxml import etree

from app.fidelity.content import compare_words, document_words, words
from app.fidelity.docx_detect import detect_docx_features, section_findings
from app.fidelity.docx_source import read_docx_source
from app.fidelity.report import FidelityPolicy, FidelityReport, FidelityStage, ReportBuilder
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


def docx_import_report(document: Document, file_bytes: bytes) -> FidelityReport:
    builder = _importer_items(document, "docx")
    try:
        source = read_docx_source(file_bytes)
    except (zipfile.BadZipFile, KeyError, ValueError, etree.LxmlError):
        # The file couldn't be read a second time: nothing is claimed about its content.
        return FidelityReport(stage=FidelityStage.IMPORT, sourceType="docx", items=builder.items())
    content = compare_words(words(source.body), document_words(document.elements), method="docx-text")
    # What the importer changes or leaves out without saying so while it reads.
    builder.extend(detect_docx_features(file_bytes))

    # One header and one footer are kept (settings.header/footer); page numbers are fields.
    kept = Counter(words(" ".join(filter(None, [document.settings.header, document.settings.footer]))))
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
    "docx.header_footer.variants": "First-page and even-page headers and footers aren't shown here; the Word export keeps them.",
    "docx.header_footer.picture": "Pictures in the header or footer aren't shown here; the Word export keeps them.",
    "docx.watermark": "The watermark isn't shown here; the Word export keeps it.",
    "docx.metadata.custom_properties": "The document's custom properties aren't shown here; the Word export keeps them.",
    "docx.metadata.sensitivity_label": "The document's sensitivity label is kept in the Word export (a PDF has none): check it before sharing.",
}
_COLUMNS = "The document is laid out in "
# The last section's own properties, which that export keeps.
KEPT_SECTION = {
    "docx.sections.page_numbering": "The last section's page numbering (its start or style) isn't shown here; the Word export keeps it.",
    "docx.sections.page_borders": "Page borders aren't shown here; the Word export keeps the last section's.",
    "docx.sections.line_numbers": "Line numbering isn't shown here; the Word export keeps the last section's.",
    "docx.sections.vertical_alignment": "Vertical alignment on the page isn't shown here; the Word export keeps the last section's.",
}


def with_source_kept(report: FidelityReport, file_bytes: bytes, document: Document) -> FidelityReport:
    """The import report once the original Word file is kept for exports: what the
    Word export keeps is no longer left out -- the last section's headers and
    footers of every kind, the watermark, custom properties, the sensitivity
    label, its columns. Headers and footers of earlier sections still are."""
    builder = ReportBuilder()
    try:
        earlier, every = section_findings(file_bytes, last_too=False), section_findings(file_bytes, last_too=True)
    except (zipfile.BadZipFile, KeyError, ValueError, etree.LxmlError):
        earlier = every = None
    for item in report.items:
        if item.feature == "docx.header_footer.text":
            continue  # counted again below, against what the Word export keeps
        if earlier is not None and item.feature.startswith("docx.sections."):
            if earlier.get(item.feature):
                builder.add(item.feature, item.policy, item.reason, source=item.sourceState, count=earlier[item.feature])
            kept = every.get(item.feature, 0) - earlier.get(item.feature, 0)
            if kept and item.feature in KEPT_SECTION:
                builder.add(item.feature, FidelityPolicy.DETECTED_NOT_EDITABLE, KEPT_SECTION[item.feature], count=kept)
            continue
        reason = KEPT_IN_WORD.get(item.feature)
        if reason is None and item.feature == "docx.layout" and item.reason.startswith(_COLUMNS):
            reason = item.reason.rstrip(".") + "; the Word export keeps the columns."
        if reason is None:
            builder.extend([item])
        else:
            builder.add(item.feature, FidelityPolicy.DETECTED_NOT_EDITABLE, reason, source=item.sourceState, count=item.count)
    try:
        source = read_docx_source(file_bytes)
    except (zipfile.BadZipFile, KeyError, ValueError, etree.LxmlError):
        builder.extend([item for item in report.items if item.feature == "docx.header_footer.text"])
        return report.model_copy(update={"items": builder.items()})
    kept = Counter(words(" ".join(filter(None, [document.settings.header, document.settings.footer, source.last_section_header_footer]))))
    lost = [word for word in _multiset_missing(words(source.header_footer), kept) if not word.isdigit()]
    if lost:
        builder.add(
            "docx.header_footer.text",
            FidelityPolicy.UNSUPPORTED,
            "Headers and footers of earlier sections were left out; the last section's are kept in the Word export.",
            source=" ".join(lost[:40]),
            content_changed=True,
            count=len(lost),
        )
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
