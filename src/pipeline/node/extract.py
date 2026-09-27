import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from controllers import ExtractController
from helpers import get_settings
from helpers.offer_events import record_offer_extracted
from pipeline.prescan import CompletenessPrescan
from pipeline.progress import JobProgress
from pipeline.resume import save_stage_checkpoint
from pipeline.state import PipelineState

STAGE_ID = "extract"


def make_extract_node(
    session_factory: Callable[[], AsyncSession],
    progress: JobProgress,
    prescan: CompletenessPrescan,
) -> Callable[[PipelineState], Awaitable[PipelineState]]:
    """Builds the node that runs the two-pass (draft -> verify) extraction over
    every document uploaded together for one offer.

    This stage does not write offer_items/tech_specs/suppliers to real tables -
    only lightweight per-document telemetry. The actual write happens in the
    persist node.

    The per-call LLM timeout only bounds one call; the draft and verify passes
    plus their repair loops stack on top of it with no other ceiling, so the
    whole `extract_offer` call is wrapped in its own total timeout.

    It is also the longest stage by far, which is why it reports chunk-level
    progress: without it the bar would sit at one number for ten minutes and
    look like a hang.

    It starts the completeness scan too. That scan reads the same parsed pages
    and nothing this stage produces, so queueing it behind the longest stage in
    the run bought nothing; started here it is finished long before its own
    stage's turn comes. If this stage fails, it takes the scan with it - the
    same rule `extract_offer` already applies to its own chunks.
    """

    async def extract_node(state: PipelineState) -> PipelineState:
        await progress.raise_if_cancelled()
        settings = get_settings()
        await progress.start_stage(STAGE_ID, "reading the offer")
        prescan.start(state["offer_id"])

        async def on_chunk(done: int, total: int) -> None:
            await progress.update_detail(
                STAGE_ID,
                f"{done} of {total} section(s) extracted" if total > 1 else "extracting",
                fraction=done / total if total else 0.0,
            )

        try:
            async with session_factory() as db:
                controller = ExtractController(db)
                documents = await controller.get_offer_documents(state["offer_id"])
                payload = await asyncio.wait_for(
                    controller.extract_offer(documents, on_chunk_progress=on_chunk),
                    timeout=settings.EXTRACTION_TOTAL_TIMEOUT_SECONDS,
                )
        except BaseException:
            # The scan is this stage's sibling, not its child: nothing else
            # would stop it, and it would go on holding a gateway slot for a run
            # that has already failed or been cancelled. Stop it, let it unwind,
            # then re-raise the ORIGINAL error - the runner turns that into the
            # sentence the reviewer reads.
            await prescan.cancel()
            raise

        await progress.finish_stage(STAGE_ID, f"{len(payload.items)} line item(s)")
        # "Bidsense extracted 34 line items". Recorded from the payload rather
        # than from the saved items, because persist has not run yet and a run
        # that fails after this point still read what it read.
        await record_offer_extracted(
            offer_id=state["offer_id"], item_count=len(payload.items)
        )
        # Cached so a failure in a LATER stage (sanity-check, verification)
        # can resume from here instead of re-running this - by far the
        # longest and most failure-prone stage - from nothing. See
        # pipeline/resume.py.
        await save_stage_checkpoint(session_factory, state["offer_id"], "extract", payload)
        return {"extraction_payload": payload}

    return extract_node
