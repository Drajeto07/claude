"""Background jobs (корекции.docx §52): heavy work is queued and answered at once
with 202 and the job; the client polls GET /api/jobs/{id} for its real stage and
progress, then reads the result (a new document's id, a formatting outcome, an
export to download, a reference document's style). Everything checkable up
front -- file type, size, access to the document, what the plan allows -- is
checked before queuing.

Every job-creating POST takes an optional Idempotency-Key header (JOB-001,
docs/architecture/jobs.md): the same user sending the same key and request gets the
same job back, never a second one. POST /api/jobs/{id}/cancel stops a job."""

import hashlib
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile

from app.api.deps import CurrentUser, DbSession, PlanChecks, Storage, WorkspaceId, if_match_number, rate_limited
from app.config import get_settings
from app.db.models import JobType
from app.jobs import uploads
from app.api.uploads import check_content, check_document_file, extension_of, instructions_from, parse_resolutions, read_limited
from app.jobs.queue import Queue
from app.jobs.runner import EXPORT, EXTRACT_REFERENCE, FORMAT, IMPORT_FILE, IMPORT_TEXT, TRANSLATE
from app.schemas.jobs import (
    BatchExportRequest,
    BatchFormatRequest,
    BatchOut,
    BatchTranslateRequest,
    ChunkedUploadOut,
    ChunkedUploadRequest,
    ChunkReceived,
    ExportJobRequest,
    ImportTextJobRequest,
    JobOut,
    TranslateDocumentJobRequest,
)
from app.security.files import UnsafeFileError, check_upload
from app.security.rate_limit import enforce
from app.security.serving import file_response
from app.services.document_service import DocumentService
from app.services.entitlements_service import EntitlementsService
from app.services.job_service import IdempotencyKeyReusedError, JobService
from app.services.template_service import TemplateNotFoundError, TemplateService
from app.services.usage_service import usage_row
from app.audit import audit
from app.billing.units import BATCH, BATCH_JOBS, TRANSLATION
from app.billing.units import EXPORT as EXPORT_UNIT
from app.storage.base import AssetNotFoundError

router = APIRouter()
logger = logging.getLogger(__name__)


def get_job_service(user: CurrentUser, db: DbSession, storage: Storage) -> JobService:
    return JobService(db, user_id=user.id, storage=storage)


Jobs = Annotated[JobService, Depends(get_job_service)]

# Letters, digits and . _ : - ; up to 128 characters, so a UUID or any random token fits.
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_BAD_KEY = {
    "code": "invalid_idempotency_key",
    "message": "The Idempotency-Key must be 1 to 128 characters: letters, digits and . _ : -",
}


def idempotency_key(
    value: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Optional, 1-128 characters (letters, digits, . _ : -). The same key with the same request, "
            "from the same user, answers the job already made instead of making another; the same key with a "
            "different request is a 422. A key is remembered as long as its job is kept (JOB_RETENTION_DAYS).",
        ),
    ] = None,
) -> str | None:
    if value is not None and not _IDEMPOTENCY_KEY.fullmatch(value):
        raise HTTPException(status_code=422, detail=_BAD_KEY)
    return value


IdempotencyKey = Annotated[str | None, Depends(idempotency_key)]


def _key_reused() -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "idempotency_key_reused",
            "message": "This Idempotency-Key was already used for a different request. Use a new key for a new request.",
        },
    )


async def _replay(jobs: JobService, key: str | None, job_type: str, **job) -> JobOut | None:
    """The job this Idempotency-Key already made from this very request, if any. Routes ask
    before the plan and content checks: a repeat is not a new job, so it is answered with
    the first one whatever the plan allows now."""
    if key is None:
        return None
    try:
        found = await jobs.find_replay(key, job_type, **job)
    except IdempotencyKeyReusedError as exc:
        raise _key_reused() from exc
    return JobOut.of(found) if found is not None else None


