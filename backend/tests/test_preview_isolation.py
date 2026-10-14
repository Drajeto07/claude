"""D-012 / docs/SMARTDOC_2_0_PREVIEW_ISOLATION_PLAN.md: the 2.0 preview has its own database and storage.
A preview that would still reach production refuses to start, and /api/health says which database a named
deployment uses -- as a fingerprint, never the host."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

PROD_REF = "prodref1234567890ab"
PROD_DB = f"postgresql://postgres.{PROD_REF}@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
PREVIEW_DB = "postgresql://postgres.previewref987654@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"


def test_a_preview_pointing_at_the_production_database_does_not_start():
    with pytest.raises(ValueError, match="points at production"):
        Settings(smartdoc_environment="preview-2.0", production_db_ref=PROD_REF, database_url=PROD_DB)


def test_nor_one_pointing_at_production_storage():
    with pytest.raises(ValueError, match="points at production"):
        Settings(
            smartdoc_environment="preview-2.0",
            production_db_ref=PROD_REF,
            database_url=PREVIEW_DB,
            s3_endpoint_url=f"https://{PROD_REF}.storage.supabase.co/storage/v1/s3",
        )


def test_a_preview_on_its_own_database_and_storage_starts():
    settings = Settings(
        smartdoc_environment="preview-2.0",
        production_db_ref=PROD_REF,
        database_url=PREVIEW_DB,
        s3_endpoint_url="https://previewref987654.storage.supabase.co/storage/v1/s3",
    )
    assert settings.smartdoc_environment == "preview-2.0"


def test_production_and_local_runs_are_not_affected():
    # No environment name (production, local): the guard is off, whatever the URL.
    assert Settings(production_db_ref=PROD_REF, database_url=PROD_DB).database_url
    assert Settings(smartdoc_environment="preview-2.0", database_url=PROD_DB).database_url  # no ref given: nothing to compare


def test_health_says_which_database_a_named_deployment_uses_without_showing_it(monkeypatch):
    client = TestClient(app)
    assert client.get("/api/health").json() == {"status": "ok"}  # unnamed: unchanged

    monkeypatch.setattr(get_settings(), "smartdoc_environment", "preview-2.0")
    monkeypatch.setattr(get_settings(), "database_url", PREVIEW_DB)
    body = client.get("/api/health").json()
    assert body["environment"] == "preview-2.0"
    assert len(body["database"]) == 10
    assert "pooler" not in client.get("/api/health").text and "previewref" not in client.get("/api/health").text


def test_the_fingerprint_tells_two_databases_apart():
    assert Settings(database_url=PROD_DB).database_fingerprint == Settings(database_url=PROD_DB).database_fingerprint
    a = Settings(database_url=PROD_DB).database_fingerprint
    b = Settings(database_url="postgresql://u@db.previewref987654.supabase.co:5432/postgres").database_fingerprint
    assert a != b
