import json
import logging
from typing import TypeVar

from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from pydantic import BaseModel

from helpers import get_settings
from helpers.llm_runnable import LlmCallError, LlmTruncatedError, LlmValidationError, run_structured_call

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Rough estimate; gemma's real context is ~60k and vLLM refuses a request whose
# input plus max_tokens exceeds a model's window. Same crude heuristic as
# `_call_with_retries`'s approx_input_tokens (len(content) // 4) - good enough
# to decide "don't bother" before burning a call that would just fail again.
HELPER_CONTEXT_TOKENS = 55_000


def build_system_human_prompt(system_prompt: str) -> ChatPromptTemplate:
    """Builds a `[system, human]` `ChatPromptTemplate` where the system
    prompt is a literal `SystemMessage`, not a templated string. These
    system prompts are long, hand-written spec documents that use `{...}`
    freely in prose (e.g. describing a field's shape as `{label: value}`) -
    passing them through `str.format()` as a template (as
    `("system", system_prompt)` would) raises `KeyError` on the first
    literal brace. Only the human turn (`{user_content}`) is ever templated."""
    return ChatPromptTemplate.from_messages(
        [SystemMessage(content=system_prompt), HumanMessagePromptTemplate.from_template("{user_content}")]
    )


def pack_result(result: BaseModel, **telemetry: object) -> str:
    """Serializes a tool's structured result plus telemetry (repair attempt
    counts, etc.) into the JSON string every LangChain tool here returns -
    callers round-trip through `unpack_result` rather than getting the
    Pydantic instance back directly."""
    return json.dumps({"result": result.model_dump(mode="json"), "telemetry": telemetry})


def unpack_result(raw: str, model: type[T]) -> tuple[T, dict]:
    """Inverse of `pack_result`."""
    data = json.loads(raw)
    return model.model_validate(data["result"]), data.get("telemetry", {})


def _model_settings(settings, *, use_helper_model: bool) -> dict:
    """The per-model fields `run_tool_call` branches on, for whichever model
    (primary or helper) is being targeted - shared so a fallback attempt can
    build the OTHER model's settings the same way."""
    if use_helper_model:
        # gemma: no reasoning_effort, ever - it is a qwen field.
        return {
            "model": settings.LLM_HELPER_MODEL,
            "enable_thinking": settings.LLM_HELPER_ENABLE_THINKING,
            "reasoning_effort": None,
            "max_output_tokens": settings.LLM_HELPER_MAX_OUTPUT_TOKENS,
        }
    return {
        "model": settings.LLM_PRIMARY_MODEL,
        "enable_thinking": settings.LLM_PRIMARY_ENABLE_THINKING,
        "reasoning_effort": settings.LLM_PRIMARY_REASONING_EFFORT.strip() or None,
        "max_output_tokens": settings.LLM_PRIMARY_MAX_OUTPUT_TOKENS,
    }


def _approx_input_tokens(prompt: ChatPromptTemplate, user_content: str) -> int:
    """Same crude heuristic as `_call_with_retries`: total character count of
    the formatted prompt, divided by 4."""
    messages = prompt.format_messages(user_content=user_content)
    return sum(len(str(m.content)) for m in messages) // 4