async def _start(
    jobs: JobService, queue: Queue, plan: EntitlementsService, workspace_id: str, job_type: str, key: str | None, **job
) -> JobOut:
    await jobs.expire_old_exports()
    try:
        created, is_new = await jobs.create(job_type, idempotency_key=key, **job)
    except IdempotencyKeyReusedError as exc:  # a concurrent request made a job under this key from another request
        raise _key_reused() from exc
    if not is_new:  # a concurrent request with this key got there first: its job is the answer
        return JobOut.of(created)
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


@router.post("/import-text", response_model=JobOut, status_code=202, dependencies=[rate_limited("ai")])
async def import_text(
    payload: ImportTextJobRequest, jobs: Jobs, queue: Queue, workspace_id: WorkspaceId, plan: PlanChecks, key: IdempotencyKey
) -> JobOut:
    """Pasted text into a new document (structure analysis, AI for plain prose)."""
    job = {"payload": {"text": payload.text, "title": payload.title}}
    if (replay := await _replay(jobs, key, IMPORT_TEXT, **job)) is not None:
        return replay
    await plan.check_new_document(workspace_id)
    return await _start(jobs, queue, plan, workspace_id, IMPORT_TEXT, key, **job)


@router.post("/import-file", response_model=JobOut, status_code=202, dependencies=[rate_limited("upload")])
async def import_file(
    jobs: Jobs,
    queue: Queue,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
    key: IdempotencyKey,
    file: UploadFile = File(...),
    title: Annotated[str | None, Form()] = None,
    autolink: Annotated[bool, Form()] = False,
    pdf_mode: Annotated[Literal["editable", "layout"], Form()] = "editable",
) -> JobOut:
    """An uploaded .docx, .pdf or .txt into a new document. `autolink`: turn a Word
    file's web and e-mail addresses written as plain text into links (off: they stay
    text, as the file has them -- DOCX-026). `pdf_mode`: a PDF as an editable document,
    or layout-focused (P2E-007)."""
    filename = file.filename or ""
    check_document_file(filename)
    contents = await read_limited(file)
    return await _queue_import(
        jobs, queue, plan, workspace_id, key, filename=filename, title=title, autolink=autolink, pdf_mode=pdf_mode, contents=contents, declared_type=file.content_type
    )


async def _queue_import(
    jobs: JobService,
    queue: Queue,
    plan: EntitlementsService,
    workspace_id: str,
    key: str | None,
    *,
    filename: str,
    title: str | None,
    autolink: bool,
    pdf_mode: str,
    contents: bytes,
    declared_type: str | None,
) -> JobOut:
    """An uploaded file's import job -- the one path for a file sent whole and one sent in parts: an earlier job
    for the same Idempotency-Key and request, else the plan's checks, what the bytes really are, and the job."""
    job = {"payload": {"filename": filename, "title": title, "autolink": autolink, "pdf_mode": pdf_mode}, "input_bytes": contents}
    if (replay := await _replay(jobs, key, IMPORT_FILE, **job)) is not None:
        return replay
    await plan.check_new_document(workspace_id)
    await plan.check_file_size(workspace_id, len(contents))
    content_type = check_upload(extension_of(filename), contents, declared_type)
    return await _start(jobs, queue, plan, workspace_id, IMPORT_FILE, key, input_content_type=content_type, **job)


# -- A document file in parts (B-035A, jobs/uploads.py) ----------------------------------------------------------


def _upload_error(status: int, code: str, message: str, **details) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **details})


def _no_upload() -> HTTPException:
    # The same answer for an upload that doesn't exist and one that isn't the caller's.
    return _upload_error(404, "upload_not_found", "There is no such upload.")


async def _own_upload(storage: Storage, workspace_id: str, user_id: str, upload_id: str) -> uploads.UploadSession:
    session = await uploads.find(storage, workspace_id=workspace_id, user_id=user_id, upload_id=upload_id)
    if session is None:
        raise _no_upload()
    return session


async def _refuse_if_expired(storage: Storage, session: uploads.UploadSession) -> None:
    if session.expired(datetime.now(timezone.utc)):
        await uploads.discard(storage, session)
        raise _upload_error(410, "upload_expired", "This upload took too long and has expired. Please upload the file again.")


