"""D-012 / docs/SMARTDOC_2_0_PREVIEW_ISOLATION_PLAN.md: the 2.0 preview has its own database and storage.

Two layers. Its settings must not mention production (and must say what production is): otherwise it doesn't
start. And the database and bucket it is actually connected to must prove they are its own, by a marker only
their setup writes (app/isolation.py): until they do, it serves nothing but the health probe. Fail-closed
throughout: anything missing or unreadable is a refusal."""

import asyncio
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
    # Production carries no guard setting and isn't a Vercel Preview of a pinned branch: nothing to prove.
    assert not isolation.required(Settings(database_url=PROD_DB))


@pytest.mark.parametrize("guard", [dict(production_db_ref=PROD_REF), dict(expected_db_instance=DB_ID), dict(expected_storage_instance=STORE_ID)])
def test_any_guard_setting_alone_switches_the_guard_on(guard):
    # A deployment carrying one of the guard's settings is a preview, named or not: with production's URL it doesn't start.
    with pytest.raises(ValueError, match="refusing to start"):
        Settings(database_url=PROD_DB, **guard)


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
        session.add(User(email="someone@example.com", hashed_password="x"))
        await session.commit()
    setup = preview(smartdoc_environment="preview-setup", storage_backend="local", expected_db_instance="", expected_storage_instance="")
    with pytest.raises(preview_identity.Refused, match="already holds users"):
        await preview_identity.create(setup, postgres_sessions, FakeStorage(None))
    async with postgres_sessions() as session:
        assert not await session.scalar(text("SELECT to_regclass('smartdoc_identity.deployment') IS NOT NULL"))


# -- Owner's negative cases (D-012 rev 2): each must refuse, and nothing may be written ---------------------------


@pytest.fixture
def two_buckets():
    """A real S3 API (moto, in process): the preview's bucket carries its marker, the other bucket -- standing in
    for production's -- carries none."""
    import boto3
    from moto import mock_aws

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        for bucket in ("preview-files", "production-files"):
            s3.create_bucket(Bucket=bucket)
        marker = json.dumps({"environment": "preview", "instance_id": STORE_ID}).encode()
        s3.put_object(Bucket="preview-files", Key=isolation.STORAGE_MARKER_KEY, Body=marker)
        yield s3


def s3_store(bucket: str):
    from app.storage.s3_provider import S3StorageProvider

    return S3StorageProvider(bucket, region="us-east-1", access_key_id="testing", secret_access_key="testing")


async def test_the_preview_bucket_proves_itself_through_the_real_s3_code(two_buckets):
    await isolation.verify(preview(), FakeSession([("preview", DB_ID)]), s3_store("preview-files"))


async def test_a_wrong_bucket_is_refused(two_buckets):
    # Pointed at another bucket (production's, say): it has no marker.
    with pytest.raises(isolation.IsolationError, match="file store: no identity marker"):
        await isolation.verify(preview(), FakeSession([("preview", DB_ID)]), s3_store("production-files"))


async def test_a_bucket_marked_for_another_preview_is_refused(two_buckets):
    with pytest.raises(isolation.IsolationError, match="file store: the marker names another instance"):
        await isolation.verify(preview(expected_storage_instance=str(uuid.uuid4())), FakeSession([("preview", DB_ID)]), s3_store("preview-files"))


async def test_a_bucket_that_does_not_exist_is_refused(two_buckets):
    with pytest.raises(isolation.IsolationError, match="file store: no identity marker"):
        await isolation.verify(preview(), FakeSession([("preview", DB_ID)]), s3_store("no-such-bucket"))


@pytest.mark.parametrize(
    "missing",
    [
        dict(production_db_ref=""),
        dict(expected_db_instance=""),
        dict(expected_storage_instance=""),
        dict(expected_db_instance="  ", expected_storage_instance="  "),
    ],
)
def test_missing_configuration_never_starts(missing):
    with pytest.raises(ValueError, match="refusing to start"):
        preview(**missing)


