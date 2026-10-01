"""Verifies the actual Alembic migration file, not just the ORM models --
`app/db/models/*.py` describes the target schema, but the migration in
`alembic/versions/` is what really runs against a database, and nothing
guarantees the two stay in sync except a test that runs the migration for
real. Deliberately synchronous tests: `alembic.command.upgrade` drives its
own `asyncio.run()` (see alembic/env.py), which cannot be called from inside
a pytest-asyncio-managed event loop.
"""

import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db.models import Base

_BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def alembic_config(tmp_path, monkeypatch):
    db_path = tmp_path / "migration_test.db"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.attributes["sqlite_sync_url"] = f"sqlite:///{db_path}"
    return config


def _table_names(sqlite_sync_url: str) -> set[str]:
    engine = create_engine(sqlite_sync_url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_upgrade_head_creates_every_model_table(alembic_config):
    command.upgrade(alembic_config, "head")

    actual = _table_names(alembic_config.attributes["sqlite_sync_url"])
    expected = set(Base.metadata.tables.keys())
    assert actual == expected


def test_upgrade_head_matches_the_models_column_for_column(alembic_config):
    # The same comparison `alembic revision --autogenerate` makes: any column,
    # index or foreign key a model has but the migrations don't (or the other
    # way round) shows up here.
    command.upgrade(alembic_config, "head")

    engine = create_engine(alembic_config.attributes["sqlite_sync_url"])
    try:
        with engine.connect() as connection:
            differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    finally:
        engine.dispose()
    assert differences == []


def test_downgrade_base_drops_every_table(alembic_config):
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    assert _table_names(alembic_config.attributes["sqlite_sync_url"]) == set()


def test_every_table_gets_rls_enabled_on_postgres(monkeypatch):
    # Offline (--sql) mode renders real PostgreSQL DDL without a live server.
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", "postgresql+asyncpg://offline:offline@localhost/offline")
    buffer = io.StringIO()
    config = Config(str(_BACKEND_DIR / "alembic.ini"), output_buffer=buffer)

    command.upgrade(config, "head", sql=True)

    script = buffer.getvalue()
    created = set(re.findall(r"^CREATE TABLE (\w+)", script, flags=re.MULTILINE))
    rls_enabled = set(re.findall(r"^ALTER TABLE (\w+) ENABLE ROW LEVEL SECURITY", script, flags=re.MULTILINE))
    assert "documents" in created
    assert created == rls_enabled


_JOB_SAFETY_COLUMNS = {"retry_count", "dead_letter", "failure_reason", "idempotency_key", "request_fingerprint"}
_BEFORE_JOB_SAFETY = "0417f0f393fc"
_UNIQUE_KEY_INDEX = "uq_processing_jobs_created_by_idempotency_key"


def _job_columns(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return {column["name"] for column in inspect(engine).get_columns("processing_jobs")}
    finally:
        engine.dispose()


def test_the_job_safety_migration_upgrades_keeps_jobs_and_downgrades(alembic_config):
    url = alembic_config.attributes["sqlite_sync_url"]
    command.upgrade(alembic_config, _BEFORE_JOB_SAFETY)
    assert not _JOB_SAFETY_COLUMNS & _job_columns(url)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO processing_jobs (id, workspace_id, job_type, status, progress, attempts, created_at) "
            "VALUES ('old-job', 'a-workspace', 'export', 'failed', 0, 1, '2026-09-01 00:00:00')"
        )

    command.upgrade(alembic_config, "head")

    assert _JOB_SAFETY_COLUMNS <= _job_columns(url)
    with engine.connect() as connection:
        row = connection.exec_driver_sql("SELECT retry_count, dead_letter, idempotency_key FROM processing_jobs").one()
        indexes = {index["name"]: index for index in inspect(connection).get_indexes("processing_jobs")}
    assert tuple(row) == (0, 0, None)  # an old job is no dead letter and has no key
    assert indexes[_UNIQUE_KEY_INDEX]["unique"] and indexes[_UNIQUE_KEY_INDEX]["column_names"] == ["created_by", "idempotency_key"]

    command.downgrade(alembic_config, _BEFORE_JOB_SAFETY)

    assert not _JOB_SAFETY_COLUMNS & _job_columns(url)
    with engine.connect() as connection:
        assert tuple(connection.exec_driver_sql("SELECT id, attempts FROM processing_jobs").one()) == ("old-job", 1)
        assert _UNIQUE_KEY_INDEX not in {index["name"] for index in inspect(connection).get_indexes("processing_jobs")}
    engine.dispose()
    command.upgrade(alembic_config, "head")  # and up again
