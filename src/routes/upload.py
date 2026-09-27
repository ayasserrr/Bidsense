import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from controllers import (
    DocumentValidationError,
    OfferAlreadyProcessedError,
    OfferNotFoundError,
    OfferNotLatestVersionError,
    UploadController,
)
from db import get_db
from helpers.offer_events import record_offer_uploaded, record_version_uploaded
from helpers.visibility import visible_offer, visible_offer_if_exists
from models.db_schema import Offer, User
from models.enums import ResponseSignal
from schema import NewOfferVersionResponse, UploadedFileResult, UploadItemStatus, UploadOfferResponse
from dependencies import current_user

logger = logging.getLogger(__name__)

upload_router = APIRouter(
    prefix="/api/v1/upload",
    tags=["upload"],
    dependencies=[Depends(current_user)],
)


async def _process_single_file(
    controller: UploadController, offer_id: int, file: UploadFile, user: User
) -> UploadedFileResult:
    """Validates, dedupes and persists one file. Raises `DocumentValidationError`
    on any expected validation/save failure - the caller turns that into an
    `error` result rather than aborting the whole batch."""
    filename = file.filename or "unknown"

    content, checksum, _size = await controller.validate_and_buffer(file)

    duplicate = await controller.find_duplicate(checksum, user, current_offer_id=offer_id)
    if duplicate is not None:
        existing, visible = duplicate
        return UploadedFileResult(
            filename=filename,
            status=UploadItemStatus.DUPLICATE,
            message=(
                f"This file was already uploaded before (offer #{existing.offer_id})."
                if visible
                else "This file was already uploaded before, to an offer in another department."
            ),
            checksum=checksum,
            document_id=existing.document_id if visible else None,
        )

    document = await controller.save_document(
        offer_id=offer_id,
        original_filename=filename,
        file_type=file.content_type or "application/octet-stream",
        checksum=checksum,
        content=content,
        commit=True,
    )
    return UploadedFileResult(
        filename=filename,
        status=UploadItemStatus.SUCCESS,
        message="Uploaded successfully.",
        checksum=checksum,
        document_id=document.document_id,
    )


@upload_router.post("", response_model=UploadOfferResponse)
async def upload_offer_documents(
    response: Response,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> UploadOfferResponse:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file must be provided.",
        )

    controller = UploadController(db)
    offer_id = await controller.create_offer(commit=True, owner=user)

    results: list[UploadedFileResult] = []
    for file in files:
        try:
            result = await _process_single_file(controller, offer_id, file, user)
        except DocumentValidationError as exc:
            result = UploadedFileResult(
                filename=file.filename or "unknown",
                status=UploadItemStatus.ERROR,
                message=exc.message,
            )
        except Exception:
            logger.exception(
                "Unexpected error while processing upload %r for offer %s",
                file.filename,
                offer_id,
            )
            result = UploadedFileResult(
                filename=file.filename or "unknown",
                status=UploadItemStatus.ERROR,
                message="Unexpected server error while processing this file.",
            )
        results.append(result)

    any_success = any(result.status == UploadItemStatus.SUCCESS for result in results)

    if not any_success:
        empty_offer = await db.get(Offer, offer_id)
        if empty_offer is not None:
            await db.delete(empty_offer)
            await db.commit()
        offer_dir = Path(controller.files_dir) / str(offer_id)
        shutil.rmtree(offer_dir, ignore_errors=True)
        # Not a 422: the per-file reasons are already fully described in
        # `results` (duplicate/error/message per file), and the frontend
        # relies on getting a normal response to read them - an error status
        # here would make the fetch client throw before it ever inspects the
        # body, hiding those reasons behind a generic "request failed".
        response.status_code = status.HTTP_200_OK
        return UploadOfferResponse(
            signal=ResponseSignal.FILE_UPLOADED_FAILED,
            offer_id=offer_id,
            results=results,
        )

    # The same first line of the offer's history that POST /jobs/offer
    # writes. Both doors into an offer have to write it, or which API a client
    # happened to use would decide whether the offer has a history at all.
    await record_offer_uploaded(
        offer_id=offer_id,
        actor=user,
        file_count=sum(1 for r in results if r.status == UploadItemStatus.SUCCESS),
    )

    response.status_code = status.HTTP_201_CREATED
    return UploadOfferResponse(
        signal=ResponseSignal.FILE_UPLOADED_SUCCESS,
        offer_id=offer_id,
        results=results,
    )


