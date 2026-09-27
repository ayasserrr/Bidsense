import logging
from functools import lru_cache

import httpx
from openai import AsyncOpenAI

from helpers.gov_context import async_hook

logger = logging.getLogger(__name__)


@lru_cache
def get_gateway_client(
    base_url: str,
    api_key: str,
    connect_timeout_seconds: float,
    verify_tls: bool,
) -> AsyncOpenAI:
    """One client per distinct configuration, cached and reused across calls -
    `lru_cache` also makes first-creation thread-safe.

    On `base_url`: the gateway is `http://10.3.23.16:4000`, with NO `/v1`
    suffix. The OpenAI SDK appends `/chat/completions` to whatever it is
    given, so the bare host:port is exactly right - adding `/v1` produces
    `/v1/chat/completions` and 404s.

    On `max_retries=0`: the SDK retries twice by default, and
    `run_structured_call` already owns retry policy (2 transport attempts x
    up to 3 repair attempts). Leaving the SDK's default on would silently
    multiply those into as many as 18 gateway calls per extraction, each
    carrying the full source text. Retry policy lives in exactly one place.

    The event hook attaches the LiteLLM governance headers at SEND time,
    which matters because this client is built once and shared while the
    signed-in user differs per request.
    """
    return AsyncOpenAI(
        base_url=base_url,
        api_key=api_key,
        max_retries=0,
        http_client=httpx.AsyncClient(
            verify=verify_tls,
            # The per-call `timeout=` argument overrides the read timeout;
            # this default only has to be generous enough not to pre-empt it.
            timeout=httpx.Timeout(600.0, connect=connect_timeout_seconds),
            event_hooks={"request": [async_hook]},
        ),
    )
