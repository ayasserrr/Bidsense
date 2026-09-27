from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from controllers import PersistController
from helpers.offer_events import record_project_name_mismatch
from pipeline.progress import JobProgress
from pipeline.resume import clear_checkpoint
from pipeline.state import PipelineState

STAGE_ID = "persist"


def make_persist_node(
    session_factory: Callable[[], AsyncSession],
    progress: JobProgress,
) -> Callable[[PipelineState], Awaitable[PipelineState]]:
    """Builds the node that writes the extraction, the sanity check and the
    verification into the real offer tables.

    Not conditional: it always runs and always writes, whatever the checks
    concluded. An offer flagged `needs_human_review` is persisted exactly like a
    clean one, just labelled as such. This stage never rejects an offer.

    It is also the line the rest of the run is measured against. Everything
    before it can still lose the run; everything after it is a check over an
    offer that is already safely saved.
    """

    async def persist_node(state: PipelineState) -> PipelineState:
        await progress.raise_if_cancelled()
        await progress.start_stage(STAGE_ID, "saving")

        async with session_factory() as db:
            controller = PersistController(db)
            offer = await controller.persist_offer(
                state["offer_id"],
                state["extraction_payload"],
                state.get("sanity_check_result"),
                state.get("verification_result"),
            )
            entered = offer.project_name_entered
            extracted = offer.project_name_original
            # Which file each line came from, resolved by finding the item's own
            # text in the merged source - never asked of the model. Both the
            # completeness report and the per-file item view read it.
            attributed = await controller.attribute_item_sources(state["offer_id"])

        await progress.finish_stage(
            STAGE_ID, f"saved; {attributed} item(s) traced to a source file"
        )

        # The typed project name and the one the document states disagree. This
        # is the first moment both exist, and it is a note, never a failure:
        # the extracted name is left exactly as the document gave it, because
        # that is the name check_same_offer_identity compares when the next
        # version arrives. Only a real disagreement is worth a line - one of
        # the two being absent is the normal case.
        if entered and extracted and entered.strip().lower() != extracted.strip().lower():
            await record_project_name_mismatch(
                offer_id=state["offer_id"], entered=entered, extracted=extracted
            )
        # The offer itself is now the durable record - a checkpoint from a
        # failed earlier attempt on this offer must not outlive it.
        await clear_checkpoint(session_factory, state["offer_id"])
        return {}

    return persist_node
