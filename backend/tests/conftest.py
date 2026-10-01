import os
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory
from argon2 import PasswordHasher, profiles
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.db import session as db_session_module
from app.db.models import Base
from app.db.session import get_db, make_engine
from app.db.types import dump_json
from app.jobs.queue import get_job_backend, get_job_session_factory
from app.mail import MemorySender, get_email_sender
from app.security import rate_limit
from app.services import auth_service
from app.services import persistence
from app.storage.factory import get_storage_provider
from app.storage.local_provider import LocalStorageProvider


@pytest.fixture(autouse=True)
def isolated_persistence(tmp_path, monkeypatch):
    """Points the legacy JSON document store (still read by
    scripts/migrate_json_documents.py) at a throwaway directory, so no test can
    touch this machine's real backend/data/documents/."""
    monkeypatch.setattr(persistence, "_DATA_DIR", tmp_path)
    yield


@pytest.fixture(autouse=True)
def sent_mail():
    """Every e-mail the app sends in a test, kept in memory: none leaves the machine
    or lands in the real outbox folder (ACCT-001)."""
    from app.main import app

    sender = MemorySender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    yield sender.sent
    app.dependency_overrides.pop(get_email_sender, None)


@pytest.fixture(autouse=True)
def never_the_real_database(monkeypatch):
    """backend/.env points at the production (Supabase) database. A test that
    forgets the api_db/db_session fixtures must fail loudly, not write there."""

    def refuse():
        raise RuntimeError("Tests must use the api_db / db_session fixtures, never the real DATABASE_URL.")

    monkeypatch.setattr(db_session_module, "get_engine", refuse)


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """Every test starts with nothing counted against the rate limits (the whole
    suite signs up far more users from one address than the limits allow)."""
    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch):
    """Production argon2 parameters cost ~80ms per hash; tests don't need that strength."""
    monkeypatch.setattr(auth_service, "_hasher", PasswordHasher.from_parameters(profiles.CHEAPEST))
    auth_service._dummy_hash.cache_clear()
    yield
    auth_service._dummy_hash.cache_clear()


def _enable_sqlite_fk(dbapi_connection, connection_record):
    # SQLite ignores foreign keys (including ON DELETE CASCADE) unless told
    # otherwise per-connection -- without this, a test could insert an
    # orphaned row or rely on a cascade that only appears to work here and
    # would fail against the real Postgres database.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def _build_test_engine():
    """A fresh, empty SQLite engine -- StaticPool keeps the same in-memory
    connection alive for the engine's lifetime (the default pool would hand
    aiosqlite a brand-new, separately-empty :memory: database on every
    checkout). Verifies the ORM layer itself; not a substitute for running
    the real Alembic migration against Postgres eventually."""
    engine = make_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    event.listen(engine.sync_engine, "connect", _enable_sqlite_fk)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest_asyncio.fixture
async def db_session():
    engine = await _build_test_engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory():
    """Like `db_session`, but hands back the `async_sessionmaker` itself
    rather than one open session -- for code (e.g. scripts/migrate_json_documents.py)
    that opens its own session per unit of work instead of receiving one."""
    engine = await _build_test_engine()
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def api_db(tmp_path):
    """Points the app's get_db dependency at a fresh SQLite file for this test,
    and asset storage at a throwaway directory, and returns a sync engine on the
    same file for setup/inspection. NullPool matters: TestClient runs each
    request in its own event loop, so no async connection may outlive the
    request that opened it."""
    from app.main import app

    db_path = tmp_path / "api.db"
    sync_engine = create_engine(f"sqlite:///{db_path}", json_serializer=dump_json)
    event.listen(sync_engine, "connect", _enable_sqlite_fk)
    Base.metadata.create_all(sync_engine)

    async_engine = make_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    event.listen(async_engine.sync_engine, "connect", _enable_sqlite_fk)
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    storage = LocalStorageProvider(tmp_path / "assets")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage_provider] = lambda: storage
    # Background jobs run inside the request here, on the same test database.
    app.dependency_overrides[get_job_backend] = lambda: "eager"
    app.dependency_overrides[get_job_session_factory] = lambda: session_factory
    yield sync_engine
    for dependency in (get_db, get_storage_provider, get_job_backend, get_job_session_factory):
        app.dependency_overrides.pop(dependency, None)
    sync_engine.dispose()


# -- PostgreSQL (TEST-031) ---------------------------------------------------------

POSTGRES_URL_ENV = "SMARTDOC_TEST_POSTGRES_URL"
_LOCAL_HOSTS = {"localhost", "127.0.0.1"}
_BACKEND_DIR = Path(__file__).resolve().parent.parent


def local_postgres_url(url: str) -> str:
    """The URL, if it names a PostgreSQL on this machine. Anything else is refused
    loudly: the tests empty every table they touch, so a URL that reached a shared or
    production database (Supabase) must never get as far as a connection."""
    parsed = make_url(url)
    if parsed.drivername != "postgresql+asyncpg":
        raise ValueError(f"{POSTGRES_URL_ENV} must be a postgresql+asyncpg:// URL (the app's driver), not {parsed.drivername}://.")
    if parsed.host not in _LOCAL_HOSTS:
        raise ValueError(f"{POSTGRES_URL_ENV} may only point at localhost or 127.0.0.1, not {parsed.host!r}.")
    return url


def _alembic_head() -> str:
    return ScriptDirectory.from_config(Config(str(_BACKEND_DIR / "alembic.ini"))).get_current_head()


async def _app_tables(connection) -> list[str]:
    rows = await connection.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema() AND tablename <> 'alembic_version'")
    )
    return sorted(row[0] for row in rows)


async def _empty_tables(engine) -> None:
    async with engine.begin() as connection:
        if tables := await _app_tables(connection):
            names = ", ".join(f'"{name}"' for name in tables)
            await connection.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def postgres_sessions():
    """An async_sessionmaker on the throwaway PostgreSQL named by
    SMARTDOC_TEST_POSTGRES_URL (CI's service container, or a local one), made by
    make_engine like the app's. Skipped when the variable isn't set, so the default
    run needs no PostgreSQL; refused for any host but this machine.

    The schema is the one the migrations made (CI runs `alembic upgrade head` first),
    which is the point: these tests run on what production runs. It must be at head;
    only a database with no tables at all gets the models' create_all, for a quick
    local run (CI's `alembic check` keeps the two the same). Every table is emptied
    before and after each test (TRUNCATE ... CASCADE; the database itself is never
    dropped)."""
    url = os.environ.get(POSTGRES_URL_ENV)
    if not url:
        pytest.skip(f"{POSTGRES_URL_ENV} is not set: no PostgreSQL to run on")
    try:
        local_postgres_url(url)
    except ValueError as exc:
        pytest.fail(str(exc), pytrace=False)

    engine = make_engine(url, poolclass=NullPool)
    async with engine.begin() as connection:
        problem = None
        if await connection.scalar(text("SELECT to_regclass('alembic_version') IS NOT NULL")):
            version = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            if version != _alembic_head():
                problem = f"The test database is at {version}, not {_alembic_head()}: run `alembic upgrade head` on it first."
        elif not await _app_tables(connection):
            await connection.run_sync(Base.metadata.create_all)
        else:
            problem = "The test database has tables but no alembic_version: use an empty database or a migrated one."
    if problem:
        await engine.dispose()
        pytest.fail(problem, pytrace=False)
    await _empty_tables(engine)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await _empty_tables(engine)
        await engine.dispose()
