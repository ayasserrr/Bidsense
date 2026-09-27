import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from models.db_schema.queue_state import MAX_PARALLEL_SLOTS, MIN_PARALLEL_SLOTS
from models.enums import JobKind, JobStageStatus, JobStatus

from .upload import UploadedFileResult


class JobStage(BaseModel):
    """One row of the progress list, exactly as the UI draws it.

    The label lives here rather than in the frontend so a job of any kind
    describes itself - a full pipeline run and a single re-check have different
    stages, and the UI should not need to know which is which.
    """

    id: str
    label: str
    weight: int = 0
    status: JobStageStatus = JobStageStatus.PENDING
    detail: str | None = None

    # Stamped as the run goes, so the row itself answers where the ten minutes
    # went. Null on a stage that has not started, and on the upload stage, which
    # was already done inside the request that created the job.
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobOut(BaseModel):
    job_id: uuid.UUID
    kind: JobKind
    status: JobStatus
    offer_id: int | None = None

    # Enough of the offer to draw a row without a second request. A job whose
    # offer is a few seconds old has none of these yet: the reference and the
    # project name are read out of the documents, which is what the job is on
    # its way to do.
    offer_ref: str | None = None
    rfq_number: str | None = None
    project_name: str | None = None
    # The design's "3 files, 42 pages". Pages stay 0 until the parse stage has
    # counted them.
    file_count: int = 0
    page_count: int = 0

    stages: list[JobStage] = Field(default_factory=list)
    current_stage: str | None = None
    progress_percent: int = 0
    error_stage: str | None = None
    error_message: str | None = None
    cancel_requested: bool = False

    # Where this job sits in the waiting list, 1 for the one that starts next.
    # This is its RANK in the queue, not the raw sort key on the row, and it is
    # the whole company's queue: a job at 3 has two ahead of it even when they
    # belong to departments this user cannot see. Null unless the job is
    # waiting.
    queue_position: int | None = None

    created_at: datetime
    # When it joined the waiting list, and when it left it. `started_at` is the
    # one to measure a read with - created_at now includes the wait.
    enqueued_at: datetime | None = None
    started_at: datetime | None = None
    updated_at: datetime
    finished_at: datetime | None = None

    created_by_user_id: int | None = None
    # "queued by Yara Kamal". Empty for a job from before sign-in existed, or
    # one whose account has since been deleted.
    created_by_display_name: str = ""

    # True once the offer is safely written. The UI uses it to decide whether a
    # failure can still be recovered from or whether the work is already banked -
    # a completeness check failing after persist is a very different thing from
    # extraction failing before it.
    offer_persisted: bool = False


class QueueJob(JobOut):
    """A job as the queue screen draws it: the job, plus where it is in time."""

    # Seconds from now until this job is expected to START, and the same thing
    # as a timestamp for a client that would rather not do the arithmetic.
    # Null - not zero - when this installation has not finished enough runs to
    # say, or when the queue is paused. `estimate_note` on the queue says which.
    estimated_start_seconds: int | None = None
    estimated_start_at: datetime | None = None

    # Running jobs only: how long it has been reading, and how much of its
    # usual time it has left.
    elapsed_seconds: int | None = None
    estimated_remaining_seconds: int | None = None


class QueueOut(BaseModel):
    """What is reading, what is waiting, and whether the queue is running.

    One endpoint for the Queue screen, the rail card, the header pill and the
    upload screen's "goes into the queue" card, because four views of a queue
    that disagree with each other is worse than none.

    The lists hold only what this user's department may see. The COUNTS and the
    positions are the whole installation's, on purpose: one runner serves the
    whole company, so a department-scoped position would tell a reviewer their
    offer is next while three other departments sit ahead of it. No content of
    another department's offer is in here - only that it exists and is ahead.
    """

    is_paused: bool
    paused_at: datetime | None = None
    paused_by: str = ""

    # What a person set (1-3), what is actually enforced, and the ceiling the
    # deployment puts on it (QUEUE_MAX_CONCURRENT_JOBS). `slots` is the smaller
    # of the first and the third; when they differ, the UI should say so rather
    # than show a dial that does nothing.
    parallel_slots: int
    slots: int
    slot_ceiling: int

    running: list[QueueJob] = Field(default_factory=list)
    waiting: list[QueueJob] = Field(default_factory=list)

    # Company-wide. `hidden_*` is the part of each count this user cannot see,
    # so a screen can explain the difference between "3 waiting" and two rows.
    running_count: int = 0
    waiting_count: int = 0
    hidden_running_count: int = 0
    hidden_waiting_count: int = 0

    # What an offer queued right now would get: its position, and when it would
    # start. This is the upload screen's "Position 4 - starts in about 49 min",
    # answered before the person has committed to anything.
    next_position: int
    next_start_seconds: int | None = None
    next_start_at: datetime | None = None
    # When everything already queued is expected to be finished.
    finishes_at: datetime | None = None

    # Whether the numbers above mean anything yet, and one sentence saying why
    # if they do not. Estimates come from the median of THIS installation's own
    # finished runs; there is no built-in constant to fall back on.
    estimates_available: bool = False
    estimate_note: str = ""
    # Per job kind, how many finished runs the median was measured over.
    estimate_runs: dict[str, int] = Field(default_factory=dict)

    # The header pill, written once here rather than three times in the UI:
    # "1 reading - 3 waiting", "Queue paused - 3 waiting", "Nothing waiting".
    summary: str


class QueuePositionRequest(BaseModel):
    """Where to move a waiting job. 1 is the front of the whole queue."""

    position: int = Field(ge=1)


class QueueSlotsRequest(BaseModel):
    parallel_slots: int = Field(ge=MIN_PARALLEL_SLOTS, le=MAX_PARALLEL_SLOTS)


class StartOfferJobResponse(BaseModel):
    """The answer to an upload: what happened to each file, and the job that is
    now waiting to read them.

    The per-file results come back immediately rather than inside the job,
    because a rejected or duplicate file is something the reviewer should see at
    once - not twenty minutes later.
    """

    job_id: uuid.UUID
    offer_id: int
    results: list[UploadedFileResult] = Field(default_factory=list)
    parent_offer_id: int | None = None
    root_offer_id: int | None = None

    # Where the upload landed in the queue and when it is expected to start, so
    # the confirmation can say "queued as position 4, starts in about 49 min"
    # instead of implying the reading has already begun.
    queue_position: int | None = None
    estimated_start_seconds: int | None = None
    estimated_start_at: datetime | None = None
