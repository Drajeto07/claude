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
