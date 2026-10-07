import asyncio
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile

from app.ai.style_analysis import analyze_style
from app.api.deps import (
    CurrentUser,
    DbSession,
    DocumentServiceDep,
    MeteredAI,
    PlanChecks,
    Reservations,
    Translator,
    WorkspaceId,
    if_match_number,
    rate_limited,
)
from app.api.uploads import check_content, check_document_file, instructions_from, parse_resolutions, read_limited
from app.billing.units import EXPORT
from app.export.docx_export import build_docx
from app.export.filenames import safe_filename
from app.export.pdf_export import build_pdf
from app.formatting.compare import DocumentComparison
from app.formatting.engine import InvalidOperationError, UnknownElementError
from app.formatting.accessibility import AccessibilityReport
from app.formatting.health import HealthReport
from app.formatting.proposals import ContentNeedsReviewError, StaleProposalError, UnknownProposalError
from app.formatting.templates import UnknownTemplateError
from app.services.translation_service import TranslationService, UnknownBlockError
from app.translation.language import detect, language_name
from app.translation.providers import TranslationUnavailable
from app.translation.service import LABEL as TRANSLATION_LABEL
from app.translation.service import RangeError
from app.models.document import DOCX_CONTENT_TYPE, Document, ElementType, FormattingProperty
from app.schemas.document import (
    AcceptProposalsRequest,
    AcceptProposalsResponse,
    AddPageRequest,
    GlossaryRequest,
    LanguageOut,
    DocumentStylePreviewOut,
    StylePreviewRequest,
    LanguageRequest,
    NotTranslated,
    TranslateRequest,
    TranslateResponse,
    ContentPatchRequest,
    ContentSaved,
    CreateDocumentRequest,
    DocumentListOut,
    DocumentVersionOut,
    FormatResponse,
    HealthFixesRequest,
    HealthFixesResponse,
    InsertElementRequest,
    RenameDocumentRequest,
    SetDocumentSettingRequest,
    StyleAnalysisResponse,
    TrackedChangesRequest,
    UpdateContentRequest,
)
from app.schemas.formatting import SetElementStyleRequest
from app.security.rate_limit import enforce
from app.security.serving import file_response
from app.services.content_patch import PatchMismatchError
from app.services.document_service import (
    FormattingConflictsError,
    NoTrackedChangesError,
    NothingToRedoError,
    NothingToUndoError,
    UnsupportedFileTypeError,
    VersionNotFoundError,
)

router = APIRouter()
T = TypeVar("T")


