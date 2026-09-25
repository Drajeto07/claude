"""Every error has one shape, {code, message, details, request_id} (корекции.docx
§49), and every response names its request (X-Request-ID)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.document_service import DocumentService

client = TestClient(app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def signed_in(api_db):
    client.cookies.clear()
    assert client.post("/api/v1/auth/register", json={"email": "errors@example.com", "password": "long enough password"}).status_code == 201
    yield
    client.cookies.clear()


def _document() -> dict:
    return client.post("/api/v1/documents", json={"text": "# Title\n\nA paragraph long enough to be one."}).json()


def test_an_error_has_a_code_a_message_and_the_request_id():
    response = client.get("/api/v1/documents/missing")

    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "message": "Document not found", "details": None, "request_id": response.headers["X-Request-ID"]}


def test_signed_out_and_foreign_origin_errors_say_which_they_are():
    client.cookies.clear()
    assert client.get("/api/v1/documents/missing").json()["code"] == "not_signed_in"

    refused = client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"})
    assert (refused.status_code, refused.json()["code"]) == (403, "cross_site_request")
    assert refused.headers["X-Request-ID"] == refused.json()["request_id"]


def test_a_validation_error_names_the_fields_but_never_echoes_what_was_sent():
    client.cookies.clear()
    response = client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "s3cr3t"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_request" and body["message"]
    assert {tuple(error["loc"]) for error in body["details"]["errors"]} >= {("body", "email")}
    assert "s3cr3t" not in response.text and "not-an-email" not in response.text


def test_a_revision_conflict_says_which_revision_is_current():
    document = _document()

    response = client.patch(f"/api/v1/documents/{document['id']}", json={"title": "New"}, headers={"If-Match": "999"})

    assert response.status_code == 412
    assert response.json()["code"] == "revision_conflict"
    assert response.json()["details"] == {"currentRevision": document["revision"]}


def test_an_unexpected_failure_is_a_plain_500_with_the_request_id(monkeypatch):
    async def broken(self, document_id):
        raise RuntimeError("internal detail that must not reach the caller")

    monkeypatch.setattr(DocumentService, "get", broken)

    response = client.get("/api/v1/documents/any", headers={"X-Request-ID": "trace-123"})

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "Something went wrong on our side. Please try again.",
        "details": None,
        "request_id": "trace-123",
    }
    assert "internal detail" not in response.text


def test_the_request_id_is_the_callers_when_sane_and_new_otherwise():
    assert client.get("/api/health", headers={"X-Request-ID": "abc-123.x_y"}).headers["X-Request-ID"] == "abc-123.x_y"

    for insane in ("has spaces", "x" * 65, "quote\"d"):
        replaced = client.get("/api/health", headers={"X-Request-ID": insane}).headers["X-Request-ID"]
        assert replaced != insane and len(replaced) == 32

    first, second = client.get("/api/health"), client.get("/api/health")
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


def test_the_browser_may_read_the_request_id():
    response = client.get("/api/health", headers={"Origin": "http://localhost:3000"})

    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()
