import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Document as DocumentRow
from app.main import app
from tests.helpers import error_body

_PASSWORD = "long enough password"

# (method, path, json body). "{id}" is the target document; element-level routes
# use a made-up element id -- the document-level check has to fail first anyway.
_DOCUMENT_ROUTES = [
    ("GET", "/api/v1/documents/{id}", None),
    ("DELETE", "/api/v1/documents/{id}", None),
    ("PATCH", "/api/v1/documents/{id}", {"title": "Hijacked"}),
    ("POST", "/api/v1/documents/{id}/format", None),
    ("POST", "/api/v1/documents/{id}/undo", None),
    ("POST", "/api/v1/documents/{id}/redo", None),
    ("PATCH", "/api/v1/documents/{id}/elements/el/style", {"property": "bold", "value": "true"}),
    ("DELETE", "/api/v1/documents/{id}/elements/el/style/bold", None),
    ("PUT", "/api/v1/documents/{id}/content", {"elements": []}),
    ("POST", "/api/v1/documents/{id}/pages", {"afterElementId": None}),
    ("POST", "/api/v1/documents/{id}/elements", {"elementType": "paragraph", "afterElementId": None, "text": "x"}),
    ("PATCH", "/api/v1/documents/{id}/settings", {"property": "pageSize", "value": "Letter"}),
    ("DELETE", "/api/v1/documents/{id}/settings/pageSize", None),
    ("POST", "/api/v1/documents/{id}/style-analysis", None),
    ("GET", "/api/v1/documents/{id}/export/docx", None),
    ("GET", "/api/v1/documents/{id}/export/pdf", None),
]


def _signed_in_client(email: str) -> TestClient:
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD}).status_code == 201
    return client


@pytest.fixture
def alice(api_db):
    return _signed_in_client("alice@example.com")


@pytest.fixture
def bob(api_db):
    return _signed_in_client("bob@example.com")


@pytest.fixture
def alices_document(alice) -> dict:
    response = alice.post("/api/v1/documents", json={"text": "# Private\n\nAlice's confidential paragraph text."})
    assert response.status_code == 201
    return response.json()


def _call(client: TestClient, method: str, path: str, body: dict | None, document_id: str):
    return client.request(method, path.format(id=document_id), json=body)


@pytest.mark.parametrize(("method", "path", "body"), _DOCUMENT_ROUTES)
def test_anonymous_requests_are_rejected(api_db, alices_document, method, path, body):
    anonymous = TestClient(app, base_url="https://testserver")

    assert _call(anonymous, method, path, body, alices_document["id"]).status_code == 401


def test_anonymous_create_and_upload_are_rejected(api_db):
    anonymous = TestClient(app, base_url="https://testserver")

    assert anonymous.post("/api/v1/documents", json={"text": "hello there"}).status_code == 401
    upload = anonymous.post("/api/v1/documents/upload", files={"file": ("a.txt", b"hello there", "text/plain")})
    assert upload.status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), _DOCUMENT_ROUTES)
def test_another_users_document_looks_exactly_like_a_missing_one(alices_document, bob, method, path, body):
    foreign = _call(bob, method, path, body, alices_document["id"])
    missing = _call(bob, method, path, body, "does-not-exist")

    assert foreign.status_code == missing.status_code == 404
    assert error_body(foreign) == error_body(missing)


def test_failed_foreign_writes_leave_the_owners_document_untouched(alice, alices_document, bob):
    for method, path, body in _DOCUMENT_ROUTES:
        _call(bob, method, path, body, alices_document["id"])

    after = alice.get(f"/api/v1/documents/{alices_document['id']}")
    assert after.status_code == 200
    assert after.json() == alices_document


def test_new_documents_belong_to_the_creators_workspace(api_db, alice, alices_document):
    me = alice.get("/api/v1/auth/me").json()

    with OrmSession(api_db) as db:
        row = db.get(DocumentRow, alices_document["id"])
    assert (row.workspace_id, row.created_by) == (me["workspaceId"], me["id"])
