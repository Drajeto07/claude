"""The import report: what the importer itself noted, plus the content check
against the source -- the Word file's own text, the pasted or uploaded text."""

import zipfile
from collections import Counter

from lxml import etree

from app.fidelity.content import compare_words, document_words, words
from app.fidelity.docx_detect import detect_docx_features
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
