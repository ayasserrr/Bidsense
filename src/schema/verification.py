from pydantic import BaseModel, Field

from models.enums import (
    ExtractionVerdict,
    FindingVerdict,
    ResponseSignal,
    SanityCheckIssueType,
    VerificationStatus,
)
from schema.offer import OfferExtractionPayload
from schema.sanity_check import SanityCheckResult


class VerifiedFinding(BaseModel):
    issue_type: SanityCheckIssueType = Field(
        description="Copy the sanity-check finding's own issue type - which finding this verification entry is about."
    )
    field_path: str = Field(
        description="Copy the sanity-check finding's own field_path - which finding this verification entry is about."
    )
    extraction_verdict: ExtractionVerdict = Field(
        description=(
            "Whether the extracted value(s) this finding is about are actually supported by the "
            "source document. 'confirmed' if the source states the same value(s) the JSON has. "
            "'incorrect' if the source clearly states something different, or the value was "
            "misread/misplaced during extraction. 'insufficient_evidence' if the source doesn't "
            "contain enough information to confirm or refute the extracted value(s) either way - "
            "never guess when the source is silent or ambiguous."
        )
    )
    extraction_correction: str | None = Field(
        default=None,
        description=(
            "Only set when extraction_verdict is 'incorrect': the correct value(s), exactly as "
            "actually stated in the source document. Leave null otherwise."
        ),
    )
    finding_verdict: FindingVerdict = Field(
        description=(
            "Whether the discrepancy the sanity check flagged is a genuine, unexplained issue. "
            "'confirmed' if the discrepancy is real and nothing in the source explains it. "
            "'explained' if the source itself states a reason for the discrepancy (a discount, a "
            "tax, a rounding note, bundled/lump-sum pricing, or another pricing rule stated in the "
            "document) - never infer an explanation the document doesn't actually state. "
            "'insufficient_evidence' if the source doesn't say enough to confirm or explain the "
            "discrepancy either way."
        )
    )
    explanation: str | None = Field(
        default=None,
        description=(
            "Only set when finding_verdict is 'explained': a short paraphrase of the document's "
            "own stated reason for the discrepancy. Leave null otherwise."
        ),
    )
    evidence_quote: str = Field(
        description=(
            "A short verbatim excerpt copied from the source document text that backs up this "
            "verdict (the sentence, line, or table row you based your judgment on). If the source "
            "genuinely says nothing relevant, state that plainly instead of quoting something "
            "unrelated."
        )
    )
    reasoning: str = Field(
        description="One or two sentences explaining how the evidence_quote leads to both verdicts above."
    )


class VerificationLlmOutput(BaseModel):
    """What the LLM itself is asked to produce - one verified_findings entry
    per sanity-check finding it was given, plus a summary. The overall
    `status` in `VerificationResult` is computed afterward from these
    verdicts rather than asked of the model, so it can't be inconsistent
    with the individual verdicts it just gave."""

    verified_findings: list[VerifiedFinding] = Field(
        description="One entry per sanity-check finding given to you, in the same order - every finding must be addressed, none skipped."
    )
    summary: str = Field(
        description=(
            "One or two sentences summarizing, for a reviewer who hasn't seen the details, how "
            "many findings were confirmed as genuine issues versus explained by the document "
            "versus left with insufficient evidence."
        )
    )


class VerificationResult(BaseModel):
    status: VerificationStatus = Field(
        description=(
            "'skipped' if the sanity check found no issues and verification did not need to run; "
            "'resolved' if every finding was either explained by the document or traced to an "
            "extraction error rather than a real pricing issue; 'needs_human_review' if at least "
            "one finding remains a genuine, unexplained issue (or evidence was insufficient) after "
            "checking the source."
        )
    )
    verified_findings: list[VerifiedFinding] = Field(default_factory=list)
    summary: str


class VerificationRequest(BaseModel):
    payload: OfferExtractionPayload
    sanity_check_result: SanityCheckResult


class VerificationOfferResponse(BaseModel):
    signal: ResponseSignal
    offer_id: int
    result: VerificationResult
