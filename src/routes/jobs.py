import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from controllers import (
    DocumentValidationError,
    JobController,
    JobForbiddenError,
    JobNotFoundError,
    JobNotWaitingError,
    OfferNotFoundError,
    OfferNotLatestVersionError,
    UploadController,
)
from controllers.JobController import (
    MIN_RUNS_FOR_ESTIMATE,
    OfferFacts,
    OfferPipelineAlreadyRunningError,
    QueuePlan,
    QueueSlot,
    effective_slots,
    plan_queue,
    seconds_between,
)
from db import get_db
from dependencies import governed_user
from helpers import get_settings
from helpers.offer_events import record_offer_uploaded, record_version_uploaded
from helpers.visibility import ensure_offer_visible, visible_job, visible_offer
from models.db_schema import Document, Offer, PipelineJob, QueueState, User
from models.enums import JobKind, JobStatus
from pipeline import runner
from schema.jobs import (
    JobOut,
    JobStage,
    QueueJob,
    QueueOut,
    QueuePositionRequest,
    QueueSlotsRequest,
    StartOfferJobResponse,
)
from schema.upload import UploadedFileResult, UploadItemStatus

logger = logging.getLogger(__name__)

jobs_router = APIRouter(
    prefix="/api/v1/jobs",
    tags=["jobs"],
    dependencies=[Depends(governed_user)],
)

# The queue itself is not addressed by a job id and is not a list of jobs - it
# is one shared thing with its own controls - so it gets its own prefix rather
# than being hung off /jobs as a special id.
queue_router = APIRouter(
    prefix="/api/v1/queue",
    tags=["queue"],
    dependencies=[Depends(governed_user)],
)


@dataclass(frozen=True)
class _QueueMaths:
    """The queue's arithmetic, done once and reused by every view of it.

    Computed over the WHOLE installation's queue - see
    `JobController.queue_skeleton` for why a department-scoped position would
    be a lie - and then read row by row for the jobs a caller may actually see.
    """

    state: QueueState
    slots: int
    running: list[QueueSlot]
    waiting: list[QueueSlot]
    plan: QueuePlan
    positions: dict[uuid.UUID, int]
    starts: dict[uuid.UUID, int | None]
    remaining: dict[uuid.UUID, int | None]
    medians: dict[str, tuple[int, int]]
    now: datetime


async def _queue_maths(controller: JobController) -> _QueueMaths:
    state = await controller.get_queue_state()
    running, waiting = await controller.queue_skeleton()
    medians = await controller.median_run_seconds()
    now = datetime.now(timezone.utc)

    def typical(kind: str) -> int | None:
        median, runs = medians.get(kind, (0, 0))
        # Below the threshold the installation has not seen enough reads to
        # have a "usual" time, and a median of two runs is a guess with a
        # number on it.
        return median if runs >= MIN_RUNS_FOR_ESTIMATE else None

    remaining: dict[uuid.UUID, int | None] = {}
    for slot in running:
        median = typical(slot.kind)
        remaining[slot.job_id] = (
            None
            if median is None or slot.started_at is None
            else max(0, median - seconds_between(slot.started_at, now))
        )

    slots = effective_slots(
        configured_ceiling=get_settings().QUEUE_MAX_CONCURRENT_JOBS,
        parallel_slots=state.parallel_slots,
    )
    if state.is_paused:
        # Nothing starts while the queue is paused, so every "starts in" would
        # be a countdown to a moment that is not coming. The screen says
        # "paused" instead.
        plan = QueuePlan(starts=tuple([None] * len(waiting)), next_start=None, finishes_in=None)
    else:
        plan = plan_queue(
            running_remaining=[remaining[slot.job_id] for slot in running],
            waiting_durations=[typical(slot.kind) for slot in waiting],
            slots=slots,
        )

    return _QueueMaths(
        state=state,
        slots=slots,
        running=running,
        waiting=waiting,
        plan=plan,
        positions={slot.job_id: index for index, slot in enumerate(waiting, start=1)},
        starts={slot.job_id: plan.starts[index] for index, slot in enumerate(waiting)},
        remaining=remaining,
        medians=medians,
        now=now,
    )


