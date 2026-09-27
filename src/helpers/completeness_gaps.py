"""What counts as a gap the reviewer has to chase, in one place.

The completeness section, the offers list and the offer header all show the same
number, and it is the number the client actually acts on: required terms this
offer either does not state or states too vaguely to use. Three copies of that
rule would eventually disagree, and the one that disagreed would be the badge -
the only one most people ever look at.

So the rule lives here twice, deliberately, and the two forms must never drift:
`is_mandatory_gap` decides one already-loaded row, and `mandatory_gap_counts`
asks the database the same question about many offers at once without loading
their rows. A reviewer's override is part of the question in both - a gap
someone has filled in, with the email to prove it, is not a gap any more.
"""

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_schema import OfferCompletenessResult
from models.enums import CompletenessVerdict

# Missing OR unclear. "Unclear" belongs here because "warranty as per
# manufacturer" is not something a buyer can act on either - the supplier still
# has to be asked.
GAP_VERDICTS: tuple[str, ...] = (
    CompletenessVerdict.MISSING.value,
    CompletenessVerdict.UNCLEAR.value,
)


def is_mandatory_gap(*, was_mandatory: bool, effective_verdict: str) -> bool:
    """Whether one result row is a gap to chase."""
    return bool(was_mandatory) and str(effective_verdict) in GAP_VERDICTS


def effective_verdict_column():
    """The SQL twin of `OfferCompletenessResult.effective_verdict`.

    The Python property is a reviewer's override where one exists, otherwise the
    checker's verdict; this says the same thing to the database. `is_overridden`
    alone is not enough - the table allows an override row whose verdict was
    never set, and reading NULL as the answer would hide the machine's.
    """
    return case(
        (
            OfferCompletenessResult.is_overridden.is_(True)
            & OfferCompletenessResult.override_verdict.is_not(None),
            OfferCompletenessResult.override_verdict,
        ),
        else_=OfferCompletenessResult.verdict,
    )


def mandatory_gap_count_query(offer_ids: list[int]):
    """Gaps per offer, for offers that have actually been checked.

    An offer with no result rows is absent from the result entirely rather than
    counted as zero. The two are not the same thing and the badge depends on the
    difference: "nothing missing" is a finding, "never checked" is not, and
    showing a clean badge for the second would be the same false reassurance the
    offers list gives today.
    """
    is_gap = case(
        (
            OfferCompletenessResult.was_mandatory.is_(True)
            & effective_verdict_column().in_(GAP_VERDICTS),
            1,
        ),
        else_=0,
    )
    return (
        select(OfferCompletenessResult.offer_id, func.coalesce(func.sum(is_gap), 0))
        .where(OfferCompletenessResult.offer_id.in_(offer_ids))
        .group_by(OfferCompletenessResult.offer_id)
    )


async def mandatory_gap_counts(db: AsyncSession, offer_ids: list[int]) -> dict[int, int]:
    """`{offer_id: gaps}`, containing only the offers that have been checked."""
    if not offer_ids:
        return {}
    rows = (await db.execute(mandatory_gap_count_query(offer_ids))).all()
    return {row[0]: int(row[1] or 0) for row in rows}