@router.post("/import-file/uploads", response_model=ChunkedUploadOut, status_code=201, dependencies=[rate_limited("upload")])
async def start_import_upload(
    payload: ChunkedUploadRequest, user: CurrentUser, storage: Storage, workspace_id: WorkspaceId, plan: PlanChecks
) -> ChunkedUploadOut:
    """A .docx, .pdf or .txt to import, too large for one request (B-035A): its name, size and SHA-256 now, its
    parts next (PUT .../parts/{index}), then POST .../complete makes the import job POST /jobs/import-file makes.
    What can be checked before the bytes arrive is checked now -- type by name, size against the server's cap and
    the plan, room for another document -- and all of it again, with the content, at completion."""
    check_document_file(payload.filename)
    max_mb = get_settings().largest_file_mb  # not MAX_UPLOAD_SIZE_MB: no request carries more than one part
    if payload.size > max_mb * 1024 * 1024:
        raise _upload_error(413, "too_large", f"File is larger than {max_mb}MB.", maxMb=max_mb)
    await plan.check_new_document(workspace_id)
    await plan.check_file_size(workspace_id, payload.size)
    try:  # this workspace's old uploads first, then anyone's, a few at a time: on Vercel nothing else sweeps them
        await uploads.sweep(storage, prefix=f"{uploads.PREFIX}{workspace_id}/")
        await uploads.sweep(storage, limit=uploads.SWEEP_BATCH)
    except Exception:  # noqa: BLE001 -- tidying, never a reason to refuse an upload
        logger.warning("Could not sweep old uploads")
    try:
        holding = await uploads.open_uploads(storage, workspace_id)
    except NotImplementedError:
        holding = 0
    if holding >= uploads.MAX_OPEN_UPLOADS:
        raise _upload_error(
            429, "too_many_uploads", "Too many uploads are still unfinished. Finish or wait for them (an hour at most), then try again.", limit=uploads.MAX_OPEN_UPLOADS
        )
    session = await uploads.start(
        storage,
        workspace_id=workspace_id,
        user_id=user.id,
        filename=payload.filename,
        size=payload.size,
        sha256=payload.sha256,
        content_type=payload.contentType,
        title=payload.title,
        autolink=payload.autolink,
        pdf_mode=payload.pdfMode,
    )
    expires = datetime.fromisoformat(session.created_at) + uploads.SESSION_TTL
    return ChunkedUploadOut(uploadId=session.id, chunkSize=session.chunk_size, chunks=session.chunks, expiresAt=expires)


@router.put("/import-file/uploads/{upload_id}/parts/{index}", response_model=ChunkReceived)
async def put_import_upload_part(
    upload_id: str,
    index: int,
    request: Request,
    user: CurrentUser,
    storage: Storage,
    workspace_id: WorkspaceId,
    sha256: Annotated[str | None, Query(pattern=r"^[0-9a-fA-F]{64}$", description="The part's SHA-256 (hex), checked against its bytes.")] = None,
) -> ChunkReceived:
    """One part, as raw bytes: exactly the size the upload expects for its number (`chunkSize`, the last one what
    is left). Sending a part again overwrites it; parts may come in any order. `sha256`, if given, is checked
    against the bytes (a query parameter, not a header: the API's CORS policy allows only the headers it lists)."""
    session = await _own_upload(storage, workspace_id, user.id, upload_id)
    if session.job_id:
        raise _upload_error(409, "upload_finished", "This upload has already been imported.")
    await _refuse_if_expired(storage, session)
    if not 0 <= index < session.chunks:
        raise _upload_error(400, "chunk_out_of_range", f"This upload has parts 0 to {session.chunks - 1}.")
    expected = session.part_size(index)
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > expected:
        raise _upload_error(413, "too_large", f"Part {index} must be {expected} bytes.")
    data = await request.body()
    if len(data) != expected:
        raise _upload_error(400, "chunk_size", f"Part {index} must be {expected} bytes, not {len(data)}.")
    if sha256 is not None and hashlib.sha256(data).hexdigest() != sha256.lower():
        raise _upload_error(400, "chunk_corrupt", f"Part {index} arrived damaged. Please send it again.")
    await uploads.put_part(storage, session, index, data)
    return ChunkReceived(index=index, size=len(data))