def _found(document: T | None) -> T:
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("", response_model=DocumentListOut)
async def list_documents(
    service: DocumentServiceDep,
    q: Annotated[str | None, Query(max_length=200, description="Words in the title")] = None,
    sort: Literal["updated", "created", "title"] = "updated",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListOut:
    """The documents the user can open (every workspace they belong to), a page at a time."""
    return await service.summaries(query=(q or "").strip() or None, sort=sort, limit=limit, offset=offset)


@router.post("", response_model=Document, status_code=201, dependencies=[rate_limited("ai")])
async def create_document(
    payload: CreateDocumentRequest, service: DocumentServiceDep, provider: MeteredAI, workspace_id: WorkspaceId, plan: PlanChecks
) -> Document:
    # Checked before the (possibly AI) analysis, not only when the document is stored.
    await plan.check_new_document(workspace_id)
    return await service.create_from_text(payload.text, title=payload.title, provider=provider)


@router.post("/upload", response_model=Document, status_code=201, dependencies=[rate_limited("upload")])
async def upload_document(
    service: DocumentServiceDep,
    provider: MeteredAI,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
    file: UploadFile = File(...),
    title: Annotated[str | None, Form()] = None,
    autolink: Annotated[bool, Form()] = False,
    pdf_mode: Annotated[Literal["editable", "layout"], Form()] = "editable",
) -> Document:
    """`autolink`: turn a Word file's web and e-mail addresses written as plain text into
    links (off: they stay text, as the file has them -- DOCX-026). `pdf_mode`: a PDF as an
    editable document, or layout-focused -- each page a page, its text in its own fonts and
    sizes (P2E-007)."""
    check_document_file(file.filename or "")
    await plan.check_new_document(workspace_id)
    contents = await read_limited(file)
    await plan.check_file_size(workspace_id, len(contents))
    check_content(file, contents)

    try:
        return await service.create_from_upload(file, title=title, provider=provider, autolink=autolink, pdf_mode=pdf_mode)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{document_id}", response_model=Document)
async def get_document(document_id: str, service: DocumentServiceDep) -> Document:
    return _found(await service.get(document_id))


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, service: DocumentServiceDep) -> Response:
    """Deletes the document for good: its version history, and the files of its
    exports, go with it. Its images go with the next unused-image sweep."""
    if not await service.delete(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(status_code=204)


@router.get("/{document_id}/versions", response_model=list[DocumentVersionOut])
async def list_versions(document_id: str, service: DocumentServiceDep) -> list[DocumentVersionOut]:
    """The kept versions, newest first: the original plus the last changes."""
    return _found(await service.versions(document_id))


@router.get("/{document_id}/versions/{number}", response_model=Document)
async def get_version(document_id: str, number: int, service: DocumentServiceDep) -> Document:
    """The document as it was at one version, to look at."""
    try:
        return _found(await service.version(document_id, number))
    except VersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{document_id}/versions/{number}/restore", response_model=Document)
async def restore_version(document_id: str, number: int, service: DocumentServiceDep) -> Document:
    """Makes an earlier version current again, as a new change (If-Match applies)."""
    try:
        return _found(await service.restore_version(document_id, number))
    except VersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{document_id}/compare", response_model=DocumentComparison)
async def compare_versions(
    document_id: str,
    service: DocumentServiceDep,
    from_version: Annotated[int, Query(alias="from", ge=1)] = 1,
    to_version: Annotated[int | None, Query(alias="to", ge=1)] = None,
) -> DocumentComparison:
    """What changed between two versions: by default the original against the
    document as it is now (before/after)."""
    try:
        return _found(await service.compare(document_id, from_version=from_version, to_version=to_version))
    except VersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{document_id}/style-preview", response_model=DocumentStylePreviewOut)
async def style_preview(document_id: str, payload: StylePreviewRequest, service: DocumentServiceDep) -> DocumentStylePreviewOut:
    """The document with a look tried on (FMT-003): before and after, as the engine resolves them,
    and what changes -- before the look is saved as a template or applied. Nothing is saved."""
    preview = _found(await service.style_preview(document_id, payload.styleSystem))
    return DocumentStylePreviewOut(
        before=preview.before, after=preview.after, settingsBefore=preview.settings_before, settingsAfter=preview.settings_after,
        changes=preview.changes, tables=preview.tables, lists=preview.lists,
    )


@router.get("/{document_id}/health", response_model=HealthReport)
async def document_health(document_id: str, service: DocumentServiceDep) -> HealthReport:
    """Document Health: deterministic checks of the formatting's consistency, and a score from them."""
    return _found(await service.health(document_id))


@router.get("/{document_id}/accessibility", response_model=AccessibilityReport)
async def document_accessibility(document_id: str, service: DocumentServiceDep) -> AccessibilityReport:
    """The accessibility checker (FEAT-010): heading hierarchy, alt text, link labels, table headers,
    reading order, language and contrast -- deterministic checks of the saved document."""
    return _found(await service.accessibility(document_id))


@router.post("/{document_id}/health/fixes", response_model=HealthFixesResponse)
async def propose_health_fixes(document_id: str, payload: HealthFixesRequest, service: DocumentServiceDep) -> HealthFixesResponse:
    """Document Health's deterministic fixes as proposals to review (HLTH-002): each shows what it
    changes, and nothing changes until it is accepted -- then only in the block as it was checked."""
    document, count = _found(await service.propose_health_fixes(document_id, payload.checkIds))
    return HealthFixesResponse(document=document, proposalCount=count)


@router.post("/{document_id}/format", response_model=FormatResponse)
async def format_document(
    document_id: str,
    service: DocumentServiceDep,
    provider: MeteredAI,
    user: CurrentUser,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
    templateId: Annotated[str | None, Form()] = None,
    instructionsText: Annotated[str | None, Form()] = None,
    instructionsFile: UploadFile | None = File(None),
    resolutions: Annotated[str | None, Form()] = None,
) -> FormatResponse:
    instructions_text = await instructions_from(instructionsText, instructionsFile)
    if instructions_text.strip():
        await enforce("ai", f"user:{user.id}")
        await plan.check_ai(workspace_id)
    resolution_inputs = parse_resolutions(resolutions)
    drop_overrides: list[tuple[str, FormattingProperty]] | None = None
    if resolution_inputs is not None:
        drop_overrides = [
            (item.elementId, item.property) for item in resolution_inputs if item.resolution == "apply_recommended"
        ]

    try:
        result = await service.format_document(
            document_id,
            template_id=templateId,
            instructions_text=instructions_text,
            provider=provider,
            drop_overrides=drop_overrides,
        )
    except UnknownTemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FormattingConflictsError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "formatting_conflicts",
                "message": "This would change formatting that was set by hand. Choose what to keep for each.",
                "conflicts": [c.model_dump() for c in exc.conflicts],
            },
        ) from exc
    except InvalidOperationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="Document not found")
    document, ai_unavailable, instruction_edit_count, proposal_count = result
    return FormatResponse(
        document=document, aiUnavailable=ai_unavailable, instructionEditCount=instruction_edit_count, proposalCount=proposal_count
    )


