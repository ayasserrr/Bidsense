from sqlalchemy import BigInteger, CheckConstraint, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .tech_spec import ENTITY_TYPE_VALUES


class IncludedFeature(Base):
    __tablename__ = "included_features"
    __table_args__ = (
        CheckConstraint(
            f"entity_type IN {ENTITY_TYPE_VALUES}", name="ck_included_features_entity_type"
        ),
        Index("ix_included_features_entity", "entity_type", "entity_id"),
    )

    feature_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    feature_text: Mapped[str] = mapped_column(Text, nullable=False)
    feature_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
