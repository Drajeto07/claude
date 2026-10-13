"""Settings for the first public release on Vercel (RELEASE, docs/deployment/vercel.md): the API is
served from the app's own origin, so a deployment's Vercel addresses may call it, and behind
Supabase's transaction pooler the API keeps no pool or prepared statements of its own."""

from sqlalchemy.pool import NullPool

from app.config import Settings
from app.db.session import engine_options


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_a_vercel_deployments_own_addresses_may_call_the_api(monkeypatch):
    monkeypatch.setenv("VERCEL_URL", "smartdoc-abc123.vercel.app")
    monkeypatch.setenv("VERCEL_BRANCH_URL", "smartdoc-git-main.vercel.app")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "smartdoc.vercel.app")

    origins = _settings(cors_origins="https://smartdoc.vercel.app").browser_origins()

    assert origins == ["https://smartdoc.vercel.app", "https://smartdoc-abc123.vercel.app", "https://smartdoc-git-main.vercel.app"]


def test_off_vercel_only_the_named_origins(monkeypatch):
    for name in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VERCEL_URL", "evil.example/path")  # never anything but a host

    assert _settings(cors_origins="http://localhost:3000, http://localhost:3100").browser_origins() == ["http://localhost:3000", "http://localhost:3100"]


def test_behind_a_transaction_pooler_no_pool_and_no_kept_prepared_statements():
    pooled = engine_options(_settings(database_url="postgresql+asyncpg://u:p@db.example.com:5432/postgres"))
    assert pooled == {"pool_pre_ping": True}

    pooler = engine_options(_settings(database_url="postgresql+asyncpg://u:p@pooler.example.com:6543/postgres", database_pooler="transaction"))
    assert pooler["poolclass"] is NullPool
    assert pooler["connect_args"]["statement_cache_size"] == 0  # asyncpg's cache
    assert pooler["connect_args"]["prepared_statement_cache_size"] == 0  # SQLAlchemy's
    names = {pooler["connect_args"]["prepared_statement_name_func"]() for _ in range(3)}
    assert len(names) == 3  # each prepared statement named afresh
    assert not any(name.startswith("__asyncpg_stmt_") for name in names)  # never asyncpg's numbered names, which collide


async def test_the_pooler_options_reach_the_driver_as_sqlalchemy_expects():
    # SQLAlchemy takes its own two options out of connect_args and hands asyncpg the rest:
    # asyncpg.connect() would refuse an argument it doesn't know.
    from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi
    from sqlalchemy.util import greenlet_spawn

    captured = {}

    class FakeAsyncpg:
        @staticmethod
        async def connect(*args, **kwargs):
            captured.update(kwargs)
            return object()

    options = engine_options(_settings(database_url="postgresql+asyncpg://u:p@pooler.example.com:6543/postgres", database_pooler="transaction"))
    dbapi = AsyncAdapt_asyncpg_dbapi(FakeAsyncpg)
    adapted = await greenlet_spawn(dbapi.connect, **options["connect_args"])  # as the engine calls it

    assert captured == {"statement_cache_size": 0}
    assert adapted._prepared_statement_cache is None  # SQLAlchemy keeps no prepared statements
    assert adapted._prepared_statement_name_func is options["connect_args"]["prepared_statement_name_func"]


def test_the_vercel_image_defaults_to_eager_jobs_and_the_transaction_pooler():
    # The project's settings may be missing on an environment (as on the first production
    # deployment, 2026-10-13): the image itself then still runs as Vercel needs.
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parent.parent / "Dockerfile.vercel").read_text(encoding="utf-8")
    env_block = dockerfile.split("ENV JOB_BACKEND=", 1)[1].split("\n\n", 1)[0]
    assert env_block.startswith("eager")
    assert "DATABASE_POOLER=transaction" in env_block


def test_the_transaction_pooler_setting_leaves_sqlite_alone():
    assert engine_options(_settings(database_url="sqlite+aiosqlite:///./x.db", database_pooler="transaction")) == {"pool_pre_ping": True}
