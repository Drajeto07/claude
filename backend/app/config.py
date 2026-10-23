import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_RATE = re.compile(r"^\s*\d+\s*/\s*(second|minute|hour|day)s?\s*$")


# D-012: Vercel Preview deployments of these branches must prove their isolation whatever their own settings say.
# Vercel itself sets VERCEL_ENV and VERCEL_GIT_COMMIT_REF on every deployment (the project exposes them at runtime),
# so a forgotten or deleted SMARTDOC_ENVIRONMENT can't switch the guard off for the 2.0 Preview.
PINNED_PREVIEW_BRANCHES = frozenset({"feature/smartdoc-2.0"})


def pinned_preview(environ=None) -> bool:
    """Whether this process is a Vercel Preview of a pinned branch (by Vercel's own variables, not the project's)."""
    environ = os.environ if environ is None else environ
    return environ.get("VERCEL_ENV") == "preview" and environ.get("VERCEL_GIT_COMMIT_REF", "") in PINNED_PREVIEW_BRANCHES


def _connection_parts(database_url: str) -> list[str]:
    """Where a database URL connects, lower-cased: host, port, user, database -- never the password."""
    try:
        url = make_url(database_url)
    except Exception:  # noqa: BLE001 -- an unreadable URL is compared as text, whole
        return [database_url.lower()]
    return [str(part or "").lower() for part in (url.host, url.port, url.username, url.database)]