async def run_tool_call(
    *,
    response_model: type[T],
    response_schema: dict,
    prompt: ChatPromptTemplate,
    user_content: str,
    log_id: str,
    pass_label: str,
    use_helper_model: bool = False,
) -> str:
    """Shared body behind every LLM-backed tool: fetches settings, calls
    `run_structured_call`, packs the result. `response_schema` is passed in
    so callers can cache it at import time instead of recomputing it here.

    `use_helper_model` routes a stage to the smaller/faster model. Extraction
    and source verification need the primary model's larger context window and
    stronger reading; the cheap judgement calls (which are handed a compact
    JSON payload rather than a whole document) do not.

    If the requested model's call still fails after its own retries
    (`LlmCallError` - a transport failure, never a truncated or schema-invalid
    response) and `LLM_FALLBACK_ENABLED` is on, the whole call is retried once
    more against the OTHER model (qwen<->gemma), with its own fresh retry loop.
    """
    settings = get_settings()
    model_settings = _model_settings(settings, use_helper_model=use_helper_model)

    async def _call(target_settings: dict) -> tuple:
        return await run_structured_call(
            response_model=response_model,
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            model=target_settings["model"],
            prompt=prompt,
            prompt_variables={"user_content": user_content},
            response_schema=response_schema,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
            max_output_tokens=target_settings["max_output_tokens"],
            temperature=settings.LLM_TEMPERATURE,
            enable_thinking=target_settings["enable_thinking"],
            reasoning_effort=target_settings["reasoning_effort"],
            connect_timeout_seconds=settings.LLM_CONNECT_TIMEOUT_SECONDS,
            verify_tls=settings.LLM_VERIFY_TLS,
            max_concurrent_requests=settings.LLM_MAX_CONCURRENT_REQUESTS,
            max_attempts=settings.LLM_CALL_MAX_ATTEMPTS,
            backoff_seconds=settings.LLM_CALL_BACKOFF_SECONDS,
            max_repair_attempts=settings.EXTRACTION_MAX_REPAIR_ATTEMPTS,
            log_id=log_id,
            pass_label=pass_label,
        )

    try:
        result, repair_attempts = await _call(model_settings)
    except (LlmTruncatedError, LlmValidationError):
        # The model answered but the JSON was cut off or invalid - a different
        # model would not obviously fix either, so no fallback attempt.
        raise
    except LlmCallError as exc:
        if not settings.LLM_FALLBACK_ENABLED:
            raise
        if settings.LLM_PRIMARY_MODEL == settings.LLM_HELPER_MODEL:
            # Nothing to fall back to.
            raise

        falling_back_to_helper = not use_helper_model
        if falling_back_to_helper:
            # qwen (256k context, thinking) -> gemma (~60k context, no
            # thinking) can genuinely not fit: gemma's output cap is smaller
            # AND its context is much smaller. Check before spending a call.
            approx_input_tokens = _approx_input_tokens(prompt, user_content)
            if approx_input_tokens + settings.LLM_HELPER_MAX_OUTPUT_TOKENS > HELPER_CONTEXT_TOKENS:
                logger.warning(
                    "llm_call log_id=%s pass=%s fallback to %s skipped: approx_input_tokens=%s + "
                    "max_output_tokens=%s would exceed HELPER_CONTEXT_TOKENS=%s",
                    log_id, pass_label, settings.LLM_HELPER_MODEL,
                    approx_input_tokens, settings.LLM_HELPER_MAX_OUTPUT_TOKENS, HELPER_CONTEXT_TOKENS,
                )
                raise type(exc)(
                    f"{exc}; fallback to {settings.LLM_HELPER_MODEL} skipped because the input "
                    f"would not fit the smaller model's context"
                ) from exc

        fallback_settings = _model_settings(settings, use_helper_model=falling_back_to_helper)
        logger.warning(
            "llm_call log_id=%s pass=%s falling back from %s to %s after: %s",
            log_id, pass_label, model_settings["model"], fallback_settings["model"], exc,
        )
        try:
            result, repair_attempts = await _call(fallback_settings)
        except Exception as fallback_exc:
            logger.error(
                "llm_call log_id=%s pass=%s fallback to %s also failed: %s "
                "(original failure on %s was: %s)",
                log_id, pass_label, fallback_settings["model"], fallback_exc,
                model_settings["model"], exc,
            )
            # Chained to the primary model's own failure (`exc`) so neither
            # reason is lost - without this, only "gemma is down" survives to
            # the caller and the log, with no trace of why qwen was tried
            # first or failed.
            raise fallback_exc from exc
        # A degraded run: it only succeeded because the OTHER model answered.
        # warning, not info - this is the one place that fact is visible at
        # all, since fallback_used/fallback_model are not currently persisted
        # anywhere downstream (see WORK_IN_PROGRESS.md's open issues).
        logger.warning(
            "llm_call log_id=%s pass=%s fallback to %s succeeded (primary %s had failed: %s)",
            log_id, pass_label, fallback_settings["model"], model_settings["model"], exc,
        )
        return pack_result(
            result,
            repair_attempts=repair_attempts,
            fallback_used=True,
            fallback_model=fallback_settings["model"],
        )

    return pack_result(result, repair_attempts=repair_attempts, fallback_used=False, fallback_model=None)
