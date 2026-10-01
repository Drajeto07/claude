"""How the app sends e-mail (tracker ACCT-001): a development outbox of .eml files,
SMTP that never goes in the clear, the choice by configuration, and no log line
holding a message's body, its address or a credential."""

import email
import logging
import smtplib

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.mail import EmailDeliveryError, EmailMessage, OutboxSender, SmtpSender
from app.mail import sender as sender_module
from app.security.rate_limit import hashed

pytestmark = pytest.mark.security  # the security regression suite (TEST-030)

_TOKEN = "reset-token-7f3a9c"  # stands for the secret a real message carries
_MESSAGE = EmailMessage(
    to="Person@Example.com",
    subject="Reset your password",
    text=f"Open https://app.example.com/reset?token={_TOKEN} to choose a new password.",
    kind="password_reset",
)


class _Records(logging.Handler):
    """Everything logged anywhere while it is attached (caplog misses non-propagating loggers' twins)."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def text(self) -> str:
        lines = []
        for record in self.records:
            lines.append(record.getMessage())
            lines.extend(str(value) for key, value in vars(record).items() if key not in ("msg", "args"))
        return "\n".join(lines)


@pytest.fixture
def logged():
    handler = _Records()
    root = logging.getLogger()
    root.addHandler(handler)
    previous = root.level
    root.setLevel(logging.DEBUG)
    yield handler
    root.removeHandler(handler)
    root.setLevel(previous)


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


async def test_the_outbox_keeps_each_message_as_a_file_and_logs_only_what_it_was(tmp_path, logged):
    await OutboxSender(tmp_path / "outbox", "SmartDoc <no-reply@example.com>").send(_MESSAGE)

    [written] = (tmp_path / "outbox").glob("*.eml")
    parsed = email.message_from_bytes(written.read_bytes())
    assert (parsed["To"], parsed["From"], parsed["Subject"]) == ("Person@Example.com", "SmartDoc <no-reply@example.com>", "Reset your password")
    assert _TOKEN in parsed.get_payload(decode=True).decode()
    assert "person" not in written.name.lower() and "password_reset" in written.name

    sent = [record for record in logged.records if record.getMessage() == "mail.sent"]
    assert [(record.kind, record.to_hash, record.backend) for record in sent] == [("password_reset", hashed("person@example.com"), "outbox")]
    assert _TOKEN not in logged.text() and "example.com/reset" not in logged.text() and "Person@" not in logged.text()


class _FakeSmtp:
    """smtplib.SMTP / SMTP_SSL as a server would answer: records what the sender did."""

    calls: list[tuple] = []
    fail_with: Exception | None = None

    def __init__(self, host, port, timeout=None, context=None):
        self.calls.append(("connect", host, port, timeout, context is not None))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append(("quit",))

    def starttls(self, context=None):
        self.calls.append(("starttls", context is not None))

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message):
        if self.fail_with:
            raise self.fail_with
        self.calls.append(("send", message["To"], message["Subject"]))


@pytest.fixture
def smtp(monkeypatch):
    _FakeSmtp.calls, _FakeSmtp.fail_with = [], None
    monkeypatch.setattr(sender_module.smtplib, "SMTP", _FakeSmtp)
    monkeypatch.setattr(sender_module.smtplib, "SMTP_SSL", _FakeSmtp)
    return _FakeSmtp


def _smtp_settings(**values) -> Settings:
    return _settings(
        email_backend="smtp", smtp_host="smtp.example.com", smtp_username="apikey", smtp_password=SecretStr("smtp-secret-1"), email_from="SmartDoc <no-reply@example.com>", **values
    )


async def test_smtp_starts_tls_before_it_signs_in_and_sends(smtp, logged):
    await SmtpSender(_smtp_settings()).send(_MESSAGE)

    assert smtp.calls == [
        ("connect", "smtp.example.com", 587, 20, False),
        ("starttls", True),
        ("login", "apikey", "smtp-secret-1"),
        ("send", "Person@Example.com", "Reset your password"),
        ("quit",),
    ]
    assert "smtp-secret-1" not in logged.text() and _TOKEN not in logged.text()


async def test_smtp_over_tls_from_the_start(smtp):
    await SmtpSender(_smtp_settings(smtp_security="ssl", smtp_port=465)).send(_MESSAGE)
    assert smtp.calls[0] == ("connect", "smtp.example.com", 465, 20, True)
    assert not [call for call in smtp.calls if call[0] == "starttls"]


async def test_a_message_that_can_t_be_sent_says_so_and_logs_no_detail_of_it(smtp, logged):
    # A server's refusal can echo the address and what the login sent.
    smtp.fail_with = smtplib.SMTPRecipientsRefused({"Person@Example.com": (550, b"no such user Person@Example.com smtp-secret-1")})

    with pytest.raises(EmailDeliveryError) as raised:
        await SmtpSender(_smtp_settings()).send(_MESSAGE)

    assert str(raised.value) == "The e-mail couldn't be sent." and raised.value.__cause__ is None
    assert "SMTPRecipientsRefused" in logged.text()
    for secret in ("smtp-secret-1", "Person@", _TOKEN):
        assert secret not in logged.text()
    assert not [record for record in logged.records if record.getMessage() == "mail.sent"]


def test_smtp_is_configured_or_refused_at_startup():
    with pytest.raises(ValidationError, match="SMTP_HOST"):
        _settings(email_backend="smtp")
    with pytest.raises(ValidationError, match="in the clear"):
        _settings(email_backend="smtp", smtp_host="smtp.example.com", smtp_security="none")
    with pytest.raises(ValidationError, match="EMAIL_FROM"):
        _settings(email_backend="smtp", smtp_host="smtp.example.com", email_from="SmartDoc")
    with pytest.raises(ValidationError):
        _settings(email_backend="carrier-pigeon")
    # A mail catcher on this machine may take it unencrypted; the password never shows in the settings.
    local = _settings(email_backend="smtp", smtp_host="localhost", smtp_port=1025, smtp_security="none", smtp_password=SecretStr("smtp-secret-1"))
    assert "smtp-secret-1" not in repr(local) and "smtp-secret-1" not in str(local.model_dump())


def test_the_outbox_is_the_default_and_smtp_is_chosen_by_configuration(monkeypatch, tmp_path):
    monkeypatch.setattr(sender_module, "get_settings", lambda: _settings(email_outbox_dir=str(tmp_path)))
    assert isinstance(sender_module.get_email_sender(), OutboxSender)
    monkeypatch.setattr(sender_module, "get_settings", _smtp_settings)
    assert isinstance(sender_module.get_email_sender(), SmtpSender)
