from sqlalchemy import BigInteger, CheckConstraint, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.enums import EntryType

from .base import Base

ENTRY_TYPE_VALUES = tuple(entry_type.value for entry_type in EntryType)


class InclusionExclusion(Base):
    __tablename__ = "inclusions_exclusions"
    __table_args__ = (
        CheckConstraint("entity_type IN ('offer')", name="ck_inclusions_exclusions_entity_type"),
        CheckConstraint(
            f"entry_type IN {ENTRY_TYPE_VALUES}", name="ck_inclusions_exclusions_entry_type"
        ),
        Index("ix_inclusions_exclusions_entity", "entity_type", "entity_id"),
    )

    entry_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False, default="offer")
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
