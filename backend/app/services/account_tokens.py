"""Single-use tokens the app e-mails (ACCT-002, ACCT-003): to choose a new password,
or to confirm an address. The raw token goes into the e-mail and nowhere else; the
database keeps its SHA-256 (256 random bits, so a fast hash is enough, as for
session tokens). A token works once, before it expires, for its own purpose, and
only while the account's address is still the one it was sent to."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.mixins import now_utc
from app.db.models import AccountToken, User

PASSWORD_RESET = "password_reset"
EMAIL_VERIFICATION = "email_verification"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Redeemed:
    user_id: str
    email: str


class AccountTokens:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue(self, user: User, purpose: str, ttl: timedelta) -> str:
        """A new token for `user`, returned raw for the e-mail; an unused one of the same
        purpose is void from now on, so only the latest link works. The caller commits."""
        now = now_utc()
        await self._session.execute(
            update(AccountToken)
            .where(AccountToken.user_id == user.id, AccountToken.purpose == purpose, AccountToken.used_at.is_(None))
            .values(used_at=now)
            .execution_options(synchronize_session=False)
        )
        token = secrets.token_urlsafe(32)
        self._session.add(AccountToken(user_id=user.id, purpose=purpose, token_hash=token_hash(token), email=user.email, expires_at=now + ttl))
        return token

    async def redeem(self, token: str, purpose: str) -> Redeemed | None:
        """Uses the token up: who it is for, or None when it is unknown, of another
        purpose, used or expired. One UPDATE, so two requests at once can't both use it.
        The caller commits."""
        now = now_utc()
        # Expiry is compared in SQL: SQLite hands datetimes back naive, Postgres aware.
        row = (
            await self._session.execute(
                update(AccountToken)
                .where(
                    AccountToken.token_hash == token_hash(token),
                    AccountToken.purpose == purpose,
                    AccountToken.used_at.is_(None),
                    AccountToken.expires_at > now,
                )
                .values(used_at=now)
                .returning(AccountToken.user_id, AccountToken.email)
                .execution_options(synchronize_session=False)
            )
        ).first()
        return Redeemed(user_id=row.user_id, email=row.email) if row else None
