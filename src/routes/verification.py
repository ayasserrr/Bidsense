import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from controllers import VerificationController
from db import get_db
from helpers import get_settings
from models.enums import ResponseSignal
from schema import VerificationOfferResponse, VerificationRequest
from dependencies import governed_user
from helpers.visibility import visible_offer

logger = logging.getLogger(__name__)

verification_router = APIRouter(
    prefix="/api/v1/verification",
    tags=["verification"],
    dependencies=[Depends(governed_user)],
)


@verification_router.post(
    "/{offer_id}", response_model=VerificationOfferResponse, dependencies=[Depends(visible_offer)]
)
async def verify_offer(
    offer_id: int,
    request: VerificationRequest,
    db: AsyncSession = Depends(get_db),
) -> VerificationOfferResponse:
    """Independently re-checks the extraction (the response body of a prior
    `POST /api/v1/extract/{offer_id}` call) and the sanity check's findings
    (the response body of a prior `POST /api/v1/sanity-check/{offer_id}`
    call), both passed back in as the request body here, against the
    offer's original parsed source document fetched from `offer_id`. Skips
    the LLM call entirely (and returns immediately) when the sanity check
    found no findings to verify."""
    settings = get_settings()
    controller = VerificationController(db)

    try:
        result = await asyncio.wait_for(
            controller.verify_offer(
                offer_id,
                request.payload,
                request.sanity_check_result,
                log_id=str(offer_id),
            ),
            timeout=settings.EXTRACTION_TOTAL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Verification exceeded {settings.EXTRACTION_TOTAL_TIMEOUT_SECONDS}s timeout.",
        ) from None
    except Exception:
        logger.exception("Unexpected error while verifying offer %s", offer_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during verification.",
        ) from None

    return VerificationOfferResponse(
        signal=ResponseSignal.VERIFICATION_COMPLETED,
        offer_id=offer_id,
        result=result,
    )