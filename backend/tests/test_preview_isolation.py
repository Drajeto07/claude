"""D-012 / docs/SMARTDOC_2_0_PREVIEW_ISOLATION_PLAN.md: the 2.0 preview has its own database and storage.

Two layers. Its settings must not mention production (and must say what production is): otherwise it doesn't
start. And the database and bucket it is actually connected to must prove they are its own, by a marker only
their setup writes (app/isolation.py): until they do, it serves nothing but the health probe. Fail-closed
throughout: anything missing or unreadable is a refusal."""

import json
import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import isolation
from app.config import Settings, get_settings
from app.main import app

PROD_REF = "prodref1234567890ab"
POOLER = "aws-0-eu-central-1.pooler.supabase.com:6543"
PROD_DB = f"postgresql://postgres.{PROD_REF}@{POOLER}/postgres"
PROD_DIRECT = f"postgresql://postgres@db.{PROD_REF}.supabase.co:5432/postgres"
PREVIEW_DB = f"postgresql://postgres.previewref987654@{POOLER}/postgres"
PREVIEW_S3 = "https://previewref987654.storage.supabase.co/storage/v1/s3"
DB_ID, STORE_ID = str(uuid.uuid4()), str(uuid.uuid4())


def preview(**overrides) -> Settings:
    values = dict(
        smartdoc_environment="preview-2.0",
        production_db_ref=PROD_REF,
        database_url=PREVIEW_DB,
        storage_backend="s3",
        s3_bucket="smartdoc-preview",
        s3_endpoint_url=PREVIEW_S3,
        expected_db_instance=DB_ID,
        expected_storage_instance=STORE_ID,
    )
    values.update(overrides)
    return Settings(**values)


# -- Layer 1: the settings ------------------------------------------------------------------------------


@pytest.mark.parametrize("url", [PROD_DB, PROD_DIRECT, PROD_DB.replace(PROD_REF, PROD_REF.upper())])
def test_a_preview_whose_database_url_names_production_does_not_start(url):
    # The pooler (ref in the user name), the direct host (ref in the host), any letter case.
    with pytest.raises(ValueError, match="DATABASE_URL points at production"):
        preview(database_url=url)


@pytest.mark.parametrize(
    "storage",
    [dict(s3_endpoint_url=f"https://{PROD_REF}.storage.supabase.co/storage/v1/s3"), dict(s3_bucket=f"{PROD_REF}-files")],
)
def test_nor_one_whose_storage_names_production(storage):
    with pytest.raises(ValueError, match="points at production"):
        preview(**storage)


def test_a_preview_that_doesnt_say_what_production_is_does_not_start():
    # Fail-closed: nothing to compare with is a refusal, not a pass.
    with pytest.raises(ValueError, match="PRODUCTION_DB_REF is not set"):
        preview(production_db_ref="")


@pytest.mark.parametrize("missing", ["expected_db_instance", "expected_storage_instance"])
def test_nor_one_that_doesnt_say_which_instances_it_expects(missing):
    with pytest.raises(ValueError, match="EXPECTED_DB_INSTANCE"):
        preview(**{missing: ""})


def test_the_setup_run_needs_no_ids_yet_and_still_refuses_production():
    assert preview(smartdoc_environment="preview-setup", expected_db_instance="", expected_storage_instance="")
    with pytest.raises(ValueError, match="points at production"):
        preview(smartdoc_environment="preview-setup", expected_db_instance="", database_url=PROD_DB)


def test_a_preview_on_its_own_database_and_storage_starts():
    assert preview().smartdoc_environment == "preview-2.0"


def test_production_and_local_runs_are_not_affected():
    assert Settings(production_db_ref=PROD_REF, database_url=PROD_DB).database_url
    assert not isolation.required(Settings(database_url=PROD_DB))


