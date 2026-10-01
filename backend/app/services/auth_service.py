import hashlib
import secrets
from datetime import timedelta
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.mixins import now_utc
from app.db.models import Session, User, Workspace, WorkspaceMember, WorkspaceRole
from app.services.account_tokens import EMAIL_VERIFICATION, PASSWORD_RESET, AccountTokens

# How long a password-reset link works (ACCT-002), and a link to confirm an address (ACCT-003).
PASSWORD_RESET_TTL = timedelta(hours=1)
EMAIL_VERIFICATION_TTL = timedelta(days=2)

# argon2id, RFC 9106 low-memory profile (argon2-cffi's default). Tests swap in a cheap profile.
_hasher = PasswordHasher()


class EmailAlreadyRegisteredError(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_session_token(token: str) -> str:
    # Session tokens are 256-bit random values, so a fast hash is enough; only
    # the hash is stored, so a leaked sessions table can't be replayed as cookies.
    return hashlib.sha256(token.encode()).hexdigest()


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(self, email: str, password: str, full_name: str | None) -> User:
        """Creates the user plus a personal workspace they own. The unique email
        index, not a pre-check, rejects duplicates, so concurrent sign-ups can't race."""
        email = normalize_email(email)
        user = User(email=email, hashed_password=_hasher.hash(password), full_name=full_name)
        workspace = Workspace(name="Personal", slug=f"personal-{secrets.token_hex(8)}")
        self._session.add(WorkspaceMember(workspace=workspace, user=user, role=WorkspaceRole.OWNER.value))
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise EmailAlreadyRegisteredError(email) from exc
        return user

    async def authenticate(self, email: str, password: str) -> User | None:
        user = (
            await self._session.execute(select(User).where(User.email == normalize_email(email)))
        ).scalar_one_or_none()
        # Verify against a dummy hash for unknown emails so response time doesn't reveal which emails exist.
        try:
            _hasher.verify(user.hashed_password if user else _dummy_hash(), password)
        except (VerificationError, InvalidHashError):
            return None
        if user is None or not user.is_active:
            return None
        if _hasher.check_needs_rehash(user.hashed_password):
            user.hashed_password = _hasher.hash(password)
            await self._session.commit()
        return user

    async def start_session(
        self, user: User, *, ttl: timedelta, user_agent: str | None = None, ip_address: str | None = None
    ) -> str:
        """Returns the raw token for the cookie; only its hash is persisted."""
        token = secrets.token_urlsafe(32)
        self._session.add(
            Session(
                user_id=user.id,
                token_hash=hash_session_token(token),
                expires_at=now_utc() + ttl,
                user_agent=user_agent[:512] if user_agent else None,
                ip_address=ip_address,
            )
        )
        await self._session.commit()
        return token

    async def resolve_session(self, token: str) -> User | None:
        # Expiry is compared in SQL: SQLite hands datetimes back naive, Postgres aware.
        return (
            await self._session.execute(
                select(User)
                .join(Session, Session.user_id == User.id)
                .where(
                    Session.token_hash == hash_session_token(token),
                    Session.revoked_at.is_(None),
                    Session.expires_at > now_utc(),
                    User.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

    async def end_session(self, token: str) -> None:
        await self._session.execute(
            update(Session)
            .where(Session.token_hash == hash_session_token(token), Session.revoked_at.is_(None))
            .values(revoked_at=now_utc())
        )
        await self._session.commit()

    async def start_password_reset(self, email: str) -> tuple[User, str] | None:
        """A reset token for the account with this address -- the user and the raw token,
        for the e-mail -- or None when there is no such active account. Committed."""
        user = (await self._session.execute(select(User).where(User.email == normalize_email(email)))).scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        token = await AccountTokens(self._session).issue(user, PASSWORD_RESET, PASSWORD_RESET_TTL)
        await self._session.commit()
        return user, token

    async def reset_password(self, token: str, password: str) -> User | None:
        """Sets a new password with a reset token, and signs the account out everywhere.
        None, whatever the reason (an unknown, used or expired token; the account gone,
        turned off, or now at another address), so a caller can't tell them apart."""
        redeemed = await AccountTokens(self._session).redeem(token, PASSWORD_RESET)
        user = await self._session.get(User, redeemed.user_id) if redeemed else None
        if redeemed is None or user is None or not user.is_active or user.email != redeemed.email:
            await self._session.commit()  # a token taken stays used, good or not
            return None
        user.hashed_password = _hasher.hash(password)
        await self.revoke_sessions(user.id)
        await self._session.commit()
        return user

    async def start_email_verification(self, user_id: str) -> tuple[User, str] | None:
        """A token to confirm the account's address -- the user and the raw token, for the
        e-mail -- or None when the account is gone, turned off or confirmed already. Committed."""
        user = await self._session.get(User, user_id)
        if user is None or not user.is_active or user.email_verified_at is not None:
            return None
        token = await AccountTokens(self._session).issue(user, EMAIL_VERIFICATION, EMAIL_VERIFICATION_TTL)
        await self._session.commit()
        return user, token

    async def verify_email(self, token: str) -> User | None:
        """Confirms the address a verification link was sent to. None, whatever the
        reason (an unknown, used or expired token; the account gone, turned off, or now
        at another address)."""
        redeemed = await AccountTokens(self._session).redeem(token, EMAIL_VERIFICATION)
        user = await self._session.get(User, redeemed.user_id) if redeemed else None
        if redeemed is None or user is None or not user.is_active or user.email != redeemed.email:
            await self._session.commit()  # a token taken stays used, good or not
            return None
        if user.email_verified_at is None:
            user.email_verified_at = now_utc()
        await self._session.commit()
        return user

    async def revoke_sessions(self, user_id: str, *, keep_token: str | None = None) -> None:
        """Signs the user out everywhere, but for the session `keep_token` is, if given."""
        condition = [Session.user_id == user_id, Session.revoked_at.is_(None)]
        if keep_token is not None:
            condition.append(Session.token_hash != hash_session_token(keep_token))
        await self._session.execute(update(Session).where(*condition).values(revoked_at=now_utc()))

    async def default_workspace_id(self, user_id: str) -> str:
        """The workspace new documents go into: the oldest one the user owns
        (their personal workspace). A workspace switcher can override this later."""
        return (
            await self._session.execute(
                select(WorkspaceMember.workspace_id)
                .where(WorkspaceMember.user_id == user_id, WorkspaceMember.role == WorkspaceRole.OWNER.value)
                .order_by(WorkspaceMember.created_at)
                .limit(1)
            )
        ).scalar_one()
