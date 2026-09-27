import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from helpers import get_settings
from helpers.offer_events import record_offer_queued, record_read_cancelled
from helpers.visibility import can_see, visibility_filter
from models.db_schema import Document, Offer, PipelineJob, QueueState, User
from models.db_schema.queue_state import (
    MAX_PARALLEL_SLOTS,
    MIN_PARALLEL_SLOTS,
    QUEUE_STATE_ID,
)
from models.enums import JobKind, JobStageStatus, JobStatus
from pipeline.progress import initial_stage_snapshot
from pipeline.stages import stages_for

from .BaseController import BaseController
from .PersistController import OfferNotFoundError

logger = logging.getLogger(__name__)

# How many finished runs of a kind this installation needs before it will put a
# number on "starts in about ...". Two runs can be minutes apart for reasons
# that have nothing to do with the next offer - one scanned document, one
# gateway hiccup - and an estimate drawn from them is a guess wearing a
# number's clothes. Below this the API says so in words instead.
MIN_RUNS_FOR_ESTIMATE = 3

# What the queue actually holds. A completeness or taxonomy re-check runs over
# an offer that is already SAVED, takes a fraction of the time, and has a
# reviewer waiting on the screen for it - putting it behind a twenty-minute
# extraction would be a regression dressed up as consistency. Those start the
# moment they are asked for (see pipeline.runner.start_job) and hold no slot;
# the ceiling that matters for them, requests in flight at the gateway, is
# enforced in the LLM transport either way.
QUEUED_KIND = JobKind.OFFER_PIPELINE


class JobNotFoundError(Exception):
    def __init__(self, job_id: uuid.UUID):
        self.job_id = job_id
        super().__init__(f"Job {job_id} not found")


class JobForbiddenError(Exception):
    """The job exists but belongs to another department."""


class JobNotWaitingError(Exception):
    """Only a job that is still waiting can be moved in the queue."""


@dataclass(frozen=True)
class QueueSlot:
    """One row of the running/waiting skeleton the queue arithmetic works on.

    Deliberately carries no offer content - ids, a kind and two timestamps. See
    `queue_skeleton` for why that one query is NOT department-scoped.
    """

    job_id: uuid.UUID
    kind: str
    status: str
    started_at: datetime | None
    enqueued_at: datetime


@dataclass(frozen=True)
class QueuePlan:
    """When each waiting job is expected to start, in seconds from now.

    `None` anywhere means "not enough finished runs to say", which is a real
    answer and not a zero: a queue screen that invents a number is worse than
    one that admits it does not know yet.
    """

    starts: tuple[int | None, ...]
    # When a job queued right this second would start - what the upload screen
    # promises before the person has committed to anything.
    next_start: int | None
    # When everything already queued is expected to be finished.
    finishes_in: int | None


@dataclass(frozen=True)
class OfferFacts:
    """What a queue row says ABOUT the offer its job is reading.

    Hand-joined and fetched for a whole page of jobs at once. `file_count` and
    `page_count` are the design's "3 files, 42 pages"; pages stay zero until
    the parse stage has filled them in, which is exactly when the UI starts
    having a page count to show.
    """

    offer_ref: str | None = None
    rfq_number: str | None = None
    project_name: str | None = None
    file_count: int = 0
    page_count: int = 0
    persisted: bool = False


def waiting_jobs_query() -> Select:
    """The canonical waiting list: the offer reads that are `queued`, in order.

    Position first, arrival second. The tie-break is not decoration - a reorder
    rewrites several positions at once and two rows can briefly share one, and
    without a total order the dispatcher could take them in a different order
    from the one the screen drew. `ix_pipeline_jobs_queue_order` is this exact
    shape; the kind is a cheap filter on top of it and never a scan of its own.
    """
    return (
        select(PipelineJob)
        .where(
            and_(
                PipelineJob.status == JobStatus.QUEUED.value,
                PipelineJob.kind == QUEUED_KIND.value,
            )
        )
        .order_by(PipelineJob.queue_position, PipelineJob.enqueued_at)
    )


def effective_slots(*, configured_ceiling: int, parallel_slots: int) -> int:
    """How many jobs may run at once: the smaller of the two controls.

    The setting is what an operator says this installation will stand; the row
    is what a reviewer asked for today. Taking the minimum means turning the
    dial up in the UI can never push the server past what it was deployed to
    handle, and turning the setting down takes effect without anyone having to
    remember to lower the row as well.
    """
    return max(MIN_PARALLEL_SLOTS, min(configured_ceiling, parallel_slots))


