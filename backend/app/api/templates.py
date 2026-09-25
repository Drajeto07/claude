from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from app.ai.base import AIProvider
from app.ai.factory import get_ai_provider
from app.api.deps import CurrentUser, DbSession, if_match_number
from app.config import get_settings
from app.formatting.style_system import StyleSystem
from app.parsers.docx import DocxParseError
from app.schemas.templates import (
    CreatedTemplateOut,
    CreateTemplateRequest,
    DefaultTemplateOut,
    DefaultTemplateRequest,
    DuplicateTemplateRequest,
    ReferenceStyleOut,
    StylePreviewOut,
    TemplateOut,
    TemplateVersionOut,
    UpdateTemplateRequest,
)
from app.services.reference_service import extract_from_docx, suggested_name
from app.services.template_service import TemplateService, preview_styles

# Errors (404/403/409/412) are mapped once, in app/main.py.
router = APIRouter()


def get_template_service(user: CurrentUser, db: DbSession) -> TemplateService:
    return TemplateService(db, user_id=user.id)


Templates = Annotated[TemplateService, Depends(get_template_service)]
ExpectedVersion = Annotated[int | None, Depends(if_match_number)]


@router.get("", response_model=list[TemplateOut])
async def list_templates(templates: Templates) -> list[TemplateOut]:
    return [TemplateOut.of(view) for view in await templates.list_visible()]


@router.post("", response_model=CreatedTemplateOut, status_code=201)
async def create_template(payload: CreateTemplateRequest, templates: Templates) -> CreatedTemplateOut:
    notes: list[str] = []
    if payload.sourceDocumentId is not None:
        view, notes = await templates.create_from_document(
            payload.sourceDocumentId,
            name=payload.name,
            category=payload.category,
            description=payload.description,
            visibility=payload.visibility,
        )
    else:
        view = await templates.create(
            name=payload.name,
            category=payload.category,
            description=payload.description,
            style_system=payload.styleSystem or StyleSystem(),
            visibility=payload.visibility,
        )
    return CreatedTemplateOut(**TemplateOut.of(view).model_dump(), notes=notes)


# Fixed paths before "/{template_id}", or "default"/"preview" would be taken for ids.
@router.put("/default", response_model=DefaultTemplateOut)
async def set_default_template(payload: DefaultTemplateRequest, templates: Templates) -> DefaultTemplateOut:
    await templates.set_default(payload.templateId)
    return DefaultTemplateOut(templateId=await templates.default_template_id())


@router.post("/preview", response_model=StylePreviewOut, dependencies=[Depends(get_template_service)])
async def preview_style_system(style_system: StyleSystem) -> StylePreviewOut:
    """What a document would resolve to under this (unsaved) style system -- for
    the template editor's live preview, computed by the real engine."""
    resolved, settings = preview_styles(style_system)
    return StylePreviewOut(resolvedStyles=resolved, settings=settings)


@router.post("/extract", response_model=ReferenceStyleOut)
async def extract_reference_style(
    templates: Templates,
    provider: Annotated[AIProvider, Depends(get_ai_provider)],
    file: UploadFile = File(...),
) -> ReferenceStyleOut:
    """Format by Example (корекции.docx §17): the style a reference Word document
    uses, read deterministically; the AI, when configured, only helps tell which
    paragraphs are headings. Nothing is saved."""
    filename = file.filename or ""
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="The reference document has to be a Word file (.docx).")
    max_mb = get_settings().max_upload_size_mb
    contents = await file.read(max_mb * 1024 * 1024 + 1)
    if len(contents) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File is larger than {max_mb}MB.")
    try:
        reference = await extract_from_docx(contents, filename, provider)
    except DocxParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    taken = {view.name for view in await templates.list_visible()}
    return ReferenceStyleOut.of(reference, suggested_name(filename, taken))


@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(template_id: str, templates: Templates) -> TemplateOut:
    return TemplateOut.of(await templates.get(template_id))


@router.put("/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: str, payload: UpdateTemplateRequest, templates: Templates, expected_version: ExpectedVersion
) -> TemplateOut:
    view = await templates.update(
        template_id,
        expected_version=expected_version,
        name=payload.name,
        category=payload.category,
        description=payload.description,
        style_system=payload.styleSystem,
        visibility=payload.visibility,
    )
    return TemplateOut.of(view)


@router.delete("/{template_id}", status_code=204)
async def delete_template(template_id: str, templates: Templates) -> Response:
    await templates.delete(template_id)
    return Response(status_code=204)


@router.post("/{template_id}/duplicate", response_model=TemplateOut, status_code=201)
async def duplicate_template(
    template_id: str, templates: Templates, payload: DuplicateTemplateRequest | None = None
) -> TemplateOut:
    return TemplateOut.of(await templates.duplicate(template_id, name=payload.name if payload else None))


@router.get("/{template_id}/versions", response_model=list[TemplateVersionOut])
async def list_template_versions(template_id: str, templates: Templates) -> list[TemplateVersionOut]:
    return [TemplateVersionOut.of(version) for version in await templates.versions(template_id)]


@router.post("/{template_id}/versions/{number}/restore", response_model=TemplateOut)
async def restore_template_version(
    template_id: str, number: int, templates: Templates, expected_version: ExpectedVersion
) -> TemplateOut:
    return TemplateOut.of(await templates.restore_version(template_id, number, expected_version=expected_version))
