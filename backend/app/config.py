import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_RATE = re.compile(r"^\s*\d+\s*/\s*(second|minute|hour|day)s?\s*$")


class Settings(BaseSettings):
    # Anchored to backend/, not the working directory: a server started from the
    # repo root would otherwise silently skip backend/.env (and its DATABASE_URL).
    model_config = SettingsConfigDict(env_file=_BACKEND_DIR / ".env", extra="ignore")

    ai_provider: str = "anthropic"
    # Secrets are SecretStr: printing or logging the settings shows "**********".
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-5"
    # How long one AI call may take before it counts as failed (the task then falls back).
    ai_timeout_seconds: float = Field(default=180, gt=0)
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
    s3_secret_access_key: SecretStr = SecretStr("")
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
    # Where background jobs run (app/jobs): "background" in this process
    # (development; a restart fails the ones running), "arq" in an arq worker via
    # Redis (production: `arq app.worker.WorkerSettings`), "eager" inside the
    # request (tests).
    job_backend: str = "background"
    redis_url: str = ""
    # How long a finished export stays downloadable, and a job's row is kept.
    job_file_ttl_hours: int = Field(default=24, ge=1)
    job_retention_days: int = Field(default=7, ge=1)
    # Billing (app/billing, services/billing_service.py). Stripe is optional: without
    # a secret key every workspace stays on its plan (free unless set otherwise)
    # and the billing page says upgrades aren't available yet.
    stripe_secret_key: SecretStr = SecretStr("")
    stripe_webhook_secret: SecretStr = SecretStr("")
    # The Stripe price id of each paid plan in billing/plans.json (stripe_price_<plan key>).
    stripe_price_pro: str = ""
    stripe_price_business: str = ""
    # Where Stripe sends the user back to after checkout or the billing portal.
    frontend_url: str = "http://localhost:3000"
    # The largest request body the API reads at all (uploads, a document's
    # content with pasted images); refused with 413 before it is taken in.
    max_request_size_mb: int = Field(default=25, ge=1)
    # Logs (app/logging_setup.py): the app's level, "text" or "json" lines, and
    # one line per request with its status and duration (production: on, and
    # uvicorn's own access log off).
    log_level: str = "INFO"
    log_format: str = "text"
    log_requests: bool = False
    # Strict-Transport-Security on every response, in seconds; 0 = off. Only
    # for a deployment served over HTTPS alone (browsers then refuse plain HTTP).
    hsts_seconds: int = Field(default=0, ge=0)
    # Rate limits (app/security/rate_limit.py) as "<count>/<second|minute|hour|day>";
    # empty turns one off. "redis" shares the counters between API processes (REDIS_URL).
    rate_limit_backend: str = "memory"
    rate_limit_global: str = "600/minute"  # every API request, per session (or address when signed out)
    rate_limit_login: str = "20/minute"  # per address
    rate_limit_login_account: str = "10/minute"  # per email address signed in to
    rate_limit_register: str = "10/hour"  # per address
    rate_limit_ai: str = "20/minute"  # per user: work that uses the AI
    rate_limit_upload: str = "20/minute"  # per user
    rate_limit_export: str = "30/minute"  # per user

    @field_validator(
        "rate_limit_global",
        "rate_limit_login",
        "rate_limit_login_account",
        "rate_limit_register",
        "rate_limit_ai",
        "rate_limit_upload",
        "rate_limit_export",
    )
    @classmethod
    def _rate_limit_shape(cls, value: str) -> str:
        if value.strip() and not _RATE.match(value):
            raise ValueError(f"A rate limit looks like '20/minute' (or is empty for none), not {value!r}")
        return value

    @field_validator("cors_origins")
    @classmethod
    def _explicit_origins(cls, value: str) -> str:
        # Session cookies go with every cross-origin call, so only named origins
        # may make them: "*" would let any site act as the signed-in user.
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if not origins or "*" in origins:
            raise ValueError("CORS_ORIGINS must list the frontend's origins, e.g. https://app.example.com; '*' isn't allowed")
        return ",".join(origins)

    @model_validator(mode="after")
    def _request_fits_an_upload(self) -> "Settings":
        if self.max_request_size_mb <= self.max_upload_size_mb:
            raise ValueError("MAX_REQUEST_SIZE_MB must be larger than MAX_UPLOAD_SIZE_MB, or no upload would get through")
        return self

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
