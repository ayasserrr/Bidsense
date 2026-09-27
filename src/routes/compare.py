"""Several offers side by side - typically every offer on one RFQ.

The offer ids arrive in the query string, which no `visible_*` dependency can
guard: those read a path parameter, and a dependency reading an id out of the
query string would be checking whatever the caller typed there rather than the
ids the route acts on. So `ensure_offer_visible` is called here, in the handler,
once per id, before anything is read - and
tests/test_department_separation.py's CHECKED_IN_HANDLER records that, so the
check cannot be dropped without a test failing.

A separate `/api/v1/compare` prefix rather than `/api/v1/offers/compare`, on
purpose: the offers router already owns `/{offer_id}`, and a sibling path under
it would match that route first and fail as a malformed integer depending on
which router happened to be included first.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from controllers.InsightsController import MAX_COMPARE_OFFERS, InsightsController
from controllers.RatesController import RatesController
from db import get_db
from dependencies import current_user
from helpers.visibility import ensure_offer_visible
from models.db_schema import User
from schema.compare import CompareResponse

logger = logging.getLogger(__name__)

compare_router = APIRouter(
    prefix="/api/v1/compare",
    tags=["compare"],
    dependencies=[Depends(current_user)],
)


@compare_router.get("", response_model=CompareResponse)
async def compare_offers(
    offer_ids: list[int] = Query(
        ...,
        alias="offer_ids",
        description=(
            "The offers to line up, repeated: ?offer_ids=1&offer_ids=2. Order is kept - "
            "the columns stay where the person put them."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> CompareResponse:
    """The facts these offers state, side by side. No winner, no score.

    Free-text terms come back exactly as the supplier wrote them. Where there is
    a mechanical rule for a comparable reading - the Incoterm code, the payment
    milestones' percentages - BOTH are returned and the normalised one says
    which rule produced it.

    Totals in more than one currency are converted with the rates on file, the
    comparison is marked `rate_dependent`, and a currency with no rate is named
    rather than guessed at.
    """
    # Duplicates would draw the same column twice and pay for it twice.
    unique_ids = list(dict.fromkeys(offer_ids))
    if not unique_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Give at least one offer to compare.",
        )
    if len(unique_ids) > MAX_COMPARE_OFFERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Compare up to {MAX_COMPARE_OFFERS} offers at once - more columns than that "
                "is a spreadsheet rather than a comparison."
            ),
        )

    # Before anything is read: 404 for an offer that does not exist, 403 for one
    # in another department. Checked per id rather than filtered out silently,
    # so asking for a colleague's offer is refused rather than answered with a
    # comparison that is quietly missing a column.
    for offer_id in unique_ids:
        await ensure_offer_visible(db, offer_id, user)

    rate_book = await RatesController(db).rate_book()
    return await InsightsController(db).compare(unique_ids, user=user, rate_book=rate_book)
