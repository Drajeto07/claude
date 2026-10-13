from collections.abc import AsyncGenerator
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.types import dump_json

# Lazy singletons rather than module-level construction: constructing an
# engine eagerly at import time would make every test/script that imports
# anything from app.db pay for (and require) a resolvable DATABASE_URL, even
# ones that never touch the database.
_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def make_engine(url: str, **options):
    """Every async engine goes through here (the tests' too), so the JSON columns are
    written the same way everywhere: as UTF-8 (PERF-006)."""
    return create_async_engine(url, json_serializer=dump_json, **options)


def engine_options(settings) -> dict:
    """How the engine connects (DATABASE_POOLER): its own pool by default; behind a transaction
    pooler none, and no prepared statement outliving its transaction -- each one named afresh, as
    SQLAlchemy's asyncpg dialect asks for PgBouncer-style poolers."""
    if settings.database_pooler == "transaction" and settings.database_url.startswith("postgresql"):
        return {
            "poolclass": NullPool,
            "connect_args": {"statement_cache_size": 0, "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__"},
        }
    # pre_ping: a pooler (Supabase's Supavisor) silently drops idle connections.
    return {"pool_pre_ping": True}


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = make_engine(settings.database_url, **engine_options(settings))
        if _engine.dialect.name == "sqlite":
            # SQLite (development, the E2E backend) enforces foreign keys -- and so runs the
            # ON DELETE cascades -- only when asked, per connection; PostgreSQL always does.
            event.listen(_engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    return _engine


def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency -- not yet wired into any route (that starts in the
    phase that adds the first DB-backed endpoint); exists now so that phase
    can `Depends(get_db)` without touching this module."""
    async with get_session_factory()() as session:
        yield session
