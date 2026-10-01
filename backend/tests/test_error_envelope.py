"""Every error the API sends (tracker SEC-019) is {code, message, details, request_id}: a
message written for people -- never a trace, an exception's own text or what was sent --
a code to branch on, and the request id the log can be searched by. Checked over every
route in the OpenAPI schema, and for the kinds of error a route doesn't choose: an
unknown path, a wrong method, a body that isn't valid, one too large, and a crash."""

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import document_service as document_service_module

pytestmark = pytest.mark.security

_SPEC = app.openapi()
_OPERATIONS = sorted(
    (method.upper(), path) for path, item in _SPEC["paths"].items() for method in item if method in ("get", "post", "put", "patch", "delete")
)
# What an error message is never: a trace, pydantic's own report, an echo of the input.
_NEVER = re.compile(r"Traceback|File \"|line \d+, in|errors\.pydantic\.dev|input_value|input_type|validation errors? for|\bat 0x[0-9a-f]+", re.I)


def _client(email: str | None = None) -> TestClient:
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    if email:
        assert client.post("/api/v1/auth/register", json={"email": email, "password": "long enough password"}).status_code == 201
    return client


def _envelope(response) -> dict:
    """The body, checked to be an envelope and nothing else."""
    body = response.json()
    assert set(body) == {"code", "message", "details", "request_id"}, body
    assert isinstance(body["code"], str) and re.fullmatch(r"[a-z_]+", body["code"]), body
    assert isinstance(body["message"], str) and body["message"].strip() and not _NEVER.search(body["message"]), body
    assert body["request_id"] and body["request_id"] == response.headers["x-request-id"], body
    if body["details"] is not None:
        assert not _NEVER.search(str(body["details"])), body
    return body


@pytest.mark.parametrize(("method", "path"), _OPERATIONS)
def test_every_route_answers_an_error_with_the_envelope(api_db, method, path):
    signed_in, anonymous = _client("envelope@example.com"), _client()
    target = re.sub(r"\{[^}]+\}", "does-not-exist", path)
    junk = {"json": {"__junk__": [1, {"deep": None}]}} if method != "GET" else {}
    for client in (anonymous, signed_in):
        response = client.request(method, target, **junk)
        if response.status_code >= 400:
            _envelope(response)


def test_the_errors_a_route_doesnt_choose_are_envelopes_too(api_db):
    client = _client("kinds@example.com")
    assert _envelope(client.get("/api/v1/no-such-thing"))["code"] == "not_found"
    assert _envelope(client.delete("/api/v1/capabilities"))["code"] == "method_not_allowed"
    invalid = client.post("/api/v1/documents", json={"text": 42, "title": ["not", "a", "title"]})
    body = _envelope(invalid)
    assert (invalid.status_code, body["code"]) == (422, "invalid_request")
    assert all(set(error) == {"loc", "msg", "type"} for error in body["details"]["errors"])  # where and what, never the value
    password = client.post("/api/v1/auth/register", json={"email": "someone@example.com", "password": "hunter2"})
    assert password.status_code == 422 and "hunter2" not in password.text
    too_large = client.post("/api/v1/documents", content=b"x", headers={"Content-Length": str(10**12), "Content-Type": "application/json"})
    assert _envelope(too_large)["code"] == "too_large"


def test_a_crash_is_a_plain_500_with_nothing_of_the_crash_in_it(api_db, monkeypatch):
    client = _client("crash@example.com")

    async def crash(*_, **__):
        raise RuntimeError("secret internal detail in C:/app/services/document_service.py")

    monkeypatch.setattr(document_service_module.DocumentService, "summaries", crash)
    response = client.get("/api/v1/documents")

    assert response.status_code == 500, response.text[:200]
    body = _envelope(response)
    assert body["code"] == "internal_error" and "secret" not in response.text and "document_service" not in response.text


def test_invalid_conflict_resolutions_say_where_not_what_was_sent(api_db):
    client = _client("resolutions@example.com")
    document = client.post("/api/v1/documents", json={"text": "# Title\n\nSome text."}).json()

    response = client.post(f"/api/v1/documents/{document['id']}/format", data={"resolutions": '[{"elementId": "private words here"}]'})

    body = _envelope(response)
    assert (response.status_code, body["code"]) == (422, "invalid_request") and "private words here" not in response.text
    assert body["details"]["errors"] and all(set(error) == {"loc", "msg", "type"} for error in body["details"]["errors"])
