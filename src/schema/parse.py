import uuid

from pydantic import BaseModel, ConfigDict

from models.enums import ExtractionMethod, ResponseSignal


class ParsedPageSummary(BaseModel):
    page_number: int | None
    extraction_method: ExtractionMethod
    has_text: bool
    table_count: int


class ParseDocumentResponse(BaseModel):
    signal: ResponseSignal
    document_id: uuid.UUID
    page_count: int
    language: str | None
    warning_count: int
    pages: list[ParsedPageSummary]


class DocumentPageDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    page_id: uuid.UUID
    page_number: int | None
    raw_text: str | None
    raw_tables: list[dict] | None
    unit_location: dict
    extraction_method: ExtractionMethod


class DocumentPagesResponse(BaseModel):
    document_id: uuid.UUID
    pages: list[DocumentPageDetail]
