import asyncio
import logging

from fastapi import Depends, APIRouter, HTTPException, status

from controllers import SanityCheckController
from helpers import get_settings
from models.enums import ResponseSignal
from schema import SanityCheckOfferResponse
from schema.offer import OfferExtractionPayload
from dependencies import governed_user
from helpers.visibility import visible_offer

logger = logging.getLogger(__name__)

sanity_check_router = APIRouter(
    prefix="/api/v1/sanity-check",
    tags=["sanity-check"],
    dependencies=[Depends(governed_user)],
)


@sanity_check_router.post(
    "/{offer_id}", response_model=SanityCheckOfferResponse, dependencies=[Depends(visible_offer)]
)
async def sanity_check_offer(
    offer_id: int,
    payload: OfferExtractionPayload,
) -> SanityCheckOfferResponse:
    """Reviews an already-extracted offer (the response body of a prior
    `POST /api/v1/extract/{offer_id}` call, passed back in as the request
    body here) for internal pricing/arithmetic consistency. `offer_id` is
    used for log correlation and for department scoping only - the offer's
    content is never re-fetched or re-extracted, so this stays fast and
    independent of the extract call. The scoping still matters: the model
    call is attributed to the caller, and it should not be spendable against
    an offer they cannot see."""
    settings = get_settings()
    controller = SanityCheckController()

    try:
        result = await asyncio.wait_for(
            controller.check_offer(payload, log_id=str(offer_id)),
            timeout=settings.EXTRACTION_TOTAL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Sanity check exceeded {settings.EXTRACTION_TOTAL_TIMEOUT_SECONDS}s timeout.",
        ) from None
    except Exception:
        logger.exception("Unexpected error while sanity-checking offer %s", offer_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during sanity check.",
        ) from None

    return SanityCheckOfferResponse(
        signal=ResponseSignal.SANITY_CHECK_COMPLETED,
        offer_id=offer_id,
        result=result,
    )