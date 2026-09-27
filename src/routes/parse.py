import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from controllers import DocumentNotFoundError, ParseController
from db import get_db
from dependencies import current_user
from helpers import (
    DocumentParseFailedError,
    ParseTimeoutError,
    ParsingServiceUnavailableError,
    ParsingStudioError,
    UnsupportedDocumentError,
)
from helpers.visibility import visible_document
from models.enums import ResponseSignal
from schema import (
    DocumentPageDetail,
    DocumentPagesResponse,
    ParseDocumentResponse,
    ParsedPageSummary,
)

logger = logging.getLogger(__name__)

parse_router = APIRouter(
    prefix="/api/v1/parse",
    tags=["parse"],
    dependencies=[Depends(current_user)],
)


@parse_router.post(
    "/{document_id}",
    response_model=ParseDocumentResponse,
    dependencies=[Depends(visible_document)],
)
async def parse_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ParseDocumentResponse:
    controller = ParseController(db)
    try:
        document, parsed = await controller.parse_document(document_id, commit=True)
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found.",
        ) from None
    except (UnsupportedDocumentError, DocumentParseFailedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ParseTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        ) from exc
    except ParsingServiceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ParsingStudioError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception:
        logger.exception("Unexpected error while parsing document %s", document_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error while parsing this document.",
        ) from None

    return ParseDocumentResponse(
        signal=ResponseSignal.PARSE_SUCCESS,
        document_id=document.document_id,
        page_count=parsed.page_count,
        language=parsed.language,
        warning_count=len(parsed.warnings),
        pages=[
            ParsedPageSummary(
                page_number=page.page_number,
                extraction_method=page.extraction_method,
                has_text=bool(page.raw_text),
                table_count=len(page.raw_tables) if page.raw_tables else 0,
            )
            for page in parsed.pages
        ],
    )


@parse_router.get(
    "/{document_id}/pages",
    response_model=DocumentPagesResponse,
    dependencies=[Depends(visible_document)],
)
async def get_document_pages(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> DocumentPagesResponse:
    controller = ParseController(db)
    try:
        await controller.get_document(document_id)
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found.",
        ) from None

    pages = await controller.get_document_pages(document_id)
    return DocumentPagesResponse(
        document_id=document_id,
        pages=[DocumentPageDetail.model_validate(page) for page in pages],
    )