def _to_out(
    job: PipelineJob,
    *,
    facts: OfferFacts | None = None,
    display_name: str = "",
    queue_position: int | None = None,
) -> JobOut:
    facts = facts or OfferFacts()
    return JobOut(
        job_id=job.job_id,
        kind=JobKind(job.kind),
        status=JobStatus(job.status),
        offer_id=job.offer_id,
        offer_ref=facts.offer_ref,
        rfq_number=facts.rfq_number,
        project_name=facts.project_name,
        file_count=facts.file_count,
        page_count=facts.page_count,
        stages=[JobStage.model_validate(stage) for stage in (job.stages or [])],
        current_stage=job.current_stage,
        progress_percent=job.progress_percent,
        error_stage=job.error_stage,
        error_message=job.error_message,
        cancel_requested=job.cancel_requested,
        queue_position=queue_position,
        created_at=job.created_at,
        enqueued_at=job.enqueued_at,
        started_at=job.started_at,
        updated_at=job.updated_at,
        finished_at=job.finished_at,
        created_by_user_id=job.created_by_user_id,
        created_by_display_name=display_name,
        offer_persisted=facts.persisted,
    )


async def _to_outs(db: AsyncSession, jobs: list[PipelineJob]) -> list[JobOut]:
    """Fills in everything a job row shows that is not on the job row itself.

    Three queries for a whole page rather than three per job: the progress page
    polls this, and an N+1 behind a poll is a load test of your own database.
    """
    if not jobs:
        return []
    controller = JobController(db)
    facts = await controller.offer_facts([job.offer_id for job in jobs])
    names = await controller.display_names([job.created_by_user_id for job in jobs])
    positions: dict[uuid.UUID, int] = {}
    if any(job.status == JobStatus.QUEUED.value for job in jobs):
        _, waiting = await controller.queue_skeleton()
        positions = {slot.job_id: index for index, slot in enumerate(waiting, start=1)}
    return [
        _to_out(
            job,
            facts=facts.get(job.offer_id),
            display_name=names.get(job.created_by_user_id, ""),
            queue_position=positions.get(job.job_id),
        )
        for job in jobs
    ]


def _at(now: datetime, seconds: int | None) -> datetime | None:
    return None if seconds is None else now + timedelta(seconds=seconds)


def _summary(*, paused: bool, running: int, waiting: int) -> str:
    """The header pill, written once here instead of three times in the UI."""
    if paused:
        return f"Queue paused - {waiting} waiting" if waiting else "Queue paused"
    if not running and not waiting:
        return "Nothing in the queue"
    parts = []
    if running:
        parts.append(f"{running} reading")
    if waiting:
        parts.append(f"{waiting} waiting")
    return " - ".join(parts)


def _estimate_note(*, paused: bool, available: bool) -> str:
    if paused:
        return (
            "The queue is paused, so nothing new starts and there is nothing to count down to. "
            "The run in progress finishes."
        )
    if not available:
        return (
            f"No estimate yet - Bidsense needs {MIN_RUNS_FOR_ESTIMATE} finished reads of its own "
            "before it will put a number on the wait. The order below is exact either way."
        )
    return "Estimated from the middle duration of this installation's own finished reads."


async def _queue_view(db: AsyncSession, user: User) -> QueueOut:
    """The queue as one user may see it, over arithmetic done for all of it."""
    controller = JobController(db)
    maths = await _queue_maths(controller)

    visible = await controller.queue_jobs(user)
    facts = await controller.offer_facts([job.offer_id for job in visible])
    names = await controller.display_names(
        [job.created_by_user_id for job in visible] + [maths.state.updated_by_user_id]
    )

    def entry(job: PipelineJob) -> QueueJob:
        row = _to_out(
            job,
            facts=facts.get(job.offer_id),
            display_name=names.get(job.created_by_user_id, ""),
            queue_position=maths.positions.get(job.job_id),
        )
        start_seconds = maths.starts.get(job.job_id)
        return QueueJob(
            **row.model_dump(),
            estimated_start_seconds=start_seconds,
            estimated_start_at=_at(maths.now, start_seconds),
            elapsed_seconds=(
                None if job.started_at is None else seconds_between(job.started_at, maths.now)
            ),
            estimated_remaining_seconds=maths.remaining.get(job.job_id),
        )

    running = [entry(job) for job in visible if job.status == JobStatus.RUNNING.value]
    waiting = [entry(job) for job in visible if job.status == JobStatus.QUEUED.value]
    waiting.sort(key=lambda row: (row.queue_position or 0))

    running_count, waiting_count = len(maths.running), len(maths.waiting)
    # "We can date something" - the next free slot, or any waiting job. Paused,
    # nothing is datable by definition.
    estimates_available = not maths.state.is_paused and (
        maths.plan.next_start is not None
        or any(start is not None for start in maths.plan.starts)
    )

    return QueueOut(
        is_paused=maths.state.is_paused,
        paused_at=maths.state.paused_at,
        # Who pressed pause. Meaningless when the queue is running - the same
        # column then names whoever resumed it - so it is only reported paused.
        paused_by=(
            names.get(maths.state.updated_by_user_id, "") if maths.state.is_paused else ""
        ),
        parallel_slots=maths.state.parallel_slots,
        slots=maths.slots,
        slot_ceiling=get_settings().QUEUE_MAX_CONCURRENT_JOBS,
        running=running,
        waiting=waiting,
        running_count=running_count,
        waiting_count=waiting_count,
        hidden_running_count=max(0, running_count - len(running)),
        hidden_waiting_count=max(0, waiting_count - len(waiting)),
        next_position=waiting_count + 1,
        next_start_seconds=maths.plan.next_start,
        next_start_at=_at(maths.now, maths.plan.next_start),
        finishes_at=_at(maths.now, maths.plan.finishes_in),
        estimates_available=estimates_available,
        estimate_note=_estimate_note(
            paused=maths.state.is_paused, available=estimates_available
        ),
        estimate_runs={kind: runs for kind, (_median, runs) in maths.medians.items()},
        summary=_summary(
            paused=maths.state.is_paused, running=running_count, waiting=waiting_count
        ),
    )


