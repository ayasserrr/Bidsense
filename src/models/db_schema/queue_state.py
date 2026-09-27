from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

# The only value `queue_state_id` may take. Callers read and write this row by
# it rather than by "the first row there is".
QUEUE_STATE_ID = 1

# What the client asked for: offers read one to three at a time.
MIN_PARALLEL_SLOTS = 1
MAX_PARALLEL_SLOTS = 3


class QueueState(Base):
    """Whether the queue is running, and how many offers it reads at once.

    One row, and the check constraint is what keeps it that way. This is a
    table rather than a module-level flag for two reasons, both of which have
    to hold: a pause must survive a restart - pausing the queue before a
    deployment and then finding the whole backlog released is the exact failure
    that makes a pause button untrustworthy - and every uvicorn worker has to
    see the same answer, not just the one that happened to take the request.

    It deliberately does not record what is currently running. That is the
    `pipeline_jobs` rows' own business, and a second copy of it here would be
    one more thing to be wrong after a crash.
    """

    __tablename__ = "queue_state"
    __table_args__ = (
        CheckConstraint(f"queue_state_id = {QUEUE_STATE_ID}", name="ck_queue_state_singleton"),
        CheckConstraint(
            f"parallel_slots BETWEEN {MIN_PARALLEL_SLOTS} AND {MAX_PARALLEL_SLOTS}",
            name="ck_queue_state_parallel_slots",
        ),
        # A paused queue always knows since when, so the banner can say it.
        CheckConstraint(
            "is_paused = false OR paused_at IS NOT NULL", name="ck_queue_state_paused_at"
        ),
    )

    queue_state_id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=False, default=QUEUE_STATE_ID
    )
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # In the database rather than in config because it is a control a
    # signed-in person turns. The LLM transport enforces its own concurrency
    # ceiling underneath this regardless, so raising it cannot overload the
    # gateway - it only decides how many offers are in flight.
    parallel_slots: Mapped[int] = mapped_column(
        Integer, nullable=False, default=MIN_PARALLEL_SLOTS
    )

    updated_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
