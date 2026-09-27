import asyncio
import contextvars
import logging
import random
import time
import weakref
from collections import deque
from contextlib import asynccontextmanager
from typing import TypeVar

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableConfig
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError
from pydantic import BaseModel, ValidationError

from helpers.llm_client import get_gateway_client

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LlmCallError(Exception):
    """The gateway call itself failed (network/API error) after exhausting retries."""


class GatewayCallError(LlmCallError):
    """A single gateway call failed (network/HTTP error, empty response).

    Subclasses `LlmCallError` deliberately: `routes/extract.py`,
    `routes/sanity_check.py` and `routes/verification.py` all catch
    `(LlmValidationError, LlmCallError)` and turn it into a useful HTTP error.
    A sibling class would escape those handlers and surface as a bare 500.
    """


class GatewayRejectedError(GatewayCallError):
    """The gateway refused the request itself - HTTP 400/401/403/404/413/422,
    e.g. an input longer than the model's context window.

    Separate from its parent so the retry loop can tell it apart: sending the
    identical request again gets the identical refusal, so it is not retried.
    It is still an `LlmCallError`, so `run_tool_call`'s fallback to the other
    model - the one thing that CAN help with a context-window refusal - still
    happens, only without the backoff and repeat request in front of it.
    """


class LlmTruncatedError(GatewayCallError):
    """The model hit its output cap mid-JSON (`finish_reason == "length"`).

    A genuinely new failure mode compared with the previous provider, and one
    worth naming: the body is invalid JSON, so without this it would surface
    as a confusing schema-validation failure and burn all three repair
    attempts re-generating a response cut off at the same place.
    """

    def __init__(self, completion_tokens: int | None = None):
        self.completion_tokens = completion_tokens
        super().__init__(
            f"model hit its output token cap before closing the JSON "
            f"(completion_tokens={completion_tokens}); raise the model's "
            f"LLM_*_MAX_OUTPUT_TOKENS or reduce the amount of source text per call"
        )


class LlmValidationError(Exception):
    """The model's JSON kept failing schema validation after exhausting repair attempts."""

    def __init__(self, raw_response: str, validation_error: ValidationError):
        self.raw_response = raw_response
        self.validation_error = validation_error
        super().__init__(str(validation_error))


def build_response_schema(model: type[BaseModel], *, force_required: bool = True) -> dict:
    """JSON Schema for `model`, with every top-level property marked required.

    THIS IS LOAD-BEARING, not a tidy-up. Pydantic omits the `required` array
    entirely when every field has a default - which is the case for
    `OfferExtractionPayload`. Under the gateway's guided decoding an absent
    `required` means the grammar legally permits `{}`, so the model may close
    the object the moment it has emitted `items`. Measured against a real
    offer, that is exactly what happened: line items came back correct while
    all twenty offer-level scalars (delivery terms, validity, warranty, VAT,
    currency, grand total, payment terms) came back null despite being plainly
    stated in the document. The same prompt against a small schema filled them
    in. Forcing `required` makes emitting each key unavoidable, so a null has
    to be a decision the model actually makes rather than one it falls into by
    closing the object early.

    Nullability is unaffected: these fields are typed `anyOf: [..., null]`, so
    a genuinely absent value is still expressible as an explicit null - which
    is what the extraction prompt asks for when the source is silent.

    Only the ROOT object is forced. Doing it recursively through `$defs` would
    also force every field of every line item, multiplying output length on a
    36-row BOQ and risking truncation - a worse failure than the one being
    fixed. Revisit per-model if a nested field turns out to be dropped.
    """
    schema = model.model_json_schema()
    if force_required:
        properties = schema.get("properties")
        if properties:
            schema["required"] = list(properties.keys())
    return schema


# HTTP statuses that mean the request itself was refused, where sending it
# again unchanged can only be refused again. 408 (timeout), 409, 429 (rate
# limit) and every 5xx are left retryable - those are the gateway or the model
# being busy, which waiting can fix.
_NOT_RETRYABLE_STATUSES = frozenset({400, 401, 403, 404, 413, 422})


# Which requests get a free gateway slot first when more are waiting than
# there are slots. Lower is sooner. The value travels in a ContextVar rather
# than as a parameter because the only thing that is ever demoted - the
# completeness scan that runs beside extraction - is a whole asyncio.Task, and
# every task it spawns copies its context: one `set` at the top of that task
# demotes all of its calls without threading an argument through five layers.
#
# Why it exists: the gate below used to be a plain FIFO semaphore. The scan is
# started a moment after extraction's first drafts are queued, so its calls
# sat in the queue AHEAD of every verify pass - extraction's second half
# waited behind work nothing downstream needed for minutes. Ordering the queue
# changes nothing about any request's content, only which one is sent first.
LLM_PRIORITY_CRITICAL = 0
LLM_PRIORITY_BACKGROUND = 1
_llm_priority: contextvars.ContextVar[int] = contextvars.ContextVar(
    "llm_priority", default=LLM_PRIORITY_CRITICAL
)


