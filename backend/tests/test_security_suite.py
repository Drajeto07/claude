"""The security regression suite's own checks (tracker TEST-030), over every route the API
has -- read from its OpenAPI schema, so a route added later can't go unchecked:

- IDOR: every route that takes an id answers a user of another workspace exactly as it
  answers an id that doesn't exist (404, the same body), and leaves the owner's
  document, picture, job and template as they were;
- anonymous: every such route needs a signed-in user;
- CSRF: every write refuses a request from another site, before it reaches the route.

The rest of the suite (`pytest -m security`): the malformed-file corpora (test_malformed_files,
test_malformed_pdfs), picture limits (test_picture_limits), the link and field policies
(test_link_policy, test_field_policy), prompt injection, upload checks and limits
(test_security), and the document authorization tests."""

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.main import _allowed_origins, app
from tests.helpers import error_body

pytestmark = pytest.mark.security

_PASSWORD = "long enough password"
_SPEC = app.openapi()
_OPERATIONS = sorted(
    (method.upper(), path) for path, item in _SPEC["paths"].items() for method in item if method in ("get", "post", "put", "patch", "delete")
)
_WITH_IDS = [operation for operation in _OPERATIONS if "{" in operation[1]]
_WRITES = [operation for operation in _OPERATIONS if operation[0] != "GET"]

# What each route that takes an id is sent -- a valid request, so a refusal is the
# ownership check's and not the body's. "property": the one that route names.
_REQUESTS: dict[tuple[str, str], dict] = {
    ("GET", "/api/v1/assets/{asset_id}"): {},
    ("GET", "/api/v1/documents/{document_id}"): {},
    ("DELETE", "/api/v1/documents/{document_id}"): {},
    ("PATCH", "/api/v1/documents/{document_id}"): {"json": {"title": "Hijacked"}},
    ("GET", "/api/v1/documents/{document_id}/compare"): {},
    ("PUT", "/api/v1/documents/{document_id}/content"): {"json": {"elements": []}},
    ("POST", "/api/v1/documents/{document_id}/elements"): {"json": {"elementType": "paragraph", "afterElementId": None, "text": "x"}},
    ("PATCH", "/api/v1/documents/{document_id}/elements/{element_id}/style"): {"json": {"property": "bold", "value": "true"}},
    ("DELETE", "/api/v1/documents/{document_id}/elements/{element_id}/style/{property}"): {"property": "bold"},
    ("GET", "/api/v1/documents/{document_id}/export/docx"): {},
    ("GET", "/api/v1/documents/{document_id}/export/pdf"): {},
    ("POST", "/api/v1/documents/{document_id}/format"): {"data": {"instructionsText": "make it formal"}},
    ("GET", "/api/v1/documents/{document_id}/health"): {},
    ("POST", "/api/v1/documents/{document_id}/pages"): {"json": {"afterElementId": None}},
    ("POST", "/api/v1/documents/{document_id}/proposals/{proposal_id}/accept"): {},
    ("POST", "/api/v1/documents/{document_id}/proposals/{proposal_id}/reject"): {},
    ("POST", "/api/v1/documents/{document_id}/redo"): {},
    ("PATCH", "/api/v1/documents/{document_id}/settings"): {"json": {"property": "pageSize", "value": "Letter"}},
    ("DELETE", "/api/v1/documents/{document_id}/settings/{property}"): {"property": "pageSize"},
    ("POST", "/api/v1/documents/{document_id}/style-analysis"): {},
    ("PUT", "/api/v1/documents/{document_id}/tracked-changes"): {"json": {"choice": "accepted"}},
    ("POST", "/api/v1/documents/{document_id}/undo"): {},
    ("GET", "/api/v1/documents/{document_id}/versions"): {},
    ("GET", "/api/v1/documents/{document_id}/versions/{number}"): {},
    ("POST", "/api/v1/documents/{document_id}/versions/{number}/restore"): {},
    ("GET", "/api/v1/jobs/{job_id}"): {},
    ("POST", "/api/v1/jobs/{job_id}/cancel"): {},
    ("GET", "/api/v1/jobs/{job_id}/file"): {},
    ("GET", "/api/v1/templates/{template_id}"): {},
    ("PUT", "/api/v1/templates/{template_id}"): {"json": {"name": "Hijacked"}, "headers": {"If-Match": '"1"'}},
    ("DELETE", "/api/v1/templates/{template_id}"): {},
    ("POST", "/api/v1/templates/{template_id}/duplicate"): {"json": {"name": "Copied"}},
    ("GET", "/api/v1/templates/{template_id}/versions"): {},
    ("POST", "/api/v1/templates/{template_id}/versions/{number}/restore"): {},
}
_MISSING = {"document_id": "does-not-exist", "asset_id": "does-not-exist", "job_id": "does-not-exist", "template_id": "does-not-exist"}


