import json
import logging

from helpers.llm_runnable import LlmCallError, LlmValidationError
from models.enums import SanityCheckSeverity, SanityCheckStatus
from schema.offer import OfferExtractionPayload
from schema.sanity_check import SanityCheckFinding, SanityCheckResult
from tools import check_offer_arithmetic, judge_sanity_check_flags
from tools._common import unpack_result

from .BaseController import BaseController

logger = logging.getLogger(__name__)


class SanityCheckController(BaseController):
    """Unlike the other controllers, this one never touches the database -
    it reviews an already-extracted, in-memory `OfferExtractionPayload` for
    internal pricing consistency, nothing more, so it doesn't accept or
    store a `db` session at all."""

    async def check_offer(self, payload: OfferExtractionPayload, log_id: str) -> SanityCheckResult:
        """Checks pricing consistency via `check_offer_arithmetic`
        (deterministic, always runs) then `judge_sanity_check_flags` (LLM,
        only if flags were found) - a fixed order, not an agent's choice, so
        a clean extraction never pays for an LLM call."""
        payload_json = payload.model_dump_json()
        flags_json = await check_offer_arithmetic.ainvoke({"payload_json": payload_json})
        flags = json.loads(flags_json)

        if not flags:
            logger.info("sanity_check log_id=%s status=passed (no arithmetic flags raised)", log_id)
            return SanityCheckResult(
                status=SanityCheckStatus.PASSED,
                findings=[],
                summary="No pricing inconsistencies detected by the automated numeric check.",
            )

        try:
            judged_raw = await judge_sanity_check_flags.ainvoke(
                {"payload_json": payload_json, "flags_json": flags_json, "log_id": log_id}
            )
            result, telemetry = unpack_result(judged_raw, SanityCheckResult)
            repair_attempts = telemetry.get("repair_attempts", 0)
        except (LlmCallError, LlmValidationError) as exc:
            # Fail safe: if the review call itself fails, surface the raw
            # deterministic flags as findings rather than silently reporting
            # "passed" - an offer with unresolved arithmetic flags must never
            # look clean just because the LLM review step errored out.
            logger.error(
                "sanity_check log_id=%s LLM review failed (%s); surfacing %s raw flag(s) unreviewed",
                log_id, exc, len(flags),
            )
            return SanityCheckResult(
                status=SanityCheckStatus.NEEDS_REVIEW,
                findings=[
                    SanityCheckFinding(
                        issue_type=flag["flag_type"],
                        severity=SanityCheckSeverity.WARNING,
                        field_path=flag["field_path"],
                        description=flag["description"] + " (automated flag; LLM review unavailable)",
                    )
                    for flag in flags
                ],
                summary=(
                    f"{len(flags)} automated pricing flag(s) were found but could not be reviewed "
                    "- surfaced as-is pending manual review."
                ),
            )

        logger.info(
            "sanity_check log_id=%s status=%s flags_raised=%s findings_kept=%s repair_attempts=%s",
            log_id, result.status, len(flags), len(result.findings), repair_attempts,
        )
        return result
