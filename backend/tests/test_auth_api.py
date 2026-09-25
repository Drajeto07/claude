from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import SESSION_COOKIE
from app.db.models import Session as SessionRow
from app.db.models import User, WorkspaceMember
from app.main import app
from tests.helpers import error_body

_CREDENTIALS = {"email": "Boril@Example.com", "password": "correct horse battery"}


@pytest.fixture
def client(api_db):
    # https base URL: the session cookie is Secure, and a cookie jar never sends
    # a Secure cookie back over plain http.
    return TestClient(app, base_url="https://testserver")


def _register(client, **overrides):
    return client.post("/api/v1/auth/register", json={**_CREDENTIALS, **overrides})


def test_register_creates_user_personal_workspace_and_signs_in(client, api_db):
    response = _register(client, fullName="Boril")

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "boril@example.com"
    assert body["fullName"] == "Boril"
    with OrmSession(api_db) as db:
        user = db.execute(select(User)).scalar_one()
        membership = db.execute(select(WorkspaceMember)).scalar_one()
    assert user.hashed_password.startswith("$argon2id$")
    assert _CREDENTIALS["password"] not in user.hashed_password
    assert (membership.user_id, membership.workspace_id, membership.role) == (user.id, body["workspaceId"], "owner")
    assert client.get("/api/v1/auth/me").json()["id"] == user.id


def test_session_cookie_is_httponly_secure_lax(client):
    cookie_header = _register(client).headers["set-cookie"].lower()

    assert f"{SESSION_COOKIE}=" in cookie_header
    assert "httponly" in cookie_header
    assert "secure" in cookie_header
    assert "samesite=lax" in cookie_header
    assert "path=/" in cookie_header


def test_only_the_token_hash_is_stored(client, api_db):
    _register(client)
    token = client.cookies[SESSION_COOKIE]

    with OrmSession(api_db) as db:
        stored = db.execute(select(SessionRow.token_hash)).scalar_one()
    assert token not in stored
    assert len(stored) == 64


def test_duplicate_email_is_rejected_case_insensitively(client):
    assert _register(client).status_code == 201
    client.cookies.clear()

    response = _register(client, email="BORIL@example.COM")

    assert response.status_code == 409


@pytest.mark.parametrize(
    "overrides", [{"password": "short"}, {"email": "not-an-email"}, {"password": "x" * 257}]
)
def test_register_validates_input(client, overrides):
    assert _register(client, **overrides).status_code == 422


def test_me_requires_a_session(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_with_correct_password_signs_in(client):
    _register(client)
    client.cookies.clear()

    response = client.post("/api/v1/auth/login", json=_CREDENTIALS)

    assert response.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_wrong_password_and_unknown_email_get_the_same_answer(client):
    _register(client)
    client.cookies.clear()

    wrong_password = client.post("/api/v1/auth/login", json={**_CREDENTIALS, "password": "wrong password"})
    unknown_email = client.post("/api/v1/auth/login", json={**_CREDENTIALS, "email": "nobody@example.com"})

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert error_body(wrong_password) == error_body(unknown_email)
    assert SESSION_COOKIE not in client.cookies


def test_logout_revokes_the_session_server_side(client, api_db):
    _register(client)
    token = client.cookies[SESSION_COOKIE]

    assert client.post("/api/v1/auth/logout").status_code == 204

    # Replaying the old token must fail even if a client kept it around.
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/api/v1/auth/me").status_code == 401
    with OrmSession(api_db) as db:
        assert db.execute(select(SessionRow.revoked_at)).scalar_one() is not None


def test_logout_without_a_session_is_harmless(client):
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_expired_session_is_rejected(client, api_db):
    _register(client)
    with OrmSession(api_db) as db:
        db.execute(update(SessionRow).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        db.commit()

    assert client.get("/api/v1/auth/me").status_code == 401


def test_deactivated_user_loses_existing_session_and_cannot_log_in(client, api_db):
    _register(client)
    with OrmSession(api_db) as db:
        db.execute(update(User).values(is_active=False))
        db.commit()

    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.clear()
    assert client.post("/api/v1/auth/login", json=_CREDENTIALS).status_code == 401


def test_cross_site_write_is_rejected_before_reaching_the_route(client):
    response = client.post("/api/v1/auth/login", json=_CREDENTIALS, headers={"Origin": "https://evil.example"})

    assert response.status_code == 403


def test_write_from_the_frontend_origin_is_allowed(client):
    response = client.post("/api/v1/auth/register", json=_CREDENTIALS, headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 201
