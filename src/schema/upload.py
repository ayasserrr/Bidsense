import uuid
from enum import Enum

from pydantic import BaseModel

from models.enums import ResponseSignal


class UploadItemStatus(str, Enum):
    SUCCESS = "success"
    DUPLICATE = "duplicate"
    ERROR = "error"


class UploadedFileResult(BaseModel):
    filename: str
    status: UploadItemStatus
    message: str
    document_id: uuid.UUID | None = None
    checksum: str | None = None


class UploadOfferResponse(BaseModel):
    signal: ResponseSignal
    offer_id: int
    results: list[UploadedFileResult]


class NewOfferVersionResponse(BaseModel):
    signal: ResponseSignal
    offer_id: int
    parent_offer_id: int
    root_offer_id: int
    results: list[UploadedFileResult]
