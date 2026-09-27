from sqlalchemy import BigInteger, CheckConstraint, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.enums import EntityType

from .base import Base

ENTITY_TYPE_VALUES = tuple(entity_type.value for entity_type in EntityType)


class TechSpec(Base):
    __tablename__ = "tech_specs"
    __table_args__ = (
        CheckConstraint(f"entity_type IN {ENTITY_TYPE_VALUES}", name="ck_tech_specs_entity_type"),
        Index("ix_tech_specs_entity", "entity_type", "entity_id"),
    )

    spec_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    spec_group: Mapped[str] = mapped_column(Text, nullable=False)
    spec_name: Mapped[str] = mapped_column(Text, nullable=False)
    spec_value: Mapped[str] = mapped_column(Text, nullable=False)
    spec_unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
