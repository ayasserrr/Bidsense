from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from controllers import SanityCheckController
from pipeline.progress import JobProgress
from pipeline.resume import save_stage_checkpoint
from pipeline.state import PipelineState

STAGE_ID = "sanity_check"


def make_sanity_check_node(
    session_factory: Callable[[], AsyncSession],
    progress: JobProgress,
) -> Callable[[PipelineState], Awaitable[PipelineState]]:
    """Builds the node that reviews the extract node's output for internal
    pricing/arithmetic consistency, and hands the resulting `SanityCheckResult`
    downstream via `sanity_check_result`.

    It works purely on the payload already in state, checking the numbers
    against each other (quantity x unit_price vs total_price, percentage-of-
    parent pricing, stated subtotals, grand_total, payment-schedule
    percentages) rather than re-grounding them against the source document,
    which is the verification node's job. `session_factory` exists only to
    cache the result on the offer for `pipeline.resume` - this stage still
    reads nothing from the database.
    """

    async def sanity_check_node(state: PipelineState) -> PipelineState:
        await progress.raise_if_cancelled()
        await progress.start_stage(STAGE_ID, "checking the arithmetic")

        controller = SanityCheckController()
        result = await controller.check_offer(
            state["extraction_payload"], log_id=str(state["offer_id"])
        )

        finding_count = len(result.findings)
        await progress.finish_stage(
            STAGE_ID,
            "no pricing issues found" if finding_count == 0 else f"{finding_count} issue(s) to review",
        )
        await save_stage_checkpoint(session_factory, state["offer_id"], "sanity_check", result)
        return {"sanity_check_result": result}

    return sanity_check_node
