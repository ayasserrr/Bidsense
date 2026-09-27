import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from controllers import CompletenessController
from helpers.completeness_gaps import is_mandatory_gap
from pipeline.prescan import CompletenessPrescan
from pipeline.progress import JobCancelled, JobProgress
from pipeline.stages import COMPLETENESS_STAGE_ID
from pipeline.state import PipelineState

logger = logging.getLogger(__name__)

STAGE_ID = COMPLETENESS_STAGE_ID


def make_completeness_node(
    session_factory: Callable[[], AsyncSession],
    progress: JobProgress,
    prescan: CompletenessPrescan,
) -> Callable[[PipelineState], Awaitable[PipelineState]]:
    """Builds the node that checks the saved offer against the client's
    twenty-item checklist and records what it fails to state.

    The check is two halves (see `pipeline/prescan.py`). In a pipeline run the
    scan half has usually finished already, alongside extraction, so what is
    left here is the reconciliation - judging those answers against the offer
    that was saved and the disciplines its items resolved to, neither of which
    existed when the scan ran. With no scan to collect (a re-check job, or the
    switch off) this does both halves itself, exactly as it always did.

    Runs AFTER persist, and swallows its own failures on purpose. By this point
    the offer is saved; letting a checklist run take the whole job down with it
    would throw away a successful extraction over a check that can simply be run
    again from the offer page. The stage is marked failed, the job is not. A
    scan that failed reports itself here, for the same treatment.

    A cancellation is the one thing it does re-raise - that is the reviewer
    asking it to stop, not something going wrong.
    """

    async def completeness_node(state: PipelineState) -> PipelineState:
        offer_id = state["offer_id"]
        await progress.start_stage(STAGE_ID, "checking against the checklist")

        async def on_scan(done: int, total: int) -> None:
            await progress.update_detail(
                STAGE_ID,
                f"{done} of {total} section(s) checked" if total > 1 else "checking",
                fraction=done / total if total else 0.0,
            )

        try:
            scans = await prescan.result()
            async with session_factory() as db:
                controller = CompletenessController(db)
                results = (
                    await controller.check_offer(offer_id, on_progress=on_scan)
                    if scans is None
                    else await controller.reconcile_and_save(offer_id, scans)
                )
        except JobCancelled:
            raise
        except Exception as exc:
            logger.exception("completeness stage failed for offer %s", offer_id)
            await progress.fail_stage(
                STAGE_ID,
                f"Could not run the completeness check ({exc}). The offer is saved - "
                "re-run the check from the offer page.",
            )
            return {"completeness_failed": True}

        # The same predicate the offers list, the offer header and the
        # completeness section count with. A fourth hand-rolled copy of it here
        # is what `helpers.completeness_gaps` exists to prevent: the stage's own
        # finish text is the first number a reviewer sees, and it must not be
        # able to drift away from the badge they see next.
        gaps = sum(
            1
            for result in results
            if is_mandatory_gap(
                was_mandatory=result.was_mandatory,
                effective_verdict=result.effective_verdict,
            )
        )
        await progress.finish_stage(
            STAGE_ID,
            "nothing missing" if gaps == 0 else f"{gaps} item(s) the supplier did not state",
        )
        return {"completeness_gaps": gaps, "completeness_failed": False}

    return completeness_node
