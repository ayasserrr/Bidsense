"""Active Directory authentication client.

Wraps the corporate AD service:

    POST {LDAP_API_URL}/authenticate  {"username": "...", "password": "..."}
    200 -> the user's directory profile
    401 -> bad credentials

The AD password is never stored by this app - `authenticate` is called on
every login, so a password change in AD takes effect immediately.

Failure modes are deliberately distinguished, because conflating them produces
a badly misleading login error:
  - wrong password        -> returns None
  - service unreachable   -> raises LdapUnavailable (caller answers 503)

Telling a user their password is wrong when the directory was simply
unreachable sends them to reset a password that was never the problem.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LdapUnavailable(RuntimeError):
    """The directory could not be reached (network error, timeout, 5xx).

    Distinct from bad credentials: it means we could not check at all.
    """


# "CN=AI Department Team,OU=El Sewedy Electric,DC=elsewedy,DC=home" -> "AI Department Team"
_CN_RE = re.compile(r"^\s*CN=([^,]+)", re.IGNORECASE)


def _clean(value: Any) -> str:
    """Normalize a directory attribute to a plain string.

    The service returns absent multi-valued attributes as the *literal string*
    "[]" (office and city in particular), not as null or an empty list - so a
    naive read stores "[]" as somebody's office. Map every empty shape to "".
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return str(value[0]).strip() if value else ""
    text = str(value).strip()
    if text in ("[]", "()", "{}", "None", "null"):
        return ""
    return text


def _clean_groups(value: Any) -> list[str]:
    """Reduce AD group DNs to their common names.

    ["CN=AI EPC Team,OU=...,DC=elsewedy,DC=home", ...] -> ["AI EPC Team", ...]
    """
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            value = [value]
    out: list[str] = []
    for dn in value or []:
        dn = str(dn).strip()
        if not dn:
            continue
        match = _CN_RE.match(dn)
        name = (match.group(1) if match else dn).strip()
        if name and name not in out:
            out.append(name)
    return out


@dataclass
class LdapProfile:
    """A normalized directory profile. All string fields default to "" (never None)."""

    username: str = ""
    email: str = ""
    domain: str = ""
    display_name: str = ""
    department: str = ""
    company: str = ""
    title: str = ""
    office: str = ""
    city: str = ""
    groups: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "LdapProfile":
        data = data or {}
        return cls(
            username=_clean(data.get("username")).lower(),
            email=_clean(data.get("email")).lower(),
            domain=_clean(data.get("domain")).lower(),
            display_name=_clean(data.get("display_name")),
            department=_clean(data.get("department")),
            company=_clean(data.get("company")),
            title=_clean(data.get("title")),
            office=_clean(data.get("office")),
            city=_clean(data.get("city")),
            groups=_clean_groups(data.get("groups")),
        )


async def authenticate(
    username: str,
    password: str,
    *,
    api_url: str,
    timeout_seconds: float,
    api_key: str = "",
    verify_tls: bool = True,
) -> LdapProfile | None:
    """Verify credentials against AD and return the directory profile.

    Returns None when the credentials are rejected. Raises `LdapUnavailable`
    when the directory cannot be reached, so the caller can answer 503 rather
    than telling the user their password is wrong.

    `httpx.AsyncClient`, not `requests`: this runs inside the request loop and
    a blocking call here would stall every other in-flight request for the
    duration of the directory round-trip.
    """
    username = (username or "").strip().lower()
    if not username or not password:
        return None

    url = f"{api_url.rstrip('/')}/authenticate"
    # The service's OpenAPI declares an X-API-Key header, but it currently
    # authenticates without one. Sent only when configured, so enabling the
    # requirement later is an .env change rather than a code change.
    headers = {"X-API-Key": api_key} if api_key else {}

    try:
        async with httpx.AsyncClient(verify=verify_tls, timeout=timeout_seconds) as client:
            response = await client.post(
                url, json={"username": username, "password": password}, headers=headers
            )
    except httpx.RequestError as exc:
        logger.error("LDAP service unreachable at %s: %s", url, exc)
        raise LdapUnavailable(str(exc)) from exc

    if response.status_code in (401, 403):
        logger.info("LDAP rejected credentials for %s", username)
        return None
    if response.status_code >= 500:
        logger.error("LDAP service error %s at %s", response.status_code, url)
        raise LdapUnavailable(f"LDAP service returned {response.status_code}")
    if response.status_code != 200:
        # A 4xx that is not an auth rejection (e.g. a malformed request) -
        # treat as a credential failure rather than an outage, but make it
        # visible in the log because it usually means a contract change.
        logger.warning("Unexpected LDAP status %s for %s", response.status_code, username)
        return None

    try:
        payload = response.json()
    except ValueError as exc:
        logger.error("LDAP returned non-JSON for %s: %s", username, exc)
        raise LdapUnavailable("LDAP returned an unreadable response") from exc

    profile = LdapProfile.from_dict(payload)
    # The directory is the source of truth, but fall back to what was typed if
    # it omits the username, so downstream code always has an identifier.
    if not profile.username:
        profile.username = username
    logger.info(
        "LDAP authenticated %s (company=%r department=%r groups=%d)",
        profile.username, profile.company, profile.department, len(profile.groups),
    )
    return profile
