import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app.api.deps import SESSION_COOKIE, BackgroundSessions, CurrentUser, DbSession, Mail, Storage, client_address
from app.audit import audit
from app.config import get_settings
from app.db.models import User
from app.schemas.auth import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RegisterRequest,
    SessionResponse,
    UserResponse,
    VerifyEmailConfirmRequest,
)
from app.db.mixins import now_utc
from app.security import sign_in_delay
from app.security.rate_limit import enforce, hashed
from app.services.account_deletion import AccountDeletionRefused, delete_account, delete_files
from app.services.account_mail import (
    send_account_deleted,
    send_new_browser_sign_in,
    send_password_changed,
    send_reset_link,
    send_verification_link,
)
from app.services.auth_service import AuthService, EmailAlreadyRegisteredError, hash_session_token
from app.services.browsers import browser_name

router = APIRouter()

# A long-lived random id for the browser (ACCT-007), so a sign-in from one the account
# hasn't been used from can be told apart: an address changes with every network and
# says nothing of the browser. Browsers keep a cookie at most 400 days.
DEVICE_COOKIE = "smartdoc_device"
DEVICE_COOKIE_MAX_AGE = 400 * 24 * 3600
_DEVICE_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")  # secrets.token_urlsafe(32)


def _device_token(request: Request, response: Response) -> str:
    """The browser's device id, a new one if it has none (or not one of ours). Set again on
    every sign-in, so its lifetime counts from the last."""
    token = request.cookies.get(DEVICE_COOKIE, "")
    if not _DEVICE_TOKEN.fullmatch(token):
        token = secrets.token_urlsafe(32)
    response.set_cookie(
        DEVICE_COOKIE,
        token,
        max_age=DEVICE_COOKIE_MAX_AGE,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return token


async def _sign_in(
    service: AuthService,
    user: User,
    request: Request,
    response: Response,
    *,
    background: BackgroundTasks,
    mail: Mail,
    new_account: bool = False,
) -> UserResponse:
    settings = get_settings()
    ttl = timedelta(days=settings.session_ttl_days)
    user_agent = request.headers.get("user-agent")
    token = await service.start_session(
        user,
        ttl=ttl,
        user_agent=user_agent,
        ip_address=request.client.host if request.client else None,
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    # A browser the account hasn't been used from: its owner is told, unless it is the one the account was made in.
    if await service.remember_browser(user.id, _device_token(request, response)) and not new_account:
        audit("auth.new_browser", user_id=user.id, ip=client_address(request))
        background.add_task(send_new_browser_sign_in, mail, user.email, browser_name(user_agent), now_utc())
    return await _user_response(service, user)


async def _user_response(service: AuthService, user: User) -> UserResponse:
    workspace_id = await service.default_workspace_id(user.id)
    return UserResponse(
        id=user.id, email=user.email, fullName=user.full_name, workspaceId=workspace_id, emailVerified=user.email_verified_at is not None
    )


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: DbSession,
    background: BackgroundTasks,
    sessions: BackgroundSessions,
    mail: Mail,
) -> UserResponse:
    await enforce("register", f"ip:{client_address(request)}")
    service = AuthService(db)
    try:
        user = await service.register(payload.email, payload.password, payload.fullName)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    audit("auth.registered", user_id=user.id, ip=client_address(request))
    # A link to confirm the address (ACCT-003), sent once the account is answered for.
    background.add_task(send_verification_link, sessions, mail, user.id)
    return await _sign_in(service, user, request, response, background=background, mail=mail, new_account=True)


@router.post("/login", response_model=UserResponse)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: DbSession, background: BackgroundTasks, mail: Mail
) -> UserResponse:
    # Per address against trying many accounts, per account against trying many passwords;
    # and after a few wrong ones for the account, a growing wait (ACCT-007).
    await enforce("login", f"ip:{client_address(request)}")
    await enforce("login_account", f"email:{hashed(payload.email)}")
    await sign_in_delay.wait_before_check(payload.email)
    service = AuthService(db)
    user = await service.authenticate(payload.email, payload.password)
    if user is None:
        await sign_in_delay.password_failed(payload.email)
        audit("auth.login_failed", email_hash=hashed(payload.email), ip=client_address(request))
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    await sign_in_delay.password_succeeded(payload.email)
    audit("auth.login_succeeded", user_id=user.id, ip=client_address(request))
    return await _sign_in(service, user, request, response, background=background, mail=mail)


