from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import assets, auth, documents, templates
from app.config import get_settings
from app.services.document_service import RevisionConflictError

settings = get_settings()
_allowed_origins = settings.cors_origins.split(",")
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

app = FastAPI(title="SmartDoc Formatter API", version="0.1.0")


@app.exception_handler(RevisionConflictError)
async def revision_conflict(request: Request, exc: RevisionConflictError) -> JSONResponse:
    # 412 Precondition Failed: the If-Match revision (or the row version loaded
    # for this request) no longer matches -- nothing was written.
    return JSONResponse(status_code=412, content={"detail": str(exc), "currentRevision": exc.current_revision})


@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    # CSRF defense in depth on top of SameSite=Lax cookies: a browser always sends
    # Origin on cross-origin writes, so a foreign one is refused outright.
    # Requests without Origin (curl, tests) can't carry a victim's cookies anyway.
    origin = request.headers.get("origin")
    if request.method in _UNSAFE_METHODS and origin is not None and origin not in _allowed_origins:
        return JSONResponse({"detail": "Cross-origin request rejected."}, status_code=403)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(assets.router, prefix="/api/assets", tags=["assets"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(templates.router, prefix="/api/templates", tags=["templates"])


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