async def test_a_store_that_cannot_even_be_built_refuses_requests(monkeypatch, named_preview):
    # e.g. STORAGE_BACKEND=s3 with no bucket: the check can't run, which is a refusal.
    monkeypatch.setattr(named_preview, "storage_backend", "s3")
    monkeypatch.setattr(named_preview, "expected_storage_instance", STORE_ID)

    def broken():
        raise ValueError("STORAGE_BACKEND=s3 requires S3_BUCKET")

    assert not await isolation.gate.ensure(named_preview, opener(FakeSession([("preview", DB_ID)])), broken)
    assert isolation.gate.state(named_preview) == "refused: the isolation check could not run"


@pytest.mark.parametrize(
    "url",
    [
        PROD_DB,
        PROD_DIRECT,
        f"postgresql+asyncpg://postgres.{PROD_REF}:pw@{POOLER}/postgres",
        f"postgresql://postgres.{PROD_REF}@aws-0-eu-central-1.pooler.supabase.com:5432/postgres",  # session pooler
    ],
)
def test_a_preview_with_production_resources_never_starts(url):
    with pytest.raises(ValueError, match="points at production"):
        preview(database_url=url)
    with pytest.raises(ValueError, match="points at production"):
        preview(s3_endpoint_url=f"https://{PROD_REF}.supabase.co/storage/v1/s3")


async def test_an_unproven_preview_does_no_start_up_writes(monkeypatch, named_preview):
    """The start-up's housekeeping writes (interrupted jobs, sweeps) wait for the proof."""
    from app import main

    calls: list[str] = []

    async def spy_fail(*args):
        calls.append("fail_interrupted_jobs")
        return 0

    async def spy_forever(*args):
        calls.append("background task")

    monkeypatch.setattr(main, "fail_interrupted_jobs", spy_fail)
    monkeypatch.setattr(main, "sweep_forever", spy_forever)
    monkeypatch.setattr(main, "recover_in_process", spy_forever)
    monkeypatch.setattr(main.settings, "job_backend", "background")
    monkeypatch.setattr(main, "get_storage_provider", lambda: FakeStorage(None))

    answers(monkeypatch, FakeSession(error=RuntimeError("no marker schema")))
    async with main.lifespan(main.app):
        pass
    assert calls == []

    # The control: proven, the same start-up does its housekeeping.
    isolation.gate.reset()
    answers(monkeypatch, FakeSession([("preview", DB_ID)]))
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
    assert "fail_interrupted_jobs" in calls


async def test_an_unproven_preview_worker_does_not_start(monkeypatch, named_preview):
    from app import worker

    built: list[object] = []
    monkeypatch.setattr(worker, "JobRunner", lambda *args: built.append(args))
    monkeypatch.setattr(worker, "get_session_factory", lambda: opener(FakeSession(error=RuntimeError("no marker schema"))))
    monkeypatch.setattr(worker, "get_settings", lambda: named_preview)
    ctx: dict = {}
    with pytest.raises(RuntimeError, match="Preview isolation not proven"):
        await worker.startup(ctx)
    assert "runner" not in ctx and built == []


def test_an_unproven_preview_writes_nothing_through_the_api(monkeypatch, named_preview, api_db):
    answers(monkeypatch, FakeSession(error=RuntimeError("no marker schema")))
    client = TestClient(app)
    for url, body in (
        ("/api/v1/auth/register", {"email": "new@example.com", "password": "a long enough password"}),
        ("/api/v1/documents", {"text": "Hello", "title": "x"}),
    ):
        assert client.post(url, json=body).status_code == 503
    with api_db.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 0
        assert connection.execute(text("SELECT count(*) FROM documents")).scalar() == 0


async def _drop_marker(postgres_sessions):
    async with postgres_sessions() as session:
        await session.execute(text(f"DROP SCHEMA IF EXISTS {isolation.MARKER_SCHEMA} CASCADE"))
        await session.commit()


def _setup_settings() -> Settings:
    return preview(smartdoc_environment="preview-setup", storage_backend="local", expected_db_instance="", expected_storage_instance="")


@pytest.mark.postgres
async def test_on_postgres_a_migrated_database_without_a_marker_is_refused(postgres_sessions):
    # Production as it is: migrated, no smartdoc_identity schema.
    async with postgres_sessions() as session:
        with pytest.raises(isolation.IsolationError, match="database: the identity marker can't be read"):
            await isolation.verify(preview(storage_backend="local", expected_storage_instance=""), session, FakeStorage(None))


