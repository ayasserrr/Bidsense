from sqlalchemy import BigInteger, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_name: Mapped[str] = mapped_column(Text, nullable=False)
    project_aliases: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    client_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_aliases: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
