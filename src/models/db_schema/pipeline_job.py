import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.enums import JobKind, JobStatus

from .base import Base

JOB_KIND_VALUES = tuple(kind.value for kind in JobKind)
JOB_STATUS_VALUES = tuple(status.value for status in JobStatus)


class PipelineJob(Base):
    """One backgrounded run of the pipeline (or of a single post-persist check).

    This row - not an in-memory task handle - is the source of truth for what a
    run is doing. That is what lets a reviewer close the tab during a
    twenty-minute extraction, come back later, and still see where it got to;
    it is also what lets a second uvicorn worker answer a status poll for a job
    it is not itself running.

    `cancel_requested` is a flag rather than a direct task cancellation for the
    same reason: the request to stop may arrive at a worker that does not hold
    the task, so the runner checks the flag at every stage boundary and stops
    itself.
    """

    __tablename__ = "pipeline_jobs"
    __table_args__ = (
        CheckConstraint(f"kind IN {JOB_KIND_VALUES}", name="ck_pipeline_jobs_kind"),
        CheckConstraint(f"status IN {JOB_STATUS_VALUES}", name="ck_pipeline_jobs_status"),
        # What the dispatcher reads to pick the next job, and what the queue
        # screen reads to draw the waiting list: `status = 'queued'` ordered by
        # position, then by arrival.
        Index("ix_pipeline_jobs_queue_order", "status", "queue_position", "enqueued_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=JobStatus.QUEUED.value, index=True
    )

    # CASCADE, not SET NULL: discarding an offer should take its run history
    # with it rather than leaving jobs pointing at nothing.
    offer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("offers.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # The progress list exactly as the UI renders it: one entry per stage with
    # its own status and a human-readable detail line ("chunk 2 of 5"). Kept as
    # JSON rather than a child table because it is only ever read and written
    # whole, and because a job's stage list depends on its kind.
    stages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    current_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- the queue ---------------------------------------------------------
    # Where this job sits in the waiting list. NULL means it is not waiting -
    # running, finished, cancelled, or never queued at all. Not unique: a
    # reorder rewrites several rows at once, and a unique constraint would
    # force a shuffle through temporary values for what is a display order.
    # Ties break on `enqueued_at`, so the order stays total even when two rows
    # briefly share a position.
    queue_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # When the job left the queue and actually began. Distinct from
    # `created_at` now that jobs really do wait: without it, created_at ->
    # finished_at quietly measures "wait + read", and both the elapsed pill on
    # the queue screen and the average read time on the dashboard would be
    # reporting the size of the backlog instead.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # The owner of the offer it runs on, copied at creation - not whoever
    # started it, so a run is visible exactly when its offer is and an admin
    # re-running another department's offer does not show that run to the
    # admin's own department. Only a job with no offer takes its starter's.
    # See JobController.create_job.
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_department: Mapped[str] = mapped_column(
        Text, nullable=False, default="", index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
