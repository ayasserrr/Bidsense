import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from controllers import (
    OfferIdentityMismatchError,
    OfferNotFoundError,
    PersistController,
    PersistIntegrityError,
)
from db import get_db
from models.enums import ResponseSignal
from schema import PersistOfferResponse, PersistRequest
from dependencies import current_user
from helpers.visibility import visible_offer

logger = logging.getLogger(__name__)

persist_router = APIRouter(
    prefix="/api/v1/persist",
    tags=["persist"],
    dependencies=[Depends(current_user)],
)


@persist_router.post(
    "/{offer_id}", response_model=PersistOfferResponse, dependencies=[Depends(visible_offer)]
)
async def persist_offer(
    offer_id: int,
    request: PersistRequest,
    db: AsyncSession = Depends(get_db),
) -> PersistOfferResponse:
    """Writes an already-extracted offer - along with its sanity-check and
    verification results, if available - into the real tables: resolves/
    creates the supplier and project, fills in the `offers` row created
    empty at upload time, and (re)creates every child row from the payload.
    Safe to call again for the same offer - every child table this stage
    owns is cleared and rewritten from scratch each time.

    The offer is written unconditionally regardless of what either check
    concluded - a 'needs_human_review' verification result is persisted
    exactly like a clean one, just labeled as such, never rejected."""
    controller = PersistController(db)

    try:
        await controller.persist_offer(
            offer_id, request.payload, request.sanity_check_result, request.verification_result
        )
    except OfferNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer {offer_id} not found.",
        ) from exc
    except OfferIdentityMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.reason,
        ) from exc
    except PersistIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception:
        logger.exception("Unexpected error while persisting offer %s", offer_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during persist.",
        ) from None

    full_offer = await controller.get_full_offer(offer_id)
    return PersistOfferResponse(
        signal=ResponseSignal.PERSIST_SUCCESS,
        offer_id=offer_id,
        offer=full_offer,
    )