from pydantic import BaseModel, Field

from models.enums import ResponseSignal, SanityCheckIssueType, SanityCheckSeverity, SanityCheckStatus


class SanityCheckFinding(BaseModel):
    issue_type: SanityCheckIssueType = Field(
        description="Which kind of pricing/arithmetic inconsistency this is."
    )
    severity: SanityCheckSeverity = Field(
        description=(
            "'critical' if the mismatch is large enough to materially change the offer's "
            "price; 'warning' otherwise (e.g. a small rounding-scale gap still worth a human "
            "glance but unlikely to change the bottom line)."
        )
    )
    field_path: str = Field(
        description="The exact field this finding is about, from the automated flag it was reviewed from (e.g. 'items[item_3].total_price')."
    )
    description: str = Field(
        description=(
            "One clear sentence explaining what's wrong, in your own words - not just a copy "
            "of the automated flag's description."
        )
    )


class SanityCheckResult(BaseModel):
    status: SanityCheckStatus = Field(
        description=(
            "'needs_review' if at least one automated flag was kept as a genuine issue; "
            "'passed' if every flag was dismissed as explainable, or there were no flags."
        )
    )
    findings: list[SanityCheckFinding] = Field(
        default_factory=list,
        description="One entry per flag kept as a genuine issue. Dismissed (explainable) flags are not included here.",
    )
    summary: str = Field(
        description=(
            "One or two sentences summarizing this offer's overall pricing consistency for a "
            "reviewer who hasn't seen the details."
        )
    )


class SanityCheckOfferResponse(BaseModel):
    signal: ResponseSignal
    offer_id: int
    result: SanityCheckResult
