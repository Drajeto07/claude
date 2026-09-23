from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import documents, templates
from app.config import get_settings

settings = get_settings()

app = FastAPI(title="SmartDoc Formatter API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(templates.router, prefix="/api/templates", tags=["templates"])


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
