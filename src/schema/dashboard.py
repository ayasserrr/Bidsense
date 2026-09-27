"""The dashboard's numbers, as one response.

Everything here is computed from this installation's own rows and scoped to
what the caller may see, so two people in different departments reading the
same screen correctly see different totals.

What is deliberately NOT here is "money at risk". The design puts a figure on
it - "312,400 EGP in confirmed mismatches" - and nothing in this database can
produce one: neither `offer_sanity_findings` nor `offer_verified_findings`
carries a monetary amount, so any number under that label would be an
approximation of a grand total dressed up as a measured loss. The product
owner ruled it out rather than have the screen invent it. What IS reported is
the money of the offers still waiting on a decision, which is a fact.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from models.enums import SanityCheckStatus, VerificationStatus
from schema.rates import ConvertedMoney, MoneyTotalOut


class OffersInReviewOut(BaseModel):
    """The "Offers in review" KPI and its sub-line."""

    count: int
    # Of those, the ones that have been sitting for longer than `stale_days` -
    # the design's "2 over three days old". Measured from when the read
    # finished (`persisted_at`), not from when the files were uploaded: the
    # clock that matters is the one since it landed on somebody's desk.
    waiting_longer_than_stale_days: int
    stale_days: int
    # The trend pill's "+3 this week".
    added_last_7_days: int
    # Everything the other numbers are a share of: live offers the caller can
    # see (read to the end, newest version, not archived).
    live_offers: int


class TermsToChaseOut(BaseModel):
    """The "Terms to chase" KPI: mandatory completeness gaps, company-wide.

    Counted out of the ten A-J commercial terms, the same rule the offers list
    and the offer header use (`helpers.completeness_gaps`). The ten technical
    disciplines are not mandatory and are not counted here - a UPS quotation is
    not incomplete for having nothing to say about Plumbing.
    """

    mandatory_gaps: int
    offers_with_gaps: int
    # The denominator, read from the live checklist rather than hard-coded, so
    # an admin's edit to it shows up here instead of quietly disagreeing.
    mandatory_terms_per_offer: int
    offers_checked: int
    # Offers the completeness check has never run for. NOT the same as "nothing
    # missing", and the screen must not show them as clear.
    offers_never_checked: int


class AverageReadTimeOut(BaseModel):
    """The "Average read time" KPI, measured on this installation.

    From `started_at` to `finished_at`, never from `created_at`: now that jobs
    really do wait in a queue, created_at -> finished_at measures the size of
    the backlog as much as the speed of the read.

    `sample_size` is returned because an average over three runs is not the same
    claim as an average over twenty, and a screen that hides the difference
    invites somebody to plan around it.
    """

    seconds: float | None = None
    sample_size: int
    # How many finished runs were asked for. A smaller `sample_size` means the
    # installation has not done that many yet.
    sample_requested: int


class ReadingNowOut(BaseModel):
    """How many reads are running and how many are waiting, for the caller.

    The counts only. The "Processing now" panel's progress bar, stage line,
    per-job ETA, reorder and pause all come from the queue endpoint, which owns
    the queue - duplicating them here would give the same screen two sources
    that can disagree.
    """

    running: int
    waiting: int


class DashboardMoneyOut(BaseModel):
    """Money totals, converted and itemised.

    Both totals carry the per-currency originals, the rate each was converted
    with and that rate's age. A currency with no rate is reported by name and
    left out of the converted figure rather than dropped.
    """

    live_offers: MoneyTotalOut
    # The offers still waiting on a human decision. NOT "money at risk": it is
    # the value of what is queued for review, not a measured exposure.
    awaiting_review: MoneyTotalOut
    # Live offers whose grand total was never extracted. They are in no total,
    # so the count is how much of the picture is missing.
    offers_without_a_total: int


class AttentionOfferOut(BaseModel):
    """One row of "Needs your attention": an offer with findings or gaps."""

    offer_id: int
    offer_ref: str | None = None
    supplier_name: str | None = None
    rfq_number: str | None = None
    # The typed name where somebody filed one, otherwise the extracted name.
    project_name: str | None = None
    project_name_entered: str | None = None
    project_name_original: str | None = None
    confirmed_findings: int
    # Null when the completeness check has never run - never shown as zero.
    mandatory_gaps: int | None = None
    mandatory_terms_total: int
    sanity_check_status: SanityCheckStatus | None = None
    verification_status: VerificationStatus | None = None
    grand_total: ConvertedMoney
    # Whole days since the read finished.
    waiting_days: int | None = None
    created_at: datetime
    persisted_at: datetime | None = None


class CompareReadyRfqOut(BaseModel):
    """An RFQ with more than one offer read against it - the design's
    "RFQ-2026-0188 · 3 offers ready" row, which is the entry point to the
    compare screen.

    It says these offers CAN be compared, and nothing about whether anybody
    has: nothing in this database records that a comparison happened.
    """

    rfq_number: str
    offer_count: int
    offer_ids: list[int] = Field(default_factory=list)
    supplier_names: list[str] = Field(default_factory=list)
    latest_created_at: datetime


class NeedsAttentionOut(BaseModel):
    offers: list[AttentionOfferOut] = Field(default_factory=list)
    compare_ready: list[CompareReadyRfqOut] = Field(default_factory=list)
    # Every offer that qualifies, not just the ones in `offers` - which is
    # capped by `attention_limit`.
    offers_total: int


class ActivityEventOut(BaseModel):
    """One line of the activity timeline, across every offer the caller can see.

    The sentence in `detail` was written when the event happened and is shown
    as-is: rebuilding it now from ids that may since have been renamed is how a
    log starts lying.
    """

    event_id: int
    offer_id: int
    offer_ref: str | None = None
    kind: str
    detail: str
    payload: dict | None = None
    actor_user_id: int | None = None
    # Snapshotted on the row. Empty for an event the system performed, which
    # the design labels "Bidsense".
    actor_display_name: str
    is_system: bool
    created_at: datetime


class DashboardResponse(BaseModel):
    """Everything the dashboard screen needs, in one request."""

    generated_at: datetime
    base_currency: str
    offers_in_review: OffersInReviewOut
    terms_to_chase: TermsToChaseOut
    average_read_time: AverageReadTimeOut
    reading_now: ReadingNowOut
    money: DashboardMoneyOut
    needs_attention: NeedsAttentionOut
    activity: list[ActivityEventOut] = Field(default_factory=list)