def plan_queue(
    *,
    running_remaining: list[int | None],
    waiting_durations: list[int | None],
    slots: int,
) -> QueuePlan:
    """Lays the waiting jobs into the free slots and says when each one starts.

    "Add up everything ahead of you" is wrong the moment there is more than one
    slot, and wrong in the direction that annoys people most - it promises
    later than the truth. So this is the actual schedule: each job takes the
    slot that frees first, and that slot is then busy for the job's own
    estimated duration.

    Unknowns propagate instead of being guessed at. A slot whose occupant has
    no estimate could free before any other, so nothing behind it can be dated
    either - unless some other slot is free RIGHT NOW, which no unknown can
    beat, and that job really does start immediately.
    """
    slots = max(MIN_PARALLEL_SLOTS, slots)
    # Fewer running than slots: the spare slots are free now. More running than
    # slots - the dial was turned down while jobs were in flight - and nothing
    # starts until the count drops back under the ceiling, which is the LAST of
    # the sorted remaining times, not the first. Unknowns sort last for the
    # same reason: one of them could be the one everything is waiting on.
    known = sorted(value for value in running_remaining if value is not None)
    unknown: list[int | None] = [None] * (len(running_remaining) - len(known))
    free: list[int | None] = [*known, *unknown, *([0] * max(0, slots - len(running_remaining)))]
    free = free[-slots:]

    starts: list[int | None] = []
    for duration in waiting_durations:
        index = _earliest_free(free)
        if index is None:
            starts.append(None)
            continue
        starts.append(free[index])
        # An unknown duration does not stop the schedule; it only poisons the
        # slot it lands in, which `_earliest_free` then reasons about.
        free[index] = None if duration is None else free[index] + duration

    next_index = _earliest_free(free)
    return QueuePlan(
        starts=tuple(starts),
        next_start=None if next_index is None else free[next_index],
        finishes_in=None if any(value is None for value in free) else max(free, default=0),
    )


def _earliest_free(free: list[int | None]) -> int | None:
    """Which slot frees first, or None when that cannot be known."""
    known = [(index, value) for index, value in enumerate(free) if value is not None]
    if not known:
        return None
    index, value = min(known, key=lambda pair: pair[1])
    # Nothing can free sooner than "now", so a slot that is already free wins
    # even against a slot whose occupant has no estimate.
    if value > 0 and len(known) != len(free):
        return None
    return index


def seconds_between(start: datetime, end: datetime) -> int:
    return int(round((end - start).total_seconds()))


def skip_unfinished(stages: list[dict] | None) -> list[dict]:
    """Closes out the stage list of a job that stopped before it ever ran.

    A cancelled job whose stages all still read "pending" leaves the progress
    list looking like it is about to start, forever. This is the rule the
    runner applies when a run is stopped mid-flight, for a run that never got
    one.
    """
    stopped = {JobStageStatus.PENDING.value, JobStageStatus.ACTIVE.value}
    return [
        {**stage, "status": JobStageStatus.SKIPPED.value}
        if stage.get("status") in stopped
        else stage
        for stage in (stages or [])
    ]


class OfferPipelineAlreadyRunningError(Exception):
    """Raised when a second OFFER_PIPELINE job is requested for an offer that
    already has one QUEUED or RUNNING.

    Two such jobs racing the same offer would both call `determine_resume_point`,
    both write to the same `offers.pipeline_checkpoint`, and both run
    `PersistController.persist_offer`'s delete-then-insert of the offer's child
    rows - a classic double-rerun-click or two-people-acting-on-one-offer race,
    not a hypothetical.
    """

    def __init__(self, offer_id: int):
        super().__init__(
            f"Offer {offer_id} already has a read queued or in progress - wait for it to "
            "finish (or fail) before starting another."
        )
        self.offer_id = offer_id


