import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from helpers.llm_runnable import LlmCallError, LlmValidationError
from helpers.source_text import get_offer_source_text
from models.enums import ExtractionVerdict, FindingVerdict, VerificationStatus
from schema.offer import OfferExtractionPayload
from schema.sanity_check import SanityCheckResult
from schema.verification import VerificationLlmOutput, VerificationResult, VerifiedFinding
from tools import verify_findings_against_source
from tools._common import unpack_result

from .BaseController import BaseController

logger = logging.getLogger(__name__)


class VerificationController(BaseController):
    """Independently re-checks the extract node's output and the sanity
    check's findings against the original source document. Unlike the
    sanity check (which only judges internal JSON consistency), this
    controller goes back to the parsed source text itself - it needs a `db`
    session to fetch it, the same way `ExtractController` does."""

    def __init__(self, db: AsyncSession):
        super().__init__()
        self.db = db

    async def verify_offer(
        self,
        offer_id: int,
        payload: OfferExtractionPayload,
        sanity_check_result: SanityCheckResult,
        log_id: str,
    ) -> VerificationResult:
        """Runs only when the sanity check found something. For every
        finding, `verify_findings_against_source` independently re-reads the
        original source text. `status` is computed here from the verdicts,
        not asked of the model, so it can't contradict them."""
        if not sanity_check_result.findings:
            logger.info("verification log_id=%s status=skipped (no sanity-check findings)", log_id)
            return VerificationResult(
                status=VerificationStatus.SKIPPED,
                verified_findings=[],
                summary="Sanity check found no issues; source verification was not needed.",
            )

        source_text = await get_offer_source_text(self.db, offer_id)
        if not source_text.strip():
            logger.error(
                "verification log_id=%s no source text available for offer_id=%s", log_id, offer_id
            )
            return self._unverified_fallback(
                sanity_check_result,
                reason="No parsed source document text was available to verify against.",
            )

        findings_json = json.dumps([finding.model_dump(mode="json") for finding in sanity_check_result.findings])

        try:
            verify_raw = await verify_findings_against_source.ainvoke(
                {
                    "source_text": source_text,
                    "payload_json": payload.model_dump_json(),
                    "findings_json": findings_json,
                    "log_id": log_id,
                }
            )
            llm_output, telemetry = unpack_result(verify_raw, VerificationLlmOutput)
            repair_attempts = telemetry.get("repair_attempts", 0)
        except (LlmCallError, LlmValidationError) as exc:
            logger.error(
                "verification log_id=%s LLM review failed (%s); surfacing %s finding(s) as unverified",
                log_id, exc, len(sanity_check_result.findings),
            )
            return self._unverified_fallback(
                sanity_check_result,
                reason="Source verification could not be completed (LLM review failed).",
            )

        status = self._compute_status(llm_output.verified_findings)
        logger.info(
            "verification log_id=%s status=%s findings_reviewed=%s repair_attempts=%s",
            log_id, status.value, len(llm_output.verified_findings), repair_attempts,
        )
        return VerificationResult(
            status=status,
            verified_findings=llm_output.verified_findings,
            summary=llm_output.summary,
        )

    @staticmethod
    def _compute_status(verified_findings: list[VerifiedFinding]) -> VerificationStatus:
        """A human still needs to look at this offer unless every finding was
        both an accurately-extracted value (extraction_verdict=confirmed)
        and a discrepancy the source itself explains away
        (finding_verdict=explained). Any incorrect extraction, any confirmed
        genuine issue, or any insufficient-evidence verdict on either axis
        keeps the offer in needs_human_review - fail-safe, not fail-clean."""
        for finding in verified_findings:
            if finding.extraction_verdict != ExtractionVerdict.CONFIRMED:
                return VerificationStatus.NEEDS_HUMAN_REVIEW
            if finding.finding_verdict != FindingVerdict.EXPLAINED:
                return VerificationStatus.NEEDS_HUMAN_REVIEW
        return VerificationStatus.RESOLVED

    @staticmethod
    def _unverified_fallback(sanity_check_result: SanityCheckResult, reason: str) -> VerificationResult:
        """Fail safe: if verification can't actually run (no source text, or
        the LLM call itself failed), surface every finding as still needing
        review rather than silently reporting 'resolved' - an offer must
        never look clean just because the verification step couldn't run."""
        return VerificationResult(
            status=VerificationStatus.NEEDS_HUMAN_REVIEW,
            verified_findings=[
                VerifiedFinding(
                    issue_type=finding.issue_type,
                    field_path=finding.field_path,
                    extraction_verdict=ExtractionVerdict.INSUFFICIENT_EVIDENCE,
                    extraction_correction=None,
                    finding_verdict=FindingVerdict.INSUFFICIENT_EVIDENCE,
                    explanation=None,
                    evidence_quote="N/A - source verification did not run.",
                    reasoning=reason,
                )
                for finding in sanity_check_result.findings
            ],
            summary=f"{reason} {len(sanity_check_result.findings)} finding(s) surfaced as needing manual review.",
        )
