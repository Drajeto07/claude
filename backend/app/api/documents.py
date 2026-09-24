import asyncio
import re
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import TypeAdapter, ValidationError

from app.ai.base import AIProvider
from app.ai.factory import get_ai_provider
from app.ai.style_analysis import analyze_style
from app.api.deps import DocumentServiceDep
from app.config import get_settings
from app.export.docx_export import build_docx
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
from app.schemas.formatting import ConflictResolutionInput, SetElementStyleRequest
from app.services.document_service import (
    FormattingConflictsError,
    NothingToRedoError,
    NothingToUndoError,
    UnsupportedFileTypeError,
)
from app.services.ingestion_service import extract_instructions_text

router = APIRouter()

_ALLOWED_UPLOAD_EXTENSIONS = {"txt", "docx", "pdf"}
_ALLOWED_INSTRUCTIONS_EXTENSIONS = {"txt", "pdf"}
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def _safe_filename(title: str) -> str:
    return _UNSAFE_FILENAME_CHARS.sub("_", title).strip() or "document"


def _content_disposition(filename: str) -> str:
    """Content-Disposition headers are Latin-1 only (RFC 7230), so a
    Cyrillic (or any non-ASCII) title needs the RFC 6266 filename* form --
    percent-encoded UTF-8, alongside a plain ASCII fallback for clients that
    don't understand filename*."""
    ascii_fallback = filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


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
    filename = file.filename or ""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in _ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: '.{extension}'. Use .txt, .docx, or .pdf.")

    max_bytes = get_settings().max_upload_size_mb * 1024 * 1024
    # file.size reflects client-reported metadata (Content-Length), which is
    # not always present -- some multipart encoders omit it, and a client
    # can misreport it either way. A hard limit must hold regardless, so it
    # is re-checked against the actual bytes read, never trusted from the
    # client alone. The stream is rewound afterwards so the parse below
    # still reads from the start.
    contents = await file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File is larger than {get_settings().max_upload_size_mb}MB.")
    await file.seek(0)

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
    instructions_text = instructionsText or ""
    if instructionsFile is not None:
        filename = instructionsFile.filename or ""
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if extension not in _ALLOWED_INSTRUCTIONS_EXTENSIONS:
            raise HTTPException(
                status_code=400, detail=f"Unsupported instructions file type: '.{extension}'. Use .txt or .pdf."
            )
        file_bytes = await instructionsFile.read()
        try:
            instructions_text = extract_instructions_text(file_bytes, filename)
        except PdfParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # `resolutions` being present at all (even `[]`) means the caller already
    # showed the user every conflict from a prior 409 -- skip re-detection.
    drop_overrides: list[tuple[str, FormattingProperty]] | None = None
    if resolutions is not None:
        try:
            resolution_inputs = TypeAdapter(list[ConflictResolutionInput]).validate_json(resolutions)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
        raise HTTPException(status_code=409, detail={"conflicts": [c.model_dump() for c in exc.conflicts]}) from exc
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
        headers={"Content-Disposition": _content_disposition(f"{_safe_filename(document.metadata.title)}.docx")},
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
        headers={"Content-Disposition": _content_disposition(f"{_safe_filename(document.metadata.title)}.pdf")},
    )
