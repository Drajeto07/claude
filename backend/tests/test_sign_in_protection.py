"""Suspicious sign-ins (tracker ACCT-007): no lockout, a growing wait after wrong passwords
for one account, and an e-mail when the account is signed in to from a browser it hadn't
been used from. Nothing here really waits: the conftest records the waits instead."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.auth import DEVICE_COOKIE
from app.config import get_settings
from app.db.models import KnownBrowser
from app.main import app
from app.security import sign_in_delay

pytestmark = pytest.mark.security  # the security regression suite (TEST-030)

_PASSWORD = "long enough password"
_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver", headers={"User-Agent": _CHROME})


@pytest.fixture
def judy(api_db, monkeypatch) -> TestClient:
    monkeypatch.setattr(get_settings(), "rate_limit_login_account", "100/minute")  # the waits, not the limit, under test
    client = _client()
    assert client.post("/api/v1/auth/register", json={"email": "judy@example.com", "password": _PASSWORD}).status_code == 201
    return client


def _login(client: TestClient, password: str, email: str = "judy@example.com") -> int:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code


def test_wrong_passwords_make_each_next_try_wait_longer_up_to_a_bound(judy, sign_in_waits):
    assert [_login(_client(), "wrong guess") for _ in range(8)] == [401] * 8

    # Three free, then 1, 2, 4, 8 seconds, and never more than the cap.
    assert sign_in_waits == [1.0, 2.0, 4.0, 8.0, 8.0]


def test_no_lockout_the_right_password_still_gets_in_and_clears_the_count(judy, sign_in_waits):
    for _ in range(10):
        _login(_client(), "wrong guess")
    waited = len(sign_in_waits)

    assert _login(_client(), _PASSWORD) == 200
    assert len(sign_in_waits) == waited + 1  # it waited too: a quick answer gives nothing away
    assert _login(_client(), "wrong guess") == 401
    assert len(sign_in_waits) == waited + 1  # and the count started again


def test_an_address_without_an_account_waits_the_same(api_db, sign_in_waits):
    for _ in range(5):
        _login(_client(), "wrong guess", email="nobody@example.com")

    assert sign_in_waits == [1.0, 2.0]


def test_failures_are_forgotten_after_the_window(judy, sign_in_waits, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(sign_in_delay, "clock", lambda: now[0])
    for _ in range(4):
        _login(_client(), "wrong guess")
    assert sign_in_waits == [1.0]

    now[0] += get_settings().sign_in_failure_window_minutes * 60 + 1
    _login(_client(), "wrong guess")

    assert sign_in_waits == [1.0]


def test_a_wrong_password_when_changing_it_or_deleting_the_account_counts_too(judy, sign_in_waits):
    judy.put("/api/v1/auth/password", json={"currentPassword": "wrong guess", "newPassword": "a brand new password"})
    judy.request("DELETE", "/api/v1/auth/account", json={"password": "wrong guess"})
    _login(_client(), "wrong guess")

    assert _login(_client(), "wrong guess") == 401
    assert sign_in_waits == [1.0]


def test_the_wait_has_its_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "sign_in_free_failures", 5)
    monkeypatch.setattr(settings, "sign_in_max_delay_seconds", 3.0)

    assert [sign_in_delay.delay_for(failures) for failures in range(9)] == [0, 0, 0, 0, 0, 1, 2, 3, 3]


def test_a_sign_in_from_a_new_browser_is_e_mailed_without_its_address(judy, sent_mail):
    assert _login(_client(), _PASSWORD) == 200

    [notice] = [message for message in sent_mail if message.kind == "new_browser_sign_in"]
    assert notice.to == "judy@example.com"
    assert "Chrome on Windows" in notice.text and " UTC" in notice.text
    assert "testclient" not in notice.text and "/settings/account" in notice.text and "/forgot-password" in notice.text


def test_the_browser_the_account_was_made_in_and_one_it_was_used_from_send_nothing(judy, sent_mail):
    assert judy.post("/api/v1/auth/logout").status_code == 204
    assert _login(judy, _PASSWORD) == 200

    laptop = _client()
    assert _login(laptop, _PASSWORD) == 200
    assert laptop.post("/api/v1/auth/logout").status_code == 204
    assert _login(laptop, _PASSWORD) == 200

    assert len([message for message in sent_mail if message.kind == "new_browser_sign_in"]) == 1  # the laptop's first


def test_a_browser_known_to_one_account_is_new_to_another(judy, sent_mail):
    other = _client()
    assert other.post("/api/v1/auth/register", json={"email": "ken@example.com", "password": _PASSWORD}).status_code == 201

    assert _login(other, _PASSWORD) == 200  # Judy's account, from Ken's browser

    assert [message.to for message in sent_mail if message.kind == "new_browser_sign_in"] == ["judy@example.com"]


def test_the_device_cookie_is_random_long_lived_and_kept_only_as_a_hash(judy, api_db):
    cookie = next(header for header in judy.cookies.jar if header.name == DEVICE_COOKIE)
    signed_in = _client().post("/api/v1/auth/login", json={"email": "judy@example.com", "password": _PASSWORD})
    set_cookie = next(value for value in signed_in.headers.get_list("set-cookie") if value.startswith(f"{DEVICE_COOKIE}="))

    assert len(cookie.value) == 43
    assert "HttpOnly" in set_cookie and "Secure" in set_cookie and f"Max-Age={400 * 24 * 3600}" in set_cookie
    with api_db.connect() as connection:
        stored = list(connection.scalars(select(KnownBrowser.device_hash)))
    assert len(stored) == 2 and cookie.value not in stored


def test_a_device_cookie_that_isnt_ours_is_replaced(judy, sent_mail):
    forged = _client()
    # Where the test client keeps the server's cookies, so it is the one sent.
    forged.cookies.set(DEVICE_COOKIE, "not-one-of-ours", domain="testserver.local")

    signed_in = forged.post("/api/v1/auth/login", json={"email": "judy@example.com", "password": _PASSWORD})

    assert signed_in.status_code == 200
    assert signed_in.cookies.get(DEVICE_COOKIE) not in (None, "not-one-of-ours")
    assert len([message for message in sent_mail if message.kind == "new_browser_sign_in"]) == 1