def test_the_fingerprint_tells_two_projects_on_the_same_pooler_apart():
    # Same pooler host and port; only the user (postgres.<ref>) differs.
    assert Settings(database_url=PROD_DB).database_fingerprint != Settings(database_url=PREVIEW_DB).database_fingerprint
    assert Settings(database_url=PROD_DB).database_fingerprint == Settings(database_url=PROD_DB).database_fingerprint


# -- Layer 2: what the connected resources say they are -----------------------------------------------------


class FakeSession:
    def __init__(self, rows=None, error=None):
        self.rows, self.error = rows or [], error

    async def execute(self, statement):
        if self.error:
            raise self.error
        assert isolation.MARKER_TABLE in str(statement)
        return self.rows


class FakeStorage:
    def __init__(self, marker: bytes | None):
        self.marker = marker

    async def get(self, key):
        assert key == isolation.STORAGE_MARKER_KEY
        if self.marker is None:
            raise FileNotFoundError(key)
        return self.marker


def store(environment="preview", instance_id=STORE_ID) -> FakeStorage:
    return FakeStorage(json.dumps({"environment": environment, "instance_id": instance_id}).encode())


async def test_matching_markers_prove_the_preview():
    await isolation.verify(preview(), FakeSession([("preview", DB_ID)]), store())


@pytest.mark.parametrize(
    "session, reason",
    [
        (FakeSession(error=RuntimeError('relation "smartdoc_identity.deployment" does not exist')), "can't be read"),
        (FakeSession([]), "no identity marker"),
        (FakeSession([("preview", DB_ID), ("preview", DB_ID)]), "more than one"),
        (FakeSession([("production", DB_ID)]), "another environment"),
        (FakeSession([("preview", str(uuid.uuid4()))]), "another instance"),
    ],
)
async def test_any_doubt_about_the_database_refuses(session, reason):
    # The first case is production as it is today: it has no marker at all.
    with pytest.raises(isolation.IsolationError, match=reason):
        await isolation.verify(preview(), session, store())


@pytest.mark.parametrize(
    "storage, reason",
    [
        (FakeStorage(None), "no identity marker"),
        (FakeStorage(b"not json"), "can't be read"),
        (store(environment="production"), "another environment"),
        (store(instance_id=str(uuid.uuid4())), "another instance"),
    ],
)
async def test_any_doubt_about_the_bucket_refuses(storage, reason):
    with pytest.raises(isolation.IsolationError, match=reason):
        await isolation.verify(preview(), FakeSession([("preview", DB_ID)]), storage)


async def test_a_preview_without_a_bucket_proves_only_its_database():
    settings = preview(storage_backend="local", expected_storage_instance="")
    await isolation.verify(settings, FakeSession([("preview", DB_ID)]), FakeStorage(None))


async def test_the_reasons_name_no_host_user_or_key():
    with pytest.raises(isolation.IsolationError) as caught:
        await isolation.verify(preview(), FakeSession(error=RuntimeError(f"password authentication failed for {PROD_REF}")), store())
    assert PROD_REF not in str(caught.value) and "pooler" not in str(caught.value)


# -- The gate: a preview serves nothing until it is proven ----------------------------------------------------


def opener(session):
    @asynccontextmanager
    async def open_session():
        yield session

    return open_session


@pytest.fixture
def named_preview(monkeypatch):
    """The running app as a preview, with the gate fresh before and after."""
    settings = get_settings()
    for name, value in dict(
        smartdoc_environment="preview-2.0",
        database_url=PREVIEW_DB,
        production_db_ref=PROD_REF,
        expected_db_instance=DB_ID,
        storage_backend="local",
    ).items():
        monkeypatch.setattr(settings, name, value)
    isolation.gate.reset()
    yield settings
    isolation.gate.reset()


def answers(monkeypatch, session):
    monkeypatch.setattr("app.main.get_session_factory", lambda: opener(session))  # called lazily, per check