@router.post("/import-file/uploads/{upload_id}/complete", response_model=JobOut, status_code=202, dependencies=[rate_limited("upload")])
async def complete_import_upload(
    upload_id: str,
    user: CurrentUser,
    storage: Storage,
    jobs: Jobs,
    queue: Queue,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
    key: IdempotencyKey,
) -> JobOut:
    """The parts put together, checked against the size and SHA-256 the upload started with, and imported as a
    file sent whole is (_queue_import). At most one job: completing again -- a retry, or two at once -- answers
    the same job (the upload's own Idempotency-Key unless the request brings one)."""
    session = await _own_upload(storage, workspace_id, user.id, upload_id)
    if session.job_id and (done := await jobs.get(session.job_id)) is not None:
        return JobOut.of(done)
    await _refuse_if_expired(storage, session)
    try:
        contents = await uploads.assemble(storage, session)
    except uploads.UploadIncomplete as exc:
        raise _upload_error(409, "upload_incomplete", f"{len(exc.missing)} part(s) of the file haven't arrived yet.", missing=exc.missing) from exc
    except uploads.UploadMismatch as exc:
        await uploads.discard(storage, session)
        raise _upload_error(422, "upload_mismatch", "The parts put together aren't the file that was started. Please upload it again.") from exc
    try:
        job = await _queue_import(
            jobs,
            queue,
            plan,
            workspace_id,
            key or f"upload-{session.id}",
            filename=session.filename,
            title=session.title,
            autolink=session.autolink,
            pdf_mode=session.pdf_mode,
            contents=contents,
            declared_type=session.content_type,
        )
    except UnsafeFileError:
        await uploads.discard(storage, session)  # not a document this app opens: nothing of it is kept
        raise
    try:
        await uploads.finished(storage, session, job.id)
    except Exception:  # noqa: BLE001 -- the job exists; a retry finds it by its key, the sweep takes the parts
        logger.warning("Could not record upload %s as job %s", session.id, job.id)
    return job


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
    key: IdempotencyKey,
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
    payload = {
        "templateId": templateId,
        "instructionsText": instructions,
        "resolutions": [item.model_dump(mode="json") for item in parsed] if parsed is not None else None,
        "expectedRevision": if_match_number(request),
    }
    if (replay := await _replay(jobs, key, FORMAT, document_id=documentId, payload=payload)) is not None:
        return replay
    if instructions.strip():
        await enforce("ai", f"user:{user.id}")
        await plan.check_ai(workspace_id)
    return await _start(jobs, queue, plan, workspace_id, FORMAT, key, document_id=documentId, payload=payload)


@router.post("/translate-document", response_model=JobOut, status_code=202, dependencies=[rate_limited("ai")])
async def translate_document(
    payload: TranslateDocumentJobRequest,
    user: CurrentUser,
    db: DbSession,
    storage: Storage,
    jobs: Jobs,
    queue: Queue,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
    key: IdempotencyKey,
) -> JobOut:
    """A translated version of a document (TRAN-006): a new document linked to the original,
    which is never changed. Its translation characters are counted when it runs."""
    await _check_document(user, db, storage, payload.documentId)
    job = {"document_id": payload.documentId, "payload": payload.model_dump(exclude={"documentId"})}
    if (replay := await _replay(jobs, key, TRANSLATE, **job)) is not None:
        return replay
    await plan.check_new_document(workspace_id)
    return await _start(jobs, queue, plan, workspace_id, TRANSLATE, key, **job)


@router.post("/export", response_model=JobOut, status_code=202, dependencies=[rate_limited("export")])
async def export_document(
    payload: ExportJobRequest,
    user: CurrentUser,
    db: DbSession,
    storage: Storage,
    jobs: Jobs,
    queue: Queue,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
    key: IdempotencyKey,
) -> JobOut:
    """A DOCX or PDF rendered in the background; download it from /api/jobs/{id}/file."""
    await _check_document(user, db, storage, payload.documentId)
    job = {"document_id": payload.documentId, "payload": payload.model_dump(exclude={"documentId"})}
    if (replay := await _replay(jobs, key, EXPORT, **job)) is not None:
        return replay
    await plan.check_export(workspace_id, payload.format)
    return await _start(jobs, queue, plan, workspace_id, EXPORT, key, **job)