@upload_router.post(
    "/{offer_id}/new-version",
    response_model=NewOfferVersionResponse,
    dependencies=[Depends(visible_offer)],
)
async def upload_new_offer_version(
    offer_id: int,
    response: Response,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> NewOfferVersionResponse:
    """Uploads a new version of an already-existing offer rather than
    overwriting it: `offer_id` (the target) is left exactly as-is, and a
    brand-new `Offer` row is created for the new version, linked to it via
    `parent_offer_id` (and `root_offer_id`, which always points at the very
    first offer in the chain, so the whole chain can be fetched with one
    query later). Only the current tip of a chain can be versioned -
    `is_active_latest` flips from the target to the new row, so exactly one
    offer per chain is ever active at a time.

    This step only creates the new offer and saves its files, mirroring
    plain upload - parse/extract/sanity-check/verification/persist all run
    against the returned `offer_id` exactly like a brand-new offer. The
    check that the new document actually belongs to the same supplier/
    project as the offer being versioned happens later, at persist time,
    once extraction has actually determined what the new document says."""
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file must be provided.",
        )

    controller = UploadController(db)
    try:
        # Locks the target row for the check-and-flip - the sole
        # authoritative "is this really the latest version" check, so two
        # concurrent requests against the same offer can't both pass it.
        new_offer_id = await controller.create_offer_version(offer_id, commit=True, owner=user)
    except OfferNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer {offer_id} not found.",
        ) from exc
    except OfferNotLatestVersionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Offer {offer_id} is not the latest version of its chain - only the current "
                "latest version can be versioned. Upload against its current latest version instead."
            ),
        ) from exc

    target = await db.get(Offer, offer_id)
    root_offer_id = target.root_offer_id or offer_id

    results: list[UploadedFileResult] = []
    for file in files:
        try:
            result = await _process_single_file(controller, new_offer_id, file, user)
        except DocumentValidationError as exc:
            result = UploadedFileResult(
                filename=file.filename or "unknown",
                status=UploadItemStatus.ERROR,
                message=exc.message,
            )
        except Exception:
            logger.exception(
                "Unexpected error while processing new-version upload %r for offer %s",
                file.filename,
                new_offer_id,
            )
            result = UploadedFileResult(
                filename=file.filename or "unknown",
                status=UploadItemStatus.ERROR,
                message="Unexpected server error while processing this file.",
            )
        results.append(result)

    any_success = any(result.status == UploadItemStatus.SUCCESS for result in results)

    if not any_success:
        # Compensate: undo the speculative version - nothing should look
        # versioned if not a single file actually made it in. Safe to
        # delete the new offer outright since no Document row was ever
        # created for it on this path (only a SUCCESS result saves one).
        new_offer = await db.get(Offer, new_offer_id)
        if new_offer is not None:
            await db.delete(new_offer)
        target.is_active_latest = True
        await db.commit()
        offer_dir = Path(controller.files_dir) / str(new_offer_id)
        shutil.rmtree(offer_dir, ignore_errors=True)
        # See upload_offer_documents - results already carries the per-file
        # reason; a 2xx status lets the frontend actually read it.
        response.status_code = status.HTTP_200_OK
        return NewOfferVersionResponse(
            signal=ResponseSignal.FILE_UPLOADED_FAILED,
            offer_id=new_offer_id,
            parent_offer_id=offer_id,
            root_offer_id=root_offer_id,
            results=results,
        )

    await record_version_uploaded(
        offer_id=new_offer_id,
        actor=user,
        file_count=sum(1 for r in results if r.status == UploadItemStatus.SUCCESS),
        parent_offer_id=offer_id,
        root_offer_id=root_offer_id,
    )

    response.status_code = status.HTTP_201_CREATED
    return NewOfferVersionResponse(
        signal=ResponseSignal.FILE_UPLOADED_SUCCESS,
        offer_id=new_offer_id,
        parent_offer_id=offer_id,
        root_offer_id=root_offer_id,
        results=results,
    )


@upload_router.post(
    "/{offer_id}/abandon",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(visible_offer_if_exists)],
)
async def abandon_offer(offer_id: int, db: AsyncSession = Depends(get_db)) -> Response:
    """Called by the frontend when a pipeline run is abandoned before persist
    completes - a step failed, the user navigated away, or the tab was
    closed mid-run - so the offer/documents/files created so far don't sit
    around as orphaned partial data. Idempotent and safe to call more than
    once or on an offer that's already gone."""
    controller = UploadController(db)
    try:
        await controller.abandon_offer(offer_id)
    except OfferAlreadyProcessedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)