@pytest.mark.postgres
async def test_on_postgres_a_wrong_database_id_is_refused(postgres_sessions):
    from scripts import preview_identity

    try:
        await preview_identity.create(_setup_settings(), postgres_sessions, FakeStorage(None))
        wrong = preview(storage_backend="local", expected_db_instance=str(uuid.uuid4()), expected_storage_instance="")
        async with postgres_sessions() as session:
            with pytest.raises(isolation.IsolationError, match="database: the marker names another instance"):
                await isolation.verify(wrong, session, FakeStorage(None))
    finally:
        await _drop_marker(postgres_sessions)


@pytest.mark.postgres
async def test_on_postgres_a_second_marker_row_is_refused(postgres_sessions):
    from scripts import preview_identity

    try:
        database_id, _ = await preview_identity.create(_setup_settings(), postgres_sessions, FakeStorage(None))
        async with postgres_sessions() as session:
            await session.execute(text(f"INSERT INTO {isolation.MARKER_TABLE} (environment, instance_id) VALUES ('preview', :id)"), {"id": database_id})
            await session.commit()
        running = preview(storage_backend="local", expected_db_instance=database_id, expected_storage_instance="")
        async with postgres_sessions() as session:
            with pytest.raises(isolation.IsolationError, match="more than one identity marker"):
                await isolation.verify(running, session, FakeStorage(None))
    finally:
        await _drop_marker(postgres_sessions)


# -- The pin (D-012, owner 2026-10-15): a Vercel Preview of feature/smartdoc-2.0 must prove its isolation even when
# SMARTDOC_ENVIRONMENT is missing. Vercel sets VERCEL_ENV and VERCEL_GIT_COMMIT_REF itself. -----------------------

PINNED = {"VERCEL_ENV": "preview", "VERCEL_GIT_COMMIT_REF": "feature/smartdoc-2.0"}
PREVIEW_DB_TX = "postgresql://postgres.previewref987654@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"


@pytest.fixture
def on_the_pinned_branch(monkeypatch):
    for name, value in PINNED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("SMARTDOC_ENVIRONMENT", raising=False)


def pinned_settings(**overrides) -> Settings:
    """The branch's settings as S6 sets them -- except that SMARTDOC_ENVIRONMENT is missing."""
    values = dict(
        _env_file=None,
        production_db_ref=PROD_REF,
        database_url=PREVIEW_DB_TX,
        storage_backend="s3",
        s3_bucket="smartdoc-preview-files",
        s3_endpoint_url=PREVIEW_S3,
        expected_db_instance=DB_ID,
        expected_storage_instance=STORE_ID,
    )
    values.update(overrides)
    return Settings(**values)


def test_the_pin_is_vercels_preview_of_the_pinned_branch_only(monkeypatch):
    from app.config import pinned_preview

    assert pinned_preview(PINNED)
    assert not pinned_preview({"VERCEL_ENV": "production", "VERCEL_GIT_COMMIT_REF": "feature/smartdoc-2.0"})
    assert not pinned_preview({"VERCEL_ENV": "preview", "VERCEL_GIT_COMMIT_REF": "some-other-branch"})
    assert not pinned_preview({"VERCEL_ENV": "preview"})
    assert not pinned_preview({})


def test_missing_smartdoc_environment_on_the_pinned_branch_still_requires_isolation(on_the_pinned_branch):
    settings = pinned_settings()
    assert settings.smartdoc_environment == "" and isolation.required(settings)


def test_missing_smartdoc_environment_and_every_guard_setting_never_starts(on_the_pinned_branch):
    # Only Vercel's variables say what this is: no reference to tell production apart -> refused.
    with pytest.raises(ValueError, match="PRODUCTION_DB_REF is not set"):
        Settings(_env_file=None, database_url=PREVIEW_DB_TX)


def test_an_inherited_production_database_url_never_starts(on_the_pinned_branch):
    # The branch value forgotten: Vercel falls back to the general Preview value, today production's pooler URL.
    with pytest.raises(ValueError, match="DATABASE_URL points at production"):
        pinned_settings(database_url=PROD_DB)
    with pytest.raises(ValueError, match="DATABASE_URL points at production"):
        pinned_settings(database_url=PROD_DIRECT)


