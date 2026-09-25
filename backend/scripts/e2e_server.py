"""A throwaway backend for the end-to-end tests (frontend/playwright.config.ts
starts it): a fresh SQLite database and asset folder in a temporary directory
-- never the real database -- migrated to the current schema, then the API on
http://127.0.0.1:8100 for the frontend under test on http://localhost:3100.

No AI key (every AI step takes its fallback), no Stripe, and no rate limits:
the tests sign up many users from one address. Everything is set in this
process's environment, which wins over backend/.env.

    python -m scripts.e2e_server
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("E2E_BACKEND_PORT", "8100"))
FRONTEND = os.environ.get("E2E_FRONTEND_URL", "http://localhost:3100")


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="smartdoc-e2e-"))
    database = f"sqlite+aiosqlite:///{(root / 'e2e.db').as_posix()}"
    os.environ.update(
        {
            "DATABASE_URL": database,
            "ALEMBIC_DATABASE_URL": database,
            "STORAGE_BACKEND": "local",
            "LOCAL_STORAGE_DIR": str(root / "assets"),
            "JOB_BACKEND": "background",
            "REDIS_URL": "",
            "CORS_ORIGINS": FRONTEND,
            "FRONTEND_URL": FRONTEND,
            "ANTHROPIC_API_KEY": "",
            "STRIPE_SECRET_KEY": "",
            "STRIPE_WEBHOOK_SECRET": "",
            "RATE_LIMIT_BACKEND": "memory",
            **{f"RATE_LIMIT_{scope}": "" for scope in ("GLOBAL", "LOGIN", "LOGIN_ACCOUNT", "REGISTER", "AI", "UPLOAD", "EXPORT")},
        }
    )
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True)
    print(f"E2E database: {root}", flush=True)

    import uvicorn  # after the environment is set: the app reads its settings on import

    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
