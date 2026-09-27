import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from controllers import VerificationController
from helpers import get_settings
from helpers.offer_events import record_findings_confirmed
from models.enums import FindingVerdict
from pipeline.progress import JobProgress
from pipeline.resume import save_stage_checkpoint
from pipeline.state import PipelineState

STAGE_ID = "verification"


def make_verification_node(
    session_factory: Callable[[], AsyncSession],
    progress: JobProgress,
) -> Callable[[PipelineState], Awaitable[PipelineState]]:
    """Builds the node that independently re-checks the extraction and the
    sanity check's findings against the original parsed source text.

    Needs a database session, unlike the sanity check: fetching the source text
    is the whole point of this stage. It never trusts the extraction's own
    reasoning about itself, only what the document actually says.

    Always runs, so `verification_status` is always explicit on persist -
    `skipped` for a clean offer rather than left null. The skip itself lives
    inside the controller, where it costs one database round-trip and no model
    call; duplicating that decision as a graph edge would be a second, subtly
    different copy of the same rule.
    """

    async def verification_node(state: PipelineState) -> PipelineState:
        await progress.raise_if_cancelled()
        await progress.start_stage(STAGE_ID, "re-reading the source")
        settings = get_settings()

        async with session_factory() as db:
            controller = VerificationController(db)
            result = await asyncio.wait_for(
                controller.verify_offer(
                    state["offer_id"],
                    state["extraction_payload"],
                    state["sanity_check_result"],
                    log_id=str(state["offer_id"]),
                ),
                timeout=settings.EXTRACTION_TOTAL_TIMEOUT_SECONDS,
            )

        await progress.finish_stage(STAGE_ID, result.status.value.replace("_", " "))

        # "Bidsense confirmed 2 findings against the source" - only when there
        # is something to say. A finding the document itself explains away is
        # this stage doing its job, not an entry in the offer's history; the
        # run's own "finished reading" line already covers the clean case.
        confirmed = sum(
            1
            for finding in result.verified_findings
            if finding.finding_verdict == FindingVerdict.CONFIRMED
        )
        if confirmed:
            await record_findings_confirmed(
                offer_id=state["offer_id"],
                confirmed_count=confirmed,
                checked_count=len(result.verified_findings),
            )
        # Cached so a failure in persist (a lost database connection, a
        # constraint this offer happens to trip) can resume straight into
        # persist instead of re-running extraction, sanity-check AND
        # verification for nothing. See pipeline/resume.py.
        await save_stage_checkpoint(session_factory, state["offer_id"], "verification", result)
        return {"verification_result": result}

    return verification_node