def test_an_unproven_preview_refuses_every_request_but_says_why_on_health(monkeypatch, named_preview):
    answers(monkeypatch, FakeSession(error=RuntimeError("no such schema")))
    client = TestClient(app)

    refused = client.get("/api/v1/capabilities")
    assert refused.status_code == 503 and refused.json()["code"] == "isolation_not_proven"
    assert client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "a long enough password"}).status_code == 503

    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["environment"] == "preview-2.0" and body["isolation"].startswith("refused: database")
    assert "pooler" not in health.text and "previewref" not in health.text and PROD_REF not in health.text


def test_a_proven_preview_serves(monkeypatch, named_preview):
    answers(monkeypatch, FakeSession([("preview", DB_ID)]))
    client = TestClient(app)
    assert client.get("/api/v1/capabilities").status_code == 200
    assert client.get("/api/health").json()["isolation"] == "verified"


def test_a_refusal_is_tried_again_after_a_while(monkeypatch, named_preview):
    answers(monkeypatch, FakeSession(error=RuntimeError("database briefly away")))
    client = TestClient(app)
    assert client.get("/api/v1/capabilities").status_code == 503
    answers(monkeypatch, FakeSession([("preview", DB_ID)]))
    assert client.get("/api/v1/capabilities").status_code == 503  # not yet: the refusal holds for a while
    monkeypatch.setattr(isolation, "RETRY_AFTER_SECONDS", 0)
    assert client.get("/api/v1/capabilities").status_code == 200


def test_production_and_local_runs_pass_untouched(monkeypatch):
    isolation.gate.reset()
    answers(monkeypatch, FakeSession(error=AssertionError("production must not even be asked")))
    client = TestClient(app)
    assert client.get("/api/v1/capabilities").status_code == 200
    assert client.get("/api/health").json() == {"status": "ok"}


# -- The setup script, on a real PostgreSQL (CI; locally with SMARTDOC_TEST_POSTGRES_URL) ------------------------


@pytest.mark.postgres
async def test_the_setup_marks_an_empty_database_once_and_then_it_proves_itself(postgres_sessions):
    from scripts import preview_identity

    setup = preview(smartdoc_environment="preview-setup", storage_backend="local", expected_db_instance="", expected_storage_instance="")
    try:
        database_id, storage_id = await preview_identity.create(setup, postgres_sessions, FakeStorage(None))
        assert storage_id is None and uuid.UUID(database_id)

        running = preview(storage_backend="local", expected_db_instance=database_id, expected_storage_instance="")
        assert (await preview_identity.check(running, postgres_sessions, FakeStorage(None))).startswith("VERIFIED")
        other = preview(storage_backend="local", expected_db_instance=str(uuid.uuid4()), expected_storage_instance="")
        assert (await preview_identity.check(other, postgres_sessions, FakeStorage(None))).startswith("REFUSED")

        with pytest.raises(preview_identity.Refused, match="already has an identity marker"):
            await preview_identity.create(setup, postgres_sessions, FakeStorage(None))
    finally:
        async with postgres_sessions() as session:
            await session.execute(text(f"DROP SCHEMA IF EXISTS {isolation.MARKER_SCHEMA} CASCADE"))
            await session.commit()


@pytest.mark.postgres
async def test_the_setup_refuses_a_database_that_is_in_use(postgres_sessions):
    from app.db.models import User
    from scripts import preview_identity

    async with postgres_sessions() as session:
        session.add(User(email="someone@example.com", password_hash="x"))
        await session.commit()
    setup = preview(smartdoc_environment="preview-setup", storage_backend="local", expected_db_instance="", expected_storage_instance="")
    with pytest.raises(preview_identity.Refused, match="already holds users"):
        await preview_identity.create(setup, postgres_sessions, FakeStorage(None))
    async with postgres_sessions() as session:
        assert not await session.scalar(text("SELECT to_regclass('smartdoc_identity.deployment') IS NOT NULL"))
