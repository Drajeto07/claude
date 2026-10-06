"""A throwaway backend for the end-to-end tests (frontend/playwright.config.ts
starts it): a fresh SQLite database and asset folder in a temporary directory
-- never the real database -- migrated to the current schema, then the API on
http://127.0.0.1:8100 for the frontend under test on http://localhost:3100.

No AI key: every AI step takes its fallback, except the few formatting
instructions scripts/e2e_ai.py answers as the real model would. No Stripe, and
no rate limits: the tests sign up many users from one address. E-mail goes to an
outbox folder, E2E_OUTBOX_DIR (emptied at start), where the tests read it.
Everything is set in this process's environment, which wins over backend/.env.

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
    outbox = Path(os.environ.get("E2E_OUTBOX_DIR") or root / "outbox")
    outbox.mkdir(parents=True, exist_ok=True)
    for message in outbox.glob("*.eml"):
        message.unlink()
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
            "TRANSLATION_PROVIDER": "pseudo",  # no AI here: the pseudo-translation shows the whole path
            "STRIPE_SECRET_KEY": "",
            "STRIPE_WEBHOOK_SECRET": "",
            "EMAIL_BACKEND": "outbox",
            "EMAIL_OUTBOX_DIR": str(outbox),
            "RATE_LIMIT_BACKEND": "memory",
            **{
                f"RATE_LIMIT_{scope}": ""
                for scope in (
                    "GLOBAL",
                    "LOGIN",
                    "LOGIN_ACCOUNT",
                    "REGISTER",
                    "PASSWORD_RESET",
                    "PASSWORD_RESET_ACCOUNT",
                    "ACCOUNT_LINK",
                    "VERIFY_EMAIL",
                    "AI",
                    "UPLOAD",
                    "EXPORT",
                )
            },
        }
    )
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True)
    print(f"E2E database: {root}", flush=True)

    # After the environment is set: the app reads its settings on import.
    import uvicorn

    from app.ai.factory import get_ai_provider
    from app.main import app
    from scripts.e2e_ai import E2EAIProvider

    app.dependency_overrides[get_ai_provider] = E2EAIProvider  # requests and the jobs they start
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
