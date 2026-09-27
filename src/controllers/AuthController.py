import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from helpers import get_settings
from helpers.ldap_client import LdapProfile, LdapUnavailable, authenticate
from helpers.security import LDAP_SENTINEL, create_access_token, hash_password, verify_password
from models.db_schema import User
from models.enums import AuthSource, UserRole

from .BaseController import BaseController

logger = logging.getLogger(__name__)

# After this many consecutive failures the account is locked briefly. This
# counts AD rejections too, so a brute-force attempt stops hammering the
# directory service rather than being relayed to it indefinitely.
LOCKOUT_MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 5

BAD_CREDENTIALS_MSG = (
    "Incorrect username or password. Use the same corporate account you sign in "
    "to your workstation with."
)
DIRECTORY_DOWN_MSG = (
    "We can't reach the corporate sign-in service right now. Please try again in "
    "a few minutes."
)


class AuthController(BaseController):
    """Corporate sign-in.

    Active Directory is the only authority for ordinary users: accounts are
    auto-provisioned on first successful login, there is no signup flow, and
    no password is stored here. The single exception is the bootstrap admin,
    who keeps a local password so an AD outage cannot lock operations out.
    """

    def __init__(self, db: AsyncSession):
        super().__init__()
        self.db = db
        self.settings = get_settings()

    async def _find_by_username(self, username: str) -> User | None:
        """Case-insensitive lookup - the username is stored lowercased but a
        pre-existing row (or a differently-typed login) must still match."""
        result = await self.db.execute(
            select(User).where(func.lower(User.username) == username.lower())
        )
        return result.scalar_one_or_none()

    async def _find_account(self, typed: str) -> User | None:
        """Resolve an account from whatever the person typed.

        An account is stored under whichever form the directory reported, but
        people type either the bare name or the full UPN interchangeably.
        Matching both means a returning user is found on the first query -
        without it, a bare-name login would miss the row stored under the UPN,
        re-enter provisioning, and only recover through the unique-constraint
        error path on every single sign-in.
        """
        user = await self._find_by_username(typed)
        if user is not None:
            return user
        upn = self._to_upn(typed)
        if upn != typed:
            return await self._find_by_username(upn)
        return None

    async def _register_failed_attempt(self, user: User) -> None:
        """Count a failed check toward the lockout, then raise 401 or 429."""
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= LOCKOUT_MAX_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
            await self.db.commit()
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Too many failed attempts. This account is locked for {LOCKOUT_MINUTES} minutes.",
            )
        await self.db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_CREDENTIALS_MSG)

    @staticmethod
    def _apply_profile(user: User, profile: LdapProfile) -> None:
        """Refresh the stored profile from AD.

        AD is authoritative, but an empty value never wipes existing data -
        some directory records simply omit a field, and blanking `department`
        would silently change which offers the person can see.
        """
        for column, attr in (
            ("display_name", "display_name"),
            ("department", "department"),
            ("company", "company"),
            ("job_title", "title"),
            ("office", "office"),
            ("city", "city"),
            ("email", "email"),
        ):
            value = (getattr(profile, attr, "") or "").strip()
            if value:
                setattr(user, column, value)
        # Groups represent current AD state, so they are replaced wholesale.
        user.ldap_groups = list(profile.groups or [])

    def _to_upn(self, username: str) -> str:
        """Complete a bare username to a UPN.

        The directory rejects anything without an "@" as a malformed username
        (HTTP 400), but people know themselves by the bare name they type at
        their workstation. Without this, every ordinary login attempt would
        fail and be reported to the user as a wrong password.
        """
        suffix = (self.settings.LDAP_UPN_SUFFIX or "").strip().lstrip("@")
        if "@" in username or not suffix:
            return username
        return f"{username}@{suffix}"

    async def login(self, username: str, password: str) -> tuple[User, str]:
        """Authenticate and return (user, session_token)."""
        username = (username or "").strip().lower()
        user = await self._find_account(username)

        # Lockout is checked before any credential check, so a locked account
        # never reaches the directory service at all.
        if user and user.locked_until and user.locked_until > datetime.now(timezone.utc):
            remaining = int((user.locked_until - datetime.now(timezone.utc)).total_seconds())
            minutes, seconds = divmod(remaining, 60)
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"This account is temporarily locked. Try again in {minutes}m {seconds}s.",
            )

        if user is not None and user.auth_source == AuthSource.LOCAL.value:
            # The bootstrap admin: local password, never sent to AD.
            if not verify_password(password, user.password_hash):
                await self._register_failed_attempt(user)
            return await self._finish_login(user)

        if not self.settings.LDAP_ENABLED:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DIRECTORY_DOWN_MSG)

        try:
            profile = await authenticate(
                self._to_upn(username),
                password,
                api_url=self.settings.LDAP_API_URL,
                timeout_seconds=self.settings.LDAP_TIMEOUT_SECONDS,
                api_key=self.settings.LDAP_API_KEY,
                verify_tls=self.settings.LDAP_VERIFY_TLS,
            )
        except LdapUnavailable:
            # Deliberately NOT reported as a wrong password - that would send
            # the user to reset a password that was never the problem.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, DIRECTORY_DOWN_MSG
            ) from None

        if profile is None:
            if user is not None:
                await self._register_failed_attempt(user)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_CREDENTIALS_MSG)

        if user is None:
            user = await self._provision(profile, username)

        self._apply_profile(user, profile)
        return await self._finish_login(user)

    async def _provision(self, profile: LdapProfile, typed_username: str) -> User:
        """Create an account on first successful corporate login."""
        user = User(
            username=(profile.username or typed_username).lower(),
            email=profile.email or "",
            password_hash=LDAP_SENTINEL,
            auth_source=AuthSource.LDAP.value,
            role=UserRole.USER.value,
            is_active=True,
        )
        self.db.add(user)
        try:
            await self.db.commit()
        except IntegrityError:
            # Two first-logins raced (two tabs, or a shared launch link).
            # Use whichever row won rather than failing the login.
            await self.db.rollback()
            existing = await self._find_by_username(user.username)
            if existing is None:
                logger.error("provisioning collision for %s with no resolvable row", user.username)
                raise HTTPException(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "Your account could not be created. Please contact your administrator.",
                ) from None
            return existing
        await self.db.refresh(user)
        logger.info("provisioned account %s from directory", user.username)
        return user

    async def _finish_login(self, user: User) -> tuple[User, str]:
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(user)

        token = create_access_token(
            subject=str(user.id),
            role=user.role,
            token_version=user.token_version or 0,
            expire_minutes=self.settings.JWT_EXPIRE_MINUTES,
            secret=self.settings.JWT_SECRET,
            algorithm=self.settings.JWT_ALGORITHM,
        )
        return user, token

    async def bootstrap_admin(self) -> None:
        """Seed the local admin if no admin exists yet.

        Must run AFTER migrations - it queries `users`, which does not exist
        until `alembic upgrade head` has run. Skipped entirely when no
        password is configured, so a deployment that relies purely on AD never
        gets an account with a guessable password.
        """
        password = (self.settings.BOOTSTRAP_ADMIN_PASSWORD or "").strip()
        if not password:
            logger.info("bootstrap: no BOOTSTRAP_ADMIN_PASSWORD set - skipping local admin")
            return

        result = await self.db.execute(
            select(User).where(User.role == UserRole.ADMIN.value).limit(1)
        )
        if result.scalar_one_or_none() is not None:
            return

        admin = User(
            username=self.settings.BOOTSTRAP_ADMIN_USERNAME.strip().lower(),
            email="",
            password_hash=hash_password(password),
            auth_source=AuthSource.LOCAL.value,
            role=UserRole.ADMIN.value,
            is_active=True,
            display_name="Administrator",
        )
        self.db.add(admin)
        try:
            await self.db.commit()
            logger.info("bootstrap: created local admin %s", admin.username)
        except IntegrityError:
            # Another worker won the race; the unique index kept it single.
            await self.db.rollback()
