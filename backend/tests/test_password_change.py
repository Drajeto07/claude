"""Changing a password (tracker ACCT-004): the current one first, then the account is
signed out everywhere but here, and its owner told."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.helpers import error_body

pytestmark = pytest.mark.security  # the security regression suite (TEST-030)

_PASSWORD = "long enough password"
_NEW = "an entirely new passphrase"


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def frank(api_db) -> TestClient:
    client = _client()
    assert client.post("/api/v1/auth/register", json={"email": "frank@example.com", "password": _PASSWORD}).status_code == 201
    return client


def _change(client: TestClient, current: str, new: str = _NEW):
    return client.put("/api/v1/auth/password", json={"currentPassword": current, "newPassword": new})


def _signs_in(password: str) -> bool:
    return _client().post("/api/v1/auth/login", json={"email": "frank@example.com", "password": password}).status_code == 200


def test_the_new_password_takes_the_current_one_and_ends_every_other_session(frank, sent_mail):
    elsewhere = _client()
    assert elsewhere.post("/api/v1/auth/login", json={"email": "frank@example.com", "password": _PASSWORD}).status_code == 200

    changed = _change(frank, _PASSWORD)

    assert changed.status_code == 204
    assert frank.get("/api/v1/auth/me").status_code == 200  # this browser stays signed in
    assert elsewhere.get("/api/v1/auth/me").status_code == 401
    assert not _signs_in(_PASSWORD) and _signs_in(_NEW)
    [notice] = [message for message in sent_mail if message.kind == "password_changed"]
    assert notice.to == "frank@example.com" and "every other browser" in notice.text


def test_a_wrong_current_password_changes_nothing(frank, sent_mail):
    elsewhere = _client()
    assert elsewhere.post("/api/v1/auth/login", json={"email": "frank@example.com", "password": _PASSWORD}).status_code == 200

    refused = _change(frank, "not my password")

    assert (refused.status_code, error_body(refused)["code"]) == (400, "wrong_password")
    assert _signs_in(_PASSWORD) and not _signs_in(_NEW)
    assert elsewhere.get("/api/v1/auth/me").status_code == 200
    assert not [message for message in sent_mail if message.kind == "password_changed"]


def test_it_is_for_the_signed_in_and_counted_with_sign_ins(frank, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_login_account", "2/minute")

    assert _change(_client(), _PASSWORD).status_code == 401
    assert [_change(frank, "wrong guess").status_code for _ in range(3)] == [400, 400, 429]
    assert _change(frank, "too short", "short").status_code == 422