@router.post("/batch-export", response_model=JobOut, status_code=202, dependencies=[rate_limited("export")])
async def batch_export(
    payload: BatchExportRequest,
    user: CurrentUser,
    db: DbSession,
    storage: Storage,
    jobs: Jobs,
    queue: Queue,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
) -> JobOut:
    """Many documents exported into one ZIP (FEAT-002, brief §61): one export job building each
    document's file as a single export does, downloaded from /api/jobs/{id}/file like any export;
    its result names each part and whether its words all came through. Every document is checked
    first (404); it takes one export of the month per document (maxExports) and counts once as a
    batch job (maxBatchJobs)."""
    document_ids = list(dict.fromkeys(payload.documentIds))
    for document_id in document_ids:
        await _check_document(user, db, storage, document_id)
    await plan.check_export(workspace_id, payload.format)
    await plan.check_monthly(workspace_id, BATCH, 1, hold=True)
    await plan.check_monthly(workspace_id, EXPORT_UNIT, len(document_ids))
    db.add(usage_row(workspace_id, BATCH_JOBS))
    # Its job belongs to the first document: an export file whose job has no document is taken
    # for one whose document is gone and swept (jobs/files.py).
    job = {"document_id": document_ids[0], "payload": {**payload.model_dump(exclude={"documentIds"}), "documentIds": document_ids}}
    started = await _start(jobs, queue, plan, workspace_id, EXPORT, None, **job)
    audit("batch.export", user_id=user.id, job_id=started.id, documents=len(document_ids), format=payload.format)
    return started


@router.post("/extract-reference", response_model=JobOut, status_code=202, dependencies=[rate_limited("upload")])
async def extract_reference(
    jobs: Jobs, queue: Queue, workspace_id: WorkspaceId, plan: PlanChecks, key: IdempotencyKey, file: UploadFile = File(...)
) -> JobOut:
    """Format by Example: the style a reference .docx uses (its result is what
    POST /api/templates/extract answers)."""
    filename = file.filename or ""
    if extension_of(filename) != "docx":
        raise HTTPException(status_code=400, detail="The reference document has to be a Word file (.docx).")
    contents = await read_limited(file)
    job = {"payload": {"filename": filename}, "input_bytes": contents}
    if (replay := await _replay(jobs, key, EXTRACT_REFERENCE, **job)) is not None:
        return replay
    await plan.check_file_size(workspace_id, len(contents))
    check_content(file, contents)
    return await _start(jobs, queue, plan, workspace_id, EXTRACT_REFERENCE, key, **job)


@router.post("/batch-format", response_model=BatchOut, status_code=202, dependencies=[rate_limited("upload")])
async def batch_format(
    payload: BatchFormatRequest,
    user: CurrentUser,
    db: DbSession,
    storage: Storage,
    jobs: Jobs,
    queue: Queue,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
) -> BatchOut:
    """One template over many documents (FEAT-001, brief §61): a format job for each, as
    POST /jobs/format makes one, answered at once with the batch; GET /jobs/batches/{id} follows
    it. A template only -- no AI instructions, so a batch costs no AI operations; a reference
    document's look is a template first (Format by Example, "Save as template"). Every document
    and the template are checked before anything is queued (404), and the batch counts once
    against the plan's batch jobs a month (maxBatchJobs). A document the template's rules
    conflict with waits for its own resolution; the others are formatted."""
    document_ids = list(dict.fromkeys(payload.documentIds))
    for document_id in document_ids:
        await _check_document(user, db, storage, document_id)
    try:
        await TemplateService(db, user_id=user.id).get(payload.templateId)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Template not found") from exc
    await plan.check_monthly(workspace_id, BATCH, 1, hold=True)
    db.add(usage_row(workspace_id, BATCH_JOBS))
    batch_id = str(uuid4())
    started = []
    for index, document_id in enumerate(document_ids):
        job = {"templateId": payload.templateId, "instructionsText": "", "resolutions": None, "expectedRevision": None, "batchId": batch_id, "batchIndex": index}
        started.append(await _start(jobs, queue, plan, workspace_id, FORMAT, None, document_id=document_id, payload=job))
    audit("batch.format", user_id=user.id, batch_id=batch_id, documents=len(document_ids), template_id=payload.templateId)
    return BatchOut.of(batch_id, [JobOut.of(job) for job in await jobs.batch(batch_id)] or started)


