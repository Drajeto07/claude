"""What accounts leave behind, deleted once it is of no more use (ACCT-006), hourly with
the job sweep (in this process, or the arq worker's cron job):

- sessions SESSION_RETENTION_DAYS after they expired or were signed out: they sign
  nothing in any more; kept a while so a recent sign-out can still be looked into;
- account tokens (reset and confirmation links) ACCOUNT_TOKEN_RETENTION_DAYS after they
  were used or expired: a used or expired token is refused anyway, so the row only
  holds the address it was sent to;
- browsers an account hasn't signed in from for KNOWN_BROWSER_RETENTION_DAYS
  (ACCT-007): their device cookie has expired by then."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.mixins import now_utc
from app.db.models import AccountToken, KnownBrowser, Session


@dataclass
class AccountSweep:
    sessions: int
    account_tokens: int
    browsers: int

    def __bool__(self) -> bool:
        return bool(self.sessions or self.account_tokens or self.browsers)


async def sweep_account_records(session_factory: async_sessionmaker[AsyncSession], *, now: datetime | None = None) -> AccountSweep:
    settings = get_settings()
    now = now or now_utc()
    sessions_before = now - timedelta(days=settings.session_retention_days)
    tokens_before = now - timedelta(days=settings.account_token_retention_days)
    async with session_factory() as session:
        sessions = await session.execute(
            delete(Session).where(or_(Session.expires_at < sessions_before, Session.revoked_at < sessions_before))
        )
        tokens = await session.execute(
            delete(AccountToken).where(or_(AccountToken.expires_at < tokens_before, AccountToken.used_at < tokens_before))
        )
        browsers = await session.execute(
            delete(KnownBrowser).where(KnownBrowser.last_used_at < now - timedelta(days=settings.known_browser_retention_days))
        )
        await session.commit()
    return AccountSweep(sessions.rowcount, tokens.rowcount, browsers.rowcount)