@router.post("/{document_id}/translate", response_model=TranslateResponse, dependencies=[rate_limited("ai")])
async def translate_blocks(
    document_id: str, payload: TranslateRequest, service: DocumentServiceDep, translator: Translator, reservations: Reservations
) -> TranslateResponse:
    """Blocks (or part of one block's text) translated as proposals to review (TRAN-005):
    nothing in the document changes until one is accepted. Refused once the month's translation
    characters are used up."""
    selection = (payload.selection.start, payload.selection.end) if payload.selection else None
    try:
        outcome = await TranslationService(service, reservations).propose(
            document_id, element_ids=payload.elementIds, target=payload.targetLanguage, source=payload.sourceLanguage,
            provider=translator, selection=selection,
        )
    except (UnknownBlockError, RangeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TranslationUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": "translation_unavailable", "message": str(exc)}) from exc
    outcome = _found(outcome)
    return TranslateResponse(
        document=outcome.document,
        proposalCount=outcome.proposals,
        sourceLanguage=outcome.source_language,
        characters=outcome.characters,
        notTranslated=[NotTranslated(elementId=element_id, reasons=reasons) for element_id, reasons in outcome.not_translated.items()],
        label=TRANSLATION_LABEL,
    )


@router.get("/{document_id}/language", response_model=LanguageOut)
async def document_language(document_id: str, service: DocumentServiceDep) -> LanguageOut:
    """The document's language, script and direction (TRAN-007): as set, and as its text reads."""
    document = _found(await service.get(document_id))
    guess = detect(" ".join(element.content for element in document.elements[:200])[:20_000])
    used = document.metadata.language or guess.language
    return LanguageOut(
        set=document.metadata.language, detected=guess.language, script=guess.script, direction=guess.direction,  # type: ignore[arg-type]
        confidence=guess.confidence, name=language_name(used),
    )


@router.put("/{document_id}/language", response_model=Document)
async def set_document_language(document_id: str, payload: LanguageRequest, service: DocumentServiceDep) -> Document:
    """The document's language as the user says it is; null: detect it."""
    return _found(await service.set_language(document_id, payload.language))


@router.put("/{document_id}/glossary", response_model=Document)
async def set_document_glossary(document_id: str, payload: GlossaryRequest, service: DocumentServiceDep) -> Document:
    """How terms are to be translated in this document (TRAN-004); locked ones always so."""
    return _found(await service.set_glossary(document_id, payload.terms))


@router.post("/{document_id}/proposals/{proposal_id}/accept", response_model=Document)
async def accept_proposal(document_id: str, proposal_id: str, service: DocumentServiceDep) -> Document:
    """Applies one change to the content an AI instruction proposed (brief §19)."""
    try:
        return _found(await service.accept_proposal(document_id, proposal_id))
    except UnknownProposalError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StaleProposalError as exc:
        raise HTTPException(status_code=409, detail={"code": "stale_proposal", "message": str(exc)}) from exc


@router.post("/{document_id}/proposals/accept", response_model=AcceptProposalsResponse)
async def accept_proposals(document_id: str, payload: AcceptProposalsRequest, service: DocumentServiceDep) -> AcceptProposalsResponse:
    """Every waiting change of one category, accepted at once as one undo step (brief §58,
    REV-003). Changes to the content never: 422 for the content category, and any change that
    would alter the words is left waiting, to be accepted on its own."""
    try:
        document, accepted, skipped = _found(await service.accept_proposals(document_id, payload.category))
    except ContentNeedsReviewError as exc:
        raise HTTPException(status_code=422, detail={"code": "content_needs_review", "message": str(exc)}) from exc
    return AcceptProposalsResponse(document=document, accepted=accepted, skipped=skipped)


@router.post("/{document_id}/proposals/{proposal_id}/reject", response_model=Document)
async def reject_proposal(document_id: str, proposal_id: str, service: DocumentServiceDep) -> Document:
    """Drops one proposed change; nothing in the document changes."""
    try:
        return _found(await service.reject_proposal(document_id, proposal_id))
    except UnknownProposalError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{document_id}/undo", response_model=Document)
async def undo_document(document_id: str, service: DocumentServiceDep) -> Document:
    try:
        return _found(await service.undo(document_id))
    except NothingToUndoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{document_id}/redo", response_model=Document)
async def redo_document(document_id: str, service: DocumentServiceDep) -> Document:
    try:
        return _found(await service.redo(document_id))
    except NothingToRedoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{document_id}/elements/{element_id}/style", response_model=Document)
async def set_element_style(
    document_id: str, element_id: str, payload: SetElementStyleRequest, service: DocumentServiceDep
) -> Document:
    try:
        return _found(
            await service.set_element_style(
                document_id, element_id=element_id, property=payload.property, value=payload.value, unit=payload.unit
            )
        )
    except UnknownElementError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{document_id}/elements/{element_id}/style/{property}", response_model=Document)
async def clear_element_style(
    document_id: str, element_id: str, property: FormattingProperty, service: DocumentServiceDep
) -> Document:
    try:
        return _found(await service.clear_element_style(document_id, element_id=element_id, property=property))
    except UnknownElementError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{document_id}/content", response_model=Document)
async def update_content(document_id: str, payload: UpdateContentRequest, service: DocumentServiceDep) -> Document:
    return _found(await service.update_content(document_id, elements=payload.elements, styles=payload.styles))


@router.patch("/{document_id}/content", response_model=ContentSaved)
async def patch_content(document_id: str, payload: ContentPatchRequest, service: DocumentServiceDep, request: Request) -> ContentSaved:
    """Saves what changed since the revision in If-Match, which a patch must name
    (PERF-003). 409 `patch_mismatch` when it doesn't fit that revision: send the
    whole list with PUT instead."""
    if if_match_number(request) is None:
        raise HTTPException(status_code=428, detail="A patch says which revision it was made from (If-Match).")
    try:
        result = await service.patch_content(
            document_id,
            changed=payload.changed,
            added=[(entry.after, entry.element) for entry in payload.added],
            removed=payload.removed,
            styles=payload.styles,
        )
    except PatchMismatchError as exc:
        raise HTTPException(status_code=409, detail={"code": "patch_mismatch", "message": str(exc)}) from exc
    saved, delta = _found(result)
    return ContentSaved(revision=saved.revision, **delta)


@router.post("/{document_id}/pages", response_model=Document, status_code=201)
async def add_page(document_id: str, payload: AddPageRequest, service: DocumentServiceDep) -> Document:
    try:
        return _found(await service.add_page(document_id, after_element_id=payload.afterElementId))
    except UnknownElementError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{document_id}/elements", response_model=Document, status_code=201)
async def add_element(document_id: str, payload: InsertElementRequest, service: DocumentServiceDep) -> Document:
    try:
        return _found(
            await service.add_element(
                document_id,
                element_type=ElementType(payload.elementType),
                after_element_id=payload.afterElementId,
                text=payload.text,
            )
        )
    except UnknownElementError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{document_id}", response_model=Document)
async def rename_document(document_id: str, payload: RenameDocumentRequest, service: DocumentServiceDep) -> Document:
    return _found(await service.rename(document_id, title=payload.title))


@router.put("/{document_id}/tracked-changes", response_model=Document)
async def set_tracked_changes(document_id: str, payload: TrackedChangesRequest, service: DocumentServiceDep) -> Document:
    """Whether a Word export keeps the file's tracked changes in the blocks not changed
    here ("kept"), or they are all accepted ("accepted"). 409 for a document without any."""
    try:
        return _found(await service.set_tracked_changes(document_id, choice=payload.choice))
    except NoTrackedChangesError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/{document_id}/settings", response_model=Document)
async def set_page_setting(
    document_id: str, payload: SetDocumentSettingRequest, service: DocumentServiceDep
) -> Document:
    return _found(
        await service.set_page_setting(document_id, property=payload.property, value=payload.value, unit=payload.unit)
    )


@router.delete("/{document_id}/settings/{property}", response_model=Document)
async def clear_page_setting(document_id: str, property: FormattingProperty, service: DocumentServiceDep) -> Document:
    return _found(await service.clear_page_setting(document_id, property=property))


@router.post("/{document_id}/style-analysis", response_model=StyleAnalysisResponse, dependencies=[rate_limited("ai")])
async def analyze_document_style(
    document_id: str, service: DocumentServiceDep, provider: MeteredAI, workspace_id: WorkspaceId, plan: PlanChecks
) -> StyleAnalysisResponse:
    document = _found(await service.get(document_id))
    await plan.check_ai(workspace_id)
    return await analyze_style(provider, document)  # the call's usage is committed by its reservation


@router.get("/{document_id}/export/docx", dependencies=[rate_limited("export")])
async def export_docx(
    document_id: str,
    service: DocumentServiceDep,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
    reservations: Reservations,
    includeHeaders: bool = True,
    includePageNumbers: bool = True,
    includePageBreaks: bool = True,
) -> Response:
    document = _found(await service.get(document_id))
    await plan.check_export(workspace_id, "docx")
    async with reservations.held(EXPORT):  # counted before it is built, given back if it can't be
        source, _ = await service.source_package(document)  # the export job reports a missing one; this download just goes without
        content = await asyncio.to_thread(
            build_docx,
            document,
            assets=await service.export_assets(document),
            source=source,
            include_headers=includeHeaders,
            include_page_numbers=includePageNumbers,
            include_page_breaks=includePageBreaks,
        )
    await service.record_export(document_id, "docx", len(content))
    return file_response(content, DOCX_CONTENT_TYPE, filename=f"{safe_filename(document.metadata.title)}.docx")


@router.get("/{document_id}/export/pdf", dependencies=[rate_limited("export")])
async def export_pdf(
    document_id: str,
    service: DocumentServiceDep,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
    reservations: Reservations,
    includeHeaders: bool = True,
    includePageNumbers: bool = True,
    includePageBreaks: bool = True,
) -> Response:
    document = _found(await service.get(document_id))
    await plan.check_export(workspace_id, "pdf")
    async with reservations.held(EXPORT):  # counted before it is built, given back if it can't be
        content = await asyncio.to_thread(
            build_pdf,
            document,
            assets=await service.export_assets(document),
            include_headers=includeHeaders,
            include_page_numbers=includePageNumbers,
            include_page_breaks=includePageBreaks,
        )
    await service.record_export(document_id, "pdf", len(content))
    return file_response(content, "application/pdf", filename=f"{safe_filename(document.metadata.title)}.pdf")
