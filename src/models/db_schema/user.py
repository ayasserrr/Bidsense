from datetime import datetime, timezone

from sqlalchemy import ARRAY, BigInteger, Boolean, CheckConstraint, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.enums import AuthSource, UserRole

from .base import Base

USER_ROLE_VALUES = tuple(role.value for role in UserRole)
AUTH_SOURCE_VALUES = tuple(source.value for source in AuthSource)


class User(Base):
    """A person who can sign in.

    Accounts are auto-provisioned on first successful corporate login - there
    is no signup flow and no password reset, because Active Directory owns the
    password. The directory profile below is refreshed from AD on every login
    rather than being editable here, so a transfer between departments takes
    effect the next time the person signs in (which matters: `department` is
    what scopes offer visibility).
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN {USER_ROLE_VALUES}", name="ck_users_role"),
        CheckConstraint(f"auth_source IN {AUTH_SOURCE_VALUES}", name="ck_users_auth_source"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # The identifier typed at the sign-in page and sent to AD. Stored
    # lowercased so lookups are stable regardless of how it was typed.
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)

    # NOT unique. The directory reports an absent attribute as an empty value,
    # so several accounts can legitimately carry "" here - a unique constraint
    # would let the first such account provision and then permanently block
    # every later one with an integrity error at login.
    email: Mapped[str] = mapped_column(Text, nullable=False, default="", index=True)

    # Only ever set for the bootstrap admin. LDAP accounts carry a sentinel
    # that cannot verify against any password.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    auth_source: Mapped[str] = mapped_column(
        Text, nullable=False, default=AuthSource.LDAP.value, index=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False, default=UserRole.USER.value, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # --- directory profile, refreshed from AD on every login ---------------
    display_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Scopes which offers this person sees. Taken verbatim from AD and never
    # inferred from the email domain - subsidiaries share one domain.
    department: Mapped[str] = mapped_column(Text, nullable=False, default="", index=True)
    company: Mapped[str] = mapped_column(Text, nullable=False, default="", index=True)
    job_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    office: Mapped[str] = mapped_column(Text, nullable=False, default="")
    city: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ldap_groups: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )

    # --- session / lockout -------------------------------------------------
    # Carried in the JWT as `tv`. Bumping it invalidates every token already
    # issued for this user, which is how a deactivation or a password change
    # takes effect immediately instead of at the token's natural expiry.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def governance_user_id(self) -> str:
        """The identifier the AI gateway attributes usage to.

        Per the gateway integration standard this is the AD username plus the
        mail-address suffix ("mohamed.ahmed@elsewedy.com"). Derived rather
        than stored because both inputs already live on this row, so a
        separate column could only ever drift from them. employeeID is
        explicitly not used - it is hand-entered in AD and unreliable.
        """
        username = (self.username or "").strip().lower()
        email = (self.email or "").strip().lower()
        if "@" in email:
            return f"{username.split('@')[0]}@{email.split('@', 1)[1]}"
        return username