def set_llm_priority(priority: int) -> None:
    """Sets the gateway-queue priority for the calling task and every task it
    creates from here on. Call it at the top of a task that runs off the
    pipeline's critical path; the default is critical."""
    _llm_priority.set(priority)


class _PriorityGate:
    """A counting semaphore that hands a freed slot to the most urgent waiter,
    FIFO among equals - with a single priority in play it behaves exactly like
    the `asyncio.Semaphore` it replaced.

    Background work is not kept off any slot, only queued behind pipeline work.
    Reserving a slot for the pipeline was measured and was slower: the scan's
    answers are needed by the completeness stage a few minutes later anyway,
    and starving it of a slot just moved the wait to the end of the run.

    Single event loop only, like the semaphore: no locks, because nothing
    between a check and its update ever awaits.
    """

    def __init__(self, slots: int):
        self._free = slots
        self._waiting: dict[int, deque[asyncio.Future]] = {
            LLM_PRIORITY_CRITICAL: deque(),
            LLM_PRIORITY_BACKGROUND: deque(),
        }

    def _someone_ahead(self, priority: int) -> bool:
        return any(
            any(not future.done() for future in queue)
            for level, queue in self._waiting.items()
            if level <= priority
        )

    def _dispatch(self) -> None:
        """Hands free slots to waiters, most urgent level first."""
        while self._free > 0:
            for level in sorted(self._waiting):
                queue = self._waiting[level]
                while queue and queue[0].done():
                    queue.popleft()  # cancelled while waiting
                if queue:
                    self._free -= 1
                    queue.popleft().set_result(None)
                    break
            else:
                return

    async def acquire(self, priority: int) -> None:
        priority = priority if priority in self._waiting else LLM_PRIORITY_CRITICAL
        if self._free > 0 and not self._someone_ahead(priority):
            self._free -= 1
            return
        future = asyncio.get_running_loop().create_future()
        self._waiting[priority].append(future)
        try:
            await future
        except BaseException:
            # Cancelled while waiting: the future is done, and `_dispatch`
            # discards it. Cancelled in the instant between being handed the
            # slot and resuming: the slot is ours, and it must be passed on or
            # it leaks for the life of the process.
            if future.done() and not future.cancelled():
                self.release()
            raise

    def release(self) -> None:
        self._free += 1
        self._dispatch()

    @asynccontextmanager
    async def slot(self, priority: int):
        await self.acquire(priority)
        try:
            yield
        finally:
            self.release()


# One ceiling on how many requests this process has in flight at the gateway
# at once, shared by every stage - extraction chunks, the completeness facets,
# taxonomy resolution, and any other run happening concurrently for another
# user. Keyed by event loop and held weakly: the gate's futures belong to the
# loop that created them, so a module-level singleton would bind a test's
# throwaway loop forever.
#
# The gate is entered around the network call ONLY. Retry backoff and repair
# re-prompting happen outside it, so a call that is merely sleeping between
# attempts is not holding a slot that another chunk could be using.
_gateway_gates: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _PriorityGate]" = (
    weakref.WeakKeyDictionary()
)


def _gateway_gate(max_concurrent_requests: int) -> _PriorityGate:
    """The gate for the running loop, created on first use.

    Sized by the first caller on that loop; every stage passes the same
    configured value (`LLM_MAX_CONCURRENT_REQUESTS`), and the point of the gate
    is a single app-wide ceiling rather than a per-stage one, so a later
    different size is deliberately ignored rather than resizing mid-flight.
    """
    loop = asyncio.get_running_loop()
    gate = _gateway_gates.get(loop)
    if gate is None:
        gate = _PriorityGate(max(1, max_concurrent_requests))
        _gateway_gates[loop] = gate
    return gate


