from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class OfferEvent(Base):
    """One line of an offer's history.

    Three screens read this table and they read it differently: the offer
    detail page wants one offer's events in order, the offers list wants the
    last few for a hover card, and the dashboard wants the newest across every
    offer the viewer may see. What none of them can do is reconstruct the past
    from the current state of the row - "parsed 42 pages across 3 files" stops
    being true the moment the offer is re-run - so an event is written when it
    happens and never derived afterwards.

    The event carries no owner of its own. It is visible exactly when its offer
    is, which means the dashboard timeline joins `offers` and applies the same
    `visibility_filter` as every other list. Copying the department onto this
    row would be a second copy of the policy, free to drift from the first.
    """

    __tablename__ = "offer_events"
    __table_args__ = (
        # One offer's log, newest first.
        Index("ix_offer_events_offer_id_created_at", "offer_id", text("created_at DESC")),
        # The dashboard's company-wide timeline.
        Index("ix_offer_events_created_at", text("created_at DESC")),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # CASCADE, like PipelineJob.offer_id: discarding an offer takes its history
    # with it rather than leaving events pointing at nothing.
    offer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False
    )

    # NULL is the system itself - the design's "Bidsense confirmed 2 findings".
    actor_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Snapshotted rather than joined. The FK above is ON DELETE SET NULL like
    # every other ownership column, so without this a deleted account would
    # turn that person's entries into system entries and quietly rewrite what
    # happened. Empty for an event nobody performed.
    actor_display_name: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )

    # Free text, not a constrained value: see models.enums.OfferEventKind for
    # why the vocabulary is in code instead of a check constraint.
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # The sentence a person reads. Written at the time, because rebuilding it
    # later out of ids that may since have been renamed or deleted is how a log
    # starts lying.
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # The same event's machine facts ({"pages": 42, "files": 3}), so a timeline
    # row can show its counts without re-querying five tables.
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
