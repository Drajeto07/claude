from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.deps import SESSION_COOKIE, CurrentUser, DbSession, client_address
from app.audit import audit
from app.config import get_settings
from app.db.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from app.security.rate_limit import enforce, hashed
from app.services.auth_service import AuthService, EmailAlreadyRegisteredError

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
    response = Response(status_code=204)
    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, secure=settings.session_cookie_secure, samesite="lax"
    )
    return response


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser, db: DbSession) -> UserResponse:
    return await _user_response(AuthService(db), user)
