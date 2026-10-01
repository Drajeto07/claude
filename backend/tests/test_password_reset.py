"""Password reset (tracker ACCT-002): a link by e-mail that works once, for an hour,
for the address it was sent to; asking for one tells no one whether an address has
an account; using it signs the account out everywhere; the token is never stored or
logged."""

import logging
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from app.config import get_settings
from app.db.models import AccountToken, User
from app.main import app
from app.mail import EmailDeliveryError, get_email_sender
from app.services.account_tokens import EMAIL_VERIFICATION, AccountTokens, token_hash
from app.services.auth_service import AuthService
from tests.helpers import error_body

pytestmark = pytest.mark.security  # the security regression suite (TEST-030)

_PASSWORD = "long enough password"
_NEW_PASSWORD = "a brand new passphrase"


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def alice(api_db) -> TestClient:
    """Signed up, and signed in in this client."""
    client = _client()
    assert client.post("/api/v1/auth/register", json={"email": "alice@example.com", "password": _PASSWORD}).status_code == 201
    return client


def _kind(sent_mail, kind: str) -> list:
    """The messages of one kind (signing up also sends a link to confirm the address)."""
    return [message for message in sent_mail if message.kind == kind]


def _token(message) -> str:
    match = re.search(r"/reset-password#token=([A-Za-z0-9_-]+)", message.text)
    assert match, message.text
    return match.group(1)


def _ask(client: TestClient, email: str):
    return client.post("/api/v1/auth/password-reset", json={"email": email})


def _confirm(client: TestClient, token: str, password: str = _NEW_PASSWORD):
    return client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "password": password})


def _signs_in(password: str) -> bool:
    return _client().post("/api/v1/auth/login", json={"email": "alice@example.com", "password": password}).status_code == 200


def test_asking_answers_the_same_whether_or_not_the_address_has_an_account(alice, sent_mail):
    stranger = _client()

    known, unknown = _ask(stranger, " Alice@Example.com "), _ask(stranger, "nobody@example.com")

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() and "If an account uses that address" in known.json()["message"]
    [reset] = _kind(sent_mail, "password_reset")
    assert reset.to == "alice@example.com"
    assert reset.text.count(f"{get_settings().frontend_url}/reset-password#token=") == 1


def test_a_link_sets_a_new_password_once_and_signs_the_account_out_everywhere(alice, sent_mail):
    elsewhere = _client()
    assert elsewhere.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": _PASSWORD}).status_code == 200
    _ask(_client(), "alice@example.com")
    token = _token(_kind(sent_mail, "password_reset")[0])

    reset = _confirm(_client(), token)

    assert reset.status_code == 204
    assert alice.get("/api/v1/auth/me").status_code == elsewhere.get("/api/v1/auth/me").status_code == 401
    assert not _signs_in(_PASSWORD) and _signs_in(_NEW_PASSWORD)
    [changed] = _kind(sent_mail, "password_changed")
    assert changed.to == "alice@example.com" and "/forgot-password" in changed.text

    again = _confirm(_client(), token, "yet another passphrase")
    assert (again.status_code, error_body(again)["code"]) == (400, "invalid_token")
    assert _signs_in(_NEW_PASSWORD)


def test_a_link_that_doesnt_work_is_one_answer_whatever_the_reason(alice, sent_mail, api_db):
    client = _client()
    _ask(client, "alice@example.com")
    replaced = _token(_kind(sent_mail, "password_reset")[0])
    _ask(client, "alice@example.com")  # a newer link: only the latest one works
    expired = _token(_kind(sent_mail, "password_reset")[1])
    with OrmSession(api_db) as session:
        session.execute(update(AccountToken).where(AccountToken.token_hash == token_hash(expired)).values(expires_at=AccountToken.created_at - timedelta(minutes=1)))
        session.commit()

    answers = [_confirm(client, token) for token in (replaced, expired, "x" * 43)]

    assert {answer.status_code for answer in answers} == {400}
    assert len({(body["code"], body["message"]) for body in map(error_body, answers)}) == 1
    assert _signs_in(_PASSWORD)


async def test_a_token_works_only_for_its_purpose_and_the_address_it_was_sent_to(db_session):
    service = AuthService(db_session)
    user = await service.register("bob@example.com", _PASSWORD, None)
    verification = await AccountTokens(db_session).issue(user, EMAIL_VERIFICATION, timedelta(hours=1))
    await db_session.commit()
    assert await AuthService(db_session).reset_password(verification, _NEW_PASSWORD) is None

    _, token = await service.start_password_reset("bob@example.com")
    user.email = "robert@example.com"  # the account moved to another address since
    await db_session.commit()
    assert await AuthService(db_session).reset_password(token, _NEW_PASSWORD) is None
    assert await AuthService(db_session).authenticate("robert@example.com", _PASSWORD) is not None


def test_only_the_tokens_hash_is_kept_and_no_log_line_holds_the_token(alice, sent_mail, api_db):
    lines: list[str] = []

    class Everything(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage() + " " + " ".join(f"{key}={value}" for key, value in vars(record).items() if key not in ("msg", "args")))

    handler = Everything(level=logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        _ask(_client(), "alice@example.com")
        token = _token(_kind(sent_mail, "password_reset")[0])
        _confirm(_client(), token)
    finally:
        root.removeHandler(handler)

    with OrmSession(api_db) as session:
        [row] = session.scalars(select(AccountToken).where(AccountToken.purpose == "password_reset")).all()
        assert row.token_hash == token_hash(token) and token not in str(vars(row))
    logged = "\n".join(lines)
    assert token not in logged and "alice@example.com" not in logged
    for event in ("auth.password_reset_requested", "auth.password_reset_sent", "auth.password_reset_completed", "mail.sent"):
        assert event in logged, event


def test_asking_is_rate_limited_per_address_and_per_account(alice, sent_mail, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_password_reset_account", "2/hour")
    monkeypatch.setattr(get_settings(), "rate_limit_password_reset", "3/hour")
    client = _client()

    per_account = [_ask(client, "alice@example.com").status_code for _ in range(3)]
    per_address = _ask(client, "carol@example.com").status_code, _ask(client, "dave@example.com").status_code

    assert per_account == [202, 202, 429]
    assert per_address == (429, 429)  # the address's 3 an hour are used up (the account's refusal counted too)
    assert len(_kind(sent_mail, "password_reset")) == 2


@pytest.mark.parametrize("failure", [EmailDeliveryError("The e-mail couldn't be sent."), RuntimeError("the outbox folder is read-only")])
def test_a_mail_that_cant_be_sent_leaves_the_answer_as_it_is(alice, failure):
    class Broken:
        async def send(self, message):
            raise failure

    app.dependency_overrides[get_email_sender] = lambda: Broken()  # sent_mail's teardown takes it out
    assert _ask(_client(), "alice@example.com").status_code == 202


def test_a_turned_off_account_gets_no_link_and_can_t_use_one(alice, sent_mail, api_db):
    _ask(_client(), "alice@example.com")
    with OrmSession(api_db) as session:
        session.execute(update(User).values(is_active=False))
        session.commit()

    assert _confirm(_client(), _token(_kind(sent_mail, "password_reset")[0])).status_code == 400
    _ask(_client(), "alice@example.com")
    assert len(_kind(sent_mail, "password_reset")) == 1
