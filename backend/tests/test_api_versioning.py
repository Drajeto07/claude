"""API versioning and probes (корекции.docx §48, §67): /api/v1 is the contract;
the unversioned /api paths still answer, as deprecated aliases that say where
they moved; /api/health and /api/ready are for the infrastructure."""

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.session import get_db
from app.main import app

client = TestClient(app, base_url="https://testserver")


def _register(email: str):
    return client.post("/api/v1/auth/register", json={"email": email, "password": "long enough password"})


def test_the_api_lives_under_v1(api_db):
    client.cookies.clear()
    assert _register("versioned@example.com").status_code == 201

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200 and response.json()["email"] == "versioned@example.com"
    assert "Deprecation" not in response.headers


def test_the_old_paths_still_answer_and_say_where_they_moved(api_db):
    client.cookies.clear()
    _register("legacy@example.com")

    response = client.get("/api/auth/me")

    assert response.status_code == 200 and response.json()["email"] == "legacy@example.com"
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Link"] == '</api/v1/auth/me>; rel="successor-version"'


def test_the_schema_describes_v1_only():
    paths = client.get("/openapi.json").json()["paths"]

    assert paths and all(path.startswith("/api/v1/") or path in ("/api/health", "/api/ready") for path in paths)
    assert "/api/v1/documents/{document_id}" in paths and "/api/documents/{document_id}" not in paths


def test_the_probes(api_db):
    assert client.get("/api/health").json() == {"status": "ok"}
    ready = client.get("/api/ready")
    assert (ready.status_code, ready.json()) == (200, {"status": "ready", "checks": {"database": "ok"}})
    assert "Deprecation" not in ready.headers


def test_not_ready_while_the_database_is_away(api_db):
    class Unreachable:
        async def execute(self, statement):
            raise ConnectionRefusedError("the database is down")

    async def unreachable_db():
        yield Unreachable()

    app.dependency_overrides[get_db] = unreachable_db
    try:
        response = client.get("/api/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert (response.status_code, response.json()) == (503, {"status": "unavailable", "checks": {"database": "unavailable"}})


def test_not_ready_while_redis_is_away_when_it_is_used(api_db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")  # nothing listens there

    response = client.get("/api/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "unavailable"}
