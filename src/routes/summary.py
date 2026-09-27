"""The detail screen's "read this first" panel and its clarification-email
draft - see `schema/review_summary.py`'s module docstring for why it is
composed from already-verified data rather than a fresh LLM output.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from controllers import JobController
from db import get_db
from dependencies import governed_user
from helpers.offer_events import record_summary_regenerated
from helpers.visibility import visible_offer
from models.db_schema import Offer, User
from models.enums import JobKind
from pipeline import runner
from pipeline.node.summary import resolve_supplier_email
from schema.jobs import JobOut, JobStage
from schema.review_summary import ChaseItem, ReviewSummaryOut

logger = logging.getLogger(__name__)

summary_router = APIRouter(
    prefix="/api/v1",
    tags=["summary"],
    dependencies=[Depends(governed_user)],
)


async def review_summary_of(db: AsyncSession, offer: Offer) -> ReviewSummaryOut:
    """Builds the response from whatever the offer already has on it, plus
    the one thing resolved fresh at read time - see `resolve_supplier_email`.
    An offer whose summary stage has not run yet (still queued, or persisted
    before this feature existed) reads back an empty chase list rather than
    404ing: the summary is a bonus, not a precondition of viewing the offer.
    """
    return ReviewSummaryOut(
        headline=offer.review_headline or "The summary has not been generated yet.",
        chase_items=[ChaseItem.model_validate(item) for item in (offer.review_chase_items or [])],
        email_to=await resolve_supplier_email(db, offer.supplier_id),
        email_subject=offer.review_email_subject or "",
        email_body=offer.review_email_body or "",
        generated_at=offer.review_summary_generated_at,
    )


@summary_router.get(
    "/offers/{offer_id}/summary",
    response_model=ReviewSummaryOut,
    dependencies=[Depends(visible_offer)],
)
async def get_review_summary(offer_id: int, db: AsyncSession = Depends(get_db)) -> ReviewSummaryOut:
    offer = await db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Offer {offer_id} not found.")
    return await review_summary_of(db, offer)


@summary_router.post(
    "/offers/{offer_id}/summary/recheck",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(visible_offer)],
)
async def recheck_summary(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> JobOut:
    """Composes the chase list and email draft again - worth doing after a
    reviewer corrects a completeness override or attaches late evidence,
    either of which can change what is left to chase."""
    offer = await db.get(Offer, offer_id)
    if offer is None or offer.persisted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This offer has not finished processing yet, so there is nothing to summarise.",
        )

    job = await JobController(db).create_job(kind=JobKind.SUMMARY, offer_id=offer_id, user=user)
    await record_summary_regenerated(offer_id=offer_id, actor=user)
    runner.start_job(job.job_id, JobKind.SUMMARY, offer_id, [])
    return JobOut(
        job_id=job.job_id,
        kind=JobKind.SUMMARY,
        status=job.status,
        offer_id=offer_id,
        stages=[JobStage.model_validate(stage) for stage in (job.stages or [])],
        current_stage=job.current_stage,
        progress_percent=job.progress_percent,
        created_at=job.created_at,
        updated_at=job.updated_at,
        offer_persisted=True,
    )
