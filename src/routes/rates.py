"""Exchange rates: read them, set one by hand, refresh them from the provider.

Deliberately not admin-only. The people who read the converted totals are the
people who know what the bank actually charged this week, and a wrong rate that
needs a ticket to fix is a wrong rate that stays on the dashboard for a month.
Every edit records who made it instead.

No route here has an offer, document or job id, and none of them lists
anything owned by a department: a rate is one company-wide number, the same for
everybody, so there is nothing for `visibility_filter` to scope. The currency
is sent in the body rather than in the path so this router adds no path
parameter for tests/test_department_separation.py to classify.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from controllers.RatesController import (
    BaseRateMustBeOneError,
    RatesController,
    UnknownCurrencyError,
)
from db import get_db
from dependencies import current_user
from models.db_schema import User
from schema.rates import ManualRateRequest, RateRefreshResponse, RatesResponse

logger = logging.getLogger(__name__)

rates_router = APIRouter(
    prefix="/api/v1/rates",
    tags=["rates"],
    dependencies=[Depends(current_user)],
)


@rates_router.get("", response_model=RatesResponse)
async def list_rates(db: AsyncSession = Depends(get_db)) -> RatesResponse:
    """Every rate on file, with its source, its editor and its age.

    Reads the table and nothing else. It never calls the provider: a page that
    fetches on the way past is a page that hangs when the provider does.
    """
    return await RatesController(db).list_rates()


@rates_router.post("", response_model=RatesResponse)
async def set_rate(
    request: ManualRateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> RatesResponse:
    """Set one rate by hand. The row's source becomes `manual` and carries the
    editor's name; a later refresh leaves it alone unless it is explicitly told
    to overwrite hand-set rates.

    Returns the whole table rather than the one row, because every screen that
    shows a rate shows all of them.
    """
    controller = RatesController(db)
    try:
        await controller.set_manual_rate(request, user=user)
    except UnknownCurrencyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BaseRateMustBeOneError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return await controller.list_rates()


@rates_router.post("/refresh", response_model=RateRefreshResponse)
async def refresh_rates(
    overwrite_manual: bool = False,
    db: AsyncSession = Depends(get_db),
) -> RateRefreshResponse:
    """Fetch today's rates from the configured provider, on demand only.

    Always 200. A provider that is down, switched off, or quoting a different
    base comes back as `ok=false` with the sentence to show and the table
    unchanged - the caller still gets every rate on file in the same response,
    so a failed refresh leaves the screen correct rather than empty.

    `overwrite_manual=true` is the deliberate choice to replace rates somebody
    typed in; without it those rows are kept and named in `kept_manual`.
    """
    return await RatesController(db).refresh(overwrite_manual=overwrite_manual)
