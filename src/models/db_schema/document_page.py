import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.enums import ExtractionMethod

from .base import Base

EXTRACTION_METHOD_VALUES = tuple(method.value for method in ExtractionMethod)


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        CheckConstraint(
            f"extraction_method IN {EXTRACTION_METHOD_VALUES}", name="ck_document_pages_extraction_method"
        ),
    )

    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_id"), nullable=False, index=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_location: Mapped[dict] = mapped_column(JSONB, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_tables: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    extraction_method: Mapped[str] = mapped_column(Text, nullable=False)
