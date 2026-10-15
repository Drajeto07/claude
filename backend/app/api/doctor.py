"""Document Doctor v0 (prototype, behind a feature flag): analyse a document's Word file, propose only repairs that
can't change its words, and hand out a repaired file only when SafeEdit verified it against the original
(app/doctor). The original Word file is never written to; every repaired file is a new download.

The editor shows this only with ?doctor=1; DOCTOR_ENABLED=false turns the routes off entirely.
"""

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.deps import DocumentServiceDep, PlanChecks, Reservations, WorkspaceId, rate_limited
from app.billing.units import EXPORT
from app.config import get_settings
from app.doctor.doctor import Analysis, analyse, build_repaired
from app.export.filenames import safe_filename
from app.models.base import ApiModel
from app.models.document import DOCX_CONTENT_TYPE, Document
from app.security.serving import file_response

router = APIRouter()


class DoctorRefusal(ApiModel):
    code: str
    message: str


class DoctorIssue(ApiModel):
    message: str
    elementIds: list[str]


class DoctorFinding(ApiModel):
    checkId: str
    title: str
    status: Literal["warn", "fail"]
    summary: str
    issues: list[DoctorIssue]
    repair: Literal["safe", "review"]


class DoctorWordRepair(ApiModel):
    id: str
    kind: Literal["empty_paragraphs", "wide_picture", "wide_table"]
    blocks: int
    where: str


class DoctorBlockRefusal(ApiModel):
    elementId: str
    checkId: str
    reason: str


class DoctorReport(ApiModel):
    """What Doctor found and may repair. `available` false: `refusals` say why nothing is repaired automatically."""

    prototype: bool = True
    available: bool
    refusals: list[DoctorRefusal]
    findings: list[DoctorFinding]
    wordRepairs: list[DoctorWordRepair]
    modelRepairs: int
    blockRefusals: list[DoctorBlockRefusal]


class DoctorProposalsResponse(ApiModel):
    document: Document
    proposalCount: int


class DoctorRepairRequest(ApiModel):
    """The repairs made in the Word file itself that the person chose (ids from DoctorReport.wordRepairs)."""

    wordRepairs: list[str] = []


class DoctorCheck(ApiModel):
    name: Literal["words", "headers", "untouched", "preserved", "package"]
    passed: bool
    detail: str


class DoctorCheckResult(ApiModel):
    verified: bool
    checks: list[DoctorCheck]
    skipped: list[str]
    refusals: list[DoctorRefusal]


def _enabled() -> None:
    if not get_settings().doctor_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


def _name(document: Document) -> str:
    return document.metadata.originalFilename or "document.docx"


def _report(analysis: Analysis) -> DoctorReport:
    return DoctorReport(
        available=analysis.available,
        refusals=[DoctorRefusal(code=refusal.code, message=refusal.message) for refusal in analysis.refusals],
        findings=[
            DoctorFinding(
                checkId=finding.checkId,
                title=finding.title,
                status=finding.status,
                summary=finding.summary,
                issues=[DoctorIssue(**issue) for issue in finding.issues],
                repair=finding.repair,
            )
            for finding in analysis.findings
        ],
        wordRepairs=[DoctorWordRepair(id=repair.id, kind=repair.kind, blocks=len(repair.blocks), where=repair.where) for repair in analysis.wordRepairs],
        modelRepairs=analysis.repairable - len(analysis.wordRepairs),
        blockRefusals=[DoctorBlockRefusal(elementId=refusal.elementId, checkId=refusal.checkId, reason=refusal.reason) for refusal in analysis.blockRefusals],
    )


async def _analysis(service, document_id: str) -> tuple[Document, bytes | None, Analysis]:
    document = await service.get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    source, problem = await service.source_package(document)
    analysis = await asyncio.to_thread(analyse, document, source, problem, _name(document))
    return document, source, analysis


async def _repaired(service, document_id: str, chosen: list[str]):
    document, source, analysis = await _analysis(service, document_id)
    refusals = [DoctorRefusal(code=refusal.code, message=refusal.message) for refusal in analysis.refusals]
    if not analysis.available or source is None:
        return document, None, DoctorCheckResult(verified=False, checks=[], skipped=[], refusals=refusals)
    unknown = set(chosen) - {repair.id for repair in analysis.wordRepairs}
    if unknown:
        raise HTTPException(status_code=409, detail={"code": "stale_repairs", "message": "Some chosen repairs no longer apply; check the document again."})
    word_repairs = [repair for repair in analysis.wordRepairs if repair.id in chosen]
    assets = await service.export_assets(document)
    content, result, skipped = await asyncio.to_thread(build_repaired, document, source, assets=assets, word_repairs=word_repairs, name=_name(document))
    checks = [DoctorCheck(name=check.name, passed=check.passed, detail=check.detail) for check in result.checks]
    return document, content, DoctorCheckResult(verified=result.verified, checks=checks, skipped=skipped, refusals=[])


@router.get("/{document_id}/doctor", response_model=DoctorReport, dependencies=[rate_limited("export")])
async def doctor_report(document_id: str, service: DocumentServiceDep) -> DoctorReport:
    """Doctor v0 (prototype): the problems found, the repairs it may make, and why it refuses when it does."""
    _enabled()
    _, _, analysis = await _analysis(service, document_id)
    return _report(analysis)


@router.post("/{document_id}/doctor/proposals", response_model=DoctorProposalsResponse)
async def doctor_proposals(document_id: str, service: DocumentServiceDep) -> DoctorProposalsResponse:
    """The safe repairs the editor can make, as changes to review (the Review panel): nothing changes until each is
    accepted. Refused (409) when Doctor refuses the document."""
    _enabled()
    found = await service.propose_doctor_repairs(document_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Document not found")
    document, count, refusals = found
    if refusals:
        raise HTTPException(status_code=409, detail={"code": "doctor_refused", "message": refusals[0].message})
    return DoctorProposalsResponse(document=document, proposalCount=count)


@router.post("/{document_id}/doctor/check", response_model=DoctorCheckResult, dependencies=[rate_limited("export")])
async def doctor_check(document_id: str, payload: DoctorRepairRequest, service: DocumentServiceDep) -> DoctorCheckResult:
    """The repaired file built (the accepted repairs and the chosen file repairs) and checked against the original,
    without downloading it: whether its words, untouched blocks, preserved features and package all hold."""
    _enabled()
    _, _, result = await _repaired(service, document_id, payload.wordRepairs)
    return result


@router.post("/{document_id}/doctor/download", dependencies=[rate_limited("export")])
async def doctor_download(
    document_id: str,
    payload: DoctorRepairRequest,
    service: DocumentServiceDep,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
    reservations: Reservations,
):
    """The repaired Word file -- only when every SafeEdit check passed; otherwise 409 with the checks, and nothing is
    handed out. The original stays as it was."""
    _enabled()
    await plan.check_export(workspace_id, "docx")
    async with reservations.held(EXPORT):
        document, content, result = await _repaired(service, document_id, payload.wordRepairs)
        if content is None or not result.verified:
            raise HTTPException(status_code=409, detail={"code": "not_verified", "message": "The repaired file didn't pass every check, so it isn't handed out.", "result": result.model_dump()})
    await service.record_export(document_id, "docx", len(content))
    response = file_response(content, DOCX_CONTENT_TYPE, filename=f"{safe_filename(document.metadata.title)} (repaired).docx")
    response.headers["X-SafeEdit"] = "verified"
    return response
