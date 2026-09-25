"""Background jobs (корекции.docx §52): heavy work is queued and answered at once
with 202 and the job; the client polls GET /api/jobs/{id} for its real stage and
progress, then reads the result (a new document's id, a formatting outcome, an
export to download, a reference document's style). Everything checkable up
front -- file type, size, access to the document, what the plan allows -- is
checked before queuing."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile

from app.api.deps import CurrentUser, DbSession, PlanChecks, Storage, WorkspaceId, if_match_number
from app.db.models import JobType
from app.api.uploads import check_document_file, extension_of, instructions_from, parse_resolutions, read_limited
from app.export.filenames import content_disposition
from app.jobs.queue import Queue
from app.jobs.runner import EXPORT, EXTRACT_REFERENCE, FORMAT, IMPORT_FILE, IMPORT_TEXT
from app.schemas.jobs import ExportJobRequest, ImportTextJobRequest, JobOut
from app.services.document_service import DocumentService
from app.services.entitlements_service import EntitlementsService
from app.services.job_service import JobService
from app.storage.base import AssetNotFoundError

router = APIRouter()
logger = logging.getLogger(__name__)


def get_job_service(user: CurrentUser, db: DbSession, storage: Storage) -> JobService:
    return JobService(db, user_id=user.id, storage=storage)


Jobs = Annotated[JobService, Depends(get_job_service)]


async def _start(jobs: JobService, queue: Queue, plan: EntitlementsService, workspace_id: str, job_type: str, **job) -> JobOut:
    await jobs.expire_old_exports()
    created = await jobs.create(job_type, **job)
    try:
        await queue.enqueue(created.id, priority=(await plan.entitlements(workspace_id)).priorityProcessing)
    except Exception as exc:  # e.g. Redis unreachable: the job is failed, not left pending forever
        logger.exception("Could not queue job %s", created.id)
        await jobs.fail(created, "Processing couldn't be started. Please try again in a moment.")
        raise HTTPException(status_code=503, detail="Processing couldn't be started. Please try again in a moment.") from exc
    found = await jobs.get(created.id)  # a job run eagerly has already finished
    return JobOut.of(found or created)


async def _check_document(user: CurrentUser, db: DbSession, storage: Storage, document_id: str) -> None:
    if await DocumentService(db, user_id=user.id, storage=storage).get(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")


@router.post("/import-text", response_model=JobOut, status_code=202)
async def import_text(payload: ImportTextJobRequest, jobs: Jobs, queue: Queue, workspace_id: WorkspaceId, plan: PlanChecks) -> JobOut:
    """Pasted text into a new document (structure analysis, AI for plain prose)."""
    await plan.check_new_document(workspace_id)
    return await _start(jobs, queue, plan, workspace_id, IMPORT_TEXT, payload={"text": payload.text, "title": payload.title})


@router.post("/import-file", response_model=JobOut, status_code=202)
async def import_file(
    jobs: Jobs,
    queue: Queue,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
    file: UploadFile = File(...),
    title: Annotated[str | None, Form()] = None,
) -> JobOut:
    """An uploaded .docx, .pdf or .txt into a new document."""
    filename = file.filename or ""
    check_document_file(filename)
    await plan.check_new_document(workspace_id)
    contents = await read_limited(file)
    await plan.check_file_size(workspace_id, len(contents))
    return await _start(
        jobs,
        queue,
        plan,
        workspace_id,
        IMPORT_FILE,
        payload={"filename": filename, "title": title},
        input_bytes=contents,
        input_content_type=file.content_type or "application/octet-stream",
    )


@router.post("/format", response_model=JobOut, status_code=202)
async def format_document(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    storage: Storage,
    jobs: Jobs,
    queue: Queue,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
    documentId: Annotated[str, Form()],
    templateId: Annotated[str | None, Form()] = None,
    instructionsText: Annotated[str | None, Form()] = None,
    instructionsFile: UploadFile | None = File(None),
    resolutions: Annotated[str | None, Form()] = None,
) -> JobOut:
    """A template and/or instructions applied to a document. The job's result says
    "applied", or lists the conflicts to resolve first (then send `resolutions`).
    Instructions need the AI, so they are refused up front once the plan's
    monthly AI operations are used up."""
    await _check_document(user, db, storage, documentId)
    parsed = parse_resolutions(resolutions)
    instructions = await instructions_from(instructionsText, instructionsFile)
    if instructions.strip():
        await plan.check_ai(workspace_id)
    payload = {
        "templateId": templateId,
        "instructionsText": instructions,
        "resolutions": [item.model_dump(mode="json") for item in parsed] if parsed is not None else None,
        "expectedRevision": if_match_number(request),
    }
    return await _start(jobs, queue, plan, workspace_id, FORMAT, document_id=documentId, payload=payload)


@router.post("/export", response_model=JobOut, status_code=202)
async def export_document(
    payload: ExportJobRequest,
    user: CurrentUser,
    db: DbSession,
    storage: Storage,
    jobs: Jobs,
    queue: Queue,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
) -> JobOut:
    """A DOCX or PDF rendered in the background; download it from /api/jobs/{id}/file."""
    await _check_document(user, db, storage, payload.documentId)
    await plan.check_export(workspace_id, payload.format)
    return await _start(
        jobs, queue, plan, workspace_id, EXPORT, document_id=payload.documentId, payload=payload.model_dump(exclude={"documentId"})
    )


@router.post("/extract-reference", response_model=JobOut, status_code=202)
async def extract_reference(jobs: Jobs, queue: Queue, workspace_id: WorkspaceId, plan: PlanChecks, file: UploadFile = File(...)) -> JobOut:
    """Format by Example: the style a reference .docx uses (its result is what
    POST /api/templates/extract answers)."""
    filename = file.filename or ""
    if extension_of(filename) != "docx":
        raise HTTPException(status_code=400, detail="The reference document has to be a Word file (.docx).")
    contents = await read_limited(file)
    await plan.check_file_size(workspace_id, len(contents))
    return await _start(jobs, queue, plan, workspace_id, EXTRACT_REFERENCE, payload={"filename": filename}, input_bytes=contents)


@router.get("", response_model=list[JobOut])
async def list_jobs(
    jobs: Jobs,
    type: JobType | None = None,
    status: Literal["pending", "running", "succeeded", "failed"] | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[JobOut]:
    """The user's latest jobs, newest first -- e.g. the dashboard's recent exports
    (type=export, status=succeeded)."""
    return [JobOut.of(job) for job in await jobs.recent(job_type=type.value if type else None, status=status, limit=limit)]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, jobs: Jobs) -> JobOut:
    job = await jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut.of(job)


@router.get("/{job_id}/file")
async def download_job_file(job_id: str, jobs: Jobs) -> Response:
    """A finished export's file (kept for JOB_FILE_TTL_HOURS)."""
    job = await jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        found = await jobs.export_file(job)
    except AssetNotFoundError:
        found = None
    if found is None:
        raise HTTPException(status_code=404, detail="No file for this job (not an export, not finished, or expired).")
    content, result = found
    return Response(
        content=content,
        media_type=result["contentType"],
        headers={"Content-Disposition": content_disposition(result["filename"])},
    )
