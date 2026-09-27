import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from controllers import DocumentHasNoParsedPagesError, ExtractController
from db import get_db
from helpers import LlmCallError, LlmValidationError, get_settings
from helpers.visibility import visible_offer
from models.enums import ResponseSignal
from schema import ExtractOfferResponse
from dependencies import governed_user

logger = logging.getLogger(__name__)

extract_router = APIRouter(
    prefix="/api/v1/extract",
    tags=["extract"],
    dependencies=[Depends(governed_user)],
)


@extract_router.post(
    "/{offer_id}", response_model=ExtractOfferResponse, dependencies=[Depends(visible_offer)]
)
async def extract_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
) -> ExtractOfferResponse:
    settings = get_settings()
    controller = ExtractController(db)
    documents = await controller.get_offer_documents(offer_id)

    try:
        payload = await asyncio.wait_for(
            controller.extract_offer(documents),
            timeout=settings.EXTRACTION_TOTAL_TIMEOUT_SECONDS,
        )
    except DocumentHasNoParsedPagesError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No parsed pages found for offer {offer_id} - parse its documents "
                "before extracting."
            ),
        ) from exc
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Extraction exceeded {settings.EXTRACTION_TOTAL_TIMEOUT_SECONDS}s timeout.",
        ) from None
    except (LlmValidationError, LlmCallError) as exc:
        logger.error("Extraction failed for offer %s: %s", offer_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Extraction failed - the extraction model did not return a usable result.",
        ) from exc
    except Exception:
        logger.exception("Unexpected error while extracting offer %s", offer_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during extraction.",
        ) from None

    return ExtractOfferResponse(
        signal=ResponseSignal.EXTRACTION_SUCCESS,
        offer_id=offer_id,
        payload=payload,
    )