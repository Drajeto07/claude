"""How the app sends e-mail (ACCT-001), chosen by EMAIL_BACKEND:

- "outbox" (the default, for development and tests): each message is written as an
  .eml file into EMAIL_OUTBOX_DIR, where it can be opened; nothing leaves the machine.
- "smtp": through the SMTP server SMTP_HOST, with STARTTLS or TLS, signed in with
  SMTP_USERNAME and SMTP_PASSWORD. Which provider, and its credentials, are Boril's.

What is sent often carries a secret -- a link with a reset or verification token --
so no log line holds a message's body or a recipient's address: a sent message is
logged by its kind and a hash of the address, a failure by the error's type alone.
"""

import asyncio
import logging
import smtplib
import ssl
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from app.audit import audit
from app.config import Settings, get_settings
from app.security.rate_limit import hashed

logger = logging.getLogger(__name__)


class EmailMessage(BaseModel):
    """One message to one person. `kind` names what it is for the logs
    ("password_reset"), which never hold the subject, the body or the address."""

    to: str = Field(..., min_length=3, max_length=320)
    subject: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., min_length=1, max_length=100_000)
    kind: str = Field(..., pattern=r"^[a-z_]{1,40}$")


class EmailDeliveryError(Exception):
    """The message couldn't be handed over. The message says nothing of the server's
    answer, which may echo the address or the credentials."""


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


def _mime(message: EmailMessage, sender: str) -> MimeMessage:
    mime = MimeMessage()
    mime["From"] = sender
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime["Date"] = formatdate(localtime=False)
    mime["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1].strip("> ") or "localhost")
    mime.set_content(message.text)
    return mime


def _sent(message: EmailMessage, backend: str) -> None:
    audit("mail.sent", kind=message.kind, to_hash=hashed(message.to), backend=backend)


class OutboxSender:
    """Development: each message an .eml file in a folder of its own."""

    def __init__(self, folder: Path, sender: str) -> None:
        self._folder = folder
        self._sender = sender

    async def send(self, message: EmailMessage) -> None:
        mime = _mime(message, self._sender)
        name = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{message.kind}-{uuid.uuid4().hex[:8]}.eml"

        def write() -> None:
            self._folder.mkdir(parents=True, exist_ok=True)
            (self._folder / name).write_bytes(mime.as_bytes())

        await asyncio.to_thread(write)
        _sent(message, "outbox")


class MemorySender:
    """Tests: the messages, kept in a list."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)
        _sent(message, "memory")


class SmtpSender:
    """Through an SMTP server, never in the clear: STARTTLS on the submission port, or
    TLS from the start ("ssl", port 465). In a thread, with a timeout, so a slow
    server holds up no request."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, message: EmailMessage) -> None:
        settings = self._settings
        mime = _mime(message, settings.email_from)

        def deliver() -> None:
            context = ssl.create_default_context()
            timeout = settings.email_timeout_seconds
            if settings.smtp_security == "ssl":
                server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=timeout, context=context)
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)
            with server:
                if settings.smtp_security == "starttls":
                    server.starttls(context=context)
                if settings.smtp_username:
                    server.login(settings.smtp_username, settings.smtp_password.get_secret_value())
                server.send_message(mime)

        try:
            await asyncio.to_thread(deliver)
        except (smtplib.SMTPException, OSError) as exc:
            # The type only: an SMTP error's text can hold the address or the server's echo of a login.
            logger.warning("mail.failed kind=%s to_hash=%s error=%s", message.kind, hashed(message.to), type(exc).__name__)
            raise EmailDeliveryError("The e-mail couldn't be sent.") from None
        _sent(message, "smtp")


def get_email_sender() -> EmailSender:
    """The sender EMAIL_BACKEND names; a dependency, so tests put a MemorySender in."""
    settings = get_settings()
    if settings.email_backend == "smtp":
        return SmtpSender(settings)
    return OutboxSender(Path(settings.email_outbox_dir), settings.email_from)
