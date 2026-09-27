from enum import Enum


class UserRole(str, Enum):
    """Who a signed-in account is allowed to act as.

    Deliberately only two values. `admin` is an escape hatch from the
    department scoping applied to everyone else - it sees and manages every
    offer - and is the role that will own checklist and taxonomy editing when
    those land. Finer-grained permissions can be added later without a schema
    change by widening the CHECK constraint; starting with a matrix nobody has
    asked for would be guesswork.
    """

    USER = "user"
    ADMIN = "admin"


class AuthSource(str, Enum):
    """How an account's password is verified.

    Everyone is `ldap`: Active Directory is the only authority, and the AD
    password is never stored here, so a change in AD takes effect on the next
    login. `local` exists for exactly one account - the bootstrap admin - so
    that an AD outage can never lock operations out of the app entirely.
    """

    LDAP = "ldap"
    LOCAL = "local"
