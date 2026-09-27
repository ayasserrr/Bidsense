"""FastAPI dependencies for authentication and authorization."""
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from helpers import get_settings, gov_context
from helpers.security import COOKIE_NAME, decode_token
from models.db_schema import User
from models.enums import UserRole


async def current_user(
    db: AsyncSession = Depends(get_db),
    session_cookie: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> User:
    """The signed-in user, or 401.

    The token is read from an HttpOnly cookie rather than an Authorization
    header. That is not a style preference: `api/offerApi.ts` abandons an
    orphaned offer through `navigator.sendBeacon`, which cannot set headers -
    a bearer scheme would leave that cleanup call permanently unauthenticated.
    """
    settings = get_settings()

    if not session_cookie:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    claims = decode_token(
        session_cookie, secret=settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")

    try:
        user_id = int(claims.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session") from None

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated")

    # A token minted before the account was deactivated or its version bumped
    # carries a stale `tv`. Without this check such a token would stay valid
    # until its natural expiry.
    if int(claims.get("tv", 0) or 0) != int(user.token_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please sign in again")

    return user


async def require_admin(user: User = Depends(current_user)) -> User:
    """Admin-only actions: seeing every department's offers, and (once they
    land) editing the completeness checklist and the category taxonomy."""
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return user


async def governed_user(user: User = Depends(current_user)) -> User:
    """Authenticate, and attribute every LLM call this request makes.

    Applied to the pipeline routes, which is where the model is actually
    called. Setting the context here - at the start of request handling,
    before any tool runs - is what the gateway integration standard requires:
    everything downstream inherits it, so it cannot be set later.

    `company` and `department` are passed through exactly as the directory
    reported them, empty values included. Substituting a placeholder would
    hide a real gap that the governance dashboard is meant to surface.
    """
    gov_context.set_context(
        company=user.company or None,
        department=user.department or None,
        user_id=user.governance_user_id or None,
        trace_id=gov_context.new_trace_id(),
    )
    return user
