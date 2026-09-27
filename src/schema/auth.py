from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    # The corporate username, as typed at the sign-in page. Not an EmailStr:
    # the directory accepts both a bare username and a UPN, and rejecting a
    # bare username here would fail the login before AD ever sees it.
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    # "Keep me signed in on this workstation". Defaults to true so a client
    # that predates the checkbox keeps the persistent cookie it always got,
    # rather than being silently switched to a browser-session one.
    remember: bool = True


class UserOut(BaseModel):
    """The signed-in user as the frontend sees them.

    Everything except `role` and `is_active` mirrors Active Directory and is
    refreshed on each login; none of it is editable in this app.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    display_name: str
    department: str
    company: str
    job_title: str
    office: str
    city: str
    role: str
    # "ldap" or "local": whether the directory or this app vouches for the
    # account, which the profile card states.
    auth_source: str
    is_admin: bool = False
    last_login_at: datetime | None = None
    created_at: datetime | None = None
