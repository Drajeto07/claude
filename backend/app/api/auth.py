from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app.api.deps import SESSION_COOKIE, BackgroundSessions, CurrentUser, DbSession, Mail, client_address
from app.audit import audit
from app.config import get_settings
from app.db.models import User
from app.schemas.auth import (
    LoginRequest,
    MessageResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RegisterRequest,
    UserResponse,
)
from app.security.rate_limit import enforce, hashed
from app.services.auth_service import AuthService, EmailAlreadyRegisteredError
from app.services.password_reset import send_password_changed, send_reset_link

router = APIRouter()


async def _sign_in(service: AuthService, user: User, request: Request, response: Response) -> UserResponse:
    settings = get_settings()
    ttl = timedelta(days=settings.session_ttl_days)
    token = await service.start_session(
        user,
        ttl=ttl,
        user_agent=request.headers.get("user-agent"),
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
    return await _user_response(service, user)


async def _user_response(service: AuthService, user: User) -> UserResponse:
    workspace_id = await service.default_workspace_id(user.id)
    return UserResponse(id=user.id, email=user.email, fullName=user.full_name, workspaceId=workspace_id)


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(payload: RegisterRequest, request: Request, response: Response, db: DbSession) -> UserResponse:
    await enforce("register", f"ip:{client_address(request)}")
    service = AuthService(db)
    try:
        user = await service.register(payload.email, payload.password, payload.fullName)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    audit("auth.registered", user_id=user.id, ip=client_address(request))
    return await _sign_in(service, user, request, response)


@router.post("/login", response_model=UserResponse)
async def login(payload: LoginRequest, request: Request, response: Response, db: DbSession) -> UserResponse:
    # Per address against trying many accounts, per account against trying many passwords.
    await enforce("login", f"ip:{client_address(request)}")
    await enforce("login_account", f"email:{hashed(payload.email)}")
    service = AuthService(db)
    user = await service.authenticate(payload.email, payload.password)
    if user is None:
        audit("auth.login_failed", email_hash=hashed(payload.email), ip=client_address(request))
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    audit("auth.login_succeeded", user_id=user.id, ip=client_address(request))
    return await _sign_in(service, user, request, response)


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
    e-mail sent after it (services/password_reset.py)."""
    await enforce("password_reset", f"ip:{client_address(request)}")
    await enforce("password_reset_account", f"email:{hashed(payload.email)}")
    audit("auth.password_reset_requested", email_hash=hashed(payload.email), ip=client_address(request))
    background.add_task(send_reset_link, sessions, mail, payload.email)
    return MessageResponse(message=RESET_REQUESTED)


@router.post("/password-reset/confirm", status_code=204)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest, request: Request, db: DbSession, background: BackgroundTasks, mail: Mail
) -> Response:
    """Sets a new password with a link's token, once; every session of the account ends,
    this browser's too. A token that doesn't work is one answer, whatever the reason."""
    await enforce("password_reset_confirm", f"ip:{client_address(request)}")
    user = await AuthService(db).reset_password(payload.token, payload.password)
    if user is None:
        audit("auth.password_reset_failed", ip=client_address(request))
        raise HTTPException(status_code=400, detail={"code": "invalid_token", "message": RESET_LINK_INVALID})
    audit("auth.password_reset_completed", user_id=user.id, ip=client_address(request))
    background.add_task(send_password_changed, mail, user.email)
    return _signed_out(Response(status_code=204))


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser, db: DbSession) -> UserResponse:
    return await _user_response(AuthService(db), user)
