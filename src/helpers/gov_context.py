"""
gov_context.py - governance context for the LiteLLM AI gateway.

Drop this file, unchanged, into any application that calls the AI gateway.
It carries the signed-in user's identity to the gateway on every LLM call so
usage can be attributed by company, department, user and application.

This file has NO application-specific imports on purpose. The same bytes work
in every app; the only per-app value is the application name, which the app
supplies at startup via configure().

--------------------------------------------------------------------------
QUICK START
--------------------------------------------------------------------------

1. At application startup, once:

       import gov_context
       gov_context.configure(application="my-app")

2. Wherever the HTTP client is built, once:

       # httpx (used by the openai SDK, LangChain, LlamaIndex)
       httpx.Client(event_hooks={"request": [gov_context.sync_hook]})
       httpx.AsyncClient(event_hooks={"request": [gov_context.async_hook]})

       # requests / aiohttp / anything without event hooks
       headers = {..., **gov_context.get_headers()}

3. At the start of handling each user request:

       gov_context.set_context(
           company=session["company"],
           department=session["department"],
           user_id=session["user_id"],
           trace_id=gov_context.new_trace_id(),
       )

That is the whole integration.

--------------------------------------------------------------------------
WHAT IT SENDS
--------------------------------------------------------------------------

Three headers, all documented by LiteLLM:

    x-litellm-spend-logs-metadata   JSON: {"company","department","application"}
    x-litellm-end-user-id           the user's id
    x-litellm-trace-id              one id per conversation turn

Headers, not request-body metadata, because the body is fixed when the client
is constructed. Cached clients and cached agent graphs are shared across
users, so per-user values must be attached at send time.

Do NOT invent custom x-<vendor>-* header names. LiteLLM records those in a
field that never reaches the spend-logs table, so nothing would appear on the
governance dashboard.
"""
from __future__ import annotations

import json
import uuid
from contextvars import ContextVar
from typing import Optional

import httpx

# --------------------------------------------------------------------------
# Header names. Do not rename - the gateway reads only these.
# --------------------------------------------------------------------------
_METADATA_HEADER = "x-litellm-spend-logs-metadata"
_END_USER_HEADER = "x-litellm-end-user-id"
_TRACE_ID_HEADER = "x-litellm-trace-id"

# Contract version. Bump when the shape of the metadata payload changes, so
# consumers can tell which shape they received without every app upgrading
# on the same day.
CTX_VERSION = "1"

# Application name, set once at startup by configure().
_application: Optional[str] = None

# Per-request values. A ContextVar rather than a module global: concurrent
# requests never see each other's values, and the value follows the task
# across asyncio.to_thread and contextvars.copy_context().
_headers: ContextVar[Optional[dict]] = ContextVar("gov_headers", default=None)


def configure(application: str) -> None:
    """Set the application name. Call once at startup, before serving traffic.

    This is the only per-app value in this module, which is what lets the file
    itself stay byte-identical across applications.
    """
    global _application
    _application = application


def new_trace_id() -> str:
    """Generate one id per user turn.

    Every LLM call made while this trace id is set is grouped under the same
    session_id in the gateway's spend logs. That is what makes it possible to
    ask what a whole conversation cost rather than what one call cost -
    important for agents, which make several LLM calls per user message.
    """
    return str(uuid.uuid4())


def set_context(
    *,
    company: Optional[str],
    department: Optional[str],
    user_id: Optional[str],
    trace_id: Optional[str] = None,
    application: Optional[str] = None,
) -> None:
    """Record who the current request belongs to.

    Call once at the start of handling a user request, before any LLM call.

    Any value may be None. The gateway records the call as unattributed rather
    than rejecting it, so a gap in the directory never blocks a user - the gap
    shows up on the dashboard's data-quality panel instead.

    `application` normally comes from configure(); pass it here only to
    override for a specific call path.
    """
    app = application or _application

    headers = {
        _METADATA_HEADER: json.dumps({
            "company": company,
            "department": department,
            "application": app,
        })
    }
    if user_id:
        headers[_END_USER_HEADER] = user_id
    if trace_id:
        headers[_TRACE_ID_HEADER] = trace_id

    _headers.set(headers)


def clear_context() -> None:
    """Forget the current request's context.

    Not usually needed - a ContextVar set inside a request does not leak into
    other requests. Useful in long-lived worker loops that process one job
    after another in the same context.
    """
    _headers.set(None)


def get_headers() -> dict:
    """Return the current governance headers, or {} when no context is set.

    For HTTP clients that do not support event hooks - requests, aiohttp,
    urllib - merge this into the headers you already send:

        headers={"Content-Type": "application/json", **get_headers()}
    """
    return dict(_headers.get() or {})


def sync_hook(request: httpx.Request) -> None:
    """httpx request event hook - attaches the headers as the request is sent.

    Running at send time is the point. The HTTP client, and any cached agent
    graph holding it, is built once and shared, while these values differ per
    user. Attaching at construction time would force a rebuild per user.

    No-ops when no context is set, so background jobs and startup calls still
    work; they simply arrive unattributed.
    """
    current = _headers.get()
    if not current:
        return
    request.headers.update(current)


async def async_hook(request: httpx.Request) -> None:
    """Async counterpart of sync_hook.

    httpx requires a coroutine for AsyncClient event hooks, but the work is
    synchronous, so this just delegates.
    """
    sync_hook(request)