class GatewayStructuredLLM(Runnable[list[BaseMessage], str]):
    """LangChain `Runnable` wrapping the corporate LiteLLM gateway's
    OpenAI-compatible JSON-schema mode.

    Talks to the gateway directly through `openai.AsyncOpenAI` rather than
    `langchain_openai.ChatOpenAI`: nothing on this path uses chat-model
    features (no tool binding, no streaming, no callbacks), and
    `with_structured_output()` would run its own parse-and-retry loop that
    fights the one in `run_structured_call`.

    Takes `BaseMessage`s from a `ChatPromptTemplate`, plus any repair turns
    appended by `run_structured_call`.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        response_schema: dict,
        schema_name: str,
        timeout_seconds: float,
        max_output_tokens: int,
        temperature: float,
        enable_thinking: bool,
        reasoning_effort: str | None,
        connect_timeout_seconds: float,
        verify_tls: bool,
        max_concurrent_requests: int,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.response_schema = response_schema
        self.schema_name = schema_name
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.enable_thinking = enable_thinking
        self.reasoning_effort = reasoning_effort or None
        self.connect_timeout_seconds = connect_timeout_seconds
        self.verify_tls = verify_tls
        self.max_concurrent_requests = max_concurrent_requests
        # Token usage of the most recent call, for the `llm_call` log line.
        # One instance serves one structured call, whose attempts run in
        # sequence, so this is never shared between concurrent requests.
        self.last_usage: dict = {}

    def _extra_body(self) -> dict:
        """Fields outside the OpenAI SDK's own parameters, sent verbatim.

        `enable_thinking` goes to the chat template; `reasoning_effort` sits
        beside it, and is left out entirely when not configured, so a model
        that does not know the field is never sent it. This is the same wire
        shape the corporate Quality Assistant proved against this gateway.
        """
        body: dict = {"chat_template_kwargs": {"enable_thinking": self.enable_thinking}}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def _describe_transport_failure(self, exc: APIConnectionError, started: float | None) -> str:
        """Says WHICH transport failure it was, because the fixes are opposite.

        "Could not connect" is a network problem on this host - a firewall, a
        wrong LLM_BASE_URL - and waiting longer will never help. "Connected, but
        no answer in time" is a busy or slow model, where a longer timeout or a
        lower reasoning effort is exactly the fix. One message for both sent
        people looking in the wrong place.
        """
        cause = exc.__cause__
        cause_name = type(cause).__name__ if cause is not None else type(exc).__name__
        elapsed = time.monotonic() - started if started is not None else 0.0
        if isinstance(cause, (httpx.ConnectTimeout, httpx.ConnectError)):
            return (
                f"could not connect to the gateway at {self.base_url} within "
                f"{self.connect_timeout_seconds:.0f}s ({cause_name}) - check that this host can reach it"
            )
        if isinstance(exc, APITimeoutError):
            return (
                f"the gateway accepted the request but {self.model} did not finish answering within "
                f"{self.timeout_seconds:.0f}s - the model is slow or busy; raise LLM_TIMEOUT_SECONDS "
                f"or lower its reasoning effort"
            )
        return f"the connection to the gateway dropped after {elapsed:.0f}s ({cause_name}: {cause})"

    @staticmethod
    def _to_openai_messages(messages: list[BaseMessage]) -> list[dict]:
        """Map LangChain roles onto the wire format.

        `ai` is accepted here where the previous transport rejected it: the
        repair loop appends the model's own rejected JSON, and an assistant
        turn is both its honest role and a practical necessity - some vLLM
        chat templates require strict user/assistant alternation and will
        either error or silently merge two consecutive user turns.
        """
        role_map = {"system": "system", "human": "user", "ai": "assistant"}
        out: list[dict] = []
        for message in messages:
            role = getattr(message, "type", "")
            mapped = role_map.get(role)
            if mapped is None:
                raise ValueError(
                    f"GatewayStructuredLLM supports 'system'/'human'/'ai' messages, got '{role}'"
                )
            content = message.content if isinstance(message.content, str) else str(message.content)
            out.append({"role": mapped, "content": content})
        return out

    def invoke(self, input: list[BaseMessage], config: RunnableConfig | None = None, **kwargs) -> str:
        raise NotImplementedError("GatewayStructuredLLM only supports async invocation - use ainvoke.")

    async def ainvoke(self, input: list[BaseMessage], config: RunnableConfig | None = None, **kwargs) -> str:
        client = get_gateway_client(
            self.base_url, self.api_key, self.connect_timeout_seconds, self.verify_tls
        )

        # Timed from when this call gets its slot, not from when it started
        # queueing for one: the timeout it is compared against is per request.
        started: float | None = None
        try:
            async with _gateway_gate(self.max_concurrent_requests).slot(_llm_priority.get()):
                started = time.monotonic()
                response = await client.chat.completions.create(
                    model=self.model,
                    messages=self._to_openai_messages(input),
                    temperature=self.temperature,
                    max_tokens=self.max_output_tokens,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": self.schema_name,
                            # `strict` is deliberately off: OpenAI strict mode
                            # requires `additionalProperties: false` on every
                            # object, which the payload's `extra_attributes`
                            # (a string -> string map) cannot satisfy. The schema is
                            # enforced by guided decoding either way, and the
                            # repair loop is the real backstop.
                            "strict": False,
                            "schema": self.response_schema,
                        },
                    },
                    # Thinking and its effort are per model (see config.py).
                    # With thinking on, the reasoning trace shares max_tokens
                    # with the answer, which is why the primary model's cap is
                    # the larger one. vLLM applies the JSON schema to the answer
                    # after the trace, not to the trace itself.
                    extra_body=self._extra_body(),
                    # An httpx.Timeout, NOT a bare float. The SDK hands a float
                    # to httpx as the limit for EVERY phase, connect included,
                    # silently replacing the client's short connect timeout: an
                    # unreachable gateway then hung for the full read timeout
                    # (ten minutes) and was indistinguishable from a slow model.
                    timeout=httpx.Timeout(self.timeout_seconds, connect=self.connect_timeout_seconds),
                )
        except (APITimeoutError, APIConnectionError) as exc:
            raise GatewayCallError(self._describe_transport_failure(exc, started)) from exc
        except APIStatusError as exc:
            if exc.status_code in _NOT_RETRYABLE_STATUSES:
                raise GatewayRejectedError(str(exc)) from exc
            raise GatewayCallError(str(exc)) from exc
        except APIError as exc:
            raise GatewayCallError(str(exc)) from exc
        except Exception as exc:
            raise GatewayCallError(f"gateway call failed unexpectedly: {exc}") from exc

        if not response.choices:
            raise GatewayCallError("gateway returned no choices")

        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        details = getattr(usage, "completion_tokens_details", None)
        self.last_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": completion_tokens,
            # How much of the output budget went on thinking, when the gateway
            # reports it - the number to watch when answers start truncating.
            "reasoning_tokens": getattr(details, "reasoning_tokens", None),
        }

        if choice.finish_reason == "length":
            raise LlmTruncatedError(completion_tokens)

        text = (choice.message.content or "").strip()
        if not text:
            # vLLM routes a reasoning trace to `reasoning_content`; if thinking
            # consumed the budget the visible content never started.
            if getattr(choice.message, "reasoning_content", None):
                raise GatewayCallError(
                    "gateway returned an empty answer - the model spent its whole output "
                    "budget on a reasoning trace; raise its LLM_*_MAX_OUTPUT_TOKENS or "
                    "lower its reasoning effort"
                )
            raise GatewayCallError("gateway returned an empty response")
        return text


async def _call_with_retries(
    *,
    llm: GatewayStructuredLLM,
    messages: list[BaseMessage],
    log_id: str,
    pass_label: str,
    max_attempts: int,
    backoff_seconds: float,
) -> str:
    start_time = time.monotonic()
    raw_response: str | None = None
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            raw_response = await llm.ainvoke(messages)
            break
        except LlmTruncatedError as exc:
            # Retrying verbatim would be cut off in the same place. Surface it
            # immediately with an actionable message rather than burning the
            # second attempt and all three repair attempts on the same wall.
            logger.error("llm_call log_id=%s pass=%s truncated: %s", log_id, pass_label, exc)
            raise
        except GatewayCallError as exc:
            last_error = exc
            logger.warning(
                "llm_call log_id=%s pass=%s attempt=%s/%s failed: %s",
                log_id, pass_label, attempt, max_attempts, exc,
            )
            if isinstance(exc, GatewayRejectedError):
                # A refusal of the request itself is not transient - the same
                # request is refused again after any backoff. Give up on this
                # model now; the caller's fallback decides what happens next.
                break
            # Transient backend errors need real recovery time - 1s wasn't enough
            # in practice. Exponential with a 30s cap plus a little jitter, so
            # concurrent chunks hitting the same failure don't all retry in lockstep.
            if attempt < max_attempts:
                sleep_seconds = min(backoff_seconds * 2 ** (attempt - 1), 30) + random.uniform(0, 1)
                logger.info(
                    "llm_call log_id=%s pass=%s backing off %.1fs before retry (attempt=%s/%s)",
                    log_id, pass_label, sleep_seconds, attempt, max_attempts,
                )
                await asyncio.sleep(sleep_seconds)

    duration_seconds = time.monotonic() - start_time
    approx_input_tokens = sum(len(str(m.content)) for m in messages) // 4

    logger.info(
        "llm_call log_id=%s pass=%s model=%s thinking=%s effort=%s approx_input_tokens=%s "
        "prompt_tokens=%s completion_tokens=%s reasoning_tokens=%s duration_seconds=%.2f",
        log_id, pass_label, llm.model, llm.enable_thinking, llm.reasoning_effort,
        approx_input_tokens, llm.last_usage.get("prompt_tokens"),
        llm.last_usage.get("completion_tokens"), llm.last_usage.get("reasoning_tokens"),
        duration_seconds,
    )

    if raw_response is None:
        if last_error is None:
            # Only reachable if max_attempts < 1 - config validation should
            # already prevent this, but fail with a real diagnostic instead
            # of a misleading LlmCallError("None") if it ever slips through.
            raise LlmCallError(f"no gateway call was attempted (max_attempts={max_attempts})")
        raise LlmCallError(str(last_error)) from last_error
    return raw_response


async def run_structured_call(
    *,
    response_model: type[T],
    base_url: str,
    api_key: str,
    model: str,
    prompt: ChatPromptTemplate,
    prompt_variables: dict,
    response_schema: dict,
    timeout_seconds: float,
    max_output_tokens: int,
    temperature: float,
    enable_thinking: bool,
    reasoning_effort: str | None,
    connect_timeout_seconds: float,
    verify_tls: bool,
    max_concurrent_requests: int,
    max_attempts: int,
    backoff_seconds: float,
    max_repair_attempts: int,
    log_id: str,
    pass_label: str,
) -> tuple[T, int]:
    """Calls the gateway via `GatewayStructuredLLM` expecting JSON matching
    `response_model`. Retries transient call failures up to `max_attempts`
    times (exponential backoff off `backoff_seconds`, capped, with jitter);
    on a Pydantic validation failure, re-prompts with the actual error and
    retries up to `max_repair_attempts` times - a separate mechanism for a
    separate failure mode. Backs every tool in `tools/`.

    Returns (validated_instance, repair_attempts_used).
    """
    llm = GatewayStructuredLLM(
        base_url=base_url,
        api_key=api_key,
        model=model,
        response_schema=response_schema,
        schema_name=response_model.__name__,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        enable_thinking=enable_thinking,
        reasoning_effort=reasoning_effort,
        connect_timeout_seconds=connect_timeout_seconds,
        verify_tls=verify_tls,
        max_concurrent_requests=max_concurrent_requests,
    )

    messages: list[BaseMessage] = prompt.format_messages(**prompt_variables)
    repair_attempts_used = 0

    for attempt in range(1, max_repair_attempts + 1):
        raw_response = await _call_with_retries(
            llm=llm,
            messages=messages,
            log_id=log_id,
            pass_label=pass_label,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
        )

        try:
            validated = response_model.model_validate_json(raw_response)
            logger.info(
                "llm_call log_id=%s pass=%s attempt=%s validation_passed=True repair_attempts_used=%s",
                log_id, pass_label, attempt, repair_attempts_used,
            )
            return validated, repair_attempts_used
        except ValidationError as exc:
            repair_attempts_used += 1
            validation_errors = str(exc)

            if attempt >= max_repair_attempts:
                logger.error(
                    "llm_call log_id=%s pass=%s validation_failed after %s repair attempts: %s",
                    log_id, pass_label, repair_attempts_used, validation_errors,
                )
                raise LlmValidationError(raw_response, exc) from exc

            repair_prompt = (
                f"The JSON you just returned failed schema validation with the following error(s):\n"
                f"{validation_errors}\n\n"
                f"Return a corrected JSON object that satisfies the schema. Fix only what is "
                f"necessary to satisfy validation — do not otherwise change field values, do "
                f"not drop any information that was present, and do not restructure items "
                f"unless the validation error itself concerns hierarchy (e.g. a dangling "
                f"parent_local_id or a cycle)."
            )

            logger.warning(
                "llm_call log_id=%s pass=%s attempt=%s validation_failed initiating repair attempt %s/%s",
                log_id, pass_label, attempt, repair_attempts_used, max_repair_attempts,
            )

            # No backoff before a repair. The model answered, and answered
            # promptly - its JSON was wrong, which is not a transient fault
            # that waiting clears; the correction prompt is sent at once.
            # Transport failures keep their own backoff in `_call_with_retries`.

            # The rejected JSON goes back as an ASSISTANT turn followed by the
            # correction as a user turn, rather than folding both into one user
            # message: it is the honest role for it, and it preserves the
            # user/assistant alternation some chat templates require.
            messages = [
                *messages,
                AIMessage(content=raw_response),
                HumanMessage(content=repair_prompt),
            ]

    # Unreachable while max_repair_attempts >= 1 (the loop either returns or
    # raises), but a falsy value would otherwise fall off the end returning None.
    raise LlmCallError(f"max_repair_attempts must be at least 1, got {max_repair_attempts}")
