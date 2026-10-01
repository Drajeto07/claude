"""Plan limits hold when requests race (tracker PLAN-003). A check that counts and
the use it allows are one step: the check right before a new document, a new
template or a pasted picture's bytes holds the workspace until that use is
committed, so a second request at the same moment waits, then counts the first
one's -- two can't both pass a limit with room for one.

The race is run on two real connections to one SQLite file, and to PostgreSQL when
SMARTDOC_TEST_POSTGRES_URL names one (TEST-031; CI's migrations job): the second
check must wait while the first transaction is open, and be refused once it commits."""

import asyncio
import base64
import io

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.billing.plans import FREE, PLANS
from app.db.base import Base
from app.db.models import DocumentAsset
from app.db.models import Template as TemplateRow
from app.db.session import make_engine
from app.main import app
from app.models.document import Document, DocumentMetadata
from app.repositories.document_repository import DocumentRepository
from app.services import entitlements_service
from app.services.auth_service import AuthService
from app.services.entitlements_service import EntitlementsService, PlanLimitError
from tests.conftest import _enable_sqlite_fk

client = TestClient(app, base_url="https://testserver")


def _free_plan(monkeypatch, **limits) -> None:
    free = PLANS[FREE]
    monkeypatch.setitem(PLANS, FREE, free.model_copy(update={"entitlements": free.entitlements.model_copy(update=limits)}))


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def race_database(request):
    """Where the race runs: None for a SQLite file (two_connections makes it), else
    PostgreSQL's sessions (TEST-031), where the hold is a row lock. Asked for here,
    outside the event loop, since an async fixture can't set another one up."""
    return request.getfixturevalue("postgres_sessions") if request.param == "postgres" else None


@pytest_asyncio.fixture
async def two_connections(race_database, tmp_path):
    """A session factory, a new connection for each session, and a signed-up user's
    workspace in it."""
    engine = None
    if race_database is not None:
        sessions = race_database
    else:
        path = tmp_path / "race.db"
        sync_engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(sync_engine)
        sync_engine.dispose()
        engine = make_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
        event.listen(engine.sync_engine, "connect", _enable_sqlite_fk)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        user = await AuthService(session).register("race@example.com", "long enough password", None)
        workspace_id = await AuthService(session).default_workspace_id(user.id)
        await session.commit()
    yield sessions, workspace_id, user.id
    if engine is not None:
        await engine.dispose()


async def _new_document(session, workspace_id: str, user_id: str) -> None:
    await DocumentRepository(session).create(workspace_id, Document(metadata=DocumentMetadata(title="Taken"), elements=[]), created_by=user_id)


async def _new_template(session, workspace_id: str, user_id: str) -> None:
    session.add(TemplateRow(workspace_id=workspace_id, created_by=user_id, name="Taken", style_system={}, rules=[]))
    await session.flush()


async def _stored_bytes(session, workspace_id: str, _user_id: str) -> None:
    session.add(DocumentAsset(workspace_id=workspace_id, storage_key="race/picture", content_type="image/png", size_bytes=700_000))
    await session.flush()


# Each limit set to room for one more, the check before that use, and the use.
_RACES = {
    "documents": ({"maxDocuments": 1}, lambda plans, workspace_id: plans.check_new_document(workspace_id, hold=True), _new_document),
    "templates": ({"maxTemplates": 1}, lambda plans, workspace_id: plans.check_new_template(workspace_id, hold=True), _new_template),
    "storage": ({"maxStorageMb": 1}, lambda plans, workspace_id: plans.check_storage(workspace_id, 700_000, hold=True), _stored_bytes),
}


@pytest.mark.parametrize("kind", sorted(_RACES))
async def test_two_requests_at_once_can_t_both_pass_a_limit_with_room_for_one(monkeypatch, two_connections, kind):
    sessions, workspace_id, user_id = two_connections
    limits, check, use = _RACES[kind]
    _free_plan(monkeypatch, **limits)

    async with sessions() as first, sessions() as second:
        await check(EntitlementsService(first), workspace_id)
        await use(first, workspace_id, user_id)
        racing = asyncio.create_task(check(EntitlementsService(second), workspace_id))
        await asyncio.sleep(0.5)
        assert not racing.done(), "the second check didn't wait for the first one's use"

        await first.commit()
        with pytest.raises(PlanLimitError):
            await asyncio.wait_for(racing, timeout=10)


def _png() -> str:
    buffer = io.BytesIO()
    PILImage.new("RGB", (4, 3), (10, 120, 200)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def test_the_checks_right_before_a_use_hold_the_workspace_and_an_ordinary_save_doesn_t(monkeypatch, api_db):
    held: list[str] = []
    real = entitlements_service.hold_workspace

    async def spy(session, workspace_id):
        held.append(workspace_id)
        await real(session, workspace_id)

    monkeypatch.setattr(entitlements_service, "hold_workspace", spy)
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "held@example.com", "password": "long enough password"}).status_code == 201

    def holds(send) -> int:
        before = len(held)
        assert send().status_code in (200, 201)
        return len(held) - before

    document = client.post("/api/v1/documents", json={"text": "# Held\n\nA paragraph."})
    assert document.status_code == 201 and len(held) >= 1
    document = document.json()
    path = f"/api/v1/documents/{document['id']}/content"
    typed = dict(document["elements"][1], content="Typed.", inline=[{"text": "Typed.", "marks": []}])
    picture = {"type": "image", "content": "", "order": 2, "image": {"src": _png()}}

    assert holds(lambda: client.put(path, json={"elements": [document["elements"][0], typed]})) == 0
    assert holds(lambda: client.put(path, json={"elements": [document["elements"][0], typed, picture]})) >= 1
    assert holds(lambda: client.post("/api/v1/templates", json={"name": "Held style"})) >= 1
    assert len(set(held)) == 1  # the user's own workspace, every time
    client.cookies.clear()
