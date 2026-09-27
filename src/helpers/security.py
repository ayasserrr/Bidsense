"""Password hashing and session-token helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

# The session cookie's name. HttpOnly, so no JavaScript in the app ever reads
# it - the browser attaches it automatically and `credentials: "include"` in
# api/client.ts is what lets it ride along.
COOKIE_NAME = "bidsense_session"

# Not a valid bcrypt hash, so `verify_password` can never accept it. Assigned
# to every LDAP-provisioned account, which by design has no local password.
LDAP_SENTINEL = "!ldap-managed"


def _bcrypt_bytes(plain: str) -> bytes:
    """bcrypt only uses the first 72 bytes and the library rejects more, so
    truncate at a byte boundary. Hash and verify must use the same slice."""
    if not isinstance(plain, str):
        plain = str(plain)
    return plain.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_bytes(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_bytes(password), password_hash.encode("utf-8"))
    except Exception:
        # A malformed or sentinel hash is a failed check, never an exception
        # that reaches the login route as a 500.
        return False


def create_access_token(
    *,
    subject: str,
    role: str,
    token_version: int,
    expire_minutes: int,
    secret: str,
    algorithm: str,
    extra: dict[str, Any] | None = None,
) -> str:
    """Mint a session JWT.

    `token_version` rides as the `tv` claim and must match the user's current
    value. Bumping the user's `token_version` therefore invalidates every
    token already issued for them - the mechanism behind immediate
    deactivation.
    """
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "tv": int(token_version),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=expire_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_token(token: str, *, secret: str, algorithm: str) -> dict[str, Any] | None:
    """Returns the claims, or None for anything invalid (bad signature,
    expired, malformed) - the caller turns that into a 401."""
    try:
        return jwt.decode(token, secret, algorithms=[algorithm])
    except JWTError:
        return None
