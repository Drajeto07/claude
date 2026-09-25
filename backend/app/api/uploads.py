"""The checks every upload goes through, shared by the document endpoints and the
job endpoints: allowed file types, the size cap on the bytes actually read,
what the bytes really are (security/files.py), instructions files, and
conflict resolutions sent with a formatting request."""

from fastapi import HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError

from app.config import get_settings
from app.parsers.pdf import PdfParseError
from app.schemas.formatting import ConflictResolutionInput
from app.security.files import check_upload
from app.services.ingestion_service import extract_instructions_text

DOCUMENT_EXTENSIONS = {"txt", "docx", "pdf"}
INSTRUCTIONS_EXTENSIONS = {"txt", "pdf"}


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


async def read_limited(file: UploadFile) -> bytes:
    """The file's bytes, refused with 413 over MAX_UPLOAD_SIZE_MB. file.size is
    whatever the client said (and sometimes missing), so the limit holds on what
    is actually read. The stream is rewound for anyone reading it again."""
    max_mb = get_settings().max_upload_size_mb
    contents = await file.read(max_mb * 1024 * 1024 + 1)
    if len(contents) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File is larger than {max_mb}MB.")
    await file.seek(0)
    return contents


def check_document_file(filename: str) -> None:
    extension = extension_of(filename)
    if extension not in DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: '.{extension}'. Use .txt, .docx, or .pdf.")


def check_content(file: UploadFile, contents: bytes) -> str:
    """The upload's real content type, once its bytes are what its name says;
    otherwise UnsafeFileError, answered 400 "invalid_file" (app/main.py)."""
    return check_upload(extension_of(file.filename or ""), contents, file.content_type)


async def instructions_from(text: str | None, file: UploadFile | None) -> str:
    """Typed instructions, or the text of an uploaded .txt/.pdf instructions file."""
    if file is None:
        return text or ""
    filename = file.filename or ""
    extension = extension_of(filename)
    if extension not in INSTRUCTIONS_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported instructions file type: '.{extension}'. Use .txt or .pdf.")
    contents = await read_limited(file)
    check_content(file, contents)
    try:
        return extract_instructions_text(contents, filename)
    except PdfParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def parse_resolutions(raw: str | None) -> list[ConflictResolutionInput] | None:
    """None when no resolutions were sent. Present at all (even `[]`) means the
    caller already showed the user every conflict, so detection is skipped."""
    if raw is None:
        return None
    try:
        return TypeAdapter(list[ConflictResolutionInput]).validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