async def _store_files(
    controller: UploadController, offer_id: int, files: list[UploadFile], user: User
) -> list[UploadedFileResult]:
    """Saves each uploaded file, turning an expected rejection into a per-file
    result instead of failing the whole batch."""
    results: list[UploadedFileResult] = []
    for file in files:
        filename = file.filename or "unknown"
        try:
            content, checksum, _size = await controller.validate_and_buffer(file)
            duplicate = await controller.find_duplicate(checksum, user, current_offer_id=offer_id)
            if duplicate is not None:
                existing, visible = duplicate
                results.append(
                    UploadedFileResult(
                        filename=filename,
                        status=UploadItemStatus.DUPLICATE,
                        message=(
                            f"This file was already uploaded before (offer #{existing.offer_id})."
                            if visible
                            else "This file was already uploaded before, to an offer in another department."
                        ),
                        checksum=checksum,
                        document_id=existing.document_id if visible else None,
                    )
                )
                continue
            document = await controller.save_document(
                offer_id=offer_id,
                original_filename=filename,
                file_type=file.content_type or "application/octet-stream",
                checksum=checksum,
                content=content,
                commit=True,
            )
            results.append(
                UploadedFileResult(
                    filename=filename,
                    status=UploadItemStatus.SUCCESS,
                    message="Uploaded successfully.",
                    checksum=checksum,
                    document_id=document.document_id,
                )
            )
        except DocumentValidationError as exc:
            results.append(
                UploadedFileResult(
                    filename=filename, status=UploadItemStatus.ERROR, message=exc.message
                )
            )
        except Exception:
            logger.exception("Unexpected error storing %r for offer %s", filename, offer_id)
            results.append(
                UploadedFileResult(
                    filename=filename,
                    status=UploadItemStatus.ERROR,
                    message="Unexpected server error while processing this file.",
                )
            )
    return results