class JobController(BaseController):
    """Reads and writes `pipeline_jobs` and the single `queue_state` row. The
    running of a job lives in `pipeline.runner`; this is only its record."""

    def __init__(self, db: AsyncSession):
        super().__init__()
        self.db = db

    async def create_job(
        self,
        *,
        kind: JobKind,
        offer_id: int | None,
        user: User,
        completed_stage_ids: tuple[str, ...] = (),
    ) -> PipelineJob:
        """Writes a queued job at the back of the waiting list.

        `completed_stage_ids` marks stages that already happened inside the
        request itself - upload is the only one today. It is shown as done from
        the very first poll rather than flicking from pending to done a moment
        later, because the files really are already in.

        A job on an offer takes that offer's owner, not `user`'s, so a run is
        visible and cancellable exactly when its offer is. Stamped with the
        starter, an admin re-running another department's offer would show that
        run - its filenames, its errors, its cancel button - to the admin's own
        department, and hide it from the department that owns the offer.

        The job is only WRITTEN here. Nothing starts it: the dispatcher in
        `pipeline.runner` takes it when a slot frees, which is what makes the
        waiting list real rather than a label on work that has already begun.
        """
        snapshot = initial_stage_snapshot(stages_for(kind))
        if completed_stage_ids:
            snapshot = [
                {**stage, "status": JobStageStatus.DONE.value}
                if stage["id"] in completed_stage_ids
                else stage
                for stage in snapshot
            ]

        if kind is JobKind.OFFER_PIPELINE and offer_id is not None:
            # Fast, friendly check - a real race is still possible between this
            # SELECT and the INSERT below, closed by the partial unique index
            # `ux_pipeline_jobs_active_offer_pipeline` (see migration 0019),
            # caught as an IntegrityError further down.
            already_active = (
                await self.db.execute(
                    select(PipelineJob.job_id).where(
                        PipelineJob.offer_id == offer_id,
                        PipelineJob.kind == JobKind.OFFER_PIPELINE.value,
                        PipelineJob.status.in_(
                            (JobStatus.QUEUED.value, JobStatus.RUNNING.value)
                        ),
                    )
                )
            ).scalar_one_or_none()
            if already_active is not None:
                raise OfferPipelineAlreadyRunningError(offer_id)

        owner_id, department = user.id, user.department or ""
        if offer_id is not None:
            offer_owner = (
                await self.db.execute(
                    select(Offer.created_by_user_id, Offer.created_by_department).where(
                        Offer.id == offer_id
                    )
                )
            ).one_or_none()
            if offer_owner is not None:
                owner_id = offer_owner.created_by_user_id
                department = offer_owner.created_by_department

        # The back of the list, for the kind of job that queues at all. Not
        # unique and not locked: two uploads landing together can take the same
        # number, and `enqueued_at` breaks that tie in the order they actually
        # arrived. Locking here would serialise every upload behind every other
        # for a number nobody reads directly.
        position = None
        if kind is QUEUED_KIND:
            last = (
                await self.db.execute(
                    select(func.max(PipelineJob.queue_position)).where(
                        and_(
                            PipelineJob.status == JobStatus.QUEUED.value,
                            PipelineJob.kind == QUEUED_KIND.value,
                        )
                    )
                )
            ).scalar()
            position = (last or 0) + 1

        job = PipelineJob(
            kind=kind.value,
            status=JobStatus.QUEUED.value,
            offer_id=offer_id,
            stages=snapshot,
            progress_percent=0,
            queue_position=position,
            enqueued_at=datetime.now(timezone.utc),
            created_by_user_id=owner_id,
            created_by_department=department,
        )
        self.db.add(job)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if kind is JobKind.OFFER_PIPELINE and offer_id is not None:
                # sqlstate 23503 (foreign_key_violation) means the offer row
                # itself is gone - e.g. `OfferController.delete_offer` won the
                # race against this insert - not that one is already active,
                # which is the partial unique index's own 23505
                # (unique_violation). Only the latter is "already running".
                sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
                if sqlstate == "23503":
                    raise OfferNotFoundError(offer_id) from exc
                raise OfferPipelineAlreadyRunningError(offer_id) from exc
            raise
        await self.db.refresh(job)

        if kind is QUEUED_KIND and offer_id is not None:
            # Written by the person who queued it, not by the offer's owner:
            # the job row takes the owner so that visibility follows the offer,
            # but the log is about who did the thing.
            await record_offer_queued(
                offer_id=offer_id,
                actor=user,
                position=job.queue_position,
                job_id=str(job.job_id),
            )
        return job

    async def get_job(self, job_id: uuid.UUID, user: User) -> PipelineJob:
        job = await self.db.get(PipelineJob, job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        if not can_see(user, job.created_by_user_id, job.created_by_department):
            raise JobForbiddenError(str(job_id))
        return job

    async def list_jobs(
        self,
        user: User,
        *,
        limit: int = 25,
        offset: int = 0,
        statuses: list[JobStatus] | None = None,
        kinds: list[JobKind] | None = None,
    ) -> list[PipelineJob]:
        """A page of the jobs this user may see, newest first.

        Offset as well as limit, because the jobs list is a screen of its own
        now rather than a strip of the last few; and filters, because "what
        failed today" is the question it gets opened with.
        """
        query = select(PipelineJob).order_by(PipelineJob.created_at.desc())
        scope = visibility_filter(
            user=user,
            owner_id_column=PipelineJob.created_by_user_id,
            department_column=PipelineJob.created_by_department,
        )
        if scope is not None:
            query = query.where(scope)
        if statuses:
            query = query.where(PipelineJob.status.in_([status.value for status in statuses]))
        if kinds:
            query = query.where(PipelineJob.kind.in_([kind.value for kind in kinds]))
        result = await self.db.execute(query.limit(limit).offset(offset))
        return list(result.scalars().all())

    async def request_cancel(self, job_id: uuid.UUID, user: User) -> PipelineJob:
        """Stops a job, whether it is running or still waiting.

        A waiting job has nothing to interrupt, so it is cancelled outright,
        here and now. Left to the flag it would have sat in the list until a
        slot freed, started, and then stopped at its first stage boundary - a
        cancel that visibly does nothing for twenty minutes and burns a slot
        anyway.

        A RUNNING job keeps the flag: the request may land on a worker that is
        not running it, and a stage torn down mid-write could leave half an
        offer behind. A stage boundary is the one place where stopping is
        always safe.
        """
        job = await self.get_job(job_id, user)
        if JobStatus(job.status).is_terminal:
            return job

        was_waiting = job.status == JobStatus.QUEUED.value
        job.cancel_requested = True
        if was_waiting:
            job.status = JobStatus.CANCELLED.value
            job.queue_position = None
            job.finished_at = datetime.now(timezone.utc)
            job.stages = skip_unfinished(job.stages)
            job.error_message = (
                "Taken out of the queue before it started. The files are still here - "
                "start the check again whenever you like."
            )
        await self.db.commit()
        await self.db.refresh(job)

        # Only an offer read earns a line in the offer's history. A cancelled
        # re-check has its own vocabulary in OfferEventKind and its own route
        # to write it from.
        #
        # After the commit, never before it: the log is written on its own
        # transaction so that a failure there cannot leave a reviewer's cancel
        # unsaved (helpers/offer_events.py). The runner deliberately writes no
        # second entry when the run actually stops - by then nobody knows who
        # asked.
        if job.kind == QUEUED_KIND.value and job.offer_id is not None:
            await record_read_cancelled(
                offer_id=job.offer_id,
                actor=user,
                was_waiting=was_waiting,
                job_id=str(job.job_id),
            )
        return job

    # --- the queue -----------------------------------------------------------

    async def get_queue_state(self, *, for_update: bool = False) -> QueueState:
        """The single control row, read by its constant id.

        Seeded by migration 0017, so this SELECTs rather than upserting: a row
        created on demand here would be a second place the defaults live, free
        to disagree with the migration's.
        """
        query = select(QueueState).where(QueueState.queue_state_id == QUEUE_STATE_ID)
        if for_update:
            # Every dispatcher and every reorder takes this lock first and in
            # the same order, which is what serialises them against each other
            # while making it impossible for them to deadlock.
            query = query.with_for_update()
        return (await self.db.execute(query)).scalar_one()

    async def set_paused(self, *, paused: bool, user: User) -> QueueState:
        """Pauses or resumes the queue, for everybody.

        Global rather than per-department on purpose: one runner serves the
        whole company, so "paused for my department only" would be a label on a
        queue that kept running. It lives in the database rather than in a
        module-level flag because of the deployment it exists for - pausing
        before a restart and finding the whole backlog released the moment the
        process comes back is exactly what makes a pause button untrustworthy.

        Nothing is stopped. A run already in flight finishes; pausing only
        stops the NEXT one starting, which is what the screen promises.
        """
        state = await self.get_queue_state(for_update=True)
        state.is_paused = paused
        # The check constraint requires a time whenever the flag is on, so the
        # banner can always say since when.
        state.paused_at = datetime.now(timezone.utc) if paused else None
        state.updated_by_user_id = user.id
        await self.db.commit()
        await self.db.refresh(state)
        return state

    async def set_parallel_slots(self, *, slots: int, user: User) -> QueueState:
        """How many offers may read at once, as a person set it.

        Refused rather than clamped outside the allowed range: the check
        constraint would refuse it anyway, and a silent clamp would leave the
        reviewer looking at a number they did not choose.
        """
        if not MIN_PARALLEL_SLOTS <= slots <= MAX_PARALLEL_SLOTS:
            raise ValueError(
                f"parallel_slots must be between {MIN_PARALLEL_SLOTS} and {MAX_PARALLEL_SLOTS}."
            )
        state = await self.get_queue_state(for_update=True)
        state.parallel_slots = slots
        state.updated_by_user_id = user.id
        await self.db.commit()
        await self.db.refresh(state)
        return state

    async def queue_skeleton(self) -> tuple[list[QueueSlot], list[QueueSlot]]:
        """Every running and waiting job in the installation, as (running, waiting).

        NOT department-scoped, and that is the point. One runner serves the
        whole company, so a department-scoped view of the ORDER would tell a
        reviewer their offer is next while three other departments sit ahead of
        it - the one number on this screen that has to be true. What comes back
        is ids, a kind and two timestamps; no offer content is read here, and
        the rows the caller actually hands out come from `queue_jobs` below,
        which is scoped like every other list.
        """
        rows = (
            await self.db.execute(
                select(
                    PipelineJob.job_id,
                    PipelineJob.kind,
                    PipelineJob.status,
                    PipelineJob.started_at,
                    PipelineJob.enqueued_at,
                )
                .where(
                    and_(
                        PipelineJob.status.in_(
                            [JobStatus.RUNNING.value, JobStatus.QUEUED.value]
                        ),
                        PipelineJob.kind == QUEUED_KIND.value,
                    )
                )
                .order_by(PipelineJob.queue_position, PipelineJob.enqueued_at)
            )
        ).all()
        slots = [QueueSlot(*row) for row in rows]
        return (
            [slot for slot in slots if slot.status == JobStatus.RUNNING.value],
            [slot for slot in slots if slot.status == JobStatus.QUEUED.value],
        )

    async def queue_jobs(self, user: User) -> list[PipelineJob]:
        """The running and waiting jobs this user may see, in queue order."""
        query = (
            select(PipelineJob)
            .where(
                and_(
                    PipelineJob.status.in_([JobStatus.RUNNING.value, JobStatus.QUEUED.value]),
                    PipelineJob.kind == QUEUED_KIND.value,
                )
            )
            .order_by(PipelineJob.queue_position, PipelineJob.enqueued_at)
        )
        scope = visibility_filter(
            user=user,
            owner_id_column=PipelineJob.created_by_user_id,
            department_column=PipelineJob.created_by_department,
        )
        if scope is not None:
            query = query.where(scope)
        return list((await self.db.execute(query)).scalars().all())

    async def median_run_seconds(self) -> dict[str, tuple[int, int]]:
        """Per kind, `(median seconds, how many runs it was measured over)`.

        Measured from `started_at`, never `created_at`: now that jobs really do
        wait, created_at -> finished_at is "wait plus read", so an estimate
        built on it would grow every time the queue got longer - the backlog
        predicting itself.

        Only succeeded runs count. A run that failed at the first stage took
        ninety seconds and one cancelled halfway took four minutes, and neither
        is how long reading an offer takes. And it is a median, not a mean, so
        the one scanned-Arabic offer that took an hour does not move every
        estimate after it.
        """
        duration = func.extract("epoch", PipelineJob.finished_at - PipelineJob.started_at)
        rows = (
            await self.db.execute(
                select(
                    PipelineJob.kind,
                    func.count().label("runs"),
                    func.percentile_cont(0.5).within_group(duration),
                )
                .where(
                    and_(
                        PipelineJob.status == JobStatus.SUCCEEDED.value,
                        PipelineJob.started_at.is_not(None),
                        PipelineJob.finished_at.is_not(None),
                    )
                )
                .group_by(PipelineJob.kind)
            )
        ).all()
        return {
            kind: (max(0, int(round(float(median)))), int(runs))
            for kind, runs, median in rows
            if median is not None
        }

    async def move_in_queue(self, job_id: uuid.UUID, position: int, user: User) -> None:
        """Moves a waiting job to `position` (1-based) and renumbers the list.

        Positions are renumbered densely rather than nudged, because the list a
        person dragged is the list they expect to see: gaps left behind by
        cancelled jobs would make the next drag land somewhere other than where
        they let go.

        The whole list is rewritten under the queue_state lock, so a dispatcher
        cannot take a job out from under the renumbering and a second reorder
        cannot interleave with this one.
        """
        job = await self.get_job(job_id, user)
        if job.status != JobStatus.QUEUED.value:
            raise JobNotWaitingError(str(job_id))

        await self.get_queue_state(for_update=True)
        waiting = list(
            (await self.db.execute(waiting_jobs_query().with_for_update())).scalars().all()
        )
        moving = next((row for row in waiting if row.job_id == job_id), None)
        if moving is None:
            # Claimed by the dispatcher between the two reads. It is running
            # now, which is a better outcome than the move.
            raise JobNotWaitingError(str(job_id))

        waiting.remove(moving)
        target = max(0, min(position - 1, len(waiting)))
        waiting.insert(target, moving)
        for index, row in enumerate(waiting, start=1):
            row.queue_position = index
        await self.db.commit()

    async def claim_jobs(self) -> list[PipelineJob]:
        """Takes as many waiting jobs as there are free slots, marked running.

        The whole decision is one transaction so that several API workers -
        each with a dispatcher of its own - cannot each decide independently
        that there is room for one more. The queue_state row is locked first
        (which serialises the claims), the running count is read from the
        database rather than from this process's memory (so another worker's
        runs count against the ceiling), and the waiting rows are taken with
        SKIP LOCKED (so two dispatchers never fight over the same row).

        Returns the rows it claimed, already RUNNING with `started_at` stamped,
        for the caller to actually run.
        """
        state = await self.get_queue_state(for_update=True)
        if state.is_paused:
            return []

        slots = effective_slots(
            configured_ceiling=get_settings().QUEUE_MAX_CONCURRENT_JOBS,
            parallel_slots=state.parallel_slots,
        )
        # Only offer reads count against the ceiling. A completeness re-check
        # holds no slot, so one running must not be able to hold the whole
        # queue still.
        running = (
            await self.db.execute(
                select(func.count())
                .select_from(PipelineJob)
                .where(
                    and_(
                        PipelineJob.status == JobStatus.RUNNING.value,
                        PipelineJob.kind == QUEUED_KIND.value,
                    )
                )
            )
        ).scalar_one()
        free = slots - int(running or 0)
        if free <= 0:
            return []

        claimed = list(
            (
                await self.db.execute(
                    waiting_jobs_query().limit(free).with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        now = datetime.now(timezone.utc)
        for job in claimed:
            job.status = JobStatus.RUNNING.value
            job.started_at = now
            # It is not waiting any more, and a position left behind would put
            # it back in the middle of the list if it were ever requeued.
            job.queue_position = None
        await self.db.commit()
        return claimed

    async def document_ids_for(self, offer_id: int | None) -> list[uuid.UUID]:
        """The documents a claimed job has to read, in upload order.

        Read at dispatch rather than carried over from the request that queued
        the job. That is what lets a waiting job survive a restart: its row
        plus its offer's documents describe it completely, so there is nothing
        left in memory to lose.
        """
        if offer_id is None:
            return []
        return list(
            (
                await self.db.execute(
                    select(Document.document_id)
                    .where(Document.offer_id == offer_id)
                    .order_by(Document.uploaded_at, Document.document_id)
                )
            )
            .scalars()
            .all()
        )

    async def offer_facts(self, offer_ids: list[int | None]) -> dict[int, OfferFacts]:
        """What the queue rows say about the offers behind them.

        Two hand-written queries for a whole page of jobs rather than one pair
        per row. There is no relationship() in this codebase and this is not
        the place to introduce one - a lazy load per row, on a list that polls
        every couple of seconds, is exactly the shape that gets found in
        production rather than in review.
        """
        wanted = sorted({offer_id for offer_id in offer_ids if offer_id is not None})
        if not wanted:
            return {}

        facts = {
            row.id: OfferFacts(
                offer_ref=row.offer_ref,
                rfq_number=row.rfq_number,
                # The typed name is what a person filed the offer under and
                # what they will look for; the extracted one is the fallback
                # for offers filed before it was asked for.
                project_name=row.project_name_entered or row.project_name_original,
                persisted=row.persisted_at is not None,
            )
            for row in (
                await self.db.execute(
                    select(
                        Offer.id,
                        Offer.offer_ref,
                        Offer.rfq_number,
                        Offer.project_name_entered,
                        Offer.project_name_original,
                        Offer.persisted_at,
                    ).where(Offer.id.in_(wanted))
                )
            ).all()
        }

        counts = (
            await self.db.execute(
                select(
                    Document.offer_id,
                    func.count().label("files"),
                    # Null until the parse stage fills it in, which is also
                    # when the UI first has a page count to show.
                    func.coalesce(func.sum(Document.page_count), 0).label("pages"),
                )
                .where(Document.offer_id.in_(wanted))
                .group_by(Document.offer_id)
            )
        ).all()
        for offer_id, files, pages in counts:
            known = facts.get(offer_id, OfferFacts())
            facts[offer_id] = OfferFacts(
                offer_ref=known.offer_ref,
                rfq_number=known.rfq_number,
                project_name=known.project_name,
                file_count=int(files),
                page_count=int(pages),
                persisted=known.persisted,
            )
        return facts

    async def display_names(self, user_ids: list[int | None]) -> dict[int, str]:
        """Who queued each job, for the design's "queued by Yara Kamal"."""
        wanted = sorted({user_id for user_id in user_ids if user_id is not None})
        if not wanted:
            return {}
        rows = (
            await self.db.execute(
                select(User.id, User.display_name, User.username).where(User.id.in_(wanted))
            )
        ).all()
        return {
            user_id: (display_name or username or "")
            for user_id, display_name, username in rows
        }

    async def reap_stale_jobs(self) -> int:
        """Settles the jobs a previous process left behind, at startup.

        Two situations that are only alike on the surface:

        * A RUNNING job died mid-read. A pipeline's worth of in-flight state
          went with the process, so it is failed explicitly - a row left
          `running` would be polled forever by a progress bar that can never
          move.
        * A QUEUED offer read never started. It holds nothing but its own row,
          and the documents it will read are in the database, so it STAYS
          QUEUED and the dispatcher picks it up in its original order. Failing
          it too, which is what this used to do, would mean every restart
          silently emptied the waiting list - and a queue that loses its
          backlog on a deploy is one nobody will trust with an afternoon's
          uploads.

        A re-check caught in the instant between being written and being
        started is the exception: nothing queues those, so nothing would ever
        pick it up again, and it is failed with the running ones.

        Returns the number of runs it had to fail.
        """
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(PipelineJob)
            .where(
                or_(
                    PipelineJob.status == JobStatus.RUNNING.value,
                    and_(
                        PipelineJob.status == JobStatus.QUEUED.value,
                        PipelineJob.kind != QUEUED_KIND.value,
                    ),
                )
            )
            .values(
                status=JobStatus.FAILED.value,
                error_message=(
                    "The server restarted while this run was in progress. Nothing was lost - "
                    "the uploaded files are still here - but the run has to be started again."
                ),
                finished_at=now,
                updated_at=now,
                queue_position=None,
            )
            .execution_options(synchronize_session=False)
        )
        # A job that was waiting keeps its place - but a NULL position sorts
        # unpredictably against the numbered ones, so anything queued without
        # one (a row from before 0017, or one whose claim was rolled back) is
        # given a place at the back, in arrival order.
        unplaced = list(
            (
                await self.db.execute(
                    waiting_jobs_query().where(PipelineJob.queue_position.is_(None))
                )
            )
            .scalars()
            .all()
        )
        if unplaced:
            last = (
                await self.db.execute(
                    select(func.max(PipelineJob.queue_position)).where(
                        and_(
                            PipelineJob.status == JobStatus.QUEUED.value,
                            PipelineJob.kind == QUEUED_KIND.value,
                        )
                    )
                )
            ).scalar() or 0
            for offset, job in enumerate(unplaced, start=1):
                job.queue_position = last + offset
        await self.db.commit()
        return result.rowcount or 0