def _client(email: str | None = None) -> TestClient:
    client = TestClient(app, base_url="https://testserver")
    if email:
        assert client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD}).status_code == 201
    return client


def _png() -> str:
    buffer = io.BytesIO()
    PILImage.new("RGB", (4, 3), (10, 120, 200)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


@pytest.fixture
def alice(api_db) -> tuple[TestClient, dict[str, str]]:
    """Alice, with a document holding a picture, a finished job and a template of her own."""
    client = _client("alice@example.com")
    document = client.post("/api/v1/documents", json={"text": "# Private\n\nAlice's confidential paragraph."}).json()
    picture = {"type": "image", "content": "", "order": 9, "image": {"src": _png()}}
    saved = client.put(f"/api/v1/documents/{document['id']}/content", json={"elements": document["elements"] + [picture]}).json()
    asset = next(element["image"]["assetId"] for element in saved["elements"] if element["type"] == "image")
    job = client.post("/api/v1/jobs/import-text", json={"text": "# Job\n\nText of a job.", "title": "Job"}).json()
    template = client.post("/api/v1/templates", json={"name": "Alice's house style"}).json()
    assert job["status"] == "succeeded" and template["id"]
    return client, {"document_id": document["id"], "asset_id": asset, "job_id": job["id"], "template_id": template["id"]}


def _send(client: TestClient, method: str, path: str, ids: dict[str, str]):
    request = _REQUESTS[(method, path)]
    values = {"element_id": "el", "proposal_id": "p", "number": "1", "property": request.get("property", "x"), **ids}
    return client.request(method, path.format(**values), json=request.get("json"), data=request.get("data"), headers=request.get("headers"))


def _state(client: TestClient, ids: dict[str, str]) -> dict:
    return {
        "document": client.get(f"/api/v1/documents/{ids['document_id']}").json(),
        "versions": client.get(f"/api/v1/documents/{ids['document_id']}/versions").json(),
        "asset": client.get(f"/api/v1/assets/{ids['asset_id']}").content,
        "job": client.get(f"/api/v1/jobs/{ids['job_id']}").json(),
        "template": client.get(f"/api/v1/templates/{ids['template_id']}").json(),
    }


def test_every_route_that_takes_an_id_is_checked():
    """A route added later gets a request here, or this fails."""
    assert sorted(_REQUESTS) == _WITH_IDS


@pytest.mark.parametrize(("method", "path"), _WITH_IDS)
def test_another_workspaces_resource_looks_exactly_like_a_missing_one(alice, method, path):
    _, ids = alice
    bob = _client("bob@example.com")

    foreign, missing = _send(bob, method, path, ids), _send(bob, method, path, _MISSING)

    assert foreign.status_code == missing.status_code == 404, (foreign.status_code, foreign.text[:200])
    assert error_body(foreign) == error_body(missing)


def test_foreign_requests_leave_the_owners_resources_as_they_were(alice):
    owner, ids = alice
    before = _state(owner, ids)
    bob = _client("bob@example.com")

    for method, path in _WITH_IDS:
        _send(bob, method, path, ids)

    assert _state(owner, ids) == before


@pytest.mark.parametrize(("method", "path"), _WITH_IDS)
def test_every_route_that_takes_an_id_needs_a_signed_in_user(alice, method, path):
    _, ids = alice
    assert _send(_client(), method, path, ids).status_code == 401


@pytest.mark.parametrize(("method", "path"), _WRITES)
def test_every_write_refuses_another_site(alice, method, path):
    owner, ids = alice
    target = path.format(**{"element_id": "el", "proposal_id": "p", "number": "1", "property": "bold", **ids})

    refused = owner.request(method, target, headers={"Origin": "https://evil.example"})

    assert (refused.status_code, refused.json()["code"]) == (403, "cross_site_request")


def test_the_apps_own_site_and_requests_without_an_origin_are_let_through(alice):
    owner, ids = alice
    renamed = owner.patch(f"/api/v1/documents/{ids['document_id']}", json={"title": "Renamed"}, headers={"Origin": _allowed_origins[0]})
    assert renamed.status_code == 200
    assert owner.patch(f"/api/v1/documents/{ids['document_id']}", json={"title": "Again"}).status_code == 200