@router.post("/logout", status_code=204)
async def logout(request: Request, db: DbSession) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await AuthService(db).end_session(token)
        audit("auth.logout", ip=client_address(request))
    return _signed_out(Response(status_code=204))


def _signed_out(response: Response) -> Response:
    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, secure=settings.session_cookie_secure, samesite="lax"
    )
    return response


RESET_REQUESTED = "If an account uses that address, we've sent it a link to choose a new password. The link works for an hour."
RESET_LINK_INVALID = "This link has expired or has already been used. Ask for a new one."


@router.post("/password-reset", response_model=MessageResponse, status_code=202)
async def request_password_reset(
    payload: PasswordResetRequest, request: Request, background: BackgroundTasks, sessions: BackgroundSessions, mail: Mail
) -> MessageResponse:
    """Sends a link to choose a new password (ACCT-002). The answer is the same, and as
    quick, whether or not the address has an account: the account is looked up and the
    e-mail sent after it (services/account_mail.py)."""
    await enforce("password_reset", f"ip:{client_address(request)}")
    await enforce("password_reset_account", f"email:{hashed(payload.email)}")
    audit("auth.password_reset_requested", email_hash=hashed(payload.email), ip=client_address(request))
    background.add_task(send_reset_link, sessions, mail, payload.email)
    return MessageResponse(message=RESET_REQUESTED)


VERIFICATION_SENT = "We've sent a link to your address. Open it within two days to confirm the address."
VERIFICATION_DONE = "Your address is confirmed already."
VERIFICATION_LINK_INVALID = "This link has expired, has already been used, or is for an address your account no longer has. Ask for a new one."


@router.post("/verify-email", response_model=MessageResponse, status_code=202)
async def request_email_verification(
    user: CurrentUser, background: BackgroundTasks, sessions: BackgroundSessions, mail: Mail
) -> MessageResponse:
    """Sends the signed-in user another link to confirm their address (ACCT-003)."""
    if user.email_verified_at is not None:
        return MessageResponse(message=VERIFICATION_DONE)
    await enforce("verify_email", f"user:{user.id}")
    background.add_task(send_verification_link, sessions, mail, user.id)
    return MessageResponse(message=VERIFICATION_SENT)


@router.post("/verify-email/confirm", status_code=204)
async def confirm_email_verification(payload: VerifyEmailConfirmRequest, request: Request, db: DbSession) -> Response:
    """Confirms an address with the link sent to it, signed in or not: the token is the
    proof. One answer for every token that doesn't work."""
    await enforce("account_link", f"ip:{client_address(request)}")
    user = await AuthService(db).verify_email(payload.token)
    if user is None:
        audit("auth.email_verification_failed", ip=client_address(request))
        raise HTTPException(status_code=400, detail={"code": "invalid_token", "message": VERIFICATION_LINK_INVALID})
    audit("auth.email_verified", user_id=user.id, ip=client_address(request))
    return Response(status_code=204)


@router.post("/password-reset/confirm", status_code=204)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest, request: Request, db: DbSession, background: BackgroundTasks, mail: Mail
) -> Response:
    """Sets a new password with a link's token, once; every session of the account ends,
    this browser's too. A token that doesn't work is one answer, whatever the reason."""
    await enforce("account_link", f"ip:{client_address(request)}")
    user = await AuthService(db).reset_password(payload.token, payload.password)
    if user is None:
        audit("auth.password_reset_failed", ip=client_address(request))
        raise HTTPException(status_code=400, detail={"code": "invalid_token", "message": RESET_LINK_INVALID})
    audit("auth.password_reset_completed", user_id=user.id, ip=client_address(request))
    background.add_task(send_password_changed, mail, user.email)
    return _signed_out(Response(status_code=204))