@router.post("/batch-translate", response_model=BatchOut, status_code=202, dependencies=[rate_limited("ai")])
async def batch_translate(
    payload: BatchTranslateRequest,
    user: CurrentUser,
    db: DbSession,
    storage: Storage,
    jobs: Jobs,
    queue: Queue,
    workspace_id: WorkspaceId,
    plan: PlanChecks,
) -> BatchOut:
    """Many documents translated into one language (FEAT-003, brief §61): a translation job for
    each, as POST /jobs/translate-document makes one -- a new document, linked to its original,
    which is never changed -- answered at once with the batch; GET /jobs/batches/{id} follows it.
    Checked before anything is queued: every document (404), a batch of the plan's batch jobs a
    month, room for a new document each, and the characters they would send against the month's
    translation allowance (each job still holds its own as it runs)."""
    from app.translation.service import collect

    document_ids = list(dict.fromkeys(payload.documentIds))
    service = DocumentService(db, user_id=user.id, storage=storage)
    characters = 0
    for document_id in document_ids:
        document = await service.get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        characters += collect(document.elements).characters
    await plan.check_monthly(workspace_id, BATCH, 1, hold=True)
    await plan.check_new_document(workspace_id, count=len(document_ids))
    if characters:
        await plan.check_monthly(workspace_id, TRANSLATION, characters)
    db.add(usage_row(workspace_id, BATCH_JOBS))
    batch_id = str(uuid4())
    started = []
    for index, document_id in enumerate(document_ids):
        job = {"targetLanguage": payload.targetLanguage, "sourceLanguage": payload.sourceLanguage, "batchId": batch_id, "batchIndex": index}
        started.append(await _start(jobs, queue, plan, workspace_id, TRANSLATE, None, document_id=document_id, payload=job))
    audit("batch.translate", user_id=user.id, batch_id=batch_id, documents=len(document_ids), target=payload.targetLanguage)
    return BatchOut.of(batch_id, [JobOut.of(job) for job in await jobs.batch(batch_id)] or started)


@router.get("/batches/{batch_id}", response_model=BatchOut)
async def get_batch(batch_id: str, jobs: Jobs) -> BatchOut:
    """A batch's jobs and how far they have got (FEAT-001)."""
    found = await jobs.batch(batch_id)
    if not found:
        raise HTTPException(status_code=404, detail="Batch not found")
    return BatchOut.of(batch_id, [JobOut.of(job) for job in found])


@router.get("", response_model=list[JobOut])
async def list_jobs(
    jobs: Jobs,
    type: JobType | None = None,
    status: Literal["pending", "running", "succeeded", "failed", "cancelled"] | None = None,
    dead_letter: Annotated[bool | None, Query(description="true: only the jobs that failed after their last attempt")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[JobOut]:
    """The user's latest jobs, newest first -- e.g. the dashboard's recent exports
    (type=export, status=succeeded), or what gave up (dead_letter=true)."""
    found = await jobs.recent(job_type=type.value if type else None, status=status, limit=limit, dead_letter=dead_letter)
    return [JobOut.of(job) for job in found]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, jobs: Jobs) -> JobOut:
    job = await jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut.of(job)


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: str, jobs: Jobs) -> JobOut:
    """Stops a job. One that hasn't started never will; a running one stops at its next
    check (a stage boundary) without writing a result. Cancelling a job that is already
    cancelled, succeeded or failed changes nothing and answers its state (200), so a
    retried or late cancel is harmless: compare `status` to see if it took."""
    job = await jobs.cancel(job_id)
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
    return file_response(content, result["contentType"], filename=result["filename"])
