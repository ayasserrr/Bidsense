"""The job queue, and the running of a job in the background.

The job outlives the request that started it. That is the whole point: a real
offer takes minutes to read, and until this existed the browser had to sit on
the page for the entire run - navigating away deleted the work. The request
returns a job id immediately and the run continues here.

Offers now WAIT rather than all starting at once. A dispatcher loop claims
waiting jobs in order, at most `QUEUE_MAX_CONCURRENT_JOBS` (and at most
`queue_state.parallel_slots`) at a time, and runs each one as an `asyncio.Task`
on the API's own event loop. There is still no Redis and no worker fleet: the
work is almost entirely waiting on the gateway and on Parsing Studio, the
ordering fits in one indexed column, and the claim is a `SELECT ... FOR UPDATE
SKIP LOCKED` that is correct even if a second uvicorn worker is doing the same
thing. Three more things to deploy would buy throughput this application does
not need.

What the queue holds is offer READS. A completeness or taxonomy re-check runs
over an offer that is already saved, takes a fraction of the time, and has a
reviewer waiting on the screen for it; putting it behind a twenty-minute
extraction would be a regression dressed up as consistency. Those still start
the moment they are asked for, and the ceiling that matters for them - requests
in flight at the gateway - is enforced in the LLM transport either way.

Across a restart the two halves of the queue are settled differently, and
`JobController.reap_stale_jobs` is where that is written down: a RUNNING job is
failed, because a pipeline's worth of in-flight state went with the process; a
WAITING job simply stays waiting, because it holds nothing but its own row.
That second half is what the queue is for - nothing here carries a payload in
memory any more, so `document_ids` are read back out of the database at the
moment a job is claimed rather than handed over by the request that queued it.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from controllers import JobController
from db import async_session_factory
from models.db_schema import PipelineJob
from helpers.offer_events import record_read_failed, record_read_finished
from models.enums import JobKind, JobStatus

from .graph import (
    build_completeness_graph,
    build_offer_pipeline_graph,
    build_summary_graph,
    build_taxonomy_graph,
)
from .prescan import CompletenessPrescan
from .progress import JobCancelled, JobProgress
from .resume import determine_resume_point
from .stages import stages_for

logger = logging.getLogger(__name__)

# Strong references to in-flight tasks. Without this the event loop is the only
# thing holding them and a task can be garbage-collected mid-run -
# asyncio.create_task returns a weakly-referenced handle.
_running: dict[uuid.UUID, asyncio.Task] = {}

_dispatcher: asyncio.Task | None = None
# Set whenever something might have changed the queue: a job queued, a job
# finished, the queue resumed, the slots raised, the order changed.
_wakeup: asyncio.Event | None = None
# Shutting down. Read on the cancellation path so that a job stopped by a
# deploy does not tell the reviewer they stopped it themselves.
_stopping = False

# The dispatcher does not rely on being woken. It is woken for the common case,
# so a queued offer starts in milliseconds rather than at the next tick, but it
# also looks on a timer: another uvicorn worker can queue a job or free a slot
# without this process ever hearing about it, and a missed wake-up would then
# leave a full queue sitting still with nobody to blame.
DISPATCH_POLL_SECONDS = 5.0

_GRAPH_BUILDERS = {
    JobKind.OFFER_PIPELINE: build_offer_pipeline_graph,
    JobKind.COMPLETENESS: build_completeness_graph,
    JobKind.TAXONOMY: build_taxonomy_graph,
    JobKind.SUMMARY: build_summary_graph,
}


def start_dispatcher() -> None:
    """Starts the loop that takes waiting jobs, once per process.

    Called at startup AFTER stale jobs have been settled, so it can never pick
    up a run that a previous process left marked `running`.
    """
    global _dispatcher, _stopping, _wakeup
    _stopping = False
    if _wakeup is None:
        _wakeup = asyncio.Event()
    if _dispatcher is None or _dispatcher.done():
        _dispatcher = asyncio.create_task(_dispatch_loop(), name="pipeline-queue-dispatcher")


def wake_dispatcher() -> None:
    """Asks the dispatcher to look at the queue now rather than at the next tick."""
    if _wakeup is not None:
        _wakeup.set()


def start_job(job_id: uuid.UUID, kind: JobKind, offer_id: int, document_ids: list[uuid.UUID]) -> None:
    """Puts a freshly created job on its way, and returns immediately.

    An offer read is NOT started here - it is already queued, and this only
    makes sure the dispatcher looks at the list now instead of on its next
    tick. `offer_id` and `document_ids` are ignored for that reason: whatever
    claims the job reads both back off the row, which is what lets a job wait
    through a restart.

    A post-persist re-check is started here and now, for the reason in this
    module's docstring.
    """
    if kind is JobKind.OFFER_PIPELINE:
        wake_dispatcher()
        return
    _spawn(job_id, kind, offer_id, document_ids)


def is_running(job_id: uuid.UUID) -> bool:
    return job_id in _running


def cancel_local(job_id: uuid.UUID) -> bool:
    """Cancels a job's task if it belongs to THIS process.

    Best-effort and secondary: the authoritative stop is the `cancel_requested`
    flag on the row, which the runner checks at every stage boundary and which
    works even when the cancel request lands on a different worker. This just
    makes the common case immediate instead of waiting for the current stage to
    end.
    """
    task = _running.get(job_id)
    if task is None:
        return False
    task.cancel()
    return True


async def shutdown() -> None:
    """Stops the dispatcher and every in-flight job, and lets them unwind.

    Without this the loop closes under running tasks and asyncpg connections
    are torn down mid-query, which surfaces as noise in the logs that looks like
    a bug and is not.

    The dispatcher goes first. Cancelling the jobs while it is still looking
    would have it refill the slots it had just watched empty.
    """
    global _dispatcher, _stopping
    _stopping = True
    if _dispatcher is not None:
        _dispatcher.cancel()
        await asyncio.gather(_dispatcher, return_exceptions=True)
        _dispatcher = None
    tasks = list(_running.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _dispatch_loop() -> None:
    """Claims what fits, then waits to be woken or for the next tick."""
    while not _stopping:
        try:
            await _dispatch_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never let one bad pass kill the loop: a dispatcher that died
            # silently would leave every later upload waiting forever, which is
            # the one failure this whole design cannot afford.
            logger.exception("queue dispatcher: could not place the next job")
        if _wakeup is None:
            return
        try:
            await asyncio.wait_for(_wakeup.wait(), timeout=DISPATCH_POLL_SECONDS)
        except (asyncio.TimeoutError, TimeoutError):
            pass
        _wakeup.clear()


async def _dispatch_once() -> int:
    """Claims as many waiting jobs as there are free slots and starts them."""
    started = 0
    async with async_session_factory() as db:
        controller = JobController(db)
        for job in await controller.claim_jobs():
            kind = JobKind(job.kind)
            document_ids = await controller.document_ids_for(job.offer_id)
            if not document_ids:
                # It can only have got here by having its documents deleted
                # while it waited. Failing it explicitly is the honest end -
                # running it would fail at the parse stage with a much worse
                # message.
                await _fail_without_documents(db, job)
                continue
            logger.info(
                "queue: starting job %s on offer %s (%d file(s))",
                job.job_id,
                job.offer_id,
                len(document_ids),
            )
            _spawn(job.job_id, kind, job.offer_id, document_ids)
            started += 1
    return started


async def _fail_without_documents(db, job: PipelineJob) -> None:
    from controllers.JobController import skip_unfinished

    job.status = JobStatus.FAILED.value
    job.error_message = (
        "This offer has no files left to read - they were removed while it was waiting in "
        "the queue. Upload them again to start a new check."
    )
    job.finished_at = datetime.now(timezone.utc)
    job.stages = skip_unfinished(job.stages)
    await db.commit()
    logger.warning("queue: job %s had no documents left to read", job.job_id)


def _spawn(job_id: uuid.UUID, kind: JobKind, offer_id: int, document_ids: list[uuid.UUID]) -> None:
    if job_id in _running:
        logger.warning("job %s is already running - ignoring duplicate start", job_id)
        return
    task = asyncio.create_task(
        _run(job_id, kind, offer_id, document_ids), name=f"pipeline-job-{job_id}"
    )
    _running[job_id] = task
    task.add_done_callback(lambda _task: _release(job_id))


def _release(job_id: uuid.UUID) -> None:
    """A finished job frees its slot, so the next one starts at once."""
    _running.pop(job_id, None)
    wake_dispatcher()


async def _run(
    job_id: uuid.UUID, kind: JobKind, offer_id: int, document_ids: list[uuid.UUID]
) -> None:
    progress = JobProgress(
        job_id=job_id, session_factory=async_session_factory, stages=stages_for(kind)
    )
    await progress.load()
    await _set_status(job_id, JobStatus.RUNNING)

    # The completeness scan runs alongside extraction and outlives the node that
    # starts it, so the runner owns it: this function is the only place that
    # sees every way out of a run.
    prescan = CompletenessPrescan(async_session_factory, progress)
    state = {"offer_id": offer_id, "document_ids": document_ids}

    try:
        if kind is JobKind.OFFER_PIPELINE:
            # Decided HERE, at the moment this job actually starts running - not
            # when it was queued. A job can wait a long time, and only the state
            # at the moment it is claimed (has every document actually finished
            # parsing, does a checkpoint from an earlier attempt on this offer
            # exist) is worth trusting. See pipeline/resume.py.
            #
            # This planning lives INSIDE the try: the job row was already
            # flipped to RUNNING above, and a failure here (a bad cached
            # checkpoint, a DB hiccup) must still land the job on FAILED
            # rather than leaving it stuck on RUNNING forever with nothing
            # watching it.
            async with async_session_factory() as db:
                plan = await determine_resume_point(db, offer_id, document_ids)
            for stage_id in plan.completed_stage_ids:
                await progress.finish_stage(stage_id, "carried over from an earlier attempt")
            state.update(plan.seed_state)
            graph = build_offer_pipeline_graph(
                async_session_factory, progress, prescan, start_stage=plan.start_stage
            )
            if plan.prescan_needs_manual_start:
                # Normally the extract node starts this. Skipping straight past
                # extract because a cached payload exists means no node in THIS
                # run will - the completeness stage still needs it collected.
                prescan.start(offer_id)
        else:
            graph = _GRAPH_BUILDERS[kind](async_session_factory, progress, prescan)

        await graph.ainvoke(state)
    except (JobCancelled, asyncio.CancelledError):
        await progress.mark_remaining_skipped()
        if _stopping:
            # A deploy, not a person. Telling the reviewer they stopped it
            # would send them looking for a colleague who never touched it.
            await _set_status(
                job_id,
                JobStatus.FAILED,
                error_message=(
                    "The server was restarted while this run was in progress. Nothing was "
                    "lost - the uploaded files are still here - but the run has to be "
                    "started again."
                ),
            )
            logger.info("job %s stopped by shutdown", job_id)
            return
        await _set_status(
            job_id,
            JobStatus.CANCELLED,
            error_message="Stopped at your request. The files are still here - start the check again whenever you like.",
        )
        # No activity-log entry here. The cancel was already recorded where
        # the person who asked for it was known - JobController.request_cancel
        # - and a second line written now would show one click twice.
        logger.info("job %s cancelled", job_id)
        return
    except Exception as exc:
        stage = await _current_stage(job_id)
        if stage:
            await progress.fail_stage(stage, str(exc)[:1000])
        await progress.mark_remaining_skipped()
        failed = await _set_status(
            job_id,
            JobStatus.FAILED,
            error_stage=stage,
            error_message=_readable(exc),
        )
        await _record_run_outcome(kind, offer_id, failed)
        logger.exception("job %s failed during %s", job_id, stage)
        return
    finally:
        # A scan the completeness node already collected is finished and this
        # does nothing. One left behind - by a failure in any stage after it
        # started, or by a cancel - is stopped here rather than going on holding
        # a gateway slot for a job nobody is watching any more.
        await prescan.cancel()

    finished = await _set_status(job_id, JobStatus.SUCCEEDED)
    await _record_run_outcome(kind, offer_id, finished)
    logger.info("job %s finished", job_id)


def _readable(exc: Exception) -> str:
    """A failure message a reviewer can act on.

    The offer and its files survive a failure now, so every message says so -
    otherwise the natural assumption is that the upload has to be redone.
    """
    from asyncio import TimeoutError as AsyncTimeoutError

    from helpers import LlmCallError, LlmTruncatedError, LlmValidationError, ParsingStudioError

    tail = " Your files are still here - you can start the check again without re-uploading."
    if isinstance(exc, ParsingStudioError):
        # Already a sentence written for a person - often the service's own
        # ("File content does not match its extension (.xlsx).").
        return str(exc)[:800].rstrip(".") + "." + tail
    if isinstance(exc, LlmTruncatedError):
        return (
            "The model ran out of room before it finished writing its answer. This offer is "
            "probably too long for one pass." + tail
        )
    if isinstance(exc, AsyncTimeoutError):
        return "This step took longer than its time limit and was stopped." + tail
    if isinstance(exc, LlmValidationError):
        return (
            "The model's answer did not match the expected shape, even after being asked to "
            "correct it." + tail
        )
    if isinstance(exc, LlmCallError):
        return f"The AI gateway could not be reached or did not answer ({exc})." + tail
    return f"{type(exc).__name__}: {exc}"[:800] + tail


async def _record_run_outcome(
    kind: JobKind, offer_id: int | None, job: PipelineJob | None
) -> None:
    """Writes how this read ended to the offer's activity log.

    Only for an offer READ. A completeness or taxonomy re-check has its own
    vocabulary in `OfferEventKind` and its own route to write it from; a second
    "Bidsense finished reading (3s)" every time somebody re-ran a check would
    bury the entries that matter and would be measuring something else anyway.

    The duration is `started_at` -> `finished_at`. Not `created_at`: now that a
    job waits its turn, created_at -> finished_at measures the size of the
    backlog as much as the length of the read, and "finished reading (41m)" for
    a six-minute read on a busy afternoon is worse than no number at all. A row
    from before the queue existed has no started_at, and there the two were the
    same moment.

    The writes themselves never raise - see helpers/offer_events.py. An offer
    whose history is missing a line is a far smaller problem than a finished run
    reported as a failure because writing that line failed.
    """
    if kind is not JobKind.OFFER_PIPELINE or offer_id is None or job is None:
        return
    began = job.started_at or job.created_at
    seconds = (
        (job.finished_at - began).total_seconds() if began and job.finished_at else None
    )
    if job.status == JobStatus.SUCCEEDED.value:
        await record_read_finished(
            offer_id=offer_id, seconds=seconds, job_id=str(job.job_id)
        )
    elif job.status == JobStatus.FAILED.value:
        await record_read_failed(
            offer_id=offer_id,
            stage_label=_stage_label(kind, job.error_stage),
            seconds=seconds,
            job_id=str(job.job_id),
        )


def _stage_label(kind: JobKind, stage_id: str | None) -> str | None:
    """The stage a run died in, named as the progress list names it - "it
    stopped at Extracting the details", not "it stopped at extract". The id is
    kept as the fallback rather than dropped: a stage that has since been
    renamed should still say which one it was."""
    if not stage_id:
        return None
    for stage in stages_for(kind):
        if stage.id == stage_id:
            return stage.label
    return stage_id


async def _set_status(
    job_id: uuid.UUID,
    status: JobStatus,
    *,
    error_stage: str | None = None,
    error_message: str | None = None,
) -> PipelineJob | None:
    """Moves the job row, and hands the row back.

    The row is returned so that the caller can read what it just wrote -
    started_at, finished_at, error_stage - without a second SELECT. It is safe
    to read after the session closes because the session factory is configured
    `expire_on_commit=False`.
    """
    async with async_session_factory() as db:
        job = await db.get(PipelineJob, job_id)
        if job is None:
            return None
        job.status = status.value
        # The dispatcher stamps this when it claims a job. A re-check that was
        # never in the queue is stamped here instead, so that "how long did it
        # take" has the same answer for every kind of job.
        if status is JobStatus.RUNNING and job.started_at is None:
            job.started_at = datetime.now(timezone.utc)
        if error_stage is not None:
            job.error_stage = error_stage
        if error_message is not None:
            job.error_message = error_message
        if status.is_terminal:
            job.finished_at = datetime.now(timezone.utc)
            # It is not waiting any more, whichever way it ended.
            job.queue_position = None
            if status is JobStatus.SUCCEEDED:
                job.progress_percent = 100
                job.current_stage = None
        await db.commit()
    return job


async def _current_stage(job_id: uuid.UUID) -> str | None:
    async with async_session_factory() as db:
        job = await db.get(PipelineJob, job_id)
        return job.current_stage if job else None
