"""Where a re-run of the offer pipeline should actually start.

Before this, the ONLY recovery from a mid-pipeline failure was
`rerun_offer_job` re-running the whole thing from `parse`: every file goes
back through Parsing Studio, and the entire chunked extraction - by far the
most expensive and most failure-prone stage (see `pipeline/stages.py`'s
weights) - runs again, even when it succeeded the first time and the failure
was three stages later.

The two things a resume needs are both already durable, so nothing new has to
be invented to find them:
  - whether a document was already parsed: `documents.page_count is not None`,
    written by `ParseController.parse_document` the moment a parse succeeds.
  - what a pre-persist stage produced: `offers.pipeline_checkpoint`, written
    here by each of extract/sanity_check/verification as it succeeds, and
    cleared by persist once it succeeds - the offer itself is the durable
    record from that point on, and post-persist stages (taxonomy,
    completeness, summary) already have their own re-run entry points that
    never needed this.

The checkpoint is invalidated as a whole - not stage by stage - the moment ANY
document in the offer's current set is not fully parsed: a checkpoint keyed to
a different set of parsed pages describes an offer that no longer exists in
that form, and reusing part of it would silently mix two different readings
of the source.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_schema import Document, Offer
from schema.offer import OfferExtractionPayload
from schema.sanity_check import SanityCheckResult
from schema.verification import VerificationResult

from .stages import OFFER_PIPELINE_STAGE_ORDER

SessionFactory = Callable[[], AsyncSession]

_CHECKPOINT_KEY_BY_STAGE = {
    "extract": "extraction_payload",
    "sanity_check": "sanity_check_result",
    "verification": "verification_result",
}


@dataclass(frozen=True)
class ResumePlan:
    """Where a job should start, and what to hand its graph before it does."""

    start_stage: str
    # Stage ids to mark DONE the moment the job is created (`create_job`'s
    # `completed_stage_ids`), so the progress bar reflects the skip from the
    # very first poll rather than flicking pending -> done a moment later.
    completed_stage_ids: tuple[str, ...] = ()
    # Merged into the graph's initial state before `ainvoke`. Empty for a run
    # starting at "parse" - there is nothing to seed.
    seed_state: dict = field(default_factory=dict)
    # True when the plan skips "extract" entirely (a cached payload exists),
    # meaning the completeness prescan - normally started BY the extract node
    # - has no node left to start it. The runner starts it directly instead.
    prescan_needs_manual_start: bool = False


async def determine_resume_point(
    db: AsyncSession, offer_id: int, document_ids: list
) -> ResumePlan:
    """Reads what is already durably true for this offer and decides where a
    run should pick up. Called at the moment a job actually starts (inside
    the runner), not when it is queued - a job can wait for a long time, and
    only the state at the moment it is claimed is worth trusting."""
    if not document_ids:
        return ResumePlan(start_stage="parse")

    parsed_count = (
        await db.execute(
            select(Document.document_id).where(
                Document.document_id.in_(document_ids), Document.page_count.is_not(None)
            )
        )
    ).scalars().all()
    all_parsed = len(parsed_count) == len(document_ids)
    if not all_parsed:
        return ResumePlan(start_stage="parse")

    offer = await db.get(Offer, offer_id)
    checkpoint = (offer.pipeline_checkpoint if offer else None) or {}

    seed: dict = {}
    completed: list[str] = ["parse"]

    if checkpoint.get("extraction_payload") is not None:
        seed["extraction_payload"] = OfferExtractionPayload.model_validate(
            checkpoint["extraction_payload"]
        )
        completed.append("extract")
    else:
        return ResumePlan(start_stage="extract", completed_stage_ids=tuple(completed))

    if checkpoint.get("sanity_check_result") is not None:
        seed["sanity_check_result"] = SanityCheckResult.model_validate(
            checkpoint["sanity_check_result"]
        )
        completed.append("sanity_check")
    else:
        return ResumePlan(
            start_stage="sanity_check",
            completed_stage_ids=tuple(completed),
            seed_state=seed,
            prescan_needs_manual_start=True,
        )

    if checkpoint.get("verification_result") is not None:
        seed["verification_result"] = VerificationResult.model_validate(
            checkpoint["verification_result"]
        )
        completed.append("verification")
        return ResumePlan(
            start_stage="persist",
            completed_stage_ids=tuple(completed),
            seed_state=seed,
            prescan_needs_manual_start=True,
        )

    return ResumePlan(
        start_stage="verification",
        completed_stage_ids=tuple(completed),
        seed_state=seed,
        prescan_needs_manual_start=True,
    )


async def save_stage_checkpoint(
    session_factory: SessionFactory, offer_id: int, stage_id: str, payload: BaseModel
) -> None:
    """Merges one stage's output into the offer's checkpoint.

    Self-contained, like `helpers.offer_events.record_event` - opens and
    commits its own short session rather than borrowing whichever one the
    calling node has open, so a node that does not otherwise touch the
    database (sanity_check) needs nothing but a `session_factory` to call
    this, and a node that does (extract, verification) is not made to hold
    its own session open any longer than it already does.

    A merge, not a replace: `offers.pipeline_checkpoint` is one JSONB blob
    covering up to three stages, and extract's write must not erase a
    checkpoint that does not exist yet, while a later stage's write must not
    erase extract's.
    """
    key = _CHECKPOINT_KEY_BY_STAGE[stage_id]
    async with session_factory() as db:
        offer = await db.get(Offer, offer_id)
        checkpoint = dict(offer.pipeline_checkpoint or {})
        checkpoint[key] = payload.model_dump(mode="json")
        offer.pipeline_checkpoint = checkpoint
        offer.pipeline_checkpoint_updated_at = datetime.now(timezone.utc)
        await db.commit()


async def clear_checkpoint(session_factory: SessionFactory, offer_id: int) -> None:
    """Called once persist succeeds. The offer itself is the durable record
    from here on - keeping stale extraction JSON around would only risk a
    future bug reading it instead of the real, saved offer."""
    async with session_factory() as db:
        offer = await db.get(Offer, offer_id)
        if offer.pipeline_checkpoint is None:
            return
        offer.pipeline_checkpoint = None
        offer.pipeline_checkpoint_updated_at = None
        await db.commit()


# Re-exported so callers that already import from `pipeline.resume` do not
# also need `pipeline.graph` just to validate a stage id.
__all__ = [
    "ResumePlan",
    "determine_resume_point",
    "save_stage_checkpoint",
    "clear_checkpoint",
    "OFFER_PIPELINE_STAGE_ORDER",
]
