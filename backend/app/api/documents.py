import re
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import TypeAdapter, ValidationError

from app.ai.base import AIProvider
from app.ai.factory import get_ai_provider
from app.ai.style_analysis import analyze_style
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
    document_service,
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


@router.post("", response_model=Document, status_code=201)
async def create_document(
    payload: CreateDocumentRequest,
    provider: Annotated[AIProvider, Depends(get_ai_provider)],
) -> Document:
    return await document_service.create_from_text(payload.text, title=payload.title, provider=provider)


@router.post("/upload", response_model=Document, status_code=201)
async def upload_document(
    provider: Annotated[AIProvider, Depends(get_ai_provider)],
    file: UploadFile = File(...),
    title: Annotated[str | None, Form()] = None,
) -> Document:
    filename = file.filename or ""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in _ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: '.{extension}'. Use .txt, .docx, or .pdf.")

    max_bytes = get_settings().max_upload_size_mb * 1024 * 1024
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(status_code=413, detail=f"File is larger than {get_settings().max_upload_size_mb}MB.")

    try:
        return await document_service.create_from_upload(file, title=title, provider=provider)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DocxParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PdfParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{document_id}", response_model=Document)
def get_document(document_id: str) -> Document:
    document = document_service.get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.post("/{document_id}/format", response_model=FormatResponse)
async def format_document(
    document_id: str,
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
        result = await document_service.format_document(
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
def undo_document(document_id: str) -> Document:
    try:
        document = document_service.undo(document_id)
    except NothingToUndoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.post("/{document_id}/redo", response_model=Document)
def redo_document(document_id: str) -> Document:
    try:
        document = document_service.redo(document_id)
    except NothingToRedoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.patch("/{document_id}/elements/{element_id}/style", response_model=Document)
def set_element_style(document_id: str, element_id: str, payload: SetElementStyleRequest) -> Document:
    try:
        document = document_service.set_element_style(
            document_id, element_id=element_id, property=payload.property, value=payload.value, unit=payload.unit
        )
    except UnknownElementError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.delete("/{document_id}/elements/{element_id}/style/{property}", response_model=Document)
def clear_element_style(document_id: str, element_id: str, property: FormattingProperty) -> Document:
    try:
        document = document_service.clear_element_style(document_id, element_id=element_id, property=property)
    except UnknownElementError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.put("/{document_id}/content", response_model=Document)
def update_content(document_id: str, payload: UpdateContentRequest) -> Document:
    document = document_service.update_content(document_id, elements=payload.elements)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.post("/{document_id}/pages", response_model=Document, status_code=201)
def add_page(document_id: str, payload: AddPageRequest) -> Document:
    try:
        document = document_service.add_page(document_id, after_element_id=payload.afterElementId)
    except UnknownElementError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.post("/{document_id}/elements", response_model=Document, status_code=201)
def add_element(document_id: str, payload: InsertElementRequest) -> Document:
    try:
        document = document_service.add_element(
            document_id,
            element_type=ElementType(payload.elementType),
            after_element_id=payload.afterElementId,
            text=payload.text,
        )
    except UnknownElementError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.patch("/{document_id}", response_model=Document)
def rename_document(document_id: str, payload: RenameDocumentRequest) -> Document:
    document = document_service.rename(document_id, title=payload.title)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.patch("/{document_id}/settings", response_model=Document)
def set_page_setting(document_id: str, payload: SetDocumentSettingRequest) -> Document:
    document = document_service.set_page_setting(
        document_id, property=payload.property, value=payload.value, unit=payload.unit
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.delete("/{document_id}/settings/{property}", response_model=Document)
def clear_page_setting(document_id: str, property: FormattingProperty) -> Document:
    document = document_service.clear_page_setting(document_id, property=property)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.post("/{document_id}/style-analysis", response_model=StyleAnalysisResponse)
async def analyze_document_style(
    document_id: str,
    provider: Annotated[AIProvider, Depends(get_ai_provider)],
) -> StyleAnalysisResponse:
    document = document_service.get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return await analyze_style(provider, document)


@router.get("/{document_id}/export/docx")
def export_docx(
    document_id: str,
    includeHeaders: bool = True,
    includePageNumbers: bool = True,
    includePageBreaks: bool = True,
) -> Response:
    document = document_service.get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    filename = _safe_filename(document.metadata.title)
    return Response(
        content=build_docx(
            document,
            include_headers=includeHeaders,
            include_page_numbers=includePageNumbers,
            include_page_breaks=includePageBreaks,
        ),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": _content_disposition(f"{filename}.docx")},
    )


@router.get("/{document_id}/export/pdf")
def export_pdf(
    document_id: str,
    includeHeaders: bool = True,
    includePageNumbers: bool = True,
    includePageBreaks: bool = True,
) -> Response:
    document = document_service.get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    filename = _safe_filename(document.metadata.title)
    return Response(
        content=build_pdf(
            document,
            include_headers=includeHeaders,
            include_page_numbers=includePageNumbers,
            include_page_breaks=includePageBreaks,
        ),
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition(f"{filename}.pdf")},
    )
