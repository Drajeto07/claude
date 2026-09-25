import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import assets, auth, billing, documents, jobs, templates, usage
from app.api.deps import SESSION_COOKIE, client_address
from app.api.errors import (
    REQUEST_ID_HEADER,
    current_request_id,
    error_response,
    install_error_handlers,
    request_id_for,
    unexpected_error,
)
from app.audit import audit
from app.billing.errors import BillingError
from app.config import get_settings
from app.db.session import get_session_factory
from app.jobs.queue import fail_interrupted_jobs, sweep_forever
from app.logging_setup import configure_logging
from app.security.files import MB, UnsafeFileError
from app.security.http import RequestSizeLimit, secure_headers
from app.security.rate_limit import RateLimitedError, enforce, hashed
from app.storage.factory import get_storage_provider
from app.services.document_service import RevisionConflictError
from app.services.entitlements_service import PlanLimitError
from app.services.template_service import (
    SourceDocumentNotFoundError,
    TemplateNotFoundError,
    TemplateNotSharedError,
    TemplateReadOnlyError,
    TemplateVersionConflictError,
)

settings = get_settings()
configure_logging(settings.log_level, settings.log_format)
_allowed_origins = settings.cors_origins.split(",")
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Outside every client's overall allowance: the health check, and Stripe's webhooks.
_UNLIMITED_PATHS = {"/api/health", "/api/billing/webhook"}

logger = logging.getLogger(__name__)
request_logger = logging.getLogger("app.request")


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


@app.exception_handler(PlanLimitError)
async def plan_limit(request: Request, exc: PlanLimitError) -> JSONResponse:
    # 402 Payment Required: the plan doesn't allow it; the message says how to go on.
    audit("limit.plan_refused", entitlement=exc.entitlement, limit=exc.limit, used=exc.used, path=request.url.path)
    return error_response(402, str(exc), code="plan_limit", details={"entitlement": exc.entitlement, "limit": exc.limit, "used": exc.used})


def _rate_limited(request: Request, exc: RateLimitedError) -> JSONResponse:
    audit("limit.rate_refused", scope=exc.scope, ip=client_address(request), path=request.url.path)
    return error_response(
        429, str(exc), code="rate_limited", details={"retryAfter": exc.retry_after}, headers={"Retry-After": str(exc.retry_after)}
    )


@app.exception_handler(RateLimitedError)
async def rate_limited(request: Request, exc: RateLimitedError) -> JSONResponse:
    return _rate_limited(request, exc)


@app.exception_handler(BillingError)
async def billing_error(request: Request, exc: BillingError) -> JSONResponse:
    return error_response(exc.status, str(exc), code=exc.code)


@app.exception_handler(UnsafeFileError)
async def invalid_file(request: Request, exc: UnsafeFileError) -> JSONResponse:
    # The file's bytes aren't what its name says, or it would unpack unsafely.
    audit("file.refused", reason=str(exc), ip=client_address(request), path=request.url.path)
    return error_response(400, str(exc), code="invalid_file")


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


# Middleware runs outside-in in the reverse of the order it is added here: CORS,
# then the request id (with the security headers), the overall rate limit, the
# cross-site check, and innermost the body-size cap -- so every refusal below
# CORS reaches the browser readable and carries its request id.
app.add_middleware(RequestSizeLimit, max_bytes=settings.max_request_size_mb * MB)


@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    # CSRF defense in depth on top of SameSite=Lax cookies: a browser always sends
    # Origin on cross-origin writes, so a foreign one is refused outright.
    # Requests without Origin (curl, tests) can't carry a victim's cookies anyway.
    origin = request.headers.get("origin")
    if request.method in _UNSAFE_METHODS and origin is not None and origin not in _allowed_origins:
        audit("request.cross_site_refused", origin=origin, path=request.url.path)
        return error_response(403, "Cross-origin request rejected.", code="cross_site_request")
    return await call_next(request)


@app.middleware("http")
async def limit_request_rate(request: Request, call_next):
    # Every client's overall allowance (security/rate_limit.py): per session when
    # signed in, per address otherwise. The per-action limits are on the routes.
    path = request.url.path
    if path.startswith("/api/") and path not in _UNLIMITED_PATHS:
        session = request.cookies.get(SESSION_COOKIE)
        try:
            await enforce("global", f"session:{hashed(session)}" if session else f"ip:{client_address(request)}")
        except RateLimitedError as exc:
            return _rate_limited(request, exc)
    return await call_next(request)


@app.middleware("http")
async def request_context(request: Request, call_next):
    # Inside CORS (added below), so even a 500 reaches the browser readable.
    request_id = request_id_for(request)
    token = current_request_id.set(request_id)
    started = time.perf_counter()
    try:
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 -- logged with the request id; the caller gets the plain 500 body
            response = await unexpected_error(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        for name, value in secure_headers(request.url.path, settings.hsts_seconds).items():
            response.headers.setdefault(name, value)
        if settings.log_requests:
            # The path only: a query string can hold what the user searched for.
            request_logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                },
            )
        return response
    finally:
        current_request_id.reset(token)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    # What the app sends; a preflight asking for anything else is refused.
    allow_headers=["Content-Type", "If-Match", REQUEST_ID_HEADER],
    expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
    max_age=600,
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(assets.router, prefix="/api/assets", tags=["assets"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(templates.router, prefix="/api/templates", tags=["templates"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(usage.router, prefix="/api/usage", tags=["usage"])
app.include_router(billing.router, prefix="/api/billing", tags=["billing"])


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
