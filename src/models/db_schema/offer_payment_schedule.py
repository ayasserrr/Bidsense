from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class OfferPaymentSchedule(Base):
    __tablename__ = "offer_payment_schedules"

    schedule_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    offer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which items this milestone's scope actually covers - resolved by
    # extraction from the document's own reference (a row-number range, a
    # named section) against the real offer_items.item_id once persisted;
    # null when scope_label is null (offer-wide) or the reference couldn't
    # be resolved to specific items.
    scope_item_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger), nullable=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_event: Mapped[str] = mapped_column(Text, nullable=False)
    percentage: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    description_original: Mapped[str] = mapped_column(Text, nullable=False)
