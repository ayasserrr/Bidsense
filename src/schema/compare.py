"""Several offers, lined up side by side. Facts only.

There is no "Recommended" column here, and no score of any kind. The design has
one - a shield, an accent pill and a sentence declaring a winner - and the
product owner ruled it out: the inputs would be four free-text fields parsed
out of PDFs, and a screen that ranks suppliers on that is a screen that gets
somebody's contract award wrong. What this returns is what each offer says, in
the supplier's own words, with a normalised reading beside it where there is a
mechanical rule for one, and every difference left for the reader to weigh.

Two things are marked rather than hidden:
  * a comparison across currencies is `rate_dependent` - the totals only line
    up as far as the rates on file are right, and each rate's age is returned;
  * offers on different RFQs are still compared, with `same_rfq` false, because
    refusing would be more annoying than useful - but the screen should say so.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from models.enums import CompletenessVerdict, SanityCheckStatus, VerificationStatus
from schema.rates import ConvertedMoney, MoneyRate


class CompareTermOut(BaseModel):
    """One term, as written and as read.

    `stated` is the supplier's own wording, never tidied. `normalized` is this
    application's comparable reading of it, and `normalized_from` names the rule
    that produced it so a reader can disagree with it. Both are returned: a
    column showing only "DDP" hides that the offer said "DDP site, Cairo", and a
    column showing only the sentence cannot be compared across three suppliers.
    """

    stated: str | None = None
    normalized: str | None = None
    # 'incoterm' (helpers.commercial_terms.normalize_incoterm),
    # 'completeness_check' (the checker's own normalised value),
    # 'payment_schedule' (the extracted milestone percentages).
    normalized_from: str | None = None
    # What the completeness check concluded about this term for this offer, so
    # a blank cell can be told apart from one the checker judged `unclear`.
    # Null when the check has never run.
    verdict: CompletenessVerdict | None = None
    # Whether a reviewer corrected that verdict with evidence attached.
    is_overridden: bool = False


class CompareTermsOut(BaseModel):
    """The terms the design lines up, one row of the table each."""

    incoterm: CompareTermOut
    delivery_terms: CompareTermOut
    delivery_lead_time: CompareTermOut
    payment_terms: CompareTermOut
    warranty: CompareTermOut
    validity: CompareTermOut


class ComparePaymentMilestoneOut(BaseModel):
    """One row of the payment schedule - the normalised form of "30 / 60 / 10".

    Returned alongside `terms.payment_terms.stated`, never instead of it: the
    percentages are comparable, and the sentence is what the supplier actually
    committed to.
    """

    sequence_no: int
    trigger_event: str
    percentage: Decimal | None = None
    description: str


class CompareGroupTotalOut(BaseModel):
    """One top-level item group's own total.

    Populated only when `grand_total.original_amount` is null - a "Base offer"
    and an "Alternative offer" each independently totaled, with nothing
    summing the two together, still has a real total per group. Mirrors
    OfferDetailPage's identical fallback so the compare screen doesn't draw a
    blank cell where the offer detail page shows figures.
    """

    label: str
    total: ConvertedMoney


class CompareOfferOut(BaseModel):
    """One column of the comparison."""

    offer_id: int
    offer_ref: str | None = None
    supplier_name: str | None = None
    rfq_number: str | None = None
    project_name_entered: str | None = None
    project_name_original: str | None = None
    # The newest version of its chain. A superseded version can be compared on
    # purpose - "what did they quote last time" is a real question - but the
    # column should say which it is.
    is_active_latest: bool
    archived: bool
    created_at: datetime
    persisted_at: datetime | None = None

    grand_total: ConvertedMoney
    group_totals: list[CompareGroupTotalOut] = Field(default_factory=list)
    confirmed_findings: int
    sanity_check_status: SanityCheckStatus | None = None
    verification_status: VerificationStatus | None = None

    # Out of `mandatory_terms_total` (ten, the A-J commercial terms). Null when
    # the check has never run for this offer - which is NOT "nothing missing",
    # and must not be drawn as a clean column.
    mandatory_gaps: int | None = None
    mandatory_terms_total: int
    completeness_checked: bool

    item_count: int
    terms: CompareTermsOut
    payment_schedule: list[ComparePaymentMilestoneOut] = Field(default_factory=list)


class UnconvertibleCurrencyOut(BaseModel):
    currency_code: str
    reason: str


class CompareResponse(BaseModel):
    """The comparison. No winner, no score, no ranking - by decision."""

    generated_at: datetime
    base_currency: str
    # In the order the caller asked for them, so the columns stay where the
    # person put them.
    offers: list[CompareOfferOut] = Field(default_factory=list)

    # The distinct RFQ numbers across these offers. More than one (or one plus
    # an offer with none) means the screen is comparing across RFQs.
    rfq_numbers: list[str] = Field(default_factory=list)
    same_rfq: bool

    currencies: list[str] = Field(default_factory=list)
    # True when the offers do not all share one currency, so the totals can
    # only be lined up through the rates - and are only as good as they are.
    rate_dependent: bool
    rates_used: list[MoneyRate] = Field(default_factory=list)
    # Currencies present that have no rate on file. Those offers keep their own
    # figure and are marked unconvertible rather than being left out or guessed.
    unconvertible_currencies: list[UnconvertibleCurrencyOut] = Field(default_factory=list)

    # Plain sentences about what this particular comparison cannot claim -
    # different RFQs, a missing rate, a superseded version in the set. Shown
    # above the table.
    notes: list[str] = Field(default_factory=list)
