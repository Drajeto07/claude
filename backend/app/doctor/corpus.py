"""Doctor v0 run over Word files the way the app runs it -- imported as an upload imports it, the safe repairs
proposed and all accepted, the repaired file written into the original, then checked (safe_edit.py). Used by the
invariant tests (tests/test_doctor.py) and by `python -m scripts.doctor_corpus` to measure the corpus."""

import hashlib
from dataclasses import dataclass, field

from app.doctor.doctor import accept_all, analyse, build_repaired, safe_proposals
from app.doctor.safe_edit import SafeEditResult
from app.export.provenance import stamp
from app.fidelity.imports import with_source_kept
from app.formatting.engine import recompute_styles
from app.models.document import Document, SourcePackage
from app.services.ingestion_service import build_document_from_docx


@dataclass
class CorpusRun:
    name: str
    refusals: list[str] = field(default_factory=list)
    findings: int = 0
    proposed: int = 0
    blocks_refused: int = 0
    word_repairs: int = 0
    skipped: list[str] = field(default_factory=list)
    result: SafeEditResult | None = None
    by_repair: dict[str, int] = field(default_factory=dict)
    file: bytes | None = None

    @property
    def verified(self) -> bool | None:
        return None if self.result is None else self.result.verified


def imported(data: bytes, name: str) -> Document:
    document = build_document_from_docx(data, name, None)
    recompute_styles(document)
    if document.importReport is not None:
        document.importReport = with_source_kept(document.importReport, data, document)
    stamp(document)
    document.sourcePackage = SourcePackage(assetId="corpus", sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    return document


def run(data: bytes, name: str) -> CorpusRun:
    document = imported(data, name)
    analysis = analyse(document, data, name=name)
    outcome = CorpusRun(name, refusals=[refusal.code for refusal in analysis.refusals], findings=len(analysis.findings))
    if not analysis.available:
        return outcome
    proposals, refused = safe_proposals(document, data, {index for repair in analysis.wordRepairs for index in repair.blocks})
    outcome.proposed, outcome.blocks_refused = len(proposals), len(refused)
    for proposal in proposals:
        outcome.by_repair[proposal.checkId or ""] = outcome.by_repair.get(proposal.checkId or "", 0) + 1
    outcome.word_repairs = len(analysis.wordRepairs)
    for repair in analysis.wordRepairs:
        outcome.by_repair[repair.kind] = outcome.by_repair.get(repair.kind, 0) + len(repair.blocks)
    accept_all(document, proposals)
    recompute_styles(document)
    outcome.file, outcome.result, outcome.skipped = build_repaired(document, data, word_repairs=analysis.wordRepairs, name=name)
    return outcome