@router.put("/password", status_code=204)
async def change_password(
    payload: ChangePasswordRequest, request: Request, user: CurrentUser, db: DbSession, background: BackgroundTasks, mail: Mail
) -> Response:
    """Changes the signed-in user's password (ACCT-004): the current one first, so a
    session left open somewhere can't lock its owner out. Every other session of the
    account ends; this one stays. Counted with sign-ins against guessing."""
    await enforce("login_account", f"email:{hashed(user.email)}")
    await sign_in_delay.wait_before_check(user.email)
    changed = await AuthService(db).change_password(
        user, payload.currentPassword, payload.newPassword, session_token=request.cookies.get(SESSION_COOKIE, "")
    )
    if not changed:
        await sign_in_delay.password_failed(user.email)
        audit("auth.password_change_failed", user_id=user.id, ip=client_address(request))
        raise HTTPException(status_code=400, detail={"code": "wrong_password", "message": "That isn't your current password."})
    await sign_in_delay.password_succeeded(user.email)
    audit("auth.password_changed", user_id=user.id, ip=client_address(request))
    background.add_task(send_password_changed, mail, user.email, kept_one=True)
    return Response(status_code=204)


@router.delete("/account", status_code=204)
async def delete_own_account(
    payload: DeleteAccountRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    background: BackgroundTasks,
    mail: Mail,
    storage: Storage,
) -> Response:
    """Deletes the signed-in user's account and what goes with it (ACCT-005; the policy is
    services/account_deletion.py): the password first, counted with sign-ins. The rows go
    in one transaction; the files in storage and the goodbye e-mail after it, once the
    answer is sent."""
    await enforce("login_account", f"email:{hashed(user.email)}")
    await sign_in_delay.wait_before_check(user.email)
    if not AuthService.password_is(user, payload.password):
        await sign_in_delay.password_failed(user.email)
        audit("auth.account_deletion_failed", user_id=user.id, ip=client_address(request))
        raise HTTPException(status_code=400, detail={"code": "wrong_password", "message": "That isn't your password."})
    await sign_in_delay.password_succeeded(user.email)
    try:
        deleted = await delete_account(db, user)
    except AccountDeletionRefused as refused:
        raise HTTPException(status_code=409, detail={"code": refused.code, "message": str(refused)}) from None
    # Nothing that names the person: the account is gone, its log lines needn't point at it.
    audit("auth.account_deleted", workspaces=deleted.workspaces, documents=deleted.documents, files=len(deleted.storage_keys))
    background.add_task(delete_files, storage, deleted.storage_keys)
    background.add_task(send_account_deleted, mail, deleted.email)
    return _signed_out(Response(status_code=204))


def _utc(at: datetime | None) -> datetime | None:
    # SQLite hands datetimes back naive; they are UTC.
    return at.replace(tzinfo=timezone.utc) if at is not None and at.tzinfo is None else at


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(request: Request, user: CurrentUser, db: DbSession) -> list[SessionResponse]:
    """The browsers signed in to the account (ACCT-006), last used first."""
    current = hash_session_token(request.cookies.get(SESSION_COOKIE, ""))
    return [
        SessionResponse(
            id=row.id,
            browser=browser_name(row.user_agent),
            createdAt=_utc(row.created_at),
            lastUsedAt=_utc(row.last_used_at),
            current=row.token_hash == current,
        )
        for row in await AuthService(db).active_sessions(user.id)
    ]


@router.post("/sessions/sign-out-others", status_code=204)
async def sign_out_other_sessions(request: Request, user: CurrentUser, db: DbSession) -> Response:
    """Signs out every browser signed in to the account but this one."""
    await AuthService(db).revoke_sessions(user.id, keep_token=request.cookies.get(SESSION_COOKIE, ""))
    await db.commit()
    audit("auth.other_sessions_revoked", user_id=user.id, ip=client_address(request))
    return Response(status_code=204)


@router.delete("/sessions/{session_id}", status_code=204)
async def sign_out_session(session_id: str, request: Request, user: CurrentUser, db: DbSession) -> Response:
    """Signs out one browser signed in to the account; this one's cookie goes too if it is this one.
    Another user's session answers as one that doesn't exist."""
    token_hash = await AuthService(db).revoke_session(user.id, session_id)
    if token_hash is None:
        raise HTTPException(status_code=404, detail="Session not found")
    audit("auth.session_revoked", user_id=user.id, ip=client_address(request))
    if token_hash == hash_session_token(request.cookies.get(SESSION_COOKIE, "")):
        return _signed_out(Response(status_code=204))
    return Response(status_code=204)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser, db: DbSession) -> UserResponse:
    return await _user_response(AuthService(db), user)
