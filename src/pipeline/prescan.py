"""The completeness scan, started early instead of queued behind extraction.

`CompletenessController.check_offer` is two halves with very different inputs.
The scan asks the model about every excerpt of the parsed text; the
reconciliation judges those answers against the offer that was actually saved
and the disciplines its items resolved to. Only the second half needs persist
and taxonomy to have happened - the first needs nothing but parsed pages, which
exist the moment the parse stage ends.

So the scan starts next to extraction rather than after taxonomy. On the
measured nine-page case that is a ~75-second model call moved off the critical
path of a run that takes about nine minutes, and the whole of the slack this
pipeline has: everything else in a run is either already concurrent (extraction
chunks, parse files) or a real data dependency (draft then verify over the
draft, sanity then verification of its findings, persist then taxonomy).

It shares a ceiling (LLM_MAX_CONCURRENT_REQUESTS) with every stage, but at
background priority: when calls are queued for a slot, every pipeline call
goes first and the scan takes only the slots nothing else is waiting for.
Before that ordering existed, its excerpts queued ahead of extraction's verify
passes and made the longest stage longer. If the scan is still ever measured
costing extraction more than it saves - the two share one backend -
COMPLETENESS_SCAN_DURING_EXTRACTION turns this off without a deploy.

The task is owned by `pipeline.runner`, not by a node, because no node spans the
whole run: a job that dies in any stage after the scan started must not leave a
model call in flight for a run nobody is watching.
"""

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from controllers import CompletenessController
from helpers import get_settings
from helpers.llm_runnable import LLM_PRIORITY_BACKGROUND, set_llm_priority
from pipeline.progress import JobProgress
from pipeline.stages import COMPLETENESS_STAGE_ID
from schema.completeness import CompletenessScanResult

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]


class CompletenessPrescan:
    """One offer's completeness scan, running beside the stages it does not
    depend on.

    Started by the extraction stage, collected by the completeness stage, and
    cancelled by the runner on every path out of a run.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        progress: JobProgress,
        *,
        enabled: bool | None = None,
    ):
        self._session_factory = session_factory
        self._progress = progress
        self._enabled = (
            get_settings().COMPLETENESS_SCAN_DURING_EXTRACTION if enabled is None else enabled
        )
        self._task: asyncio.Task | None = None

    def start(self, offer_id: int) -> None:
        """Puts the scan in flight and returns immediately.

        Deliberately not a coroutine: the caller is the extraction stage, which
        must get straight on with the longest work in the run rather than
        awaiting anything here. Starting twice is a no-op - one offer gets one
        scan.
        """
        if self._task is not None or not self._enabled:
            return
        self._task = asyncio.create_task(
            self._scan(offer_id), name=f"completeness-prescan-{offer_id}"
        )

    async def result(self) -> list[CompletenessScanResult] | None:
        """What the scan found, or None when there was no scan to collect.

        None means "do it yourself": the switch is off, or this is a re-check
        job, which has no extraction to run alongside. A scan that FAILED raises
        here instead, in the completeness node, which already treats any failure
        of its own as a failed stage and never as a failed job - the offer is
        saved by then and a re-check is one click away.
        """
        if self._task is None:
            return None
        return await self._task

    async def cancel(self) -> None:
        """Stops a scan nothing is going to collect, and waits for it to unwind.

        Idempotent, and safe when nothing was ever started, because the runner
        calls it on every path out of a run - including the successful one,
        where the completeness node has already collected it and this does
        nothing.
        """
        if self._task is None:
            return
        if not self._task.done():
            self._task.cancel()
        # Gathered either way: a task whose exception is never retrieved logs
        # "Task exception was never retrieved" when it is garbage-collected,
        # which reads like a crash in some unrelated job.
        await asyncio.gather(self._task, return_exceptions=True)

    async def _scan(self, offer_id: int) -> list[CompletenessScanResult]:
        # Behind extraction in the gateway queue, not beside it. This task is
        # the only one that runs its own calls, and the priority is copied into
        # every task it spawns, so the scan's excerpts all wait while any
        # pipeline call is waiting - and still use every slot the pipeline is
        # not. Its result is not needed until the completeness stage, long
        # after extraction, sanity and verification, whose calls it used to
        # queue ahead of. Changes the order of requests, never their content.
        set_llm_priority(LLM_PRIORITY_BACKGROUND)
        await self._progress.start_stage(COMPLETENESS_STAGE_ID, "reading the documents for gaps")
        # Its OWN session, never the extraction stage's. The two run at the same
        # time, and one AsyncSession driven from two tasks interleaves
        # statements on a single connection - which asyncpg answers with a
        # different error every time it happens.
        async with self._session_factory() as db:
            scans = await CompletenessController(db).scan_offer(
                offer_id, on_progress=self._report
            )
        logger.info(
            "completeness prescan offer_id=%s read %s excerpt(s) alongside extraction",
            offer_id,
            len(scans),
        )
        return scans

    async def _report(self, done: int, total: int) -> None:
        """Reports the scan on the completeness stage, while extraction is still
        reporting on its own.

        Two stages are genuinely running at once here. The progress snapshot
        carries a fraction per stage so this cannot credit extraction's weight,
        and the row's current stage is derived as the first running stage in
        list order, so the headline stays on extraction - see
        `pipeline/progress.py`.
        """
        await self._progress.update_detail(
            COMPLETENESS_STAGE_ID,
            f"{done} of {total} section(s) read" if total > 1 else "reading the documents",
            fraction=done / total if total else 0.0,
        )