def test_an_inherited_production_storage_endpoint_never_starts(on_the_pinned_branch):
    with pytest.raises(ValueError, match="points at production"):
        pinned_settings(s3_endpoint_url=f"https://{PROD_REF}.storage.supabase.co/storage/v1/s3")


def test_a_missing_expected_storage_instance_never_starts(on_the_pinned_branch):
    with pytest.raises(ValueError, match="EXPECTED_DB_INSTANCE / EXPECTED_STORAGE_INSTANCE"):
        pinned_settings(expected_storage_instance="")


def test_a_missing_database_url_starts_nothing_that_can_serve(monkeypatch, on_the_pinned_branch):
    # No DATABASE_URL at all: the code's default (a database on localhost) -- not production, so the first layer
    # lets it start, but it can't read a marker there: every request is refused.
    settings = get_settings()
    for name, value in dict(database_url=Settings.model_fields["database_url"].default, production_db_ref=PROD_REF, expected_db_instance=DB_ID, storage_backend="local", smartdoc_environment="").items():
        monkeypatch.setattr(settings, name, value)
    isolation.gate.reset()
    answers(monkeypatch, FakeSession(error=OSError("connection refused")))
    client = TestClient(app)
    assert client.get("/api/v1/capabilities").status_code == 503
    body = client.get("/api/health").json()
    assert body["pinned"] == "yes" and body["isolation"].startswith("refused: database")
    isolation.gate.reset()


async def test_a_wrong_expected_db_instance_is_refused_by_the_real_marker_check(on_the_pinned_branch):
    with pytest.raises(isolation.IsolationError, match="another instance"):
        await isolation.verify(pinned_settings(expected_db_instance=str(uuid.uuid4())), FakeSession([("preview", DB_ID)]), store())


async def test_a_wrong_or_unreachable_bucket_is_refused_on_the_pinned_branch(on_the_pinned_branch, two_buckets):
    with pytest.raises(isolation.IsolationError, match="file store: no identity marker"):
        await isolation.verify(pinned_settings(), FakeSession([("preview", DB_ID)]), s3_store("production-files"))
    with pytest.raises(isolation.IsolationError, match="file store: no identity marker"):
        await isolation.verify(pinned_settings(), FakeSession([("preview", DB_ID)]), s3_store("does-not-exist"))
    await isolation.verify(pinned_settings(), FakeSession([("preview", DB_ID)]), s3_store("preview-files"))


@pytest.fixture
def pinned_app(monkeypatch, on_the_pinned_branch):
    """The running app as the pinned branch's Preview with SMARTDOC_ENVIRONMENT missing."""
    settings = get_settings()
    for name, value in dict(smartdoc_environment="", database_url=PREVIEW_DB_TX, production_db_ref=PROD_REF, expected_db_instance=DB_ID, storage_backend="local").items():
        monkeypatch.setattr(settings, name, value)
    isolation.gate.reset()
    yield settings
    isolation.gate.reset()


def test_unproven_the_pinned_backend_refuses_every_request_and_writes_nothing(monkeypatch, pinned_app, api_db):
    answers(monkeypatch, FakeSession(error=RuntimeError("no marker schema")))
    client = TestClient(app)
    assert client.post("/api/v1/auth/register", json={"email": "x@example.com", "password": "a long enough password"}).status_code == 503
    assert client.get("/api/v1/capabilities").status_code == 503
    with api_db.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM users")).scalar() == 0
    body = client.get("/api/health").json()
    assert body["environment"] == "preview" and body["pinned"] == "yes" and body["isolation"].startswith("refused")


def test_proven_the_pinned_backend_serves(monkeypatch, pinned_app):
    answers(monkeypatch, FakeSession([("preview", DB_ID)]))
    client = TestClient(app)
    assert client.get("/api/v1/capabilities").status_code == 200
    assert client.get("/api/health").json()["isolation"] == "verified"


