"""The e-mails about an account, each sent after its request has been answered, in a
task of its own: a password reset (ACCT-002) -- the answer to "reset my password" is
then the same, and as quick, whether or not the address has an account, since the
account is looked up only afterwards -- and an address's confirmation (ACCT-003).
A link's token goes in its fragment (#token=...): browsers send no fragment to any
server, so no access log or Referer header carries it."""

import logging
from datetime import datetime, timezone

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
    """A reset link to the account with this address, if there is one."""
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


async def send_verification_link(sessions: async_sessionmaker[AsyncSession], mail: EmailSender, user_id: str) -> None:
    """A link to confirm the account's address, unless it is confirmed already."""
    try:
        async with sessions() as session:
            started = await AuthService(session).start_email_verification(user_id)
        if started is None:
            return
        user, token = started
        await mail.send(messages.email_verification(user.email, _frontend(f"/verify-email#token={token}")))
        audit("auth.email_verification_sent", user_id=user.id)
    except EmailDeliveryError:
        return
    except Exception:  # noqa: BLE001 -- after the answer there is no one to tell but the log
        logger.exception("The verification e-mail couldn't be prepared.")


async def send_password_changed(mail: EmailSender, email: str, *, kept_one: bool = False) -> None:
    """Tells the account's owner their password was changed, with the way back if it wasn't them."""
    try:
        await mail.send(messages.password_changed(email, _frontend("/forgot-password"), kept_one=kept_one))
    except EmailDeliveryError:
        return


async def send_account_deleted(mail: EmailSender, email: str) -> None:
    """The goodbye (ACCT-005): only this task still knows the address, the account is gone."""
    try:
        await mail.send(messages.account_deleted(email))
    except EmailDeliveryError:
        return
    except Exception:  # noqa: BLE001 -- after the answer there is no one to tell but the log
        logger.exception("The account deletion e-mail couldn't be prepared.")


async def send_new_browser_sign_in(mail: EmailSender, email: str, browser: str, when: datetime) -> None:
    """Tells the owner their account was signed in to from a browser it hadn't been used from (ACCT-007)."""
    try:
        at = when.astimezone(timezone.utc)
        moment = f"{at.day} {at:%B %Y at %H:%M} UTC"  # not %-d: glibc only, an error on Windows
        await mail.send(messages.new_browser_sign_in(email, browser, moment, _frontend("/settings/account"), _frontend("/forgot-password")))
    except EmailDeliveryError:
        return
    except Exception:  # noqa: BLE001 -- after the answer there is no one to tell but the log
        logger.exception("The new sign-in e-mail couldn't be prepared.")
