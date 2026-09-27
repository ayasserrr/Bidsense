import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from controllers import TaxonomyController
from helpers.offer_events import record_taxonomy_resorted
from pipeline.progress import JobCancelled, JobProgress
from pipeline.state import PipelineState

logger = logging.getLogger(__name__)

STAGE_ID = "taxonomy"


def make_taxonomy_node(
    session_factory: Callable[[], AsyncSession],
    progress: JobProgress,
) -> Callable[[PipelineState], Awaitable[PipelineState]]:
    """Builds the node that sorts the saved offer's line items into the ten
    disciplines.

    Runs before completeness in the graph on purpose: a resolved item is the
    strongest evidence there is that the offer covers its discipline, so doing
    this first means the technical half of the checklist is answered by the bill
    of quantities rather than by a second opinion about it.

    Like completeness, it runs after persist and does not fail the job. An
    unresolved item is a visible, one-click-fixable state; losing a finished
    offer over a categorisation pass would not be.
    """

    async def taxonomy_node(state: PipelineState) -> PipelineState:
        offer_id = state["offer_id"]
        await progress.start_stage(STAGE_ID, "sorting items by discipline")

        async def on_resolve(done: int, total: int) -> None:
            await progress.update_detail(
                STAGE_ID,
                f"{done} of {total} item(s) sorted",
                fraction=done / total if total else 1.0,
            )

        try:
            async with session_factory() as db:
                resolved, unresolved = await TaxonomyController(db).resolve_offer_items(
                    offer_id, on_progress=on_resolve
                )
        except JobCancelled:
            raise
        except Exception as exc:
            logger.exception("taxonomy stage failed for offer %s", offer_id)
            await progress.fail_stage(
                STAGE_ID,
                f"Could not sort the items by discipline ({exc}). The offer is saved - "
                "re-run this from the offer page.",
            )
            return {"taxonomy_resolved": 0, "taxonomy_unresolved": 0}

        await progress.finish_stage(
            STAGE_ID,
            f"{resolved} item(s) sorted"
            + (f", {unresolved} left uncategorised" if unresolved else ""),
        )
        # Covers the re-sort an admin triggers from the offer page as well as
        # the one inside a full run: both come through this node, so the log
        # does not need to know which job it was.
        await record_taxonomy_resorted(
            offer_id=offer_id, resolved=resolved, unresolved=unresolved
        )
        return {"taxonomy_resolved": resolved, "taxonomy_unresolved": unresolved}

    return taxonomy_node