async def test_unproven_the_pinned_start_up_does_no_writes(monkeypatch, pinned_app):
    from app import main

    calls: list[str] = []

    async def spy(*args):
        calls.append("write")
        return 0

    monkeypatch.setattr(main, "fail_interrupted_jobs", spy)
    monkeypatch.setattr(main, "sweep_forever", spy)
    monkeypatch.setattr(main, "recover_in_process", spy)
    monkeypatch.setattr(main.settings, "job_backend", "background")
    monkeypatch.setattr(main, "get_storage_provider", lambda: FakeStorage(None))
    answers(monkeypatch, FakeSession(error=RuntimeError("no marker schema")))
    async with main.lifespan(main.app):
        pass
    assert calls == []


async def test_unproven_the_pinned_worker_takes_no_jobs(monkeypatch, pinned_app):
    from app import worker

    built: list[object] = []
    monkeypatch.setattr(worker, "JobRunner", lambda *args: built.append(args))
    monkeypatch.setattr(worker, "get_session_factory", lambda: opener(FakeSession(error=RuntimeError("no marker schema"))))
    monkeypatch.setattr(worker, "get_settings", lambda: pinned_app)
    ctx: dict = {}
    with pytest.raises(RuntimeError, match="Preview isolation not proven"):
        await worker.startup(ctx)
    assert "runner" not in ctx and built == []


def test_other_branches_and_production_are_not_pinned(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_REF", "some-other-branch")
    assert not isolation.required(Settings(_env_file=None, database_url=PROD_DB))
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_REF", "main")
    assert not isolation.required(Settings(_env_file=None, database_url=PROD_DB))


# -- Secrets never reach a log: a refused setting prints no input (D-012, owner 2026-10-15) ----------------------

SECRET = "Pw-must-not-leak-42"


@pytest.mark.parametrize(
    "values",
    [
        # The guard refusing production's URL (short settings: nothing for pydantic to cut off).
        dict(smartdoc_environment="preview", production_db_ref=PROD_REF, expected_db_instance=DB_ID, database_url=f"postgresql://postgres.{PROD_REF}:{SECRET}@{POOLER}/postgres"),
        # A setting refused for another reason while DATABASE_URL holds a password.
        dict(database_url=f"postgresql://postgres.x:{SECRET}@{POOLER}/postgres", cors_origins="*"),
        dict(database_url=f"postgresql://postgres.x:{SECRET}@{POOLER}/postgres", max_request_size_mb=1, max_upload_size_mb=4),
    ],
)
def test_a_refused_setting_never_prints_the_password(values):
    with pytest.raises(Exception) as caught:
        Settings(_env_file=None, **values)
    assert SECRET not in str(caught.value) and SECRET not in repr(caught.value)
    assert "input_value" not in str(caught.value)


@pytest.mark.parametrize("password", ["Ab12/cd", "Ab12?cd", "Ab12#cd", "Ab12:cd"])
def test_a_password_with_special_characters_survives_as_it_was(password):
    from sqlalchemy.engine import make_url

    settings = Settings(_env_file=None, database_url=f"postgresql://postgres.x:{password}@{POOLER}/postgres")
    assert make_url(settings.database_url).password == password


def test_a_percent_sign_and_an_at_sign_must_be_encoded():
    from sqlalchemy.engine import make_url

    def password(url: str) -> str | None:
        return make_url(Settings(_env_file=None, database_url=url).database_url).password

    # Unencoded, "%" starts an escape and "@" ends the password: both change it. Encoded, they come through.
    assert password(f"postgresql://postgres.x:Ab%2512@{POOLER}/postgres") == "Ab%12"
    assert password(f"postgresql://postgres.x:Ab%4012@{POOLER}/postgres") == "Ab@12"
    assert password(f"postgresql://postgres.x:Ab@12@{POOLER}/postgres") != "Ab@12"


def test_health_and_refusals_never_show_the_address(monkeypatch, named_preview):
    monkeypatch.setattr(named_preview, "database_url", f"postgresql://postgres.previewref987654:{SECRET}@{POOLER}/postgres")
    answers(monkeypatch, FakeSession(error=RuntimeError(f"connection to {POOLER} failed for password {SECRET}")))
    client = TestClient(app)
    refused = client.get("/api/v1/capabilities")
    health = client.get("/api/health")
    for text in (refused.text, health.text):
        assert SECRET not in text and "pooler" not in text and "previewref" not in text
