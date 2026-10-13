"""E-mail off (EMAIL_BACKEND=disabled, the Vercel image's default until a sending domain
exists -- RELEASE): the app never says it sent a link. The API says whether e-mail can
arrive, refuses a password reset or another confirmation link with 503 -- the same for
every address -- and signing up, signing in and the rest go on working without mail."""

import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.mail import DisabledSender, EmailDeliveryError, EmailMessage, OutboxSender, SmtpSender, get_email_sender
from tests.helpers import error_body

_PASSWORD = "long enough password"


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def email_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "email_backend", "disabled")


@pytest.fixture
def dana(api_db) -> TestClient:
    client = _client()
    assert client.post("/api/v1/auth/register", json={"email": "dana@example.com", "password": _PASSWORD}).status_code == 201
    return client


def test_the_api_says_whether_e_mail_arrives(api_db, monkeypatch):
    client = _client()  # signed out: the sign-in page asks
    assert client.get("/api/v1/auth/email-delivery").json() == {"available": True}  # the development outbox

    monkeypatch.setattr(get_settings(), "email_backend", "disabled")
    assert client.get("/api/v1/auth/email-delivery").json() == {"available": False}


def test_no_password_reset_is_promised_for_any_address(api_db, dana, email_off, sent_mail):
    answers = [_client().post("/api/v1/auth/password-reset", json={"email": email}) for email in ("dana@example.com", "nobody@example.com")]

    for answer in answers:
        assert answer.status_code == 503
        body = error_body(answer)
        assert body["code"] == "unavailable"
        assert "isn't available yet" in body["message"] and "sent" not in body["message"]
    assert error_body(answers[0])["message"] == error_body(answers[1])["message"]  # tells no one which address has an account
    assert sent_mail == [] or all(message.kind != "password_reset" for message in sent_mail)


def test_no_confirmation_link_is_promised(api_db, dana, email_off):
    answer = dana.post("/api/v1/auth/verify-email")

    assert answer.status_code == 503
    assert "isn't available yet" in error_body(answer)["message"]
    assert dana.get("/api/v1/auth/me").json()["emailVerified"] is False


def test_signing_up_and_in_work_without_e_mail(api_db, monkeypatch):
    # The real sender this time (no MemorySender): every message the account would get fails quietly.
    monkeypatch.setattr(get_settings(), "email_backend", "disabled")
    app.dependency_overrides.pop(get_email_sender, None)

    client = _client()
    assert client.post("/api/v1/auth/register", json={"email": "erin@example.com", "password": _PASSWORD}).status_code == 201
    assert client.post("/api/v1/auth/logout").status_code == 204
    fresh = _client()  # a browser the account hasn't been used from: a sign-in notice would be e-mailed
    assert fresh.post("/api/v1/auth/login", json={"email": "erin@example.com", "password": _PASSWORD}).status_code == 200
    assert fresh.get("/api/v1/auth/me").json()["email"] == "erin@example.com"


def test_the_disabled_sender_sends_nothing_and_says_so(caplog):
    message = EmailMessage(to="someone@example.com", subject="A link", text="https://example.com/#token=secret-token", kind="password_reset")

    with caplog.at_level(logging.INFO), pytest.raises(EmailDeliveryError):
        asyncio.run(DisabledSender().send(message))

    assert "mail.not_sent kind=password_reset reason=disabled" in caplog.text
    assert "someone@example.com" not in caplog.text and "secret-token" not in caplog.text


def test_the_backend_setting_picks_the_sender(monkeypatch):
    for backend, kind in (("disabled", DisabledSender), ("outbox", OutboxSender)):
        monkeypatch.setattr(get_settings(), "email_backend", backend)
        assert isinstance(get_email_sender(), kind)
    smtp = Settings(_env_file=None, email_backend="smtp", smtp_host="smtp.example.com", email_from="SmartDoc <no-reply@example.com>")
    monkeypatch.setattr("app.mail.sender.get_settings", lambda: smtp)
    assert isinstance(get_email_sender(), SmtpSender)
    assert Settings(_env_file=None, email_backend="disabled").email_delivers is False
    assert smtp.email_delivers is True


def test_the_vercel_image_sends_no_e_mail_by_default():
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parent.parent / "Dockerfile.vercel").read_text(encoding="utf-8")
    assert "EMAIL_BACKEND=disabled" in dockerfile.split("ENV JOB_BACKEND=", 1)[1].split("\n\n", 1)[0]
