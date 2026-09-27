from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from controllers import AuthController
from db import get_db
from dependencies import current_user
from helpers import get_settings
from helpers.security import COOKIE_NAME
from models.db_schema import User
from models.enums import UserRole
from schema.auth import LoginRequest, UserOut

auth_router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
)


def _user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.is_admin = user.role == UserRole.ADMIN.value
    return out


def _set_session_cookie(response: Response, token: str, *, remember: bool) -> None:
    settings = get_settings()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        # Unticking "Keep me signed in" asks for the session to end with the
        # browser, so the cookie gets no Max-Age (and no Expires) and the
        # browser drops it on close. That is best effort: browsers set to
        # "continue where you left off" restore session cookies when they
        # reopen. The JWT's own exp is therefore still the real limit - neither
        # kind of cookie carries a usable session past JWT_EXPIRE_MINUTES.
        max_age=settings.JWT_EXPIRE_MINUTES * 60 if remember else None,
        httponly=True,
        # SameSite=lax is the CSRF defence here, and it is load-bearing: the
        # abandon-offer endpoint is a destructive, id-addressable, empty-body
        # POST reachable by sendBeacon. Lax keeps a cross-site page from
        # issuing it with the user's cookie attached.
        samesite="lax",
        secure=settings.SESSION_COOKIE_SECURE,
        path="/",
    )


@auth_router.post("/login", response_model=UserOut)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Sign in against the corporate directory.

    Public by design - this is the only unauthenticated endpoint.
    """
    controller = AuthController(db)
    user, token = await controller.login(body.username, body.password)
    _set_session_cookie(response, token, remember=body.remember)
    return _user_out(user)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    """Clearing the cookie is the whole logout: the token is stateless, and
    `token_version` exists for the cases where a session must die server-side.

    Returns None rather than a fresh `Response`. Constructing a new one here
    would discard the injected `response` - and with it the Set-Cookie header
    that does the actual clearing - so logout would answer 204 while leaving
    the session fully valid.
    """
    response.delete_cookie(COOKIE_NAME, path="/")


@auth_router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    """Who the session belongs to. The frontend calls this on load to decide
    between the app and the sign-in page."""
    return _user_out(user)
