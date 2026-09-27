from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Currency(Base):
    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str | None] = mapped_column(Text, nullable=True)
