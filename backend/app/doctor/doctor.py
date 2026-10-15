"""Document Doctor v0 (prototype, behind a feature flag; docs/SMARTDOC_DOCUMENT_DOCTOR_SAFEEDIT_ANALYSIS.md
section 11): find layout and structure problems in a Word file, propose only repairs that cannot change its
words, and check every repaired file against the untouched original (safe_edit.py) before handing it out.

Upload DOCX -> analyse -> proposed repairs -> review and accept (the editor's Review panel) -> repaired file
-> independent check -> download. The original Word file is never written to: it is the stored source package,
checked by its checksum, and every result is a new file.

Deterministic throughout: the findings are Document Health's checks, the repairs its fixes; no AI.

What Doctor v0 refuses outright (the whole document): a document with no Word file behind it; a Word file it
can't read back as it was kept; an import whose own word check didn't pass; tracked changes still waiting for
a decision; a signed file (any change breaks the signature); a file with macros; a package already broken.
What it refuses per block: a repair of a block that holds something the app only keeps (a bookmark, a field, a
content control, a drawing, a note reference...), since rewriting the block could lose it.
"""

import io
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field

from lxml import etree

from app.doctor.safe_edit import PRESERVED, SafeEditResult, verify
from app.doctor.word_repairs import BlockRepair, find_all
from app.doctor.word_repairs import apply as apply_word_repairs
from app.export.package_check import package_problems
from app.export.provenance import unchanged
from app.formatting import health
from app.formatting.health_fixes import fixes as health_fixes
from app.models.document import Document, ProposedChange

# The repairs Doctor v0 may propose: each changes how things look or removes an empty block, never a word.
SAFE_REPAIRS: tuple[str, ...] = ("empty_paragraphs", "page_breaks", "duplicated_formatting", "layout", "fonts")

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_SIGNATURE_PARTS = ("_xmlsignatures/",)
_MACROS = ("word/vbaProject.bin", "word/vbaData.xml")


@dataclass
class Refusal:
    code: str
    message: str


@dataclass
class Finding:
    checkId: str
    title: str
    status: str
    summary: str
    issues: list[dict]
    repair: str  # "safe" (Doctor v0 can propose a repair) or "review" (a person decides)


@dataclass
class BlockRefusal:
    elementId: str
    checkId: str
    reason: str


@dataclass
class Analysis:
    refusals: list[Refusal] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    repairable: int = 0
    blockRefusals: list[BlockRefusal] = field(default_factory=list)
    wordRepairs: list[BlockRepair] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return not self.refusals


def document_refusals(document: Document, source: bytes | None, source_problem: str | None = None) -> list[Refusal]:
    """Why Doctor v0 won't repair this document automatically -- empty when it may."""
    found: list[Refusal] = []
    if document.sourcePackage is None:
        return [Refusal("no_word_file", "This document wasn't made from a Word file, so there is no original to repair and compare with.")]
    if source is None:
        return [Refusal("source_unreadable", source_problem or "The original Word file isn't stored any more.")]
    report = document.importReport
    if report is None or report.contentStatus != "verified":
        found.append(Refusal("import_not_verified", "The import's own word check didn't confirm every word of the Word file, so a repair couldn't be checked against it."))
    if document.trackedChanges == "kept":
        found.append(Refusal("tracked_changes", "The file has tracked changes waiting for a decision: accept or reject them first (Check panel)."))
    try:
        with zipfile.ZipFile(io.BytesIO(source)) as package:
            names = package.namelist()
    except zipfile.BadZipFile:
        return [*found, Refusal("unreadable", "The Word file can't be opened as a Word package.")]
    if any(name.startswith(_SIGNATURE_PARTS) for name in names):
        found.append(Refusal("signed", "The file is digitally signed: any change would break the signature."))
    if any(name in _MACROS for name in names):
        found.append(Refusal("macros", "The file contains macros, which Doctor doesn't handle."))
    if package_problems(source):
        found.append(Refusal("broken_package", "The Word file's package is already damaged; Doctor v0 doesn't repair packages."))
    return found


def _body_children(source: bytes) -> list[etree._Element]:
    with zipfile.ZipFile(io.BytesIO(source)) as package:
        root = etree.fromstring(package.read("word/document.xml"))
    body = root.find(f"{{{_W}}}body")
    return list(body) if body is not None else []


def _holds_preserved(block: etree._Element) -> str | None:
    for name, tag in PRESERVED.items():
        if name == "section breaks" and etree.QName(block).localname == "sectPr":
            continue
        if block.find(f".//{tag}") is not None or block.tag == tag:
            return name
    return None


