"""The dashboard screen's numbers, in one request.

Scoped throughout by `visibility_filter` - there is no id in the path, so there
is nothing for a `visible_*` guard to check; what this route must never do is
count a row the caller cannot open, and every query behind it carries the
department clause.

It never calls the exchange rate provider. The rates are read from the table
exactly as they stand, so a provider outage cannot make this page slow or make
it fail - a currency with no rate is reported as unconvertible instead.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from controllers.InsightsController import InsightsController
from controllers.RatesController import RatesController
from db import get_db
from dependencies import current_user
from models.db_schema import User
from schema.dashboard import DashboardResponse

logger = logging.getLogger(__name__)

dashboard_router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(current_user)],
)


@dashboard_router.get("", response_model=DashboardResponse)
async def get_dashboard(
    stale_days: int = Query(
        default=3,
        ge=1,
        le=365,
        description=(
            "How long an offer may sit in review before it counts as waiting too long. "
            "The design's sub-line is 'over three days old'."
        ),
    ),
    read_time_sample: int = Query(
        default=20,
        ge=1,
        le=500,
        description="How many of the most recent finished reads the average is taken over.",
    ),
    attention_limit: int = Query(
        default=10,
        ge=1,
        le=50,
        description="How many 'needs your attention' rows to return.",
    ),
    activity_limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="How many activity events to return, newest first.",
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> DashboardResponse:
    """Where every offer the caller can see stands this week.

    There is no "money at risk" figure here and there will not be one: no table
    in this database records a monetary amount per finding, so the number the
    design asks for could only be a guess dressed as a measurement. What is
    returned instead is the value of the offers still waiting on a decision,
    which is a fact - each total carrying its per-currency originals, the rate
    used and that rate's age.
    """
    rate_book = await RatesController(db).rate_book()
    return await InsightsController(db).dashboard(
        user=user,
        rate_book=rate_book,
        stale_days=stale_days,
        read_time_sample=read_time_sample,
        attention_limit=attention_limit,
        activity_limit=activity_limit,
    )
