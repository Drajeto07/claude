"""PDF page operations (tracker PDF-020), a service of their own beside the documents: a PDF in,
a PDF (or a ZIP of PDFs) out, nothing stored. Signed in, counted against the upload allowance,
each file within the plan's file size and checked to be a PDF (security/files.py); what the
service does to it is in services/pdf_pages.py.

    POST /pdf/info        file                       -> each page's size and rotation
    POST /pdf/pages       file, operations (JSON)    -> the PDF with them done
    POST /pdf/split       file, ranges (JSON) | every -> a ZIP of the parts
    POST /pdf/merge       files (2-20)               -> one PDF
"""

import asyncio
import io
import json
import zipfile
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from pydantic import Field, TypeAdapter, ValidationError

from app.api.deps import CurrentUser, PlanChecks, WorkspaceId, rate_limited
from app.api.uploads import check_content, extension_of, read_limited
from app.audit import audit
from app.config import get_settings
from app.export.filenames import safe_filename
from app.security.serving import file_response
from app.services import pdf_pages
from app.services.pdf_pages import MAX_MERGED_FILES, MAX_SPLIT_PARTS, Operation, PageInfo, PdfPagesError

router = APIRouter()

_PDF = "application/pdf"
_OPERATIONS = TypeAdapter(Annotated[list[Operation], Field(min_length=1, max_length=pdf_pages.MAX_OPERATIONS)])
_RANGES = TypeAdapter(Annotated[list[tuple[Annotated[int, Field(ge=1)], Annotated[int, Field(ge=1)]]], Field(min_length=1, max_length=MAX_SPLIT_PARTS)])


async def _pdf(file: UploadFile, workspace_id: str, plan: PlanChecks) -> bytes:
    """The upload's bytes, once it is a PDF within the limits."""
    if extension_of(file.filename or "") != "pdf":
        raise HTTPException(status_code=400, detail="Upload a .pdf file.")
    contents = await read_limited(file)
    await plan.check_file_size(workspace_id, len(contents))
    check_content(file, contents)
    return contents


def _parsed(adapter: TypeAdapter, raw: str, field: str):
    """A form field's JSON, checked as an invalid request is answered: where and what, never what was sent (SEC-019)."""
    try:
        return adapter.validate_python(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise RequestValidationError([{"type": "json_invalid", "loc": ("body", field), "msg": "Invalid JSON", "input": None}]) from exc
    except ValidationError as exc:
        raise RequestValidationError([{**error, "loc": ("body", field, *error["loc"])} for error in exc.errors()]) from exc


def _stem(file: UploadFile) -> str:
    name = file.filename or "document.pdf"
    return safe_filename(name.rsplit(".", 1)[0] if "." in name else name)


@router.post("/info", response_model=list[PageInfo], dependencies=[rate_limited("upload")])
async def pdf_info(user: CurrentUser, workspace_id: WorkspaceId, plan: PlanChecks, file: UploadFile = File(...)) -> list[PageInfo]:
    return await asyncio.to_thread(pdf_pages.page_info, await _pdf(file, workspace_id, plan))


@router.post("/pages", dependencies=[rate_limited("upload")])
async def pdf_operations(
    user: CurrentUser, workspace_id: WorkspaceId, plan: PlanChecks, file: UploadFile = File(...), operations: Annotated[str, Form()] = ""
) -> Response:
    """`operations`: e.g. [{"op": "rotate", "pages": [2], "degrees": 90}, {"op": "delete", "pages": [5]}] --
    reorder (order: every page), rotate (pages, degrees), delete, duplicate, extract (pages)."""
    data = await _pdf(file, workspace_id, plan)
    asked = _parsed(_OPERATIONS, operations or "null", "operations")
    try:
        result = await asyncio.to_thread(pdf_pages.apply_operations, data, asked)
    except PdfPagesError as exc:
        raise HTTPException(status_code=422, detail={"code": "pdf_pages", "message": str(exc)}) from exc
    audit("pdf_pages.operations", user_id=user.id, operations=len(asked), bytes=len(result))
    return file_response(result, _PDF, filename=f"{_stem(file)}.pdf")


@router.post("/split", dependencies=[rate_limited("upload")])
async def pdf_split(
    user: CurrentUser,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
    file: UploadFile = File(...),
    ranges: Annotated[str | None, Form()] = None,
    every: Annotated[int | None, Form(ge=1, le=10_000)] = None,
) -> Response:
    """`ranges`: e.g. [[1, 3], [4, 10]] (first and last page of each part), or `every`: so many pages a part."""
    data = await _pdf(file, workspace_id, plan)
    parts_asked = _parsed(_RANGES, ranges, "ranges") if ranges is not None else None
    try:
        parts = await asyncio.to_thread(pdf_pages.split, data, parts_asked, every)
    except PdfPagesError as exc:
        raise HTTPException(status_code=422, detail={"code": "pdf_pages", "message": str(exc)}) from exc
    stem = _stem(file)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as package:
        for number, part in enumerate(parts, start=1):
            package.writestr(f"{stem}-{number:0{len(str(len(parts)))}d}.pdf", part)
    audit("pdf_pages.split", user_id=user.id, parts=len(parts))
    return file_response(out.getvalue(), "application/zip", filename=f"{stem}-parts.zip")


@router.post("/merge", dependencies=[rate_limited("upload")])
async def pdf_merge(user: CurrentUser, workspace_id: WorkspaceId, plan: PlanChecks, files: list[UploadFile] = File(...)) -> Response:
    if not 2 <= len(files) <= MAX_MERGED_FILES:
        raise HTTPException(status_code=422, detail={"code": "pdf_pages", "message": f"Merge 2 to {MAX_MERGED_FILES} PDFs."})
    contents = [await _pdf(file, workspace_id, plan) for file in files]
    max_mb = get_settings().max_upload_size_mb
    if sum(len(data) for data in contents) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Together the files are larger than {max_mb}MB.")
    try:
        result = await asyncio.to_thread(pdf_pages.merge, contents)
    except PdfPagesError as exc:
        raise HTTPException(status_code=422, detail={"code": "pdf_pages", "message": str(exc)}) from exc
    audit("pdf_pages.merge", user_id=user.id, files=len(files), bytes=len(result))
    return file_response(result, _PDF, filename=f"{_stem(files[0])}-merged.pdf")
