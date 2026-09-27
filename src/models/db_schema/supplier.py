from sqlalchemy import BigInteger, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    supplier_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    supplier_aliases: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    is_sole_agent_for: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
