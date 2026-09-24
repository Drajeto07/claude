import pytest
import pytest_asyncio
from argon2 import PasswordHasher, profiles
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from app.db import session as db_session_module
from app.db.models import Base
from app.db.session import get_db
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
def never_the_real_database(monkeypatch):
    """backend/.env points at the production (Supabase) database. A test that
    forgets the api_db/db_session fixtures must fail loudly, not write there."""

    def refuse():
        raise RuntimeError("Tests must use the api_db / db_session fixtures, never the real DATABASE_URL.")

    monkeypatch.setattr(db_session_module, "get_engine", refuse)


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
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
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
    sync_engine = create_engine(f"sqlite:///{db_path}")
    event.listen(sync_engine, "connect", _enable_sqlite_fk)
    Base.metadata.create_all(sync_engine)

    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    event.listen(async_engine.sync_engine, "connect", _enable_sqlite_fk)
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    storage = LocalStorageProvider(tmp_path / "assets")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage_provider] = lambda: storage
    yield sync_engine
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_storage_provider, None)
    sync_engine.dispose()
