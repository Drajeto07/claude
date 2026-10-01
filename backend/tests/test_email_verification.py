"""E-mail verification (tracker ACCT-003): a link at sign-up and on request confirms the
address it was sent to -- once, within two days, only while the account still has
that address -- and the signed-in user can see whether theirs is confirmed."""

import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session as OrmSession

from app.config import get_settings
from app.db.models import AccountToken, User
from app.main import app
from app.services.account_tokens import EMAIL_VERIFICATION, PASSWORD_RESET, AccountTokens, token_hash
from app.services.auth_service import AuthService
from tests.helpers import error_body

pytestmark = pytest.mark.security  # the security regression suite (TEST-030)

_PASSWORD = "long enough password"


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def carol(api_db) -> TestClient:
    client = _client()
    assert client.post("/api/v1/auth/register", json={"email": "carol@example.com", "password": _PASSWORD}).status_code == 201
    return client


def _links(sent_mail) -> list[str]:
    return [re.search(r"/verify-email#token=([A-Za-z0-9_-]+)", message.text).group(1) for message in sent_mail if message.kind == "email_verification"]


def _confirm(token: str):
    return _client().post("/api/v1/auth/verify-email/confirm", json={"token": token})


def test_signing_up_sends_a_link_that_confirms_the_address_once(carol, sent_mail):
    assert carol.get("/api/v1/auth/me").json()["emailVerified"] is False
    [message] = [message for message in sent_mail if message.kind == "email_verification"]
    assert message.to == "carol@example.com" and f"{get_settings().frontend_url}/verify-email#token=" in message.text
    [token] = _links(sent_mail)

    confirmed = _confirm(token)  # from another browser: the link is the proof

    assert confirmed.status_code == 204
    assert carol.get("/api/v1/auth/me").json()["emailVerified"] is True
    again = _confirm(token)
    assert (again.status_code, error_body(again)["code"]) == (400, "invalid_token")


def test_asking_again_sends_a_new_link_and_voids_the_old_one(carol, sent_mail):
    asked = carol.post("/api/v1/auth/verify-email")

    assert asked.status_code == 202 and "sent a link" in asked.json()["message"]
    first, second = _links(sent_mail)
    assert _confirm(first).status_code == 400
    assert _confirm(second).status_code == 204

    # Confirmed already: nothing more is sent.
    count = len(sent_mail)
    assert carol.post("/api/v1/auth/verify-email").json()["message"] == "Your address is confirmed already."
    assert len(sent_mail) == count


def test_asking_again_is_for_the_signed_in_and_limited(carol, sent_mail, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_verify_email", "1/hour")

    assert _client().post("/api/v1/auth/verify-email").status_code == 401
    assert carol.post("/api/v1/auth/verify-email").status_code == 202
    assert carol.post("/api/v1/auth/verify-email").status_code == 429
    assert len(_links(sent_mail)) == 2  # the one at sign-up, and one more


def test_a_link_doesnt_work_expired_or_for_an_address_the_account_no_longer_has(carol, sent_mail, api_db):
    [token] = _links(sent_mail)
    with OrmSession(api_db) as session:
        session.execute(update(User).values(email="caroline@example.com"))
        session.commit()
    moved = _confirm(token)

    carol.post("/api/v1/auth/verify-email")
    newest = _links(sent_mail)[-1]
    with OrmSession(api_db) as session:
        session.execute(update(AccountToken).where(AccountToken.token_hash == token_hash(newest)).values(expires_at=AccountToken.created_at - timedelta(minutes=1)))
        session.commit()
    expired = _confirm(newest)

    assert moved.status_code == expired.status_code == 400
    assert error_body(moved)["message"] == error_body(expired)["message"]
    assert carol.get("/api/v1/auth/me").json()["emailVerified"] is False


async def test_a_reset_token_doesnt_confirm_an_address_nor_the_other_way_round(db_session):
    service = AuthService(db_session)
    user = await service.register("dan@example.com", _PASSWORD, None)
    reset = await AccountTokens(db_session).issue(user, PASSWORD_RESET, timedelta(hours=1))
    verification = await AccountTokens(db_session).issue(user, EMAIL_VERIFICATION, timedelta(days=2))
    await db_session.commit()

    assert await service.verify_email(reset) is None
    assert await service.reset_password(verification, "a brand new passphrase") is None
    assert (await service.verify_email(verification)).email_verified_at is not None
    assert await service.start_email_verification(user.id) is None  # confirmed: no new link
