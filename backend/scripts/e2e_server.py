"""A throwaway backend for the end-to-end tests (frontend/playwright.config.ts
starts it): a fresh SQLite database and asset folder in a temporary directory
-- never the real database -- migrated to the current schema, then the API on
http://127.0.0.1:8100 for the frontend under test on http://localhost:3100.

No AI key: every AI step takes its fallback, except the few formatting
instructions scripts/e2e_ai.py answers as the real model would. No Stripe, and
no rate limits: the tests sign up many users from one address. E-mail goes to an
outbox folder, E2E_OUTBOX_DIR (emptied at start), where the tests read it.
Everything is set in this process's environment, which wins over backend/.env.

Its temporary directory goes when it stops on its own; Playwright ends it by
killing it, so each start also removes what earlier runs left (TEST-006): their
directories untouched for STALE_HOURS -- never the outbox, nor one in use.

    python -m scripts.e2e_server
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("E2E_BACKEND_PORT", "8100"))
FRONTEND = os.environ.get("E2E_FRONTEND_URL", "http://localhost:3100")
PREFIX = "smartdoc-e2e-"
# An earlier run's directory nothing has written to for this long is left over: a running
# server's database changes far more often (and a file still open isn't removed on Windows).
STALE_HOURS = 6


def _last_written(directory: Path) -> float:
    return max([directory.stat().st_mtime, *(child.stat().st_mtime for child in directory.iterdir())], default=0.0)


def sweep(temp: Path, *, keep: tuple[Path, ...] = (), now: float | None = None) -> list[Path]:
    """Removes the directories earlier runs left in `temp` -- ones holding an e2e database, or
    nothing, untouched for STALE_HOURS -- but never those in `keep`; what it removed."""
    now = time.time() if now is None else now
    kept = {path.resolve() for path in keep}
    removed = []
    for directory in temp.glob(f"{PREFIX}*"):
        try:
            if not directory.is_dir() or directory.is_symlink() or directory.resolve() in kept:
                continue
            ours = (directory / "e2e.db").is_file() or not any(directory.iterdir())
            if not ours or now - _last_written(directory) < STALE_HOURS * 3600:
                continue
        except OSError:
            continue
        shutil.rmtree(directory, ignore_errors=True)
        if not directory.exists():
            removed.append(directory)
    return removed


def main() -> None:
    outbox_setting = os.environ.get("E2E_OUTBOX_DIR")
    left = sweep(Path(tempfile.gettempdir()), keep=(Path(outbox_setting),) if outbox_setting else ())
    if left:
        print(f"Removed {len(left)} directories earlier end-to-end runs left", flush=True)
    root = Path(tempfile.mkdtemp(prefix=PREFIX))
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
    # Batches to exercise (FEAT-001): the real free plan has none (billing/plans.json).
    from app.billing.plans import FREE, PLANS

    free = PLANS[FREE]
    PLANS[FREE] = free.model_copy(update={"entitlements": free.entitlements.model_copy(update={"maxBatchJobs": 20})})
    try:
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    finally:  # stopped on its own (Ctrl+C): its directory goes now; killed, the next start's sweep takes it
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
