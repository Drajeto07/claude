import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from app.ai.base import AIProvider
from app.ai.factory import get_ai_provider
from app.ai.style_analysis import analyze_style
from app.api.deps import DocumentServiceDep
from app.api.uploads import check_document_file, instructions_from, parse_resolutions, read_limited
from app.export.docx_export import build_docx
from app.export.filenames import content_disposition, safe_filename
from app.export.pdf_export import build_pdf
from app.formatting.engine import InvalidOperationError, UnknownElementError
from app.formatting.templates import UnknownTemplateError
from app.models.document import Document, ElementType, FormattingProperty
from app.parsers.docx import DocxParseError
from app.parsers.pdf import PdfParseError
from app.schemas.document import (
    AddPageRequest,
    CreateDocumentRequest,
    FormatResponse,
    InsertElementRequest,
    RenameDocumentRequest,
    SetDocumentSettingRequest,
    StyleAnalysisResponse,
    UpdateContentRequest,
)
from app.schemas.formatting import SetElementStyleRequest
from app.services.document_service import (
    FormattingConflictsError,
    NothingToRedoError,
    NothingToUndoError,
    UnsupportedFileTypeError,
)

router = APIRouter()

def _found(document: Document | None) -> Document:
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.post("", response_model=Document, status_code=201)
async def create_document(
    payload: CreateDocumentRequest,
    service: DocumentServiceDep,
    provider: Annotated[AIProvider, Depends(get_ai_provider)],
) -> Document:
    return await service.create_from_text(payload.text, title=payload.title, provider=provider)


@router.post("/upload", response_model=Document, status_code=201)
async def upload_document(
    service: DocumentServiceDep,
    provider: Annotated[AIProvider, Depends(get_ai_provider)],
    file: UploadFile = File(...),
    title: Annotated[str | None, Form()] = None,
) -> Document:
    check_document_file(file.filename or "")
    await read_limited(file)

    try:
        return await service.create_from_upload(file, title=title, provider=provider)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DocxParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PdfParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{document_id}", response_model=Document)
async def get_document(document_id: str, service: DocumentServiceDep) -> Document:
    return _found(await service.get(document_id))


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, service: DocumentServiceDep) -> Response:
    if not await service.delete(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(status_code=204)


@router.post("/{document_id}/format", response_model=FormatResponse)
async def format_document(
    document_id: str,
    service: DocumentServiceDep,
    provider: Annotated[AIProvider, Depends(get_ai_provider)],
    templateId: Annotated[str | None, Form()] = None,
    instructionsText: Annotated[str | None, Form()] = None,
    instructionsFile: UploadFile | None = File(None),
    resolutions: Annotated[str | None, Form()] = None,
) -> FormatResponse:
    instructions_text = await instructions_from(instructionsText, instructionsFile)
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
    document, ai_unavailable, instruction_edit_count = result
    return FormatResponse(document=document, aiUnavailable=ai_unavailable, instructionEditCount=instruction_edit_count)


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
    return _found(await service.update_content(document_id, elements=payload.elements))


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


@router.post("/{document_id}/style-analysis", response_model=StyleAnalysisResponse)
async def analyze_document_style(
    document_id: str,
    service: DocumentServiceDep,
    provider: Annotated[AIProvider, Depends(get_ai_provider)],
) -> StyleAnalysisResponse:
    return await analyze_style(provider, _found(await service.get(document_id)))


@router.get("/{document_id}/export/docx")
async def export_docx(
    document_id: str,
    service: DocumentServiceDep,
    includeHeaders: bool = True,
    includePageNumbers: bool = True,
    includePageBreaks: bool = True,
) -> Response:
    document = _found(await service.get(document_id))
    content = await asyncio.to_thread(
        build_docx,
        document,
        assets=await service.export_assets(document),
        include_headers=includeHeaders,
        include_page_numbers=includePageNumbers,
        include_page_breaks=includePageBreaks,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": content_disposition(f"{safe_filename(document.metadata.title)}.docx")},
    )


@router.get("/{document_id}/export/pdf")
async def export_pdf(
    document_id: str,
    service: DocumentServiceDep,
    includeHeaders: bool = True,
    includePageNumbers: bool = True,
    includePageBreaks: bool = True,
) -> Response:
    document = _found(await service.get(document_id))
    content = await asyncio.to_thread(
        build_pdf,
        document,
        assets=await service.export_assets(document),
        include_headers=includeHeaders,
        include_page_numbers=includePageNumbers,
        include_page_breaks=includePageBreaks,
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(f"{safe_filename(document.metadata.title)}.pdf")},
    )
