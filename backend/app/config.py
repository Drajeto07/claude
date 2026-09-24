from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Anchored to backend/, not the working directory: a server started from the
    # repo root would otherwise silently skip backend/.env (and its DATABASE_URL).
    model_config = SettingsConfigDict(env_file=_BACKEND_DIR / ".env", extra="ignore")

    ai_provider: str = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    cors_origins: str = "http://localhost:3000"
    max_upload_size_mb: int = 10
    ai_structure_max_retries: int = 1
    # Deliberately a real (if unreachable-until-configured) Postgres URL, not
    # a SQLite fallback -- корекции.docx §5 mandates Postgres for real usage,
    # so the *default* must fail loudly rather than silently run production
    # on SQLite because DATABASE_URL was never set. Tests override this via
    # their own fixture-constructed engine (see tests/conftest.py), never by
    # relying on this default.
    database_url: str = "postgresql+asyncpg://smartdoc:smartdoc@localhost:5432/smartdoc"
    storage_backend: str = "local"
    local_storage_dir: str = str(_BACKEND_DIR / "data" / "assets")
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    session_ttl_days: int = 30
    # Browsers accept Secure cookies from http://localhost, so this can stay on in dev.
    session_cookie_secure: bool = True
    # Undo steps kept per document; older ones are dropped (корекции.docx §14).
    document_history_max_steps: int = Field(default=50, ge=2)
    # Saved versions kept per template.
    template_history_max_versions: int = Field(default=50, ge=1)
    # Extra folders with .ttf fonts for PDF export (os.pathsep-separated), searched
    # before the system font folders. See app/export/fonts.py.
    pdf_font_dirs: str = ""

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        # Accepts a URI pasted straight from Supabase's dashboard (postgres:// or
        # postgresql://, which would otherwise load the absent sync psycopg2 driver).
        url = make_url(value)
        if url.get_backend_name() not in ("postgres", "postgresql"):
            return value
        url = url.set(drivername="postgresql+asyncpg")
        if url.host not in _LOOPBACK_HOSTS and "ssl" not in url.query:
            url = url.update_query_dict({"ssl": "require"})
        return url.render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
