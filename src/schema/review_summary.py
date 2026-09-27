"""The detail screen's "read this first" panel, and its clarification-email
draft.

Deliberately NOT a fresh LLM output. `pipeline/node/summary.py` composes both
from findings and completeness gaps THIS OFFER'S OWN PIPELINE has already
verified - a confirmed mismatch, a mandatory term the checker could not find.
A new LLM paragraph summarising the offer would be the first thing a reviewer
reads, and the one part of it nothing downstream re-checks: wrong there is
worse than absent. See `pipeline/stages.py`'s SUMMARY_STAGE_ID docstring.

There is no "money at risk" figure here and there will not be one, for the
same reason `schema/dashboard.py` gives: no table in this database stores a
monetary amount per finding, so the number would be a guess dressed as a
measurement. There is no ranking or "recommended" verdict either - this is
one offer's own panel, not a comparison (`schema/compare.py` already covers
that, and rules the same thing out for the same reason).
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ChaseItemKind(str, Enum):
    """Where a chase item came from - lets the panel group or icon them
    differently without re-deriving the source from its text."""

    CONFIRMED_FINDING = "confirmed_finding"
    MANDATORY_GAP = "mandatory_gap"


class ChaseItem(BaseModel):
    """One thing to chase before this offer can go to sign-off."""

    kind: ChaseItemKind
    title: str
    detail: str
    # Present for a MANDATORY_GAP item when the checker names one; a
    # CONFIRMED_FINDING's source is the verification quote itself, already in
    # `detail` - repeating it here would be the same sentence twice.
    source_filename: str | None = None
    source_page_number: int | None = None


class ReviewSummaryOut(BaseModel):
    """What the detail screen's Summary section reads directly."""

    headline: str
    chase_items: list[ChaseItem] = Field(default_factory=list)
    # The recipient's own words, so the send button knows whether it is
    # missing something: extraction of a contact email off a supplier's own
    # letterhead is unreliable, and a draft is honest about that rather than
    # inventing an address.
    email_to: str | None = None
    email_subject: str
    email_body: str
    generated_at: datetime | None = None


class RegenerateSummaryResponse(BaseModel):
    offer_id: int
    summary: ReviewSummaryOut