@jobs_router.post("/offer", response_model=StartOfferJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_offer_job(
    response: Response,
    files: list[UploadFile] = File(...),
    target_offer_id: int | None = None,
    project_name_entered: str | None = Form(None),
    rfq_number: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> StartOfferJobResponse:
    """Uploads an offer's files and puts it in the queue to be read.

    Returns as soon as the files are stored - typically a second or two - with
    a job id to poll, its place in the queue and when it is expected to start.
    The reading itself (parse, extract, check, save, then the completeness and
    discipline passes) can take many minutes on a real offer, and it now runs on
    the server: closing the tab, navigating away, or losing the network no
    longer discards it.

    The job WAITS rather than starting here. Nothing about this response is a
    promise that reading has begun - `queue_position` and
    `estimated_start_seconds` say when it will.

    Pass `target_offer_id` to upload a new VERSION of an existing offer instead
    of creating a new one - `project_name_entered` and `rfq_number` are then
    ignored (and should not be sent): a version answers the same RFQ under the
    same typed name as the rest of its chain, inherited in
    `UploadController.create_offer_version`, not re-typed.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="At least one file must be provided."
        )

    controller = UploadController(db)
    parent_offer_id: int | None = None
    root_offer_id: int | None = None

    if target_offer_id is not None:
        # Checked here because the id is optional and arrives in the query
        # string, which no path guard sees. Versioning another department's
        # offer would flip its is_active_latest and graft this upload onto it.
        await ensure_offer_visible(db, target_offer_id, user)
        try:
            offer_id = await controller.create_offer_version(
                target_offer_id, commit=True, owner=user
            )
        except OfferNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Offer {target_offer_id} not found."
            ) from exc
        except OfferNotLatestVersionError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Offer {target_offer_id} is not the latest version of its chain - only the "
                    "current latest version can be versioned."
                ),
            ) from exc
        target = await db.get(Offer, target_offer_id)
        parent_offer_id = target_offer_id
        root_offer_id = target.root_offer_id or target_offer_id
    else:
        offer_id = await controller.create_offer(
            commit=True,
            owner=user,
            project_name_entered=project_name_entered,
            rfq_number=rfq_number,
        )

    results = await _store_files(controller, offer_id, files, user)
    document_ids = [
        result.document_id
        for result in results
        if result.status == UploadItemStatus.SUCCESS and result.document_id
    ]

    if not document_ids:
        # Nothing to read. The speculative offer (and, for a version, the flip
        # of is_active_latest) is undone here rather than left behind - no job
        # is ever started, so nothing else will clean it up.
        # abandon_offer also restores the parent's is_active_latest, so a
        # failed version upload leaves the chain exactly as it was.
        await controller.abandon_offer(offer_id)
        # A 2xx so the client can actually read the per-file reasons; an error
        # status makes the fetch wrapper throw before it inspects the body.
        response.status_code = status.HTTP_200_OK
        return StartOfferJobResponse(
            job_id=uuid.UUID(int=0),
            offer_id=offer_id,
            results=results,
            parent_offer_id=parent_offer_id,
            root_offer_id=root_offer_id,
        )

    # "Mohanad Hassan uploaded 3 files" - the first line of this offer's
    # history, written before the job is queued so the log reads in the order
    # things actually happened. Counted from the files that landed, not the
    # files that were offered: a duplicate or a rejected type never became part
    # of this offer.
    if parent_offer_id is None:
        await record_offer_uploaded(
            offer_id=offer_id, actor=user, file_count=len(document_ids)
        )
    else:
        await record_version_uploaded(
            offer_id=offer_id,
            actor=user,
            file_count=len(document_ids),
            parent_offer_id=parent_offer_id,
            root_offer_id=root_offer_id,
        )

    job_controller = JobController(db)
    try:
        job = await job_controller.create_job(
            kind=JobKind.OFFER_PIPELINE,
            offer_id=offer_id,
            user=user,
            completed_stage_ids=("upload",),
        )
    except OfferPipelineAlreadyRunningError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OfferNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Offer {offer_id} not found."
        ) from exc
    runner.start_job(job.job_id, JobKind.OFFER_PIPELINE, offer_id, document_ids)

    # Read back AFTER the job is written, so the position it reports is the one
    # it actually has rather than the one it would have had.
    maths = await _queue_maths(job_controller)
    start_seconds = maths.starts.get(job.job_id)
    return StartOfferJobResponse(
        job_id=job.job_id,
        offer_id=offer_id,
        results=results,
        parent_offer_id=parent_offer_id,
        root_offer_id=root_offer_id,
        queue_position=maths.positions.get(job.job_id),
        estimated_start_seconds=start_seconds,
        estimated_start_at=_at(maths.now, start_seconds),
    )


@jobs_router.post(
    "/offer/{offer_id}/rerun",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(visible_offer)],
)
async def rerun_offer_job(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> JobOut:
    """Queues the pipeline again over files that are already uploaded.

    This is what a failed run leads to now. The offer and its documents are
    kept when a run fails, so retrying costs a re-read, not a re-upload - which
    matters when the failure was a gateway timeout ten minutes in.
    """
    document_ids = list(
        (await db.execute(select(Document.document_id).where(Document.offer_id == offer_id)))
        .scalars()
        .all()
    )
    if not document_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This offer has no uploaded files to read.",
        )

    try:
        job = await JobController(db).create_job(
            kind=JobKind.OFFER_PIPELINE,
            offer_id=offer_id,
            user=user,
            completed_stage_ids=("upload",),
        )
    except OfferPipelineAlreadyRunningError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OfferNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Offer {offer_id} not found."
        ) from exc
    runner.start_job(job.job_id, JobKind.OFFER_PIPELINE, offer_id, document_ids)
    return (await _to_outs(db, [job]))[0]


@jobs_router.get("/{job_id}", response_model=JobOut, dependencies=[Depends(visible_job)])
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> JobOut:
    """The job's current state. This is what the progress bar polls."""
    try:
        job = await JobController(db).get_job(job_id, user)
    except JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.") from None
    except JobForbiddenError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This job belongs to another department."
        ) from None
    return (await _to_outs(db, [job]))[0]


@jobs_router.get("", response_model=list[JobOut])
async def list_jobs(
    limit: int = 25,
    offset: int = 0,
    status_filter: list[JobStatus] | None = Query(default=None, alias="status"),
    kind: list[JobKind] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> list[JobOut]:
    """A page of this department's jobs, newest first.

    `status` and `kind` may each be repeated (`?status=failed&status=cancelled`)
    and filter to any of the values given. `offer_persisted`, the file and page
    counts and the uploader's name are filled in on EVERY row - they used to be
    computed only on the single-job route, which meant a list could not tell a
    failure that lost the work from one that did not.
    """
    jobs = await JobController(db).list_jobs(
        user,
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
        statuses=status_filter,
        kinds=kind,
    )
    return await _to_outs(db, jobs)


@jobs_router.post("/{job_id}/cancel", response_model=JobOut, dependencies=[Depends(visible_job)])
async def cancel_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> JobOut:
    """Stops a job, whether it is reading or still waiting its turn.

    A waiting job is taken out of the queue immediately - there is nothing to
    interrupt. A running one is asked to stop at its next stage boundary: the
    flag on the row is the authoritative signal, because it works even when the
    request lands on a worker that is not running the job, and cancelling the
    local task as well just makes the common case immediate.
    """
    try:
        job = await JobController(db).request_cancel(job_id, user)
    except JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.") from None
    except JobForbiddenError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This job belongs to another department."
        ) from None
    runner.cancel_local(job_id)
    return (await _to_outs(db, [job]))[0]


@jobs_router.patch(
    "/{job_id}/position", response_model=QueueOut, dependencies=[Depends(visible_job)]
)
async def move_job(
    job_id: uuid.UUID,
    request: QueuePositionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> QueueOut:
    """Moves a waiting job to a position in the queue. 1 starts next.

    The position is the whole queue's, which is the same number the job's own
    row reports - so "move up" is `position - 1` and needs no knowledge of who
    owns the row above. A job may only be moved by someone who can see it, but
    where it lands moves other departments' jobs by one: there is one runner
    and therefore one order, and pretending otherwise would mean a queue screen
    whose drag did something different from what it showed.

    Returns the whole queue, because every position after the move has changed.
    """
    try:
        await JobController(db).move_in_queue(job_id, request.position, user)
    except JobNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.") from None
    except JobForbiddenError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This job belongs to another department."
        ) from None
    except JobNotWaitingError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This job is not waiting any more - it has already started or finished.",
        ) from None
    return await _queue_view(db, user)