class Settings(BaseSettings):
    # Anchored to backend/, not the working directory: a server started from the
    # repo root would otherwise silently skip backend/.env (and its DATABASE_URL).
    # hide_input_in_errors: a refused setting never prints the others -- DATABASE_URL holds the password, and a
    # start-up error lands in the host's logs (D-012).
    model_config = SettingsConfigDict(env_file=_BACKEND_DIR / ".env", extra="ignore", hide_input_in_errors=True)

    ai_provider: str = "anthropic"
    # The OCR engine scanned PDF pages are read with (app/ocr, P2E-006); "none" reads none.
    ocr_provider: str = "none"
    # Who translates (app/translation/providers.py): "ai", or "pseudo" (no AI: tests, demos).
    translation_provider: str = "ai"
    # Secrets are SecretStr: printing or logging the settings shows "**********".
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-5"
    # How long one AI call may take before it counts as failed (the task then falls back).
    ai_timeout_seconds: float = Field(default=180, gt=0)
    cors_origins: str = "http://localhost:3000"
    # The largest file one request may carry (on Vercel 4: its requests stop at 4.5 MB, Dockerfile.vercel).
    max_upload_size_mb: int = 10
    # The largest document file imported in parts (B-035A, POST /jobs/import-file/uploads): no request then carries
    # more than one 3 MiB part, so it isn't bound by MAX_UPLOAD_SIZE_MB. What a plan may allow (largest_file_mb).
    max_chunked_upload_size_mb: int = Field(default=10, ge=1)
    # How the API holds its database connections (RELEASE): "session" -- a pool of its own, for a
    # direct connection or Supabase's session pooler; "transaction" -- Supabase's transaction pooler
    # (Supavisor, port 6543) on a serverless host: no pool of its own (the pooler is the pool) and no
    # prepared statements kept across transactions, which that pooler can't route.
    database_pooler: Literal["session", "transaction"] = "session"
    # Retries of one AI task after a failed answer; bounded, as a misconfigured value
    # would otherwise multiply every call (AI-008).
    ai_structure_max_retries: int = Field(default=1, ge=0, le=3)
    # The AI one job (an import, a formatting run) or one request may use: calls,
    # and seconds from its first call to its last (app/ai/budget.py).
    ai_calls_per_job: int = Field(default=50, ge=1, le=500)
    ai_seconds_per_job: float = Field(default=900, gt=0, le=3600)
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
    # Which deployment this is ("preview-2.0", ...); empty for production and local runs. A preview must name
    # PRODUCTION_DB_REF (the production Supabase project's ref -- not a secret) and the instance ids its own
    # database and bucket carry (random ids from scripts/preview_identity.py -- not secrets either). It refuses to
    # start when its URLs mention production, and refuses every request until the connected database and bucket
    # prove they are its own (app/isolation.py; docs/SMARTDOC_2_0_PREVIEW_ISOLATION_PLAN.md, D-012).
    smartdoc_environment: str = ""
    # Document Doctor v0 (prototype; the editor shows it only with ?doctor=1): false turns its routes off.
    doctor_enabled: bool = True
    production_db_ref: str = ""
    expected_db_instance: str = ""
    expected_storage_instance: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: SecretStr = SecretStr("")
    session_ttl_days: int = 30
    # Browsers accept Secure cookies from http://localhost, so this can stay on in dev.
    session_cookie_secure: bool = True
    # What an account leaves behind, deleted hourly by the job sweep (services/account_cleanup.py):
    # a session this many days after it expired or was signed out (ACCT-006), kept a while
    # so a recent sign-out can still be looked into; an account token (a reset or
    # confirmation link) this many days after it was used or expired; and a browser the
    # account hasn't signed in from for this many days (ACCT-007), the device cookie's
    # own lifetime, after which a sign-in from it is e-mailed as from a new one.
    session_retention_days: int = Field(default=30, ge=1)
    account_token_retention_days: int = Field(default=7, ge=1)
    known_browser_retention_days: int = Field(default=400, ge=1)
    # Signing in with a wrong password (ACCT-007): after this many failures for one
    # account within the window, each next try for it waits 1 s, then 2 s, 4 s ... at
    # most the cap, before the password is checked. Not a lockout: the right password
    # still gets in, only later (app/security/sign_in_delay.py).
    sign_in_free_failures: int = Field(default=3, ge=1)
    sign_in_failure_window_minutes: int = Field(default=15, ge=1)
    sign_in_max_delay_seconds: float = Field(default=8.0, ge=0, le=30)
    # Undo steps kept per document; older ones are dropped (корекции.docx §14).
    document_history_max_steps: int = Field(default=50, ge=2)
    # And the bytes (compressed) a document's undo history may take before its oldest
    # steps go too; the original, the current step and the one below it always stay
    # (services/version_history.py, PERF-004).
    document_history_max_bytes: int = Field(default=10 * 1024 * 1024, ge=0)
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
    # How long the Word file kept as a document's original (for Word exports) stays,
    # counted from when it was stored. 0 = as long as its document, which is the
    # default (STOR-001: the owner decides). Past it the file goes even if the
    # document is still there; an export then says the original is no longer stored
    # and is written without it (services/asset_cleanup.py).
    kept_original_retention_days: int = Field(default=0, ge=0)
    # A job is started at most this many times: a transient failure is retried with
    # exponential backoff (the first retry waits the base, each next one twice as
    # long, up to the cap); after the last attempt it is a dead letter (app/jobs/policy.py).
    # The longest any job may run on this host, whatever its type allows (0: no such limit). On
    # Vercel (RELEASE) a job runs inside its request, which the platform ends at 300 s: the
    # image sets 270, so a job stops itself and says why before the request is cut off.
    job_time_limit_seconds: float = Field(default=0, ge=0)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    job_retry_base_seconds: float = Field(default=5.0, ge=0, le=300)
    job_retry_max_seconds: float = Field(default=300.0, ge=0, le=3600)
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
    # E-mail (app/mail): "outbox" writes each message as a file into email_outbox_dir
    # (development: nothing leaves the machine), "smtp" sends it through smtp_host --
    # with STARTTLS ("starttls", port 587) or TLS ("ssl", port 465); "none" only to a
    # server on this machine (a development mail catcher); "disabled" sends nothing, and the
    # API says so (GET /api/v1/auth/email-delivery) instead of claiming a link went out --
    # the Vercel image's default until a sending domain exists (RELEASE).
    email_backend: Literal["outbox", "smtp", "disabled"] = "outbox"
    email_outbox_dir: str = str(_BACKEND_DIR / "data" / "outbox")
    email_from: str = "SmartDoc <no-reply@localhost>"
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    email_timeout_seconds: float = Field(default=20, gt=0, le=120)
    # The largest request body the API reads at all (uploads, a document's
    # content with pasted images); refused with 413 before it is taken in.
    max_request_size_mb: int = Field(default=25, ge=1)
    # Logs (app/logging_setup.py): the app's level, "text" or "json" lines, and
    # one line per request with its status and duration (production: on, and
    # uvicorn's own access log off).
    log_level: str = "INFO"
    log_format: str = "text"
    log_requests: bool = False
    # GET /api/metrics (app/observability.py, OBS-001) answers only with this as its bearer
    # token; unset, the endpoint isn't there.
    metrics_token: str | None = None
    # Error reporting to Sentry (app/monitoring.py, RELEASE): only with a DSN set. The environment
    # defaults to Vercel's (production, preview); tracing is off unless a sample rate is given.
    sentry_dsn: str = ""
    sentry_environment: str = ""
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    # GET /api/v1/admin/operations (OBS-003): failed jobs, usage spikes, storage, refusals across
    # every workspace, only with this as its bearer token; unset, the endpoint isn't there.
    admin_token: str | None = None
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
    rate_limit_password_reset: str = "10/hour"  # per address: asking for a reset link
    rate_limit_password_reset_account: str = "3/hour"  # per email address: no one's inbox filled with links
    rate_limit_account_link: str = "20/hour"  # per address: using a link from an e-mail (a reset, a confirmation)
    rate_limit_verify_email: str = "5/hour"  # per user: asking for another link to confirm the address
    rate_limit_ai: str = "20/minute"  # per user: work that uses the AI
    rate_limit_upload: str = "20/minute"  # per user
    rate_limit_export: str = "30/minute"  # per user

    @field_validator(
        "rate_limit_global",
        "rate_limit_login",
        "rate_limit_login_account",
        "rate_limit_register",
        "rate_limit_password_reset",
        "rate_limit_password_reset_account",
        "rate_limit_account_link",
        "rate_limit_verify_email",
        "rate_limit_ai",
        "rate_limit_upload",
        "rate_limit_export",
    )
    @classmethod
    def _rate_limit_shape(cls, value: str) -> str:
        if value.strip() and not _RATE.match(value):
            raise ValueError(f"A rate limit looks like '20/minute' (or is empty for none), not {value!r}")
        return value

    def browser_origins(self) -> list[str]:
        """The origins a browser may call the API from: CORS_ORIGINS, and on Vercel (RELEASE) the
        deployment's own addresses -- its unique, branch and production URLs, which Vercel sets
        (VERCEL_URL ...) -- since the frontend there is served from the same origin as the API."""
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        for name in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
            host = os.environ.get(name, "").strip()
            if host and "/" not in host and f"https://{host}" not in origins:
                origins.append(f"https://{host}")
        return origins

    @property
    def largest_file_mb(self) -> int:
        """The largest document file this server imports, in parts where one request can't carry it: no plan's
        file size goes past it. Never below MAX_UPLOAD_SIZE_MB, so a file one request carries is never refused."""
        return max(self.max_chunked_upload_size_mb, self.max_upload_size_mb)

    @property
    def ai_configured(self) -> bool:
        """Whether the AI steps really call a model: a provider with a key. Without one they use their
        rules-based fallbacks, and the app must not call those AI."""
        return self.ai_provider == "anthropic" and bool(self.anthropic_api_key.get_secret_value().strip())

    @property
    def email_delivers(self) -> bool:
        """Whether a message the app sends reaches anyone: through SMTP, or into the development outbox."""
        return self.email_backend != "disabled"

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
    def _preview_never_reaches_production(self) -> "Settings":
        """The first, cheap layer: a preview whose own settings mention production doesn't start. Fail-closed --
        a preview that doesn't say what production is, or which instances it expects, doesn't start either. The
        layer that counts is app/isolation.py: what the connected database and bucket say they are."""
        if not self.isolation_required:
            return self
        name = self.smartdoc_environment or ("preview (pinned branch)" if pinned_preview() else "preview")
        ref = self.production_db_ref.strip().lower()
        if not ref:
            raise ValueError(f"{name}: PRODUCTION_DB_REF is not set, so production can't be told apart; refusing to start")
        # "preview-setup": scripts/preview_identity.py making the markers, before there are ids to expect. Such a
        # deployment never serves: app/isolation.py refuses without an expected id.
        missing = not self.expected_db_instance.strip() or (self.storage_backend == "s3" and not self.expected_storage_instance.strip())
        if missing and name != "preview-setup":
            raise ValueError(f"{name}: EXPECTED_DB_INSTANCE / EXPECTED_STORAGE_INSTANCE are not set; refusing to start")
        if any(ref in part for part in _connection_parts(self.database_url)):
            raise ValueError(f"{name}: DATABASE_URL points at production; refusing to start")
        if ref in self.s3_endpoint_url.lower() or ref in self.s3_bucket.lower():
            raise ValueError(f"{name}: S3_ENDPOINT_URL or S3_BUCKET points at production; refusing to start")
        return self

    @property
    def isolation_required(self) -> bool:
        """Whether this deployment must prove its isolation (app/isolation.py): it names itself a preview, Vercel says
        it is a Preview of a pinned branch, or it carries any of the guard's settings -- each alone is enough, so no
        single forgotten variable turns the guard off. Production and local runs carry none of them."""
        guard = (self.production_db_ref, self.expected_db_instance, self.expected_storage_instance)
        return self.smartdoc_environment.startswith("preview") or pinned_preview() or any(value.strip() for value in guard)

    @property
    def database_fingerprint(self) -> str:
        """A short, non-reversible name for the database a deployment uses, without showing it. Host, port, user and
        database together: Supabase's pooler serves every project of a region from the same host, and only the
        user (postgres.<project ref>) tells them apart."""
        import hashlib

        return hashlib.sha256("|".join(_connection_parts(self.database_url)).encode()).hexdigest()[:10]

    @model_validator(mode="after")
    def _request_fits_an_upload(self) -> "Settings":
        if self.max_request_size_mb <= self.max_upload_size_mb:
            raise ValueError("MAX_REQUEST_SIZE_MB must be larger than MAX_UPLOAD_SIZE_MB, or no upload would get through")
        return self

    @model_validator(mode="after")
    def _email_can_go_out(self) -> "Settings":
        if self.email_backend != "smtp":
            return self
        if not self.smtp_host:
            raise ValueError("EMAIL_BACKEND=smtp needs SMTP_HOST")
        if self.smtp_security == "none" and self.smtp_host not in _LOOPBACK_HOSTS:
            raise ValueError("SMTP_SECURITY=none would send the password and every message in the clear: only to a server on this machine")
        if "@" not in self.email_from:
            raise ValueError("EMAIL_FROM must hold an address, e.g. 'SmartDoc <no-reply@example.com>'")
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
