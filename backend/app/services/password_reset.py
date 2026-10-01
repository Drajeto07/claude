"""The e-mails of a password reset (ACCT-002), sent after the request has been
answered: the answer to "reset my password" is the same, and as quick, whether or not
the address has an account, since the account is looked up only afterwards."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import audit
from app.config import get_settings
from app.mail import EmailDeliveryError, EmailSender
from app.mail import messages
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)


def _frontend(path: str) -> str:
    return f"{get_settings().frontend_url.rstrip('/')}{path}"


async def send_reset_link(sessions: async_sessionmaker[AsyncSession], mail: EmailSender, email: str) -> None:
    """A reset link to the account with this address, if there is one. The token goes
    in the link's fragment (#token=...): browsers send no fragment to any server, so
    no access log or Referer header carries it."""
    try:
        async with sessions() as session:
            started = await AuthService(session).start_password_reset(email)
        if started is None:
            return
        user, token = started
        await mail.send(messages.password_reset(user.email, _frontend(f"/reset-password#token={token}")))
        audit("auth.password_reset_sent", user_id=user.id)
    except EmailDeliveryError:
        return  # the sender logged it, without the message
    except Exception:  # noqa: BLE001 -- after the answer there is no one to tell but the log
        logger.exception("The password reset e-mail couldn't be prepared.")


async def send_password_changed(mail: EmailSender, email: str) -> None:
    """Tells the account's owner their password was changed, with the way back if it wasn't them."""
    try:
        await mail.send(messages.password_changed(email, _frontend("/forgot-password")))
    except EmailDeliveryError:
        return