@queue_router.get("", response_model=QueueOut)
async def read_queue(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> QueueOut:
    """What is reading, what is waiting, and whether the queue is running.

    The one endpoint behind the Queue screen, the rail's queue card, the header
    pill and the upload screen's "goes into the queue" card.
    """
    return await _queue_view(db, user)


@queue_router.post("/pause", response_model=QueueOut)
async def pause_queue(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> QueueOut:
    """Stops anything NEW from starting. The run in progress finishes.

    Global, not per-department: one runner serves the whole company, so a pause
    that only covered your own department would be a label on a queue that kept
    running. It is stored in the database, so it survives a restart - a pause
    that quietly lifted itself during a deploy is exactly the failure that makes
    the button untrustworthy.
    """
    await JobController(db).set_paused(paused=True, user=user)
    return await _queue_view(db, user)


@queue_router.post("/resume", response_model=QueueOut)
async def resume_queue(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> QueueOut:
    await JobController(db).set_paused(paused=False, user=user)
    # Without this the first offer waits for the dispatcher's next tick, and a
    # resume button that visibly does nothing for five seconds gets pressed
    # again.
    runner.wake_dispatcher()
    return await _queue_view(db, user)


@queue_router.patch("/slots", response_model=QueueOut)
async def set_queue_slots(
    request: QueueSlotsRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> QueueOut:
    """How many offers may read at the same time (1-3).

    The deployment's own ceiling still applies on top: if
    QUEUE_MAX_CONCURRENT_JOBS is lower than this, the lower number is what runs,
    and the response says both so the UI can explain the difference rather than
    show a dial that does nothing.

    Lowering it never stops a run that has already started; the extra slots are
    simply not refilled.
    """
    try:
        await JobController(db).set_parallel_slots(slots=request.parallel_slots, user=user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    runner.wake_dispatcher()
    return await _queue_view(db, user)
