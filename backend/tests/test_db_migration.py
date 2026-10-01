"""Verifies the actual Alembic migration file, not just the ORM models --
`app/db/models/*.py` describes the target schema, but the migration in
`alembic/versions/` is what really runs against a database, and nothing
guarantees the two stay in sync except a test that runs the migration for
real. Deliberately synchronous tests: `alembic.command.upgrade` drives its
own `asyncio.run()` (see alembic/env.py), which cannot be called from inside
a pytest-asyncio-managed event loop.
"""

import io
import json
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Base, DocumentVersion

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


def test_compressed_versions_keep_old_rows_readable_and_the_downgrade_decompresses_them(alembic_config):
    # PERF-004 (b8534d3c4256): rows from before stay uncompressed and readable; a
    # downgrade turns compressed rows back into JSON rather than losing them.
    command.upgrade(alembic_config, "c3a91f7d2b64")
    old_state = {"metadata": {"title": "Before compression"}, "elements": []}
    engine = create_engine(alembic_config.attributes["sqlite_sync_url"])
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document_versions (id, document_id, revision_number, kind, data, created_at) "
                    "VALUES ('old', 'doc', 1, 'created', :data, '2026-09-30 10:00:00')"
                ),
                {"data": json.dumps(old_state)},
            )

        command.upgrade(alembic_config, "b8534d3c4256")
        new_state = {"metadata": {"title": "Компресиран"}, "elements": [{"id": "x", "content": "text " * 200}]}
        with OrmSession(engine) as session:
            assert session.get(DocumentVersion, "old").data == old_state
            session.add(DocumentVersion(id="new", document_id="doc", revision_number=2, data=new_state))
            session.commit()
        with engine.connect() as connection:
            stored = connection.execute(text("SELECT data, compressed_data FROM document_versions WHERE id = 'new'")).one()
            # Every row holds exactly one copy of its state.
            with pytest.raises(Exception, match="CHECK constraint failed"):
                connection.execute(text("UPDATE document_versions SET data = NULL WHERE id = 'old'"))
        assert stored.data is None and len(stored.compressed_data) < len(json.dumps(new_state)) / 3

        command.downgrade(alembic_config, "c3a91f7d2b64")
        with engine.connect() as connection:
            assert "compressed_data" not in {column["name"] for column in inspect(connection).get_columns("document_versions")}
            rows = dict(connection.execute(text("SELECT id, data FROM document_versions")).all())
        assert {key: json.loads(value) for key, value in rows.items()} == {"old": old_state, "new": new_state}

        command.upgrade(alembic_config, "head")
        with OrmSession(engine) as session:
            assert session.get(DocumentVersion, "new").data == new_state
    finally:
        engine.dispose()


def test_the_stripe_synced_at_migration_keeps_subscriptions_and_downgrades(alembic_config):
    # PLAN-004 (d41f7a60c9e2): a subscription row from before has no read recorded.
    url = alembic_config.attributes["sqlite_sync_url"]
    command.upgrade(alembic_config, "b8534d3c4256")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO subscriptions (id, workspace_id, plan, status, cancel_at_period_end, created_at, updated_at) "
                "VALUES ('sub-row', 'a-workspace', 'pro', 'active', 0, '2026-09-01 00:00:00', '2026-09-01 00:00:00')"
            )

        command.upgrade(alembic_config, "d41f7a60c9e2")
        with engine.connect() as connection:
            assert tuple(connection.exec_driver_sql("SELECT plan, stripe_synced_at FROM subscriptions").one()) == ("pro", None)

        command.downgrade(alembic_config, "b8534d3c4256")
        with engine.connect() as connection:
            assert "stripe_synced_at" not in {column["name"] for column in inspect(connection).get_columns("subscriptions")}
            assert tuple(connection.exec_driver_sql("SELECT plan, status FROM subscriptions").one()) == ("pro", "active")
        command.upgrade(alembic_config, "head")
    finally:
        engine.dispose()
