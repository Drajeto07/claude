"""What the app says it changes or leaves out of a Word file (tracker TEST-021, audit
AUD-20): its import report and its Word and PDF exports' reports, as an upload and an
export job make them, reduced to what they claim -- each item's feature, policy,
count and whether it changes content, and each content check's status. A fixture's
committed manifest (<fixture>.expected-loss.json, scripts/export_expected_losses.py)
is compared with what happens now (tests/test_expected_losses.py), so a new loss, or
one that went away, fails until the manifest is rewritten on purpose.

A PDF's report depends on the fonts the machine has (export/fonts.py searches the
system's), so its claims are kept per platform and compared only where they were
recorded."""

import sys
from typing import Any

from app.export.docx_export import build_docx
from app.export.pdf_export import build_pdf
from app.export.provenance import stamp
from app.fidelity.exports import export_report
from app.fidelity.imports import with_source_kept
from app.fidelity.report import FidelityReport, ReportBuilder
from app.services.ingestion_service import build_document_from_docx


def claims(report: FidelityReport | None) -> dict[str, Any]:
    if report is None:
        return {"content": None, "items": []}
    items = sorted(
        (
            {"feature": item.feature, "policy": item.policy.value, "count": item.count, "contentChanged": item.contentChanged}
            for item in report.items
        ),
        key=lambda item: (item["feature"], item["policy"]),
    )
    return {"content": report.contentStatus, "items": items}


def loss_manifest(data: bytes, name: str) -> dict[str, Any]:
    """The claims about one Word file: imported as an upload imports it (the file kept,
    its blocks fingerprinted), exported to Word (into the original) and to PDF."""
    document = build_document_from_docx(data, name, None)
    if document.importReport is not None:
        document.importReport = with_source_kept(document.importReport, data, document)
    stamp(document)
    manifest: dict[str, Any] = {"import": claims(document.importReport)}
    for file_format, build, extra in (("docx", build_docx, {"source": data}), ("pdf", build_pdf, {})):
        noted = ReportBuilder()
        content = build(document, report=noted, **extra)
        found = claims(export_report(document, content, file_format, noted.items()))
        manifest[file_format] = found if file_format == "docx" else {sys.platform: found}
    return manifest
