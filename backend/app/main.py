import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import assets, auth, documents, jobs, templates
from app.api.errors import (
    REQUEST_ID_HEADER,
    current_request_id,
    error_response,
    install_error_handlers,
    request_id_for,
    unexpected_error,
)
from app.config import get_settings
from app.db.session import get_session_factory
from app.jobs.queue import fail_interrupted_jobs, sweep_forever
from app.storage.factory import get_storage_provider
from app.services.document_service import RevisionConflictError
from app.services.template_service import (
    SourceDocumentNotFoundError,
    TemplateNotFoundError,
    TemplateNotSharedError,
    TemplateReadOnlyError,
    TemplateVersionConflictError,
)

settings = get_settings()
_allowed_origins = settings.cors_origins.split(",")
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Jobs run in this process die with it; ones a restart cut off are failed,
    # so nobody polls them forever, and this process also tidies up job files
    # (an arq worker keeps its own queue and runs the sweep itself).
    sweep = None
    if settings.job_backend == "background":
        try:
            if interrupted := await fail_interrupted_jobs(get_session_factory(), get_storage_provider()):
                logger.warning("Marked %d interrupted background job(s) as failed", interrupted)
        except Exception:  # noqa: BLE001 -- the API must start even when the database is briefly away
            logger.exception("Could not check for interrupted background jobs")
        sweep = asyncio.create_task(sweep_forever(get_session_factory(), get_storage_provider()))
    yield
    if sweep is not None:
        sweep.cancel()


app = FastAPI(title="SmartDoc Formatter API", version="0.1.0", lifespan=lifespan)
install_error_handlers(app)


@app.exception_handler(RevisionConflictError)
async def revision_conflict(request: Request, exc: RevisionConflictError) -> JSONResponse:
    # 412 Precondition Failed: the If-Match revision (or the row version loaded
    # for this request) no longer matches -- nothing was written.
    return error_response(412, str(exc), code="revision_conflict", details={"currentRevision": exc.current_revision})


@app.exception_handler(TemplateVersionConflictError)
async def template_version_conflict(request: Request, exc: TemplateVersionConflictError) -> JSONResponse:
    return error_response(412, str(exc), code="template_version_conflict", details={"currentVersion": exc.current_version})


_TEMPLATE_ERRORS = {
    TemplateNotFoundError: (404, "template_not_found", "Template not found"),
    SourceDocumentNotFoundError: (404, "document_not_found", "Document not found"),
    TemplateReadOnlyError: (403, "template_read_only", None),
    TemplateNotSharedError: (409, "template_not_shared", None),
}


async def _template_error(request: Request, exc: Exception) -> JSONResponse:
    # Not-found messages are fixed, so they never echo which ids exist.
    status, code, fixed_message = _TEMPLATE_ERRORS[type(exc)]
    return error_response(status, fixed_message or str(exc), code=code)


for _error in _TEMPLATE_ERRORS:
    app.add_exception_handler(_error, _template_error)


@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    # CSRF defense in depth on top of SameSite=Lax cookies: a browser always sends
    # Origin on cross-origin writes, so a foreign one is refused outright.
    # Requests without Origin (curl, tests) can't carry a victim's cookies anyway.
    origin = request.headers.get("origin")
    if request.method in _UNSAFE_METHODS and origin is not None and origin not in _allowed_origins:
        return error_response(403, "Cross-origin request rejected.", code="cross_site_request")
    return await call_next(request)


@app.middleware("http")
async def request_context(request: Request, call_next):
    # Inside CORS (added below), so even a 500 reaches the browser readable.
    request_id = request_id_for(request)
    token = current_request_id.set(request_id)
    try:
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 -- logged with the request id; the caller gets the plain 500 body
            response = await unexpected_error(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    finally:
        current_request_id.reset(token)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
    expose_headers=[REQUEST_ID_HEADER],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(assets.router, prefix="/api/assets", tags=["assets"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(templates.router, prefix="/api/templates", tags=["templates"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