def safe_proposals(document: Document, source: bytes, covered: set[int] | None = None) -> tuple[list[ProposedChange], list[BlockRefusal]]:
    """The safe repairs' proposals, without those whose block holds something the app only keeps, and without those
    whose block a repair made in the file itself already covers (`covered`): that one is the smaller edit -- the
    editor's would write the whole block, and the export may rewrite its neighbours with it."""
    children = _body_children(source)
    elements = {element.id: element for element in document.elements}
    kept: list[ProposedChange] = []
    refused: list[BlockRefusal] = []
    for proposal in health_fixes(document, list(SAFE_REPAIRS)):
        element = elements.get(proposal.elementId or "")
        if element is None or not element.sourceBlocks:
            refused.append(BlockRefusal(proposal.elementId or "", proposal.checkId or "", "The block isn't one of the Word file's own, so a repair couldn't be checked."))
            continue
        if covered and covered & set(element.sourceBlocks):
            continue
        holding = next((what for index in element.sourceBlocks if 0 <= index < len(children) and (what := _holds_preserved(children[index]))), None)
        if holding:
            refused.append(BlockRefusal(element.id, proposal.checkId or "", f"The block holds {holding}, which a repair could lose: left for you to decide."))
            continue
        kept.append(proposal)
    return kept, refused


def write_back_baseline(source: bytes, name: str = "document.docx") -> SafeEditResult:
    """The Word file imported as it is and written straight back, with no repair: what the export itself would change.
    A file that doesn't come back verified here (a link the app won't write, a structure it can't keep) can't be
    repaired with a promise that nothing else changed."""
    from app.export.docx_export import build_docx
    from app.export.provenance import stamp
    from app.formatting.engine import recompute_styles
    from app.services.ingestion_service import build_document_from_docx

    document = build_document_from_docx(source, name, None)
    recompute_styles(document)
    stamp(document)
    return verify(source, build_docx(document, source=source), set())


def analyse(document: Document, source: bytes | None, source_problem: str | None = None, name: str = "document.docx") -> Analysis:
    analysis = Analysis(refusals=document_refusals(document, source, source_problem))
    if analysis.available and source is not None:
        baseline = write_back_baseline(source, name)
        if not baseline.verified:
            details = " ".join(check.detail for check in baseline.failed())
            analysis.refusals.append(Refusal("write_back_changes", f"Even with no repair, writing this Word file back would change it: {details} Doctor v0 won't repair it."))
    report = health.check_health(document)
    analysis.wordRepairs = find_all(source) if analysis.available and source is not None else []
    covered = {index for repair in analysis.wordRepairs for index in repair.blocks}
    proposals, refused = (safe_proposals(document, source, covered) if analysis.available and source is not None else ([], []))
    by_check: dict[str, int] = {}
    for proposal in proposals:
        by_check[proposal.checkId or ""] = by_check.get(proposal.checkId or "", 0) + 1
    for check in report.checks:
        if check.status not in ("warn", "fail"):
            continue
        analysis.findings.append(
            Finding(
                checkId=check.id,
                title=check.title,
                status=check.status,
                summary=check.summary,
                issues=[{"message": issue.message, "elementIds": issue.elementIds} for issue in check.issues],
                repair="safe" if by_check.get(check.id) else "review",
            )
        )
    analysis.repairable = len(proposals) + len(analysis.wordRepairs)
    analysis.blockRefusals = refused
    return analysis


def import_time_blocks(source: bytes, name: str) -> set[int]:
    """Which of the original's body blocks the import made elements of (read again from the file itself)."""
    from app.services.ingestion_service import build_document_from_docx

    imported = build_document_from_docx(source, name, None)
    return {index for element in imported.elements for index in (element.sourceBlocks or [])}


def touched_blocks(document: Document, source: bytes, name: str = "document.docx") -> set[int]:
    """The original's body blocks a repair (or any edit) may have changed: those of every element that is no longer
    as imported, and those whose element is gone. Everything else must come through byte for byte."""
    touched: set[int] = set()
    now: set[int] = set()
    for element in document.elements:
        blocks = set(element.sourceBlocks or [])
        now |= blocks
        if blocks and not unchanged(document, element):
            touched |= blocks
    return touched | (import_time_blocks(source, name) - now)


def check_repaired(document: Document, source: bytes, result: bytes, name: str = "document.docx") -> SafeEditResult:
    return verify(source, result, touched_blocks(document, source, name))


def build_repaired(
    document: Document,
    source: bytes,
    *,
    assets: dict[str, bytes] | None = None,
    word_repairs: Iterable[BlockRepair] = (),
    name: str = "document.docx",
) -> tuple[bytes, SafeEditResult, list[str]]:
    """The repaired file: the document (with the repairs accepted in it) written into the original, then the chosen
    Word-level repairs made in that file -- and the SafeEdit check of the result against the original. Returns the
    file, the check, and the Word-level repairs that couldn't be lined up and so were skipped."""
    from app.export.docx_export import build_docx

    result = build_docx(document, assets=assets or {}, source=source)
    touched = touched_blocks(document, source, name)
    skipped: list[str] = []
    chosen = list(word_repairs)
    if chosen:
        result, word_touched, skipped = apply_word_repairs(source, result, chosen)
        touched |= word_touched
    return result, verify(source, result, touched), skipped


def accept_all(document: Document, proposals: Iterable[ProposedChange]) -> Document:
    """Test helper and batch path: the given proposals accepted, as the Review panel would, one by one."""
    from app.formatting.proposals import accept

    proposals = list(proposals)
    document.proposals = [*document.proposals, *proposals]
    for proposal in proposals:
        accept(document, proposal.id)
    return document
