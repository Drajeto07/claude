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


def test_compressed_versions_keep_old_rows_readable_and_the_downgrade_decompresses_them(alembic_config):
    # PERF-004 (b8534d3c4256): rows from before stay uncompressed and readable; a
    # downgrade turns compressed rows back into JSON rather than losing them.
    command.upgrade(alembic_config, "85211092fe4c")
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

        command.downgrade(alembic_config, "85211092fe4c")
        with engine.connect() as connection:
            assert "compressed_data" not in {column["name"] for column in inspect(connection).get_columns("document_versions")}
            rows = dict(connection.execute(text("SELECT id, data FROM document_versions")).all())
        assert {key: json.loads(value) for key, value in rows.items()} == {"old": old_state, "new": new_state}

        command.upgrade(alembic_config, "head")
        with OrmSession(engine) as session:
            assert session.get(DocumentVersion, "new").data == new_state
    finally:
        engine.dispose()
