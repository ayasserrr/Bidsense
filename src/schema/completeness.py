import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from models.enums import CompletenessVerdict, EvidenceKind, RequirementGroup, ResponseSignal

# --- what the model is asked for -------------------------------------------


class CompletenessScanFinding(BaseModel):
    """One requirement, judged against one excerpt of the offer.

    Note what is NOT here: any mention of a file or page. The model is asked
    only for a verbatim quote, and the quote is located in the merged source
    text mechanically (see `helpers/source_index.py`). A filename the model
    supplied would be unverifiable, and a wrong one would destroy exactly the
    traceability this feature exists to provide.
    """

    requirement_code: str = Field(
        description=(
            "The code of the checklist requirement this finding is about. Must be one of the "
            "codes given in the request - never invent a new one."
        )
    )
    verdict: CompletenessVerdict = Field(
        description=(
            "'present' if THIS excerpt states the requirement clearly enough to act on; "
            "'unclear' if it touches the subject without pinning it down; "
            "'not_applicable' if the requirement plainly does not apply to the kind of offer "
            "this is (e.g. Plumbing in a UPS quotation) - only ever for a technical discipline, "
            "never for a commercial term, since every offer has a price, a currency, a delivery "
            "and a validity; "
            "'missing' if this excerpt is about the subject and says nothing definite. "
            "Judge ONLY this excerpt - another part of the offer may state it, and the parts "
            "are reconciled afterwards."
        )
    )
    extracted_value: str | None = Field(
        default=None,
        description=(
            "The answer itself, in as few words as possible ('CIF Alexandria', '30 days', "
            "'24 months from commissioning', '50% advance / 50% on delivery'). Null when the "
            "verdict is not 'present'."
        ),
    )
    evidence_quote: str | None = Field(
        default=None,
        description=(
            "The sentence or table row from the excerpt that states this, copied VERBATIM, "
            "character for character. Do not paraphrase, do not tidy the spacing, do not "
            "translate. A quote that is not word-for-word in the source cannot be located and "
            "the finding loses its source attribution. Null when nothing was found."
        ),
    )
    reasoning: str | None = Field(
        default=None,
        description="One short sentence on why this verdict, for a reviewer to check.",
    )


class CompletenessScanResult(BaseModel):
    findings: list[CompletenessScanFinding] = Field(
        default_factory=list,
        description=(
            "One entry per requirement this excerpt has something to say about. Omit a "
            "requirement entirely rather than guessing about it - silence here is read as "
            "'this excerpt did not address it', which is the honest answer."
        ),
    )


# --- what the API returns --------------------------------------------------


class CompletenessEvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evidence_id: uuid.UUID
    requirement_code: str
    evidence_kind: EvidenceKind
    original_filename: str
    file_size: int
    uploaded_at: datetime


class CompletenessResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    result_id: int
    requirement_code: str
    requirement_label: str
    requirement_group: RequirementGroup
    was_mandatory: bool
    sort_order: int

    verdict: CompletenessVerdict
    extracted_value: str | None = None
    normalized_value: str | None = None
    evidence_quote: str | None = None
    source_document_id: uuid.UUID | None = None
    source_filename: str | None = None
    source_page_number: int | None = None
    reasoning: str | None = None

    is_overridden: bool = False
    override_verdict: CompletenessVerdict | None = None
    override_value: str | None = None
    override_note: str | None = None
    override_evidence_id: uuid.UUID | None = None
    override_evidence_filename: str | None = None
    overridden_by: str | None = None
    overridden_at: datetime | None = None

    # Computed server-side so the UI never has to re-implement the
    # override-wins rule and get it subtly different.
    effective_verdict: CompletenessVerdict
    effective_value: str | None = None
    checked_at: datetime


class CompletenessSummary(BaseModel):
    """The headline counts a reviewer reads before anything else."""

    total: int
    present: int
    missing: int
    unclear: int
    not_applicable: int
    # Missing or unclear AND mandatory - the number that actually means "go back
    # to the supplier".
    mandatory_gaps: int
    overridden: int


class OfferCompletenessResponse(BaseModel):
    signal: ResponseSignal
    offer_id: int
    checked_at: datetime | None = None
    summary: CompletenessSummary
    results: list[CompletenessResultOut]
    evidence: list[CompletenessEvidenceOut] = Field(default_factory=list)


class CompletenessOverrideRequest(BaseModel):
    """A reviewer correcting one verdict.

    `evidence_id` is required and has no default: the client was explicit that
    filling a gap needs a document behind it, and making the field optional here
    would push that rule down to a runtime check that is easy to forget. The
    database carries the same rule as a constraint.
    """

    verdict: CompletenessVerdict
    value: str | None = None
    note: str | None = None
    evidence_id: uuid.UUID


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    requirement_id: int
    code: str
    requirement_group: RequirementGroup
    label: str
    description: str
    is_mandatory: bool
    is_active: bool
    sort_order: int


class RequirementUpdateRequest(BaseModel):
    """Admin edit of one checklist row. Every field optional - only what is
    sent is changed. `code` is not editable: it is the identity results are
    recorded against."""

    label: str | None = None
    description: str | None = None
    is_mandatory: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None
