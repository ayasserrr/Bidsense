import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from controllers import (
    OfferController,
    OfferHasActiveJobError,
    OfferHasNewerVersionError,
    OfferNotFoundError,
    PersistController,
)
from controllers.OfferController import OfferListQuery, project_label_of
from db import get_db
from helpers.completeness_gaps import mandatory_gap_counts
from helpers.visibility import visible_offer
from models.db_schema import User
from schema import OfferFullDB, OfferSummary
from schema.offer_summary import (
    OfferDocumentsResponse,
    OfferFilterOptions,
    OfferListPage,
    OfferListStatus,
    OfferSortKey,
    SortDirection,
)
from dependencies import current_user

logger = logging.getLogger(__name__)

offers_router = APIRouter(
    prefix="/api/v1/offers",
    tags=["offers"],
    dependencies=[Depends(current_user)],
)


@offers_router.get("", response_model=OfferListPage)
async def list_offers(
    q: str | None = None,
    supplier_id: int | None = None,
    project: str | None = None,
    rfq: str | None = None,
    uploaded_by: int | None = None,
    uploaded_from: date | None = None,
    uploaded_to: date | None = None,
    # Sent as `status`, which is also the name of the FastAPI module this
    # file raises HTTPExceptions through. Aliased rather than renamed so the
    # query string reads like the control it serves without a parameter in
    # here shadowing `status.HTTP_404_NOT_FOUND` for whoever edits next.
    offer_status: OfferListStatus | None = Query(None, alias="status"),
    include_superseded: bool = False,
    sort: OfferSortKey = OfferSortKey.UPLOADED_AT,
    direction: SortDirection = SortDirection.DESC,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> OfferListPage:
    """One page of finished offers, newest first - only the active-latest
    version of each chain unless `include_superseded=true`, and only those
    belonging to the caller's department unless they are an admin.

    Archived offers are left out unless `offer_status` asks for them, and the
    page always reports `archived_matching` so the screen can say how many it
    is not showing rather than dropping them in silence.
    """
    controller = OfferController(db)
    return await controller.list_offers_page(
        OfferListQuery(
            q=q,
            supplier_id=supplier_id,
            project=project,
            rfq=rfq,
            uploaded_by_user_id=uploaded_by,
            uploaded_from=uploaded_from,
            uploaded_to=uploaded_to,
            status=offer_status,
            include_superseded=include_superseded,
            sort=sort,
            direction=direction,
            limit=limit,
            offset=offset,
        ),
        user=user,
    )


# Declared before `/{offer_id}`: FastAPI matches routes in order, and a path
# parameter typed `int` still matches the literal "filter-options" first and
# then fails to parse it, so the order here is what keeps this route reachable.
@offers_router.get("/filter-options", response_model=OfferFilterOptions)
async def get_offer_filter_options(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> OfferFilterOptions:
    """The filter bar's dropdowns - suppliers, projects, uploaders and RFQ
    numbers - built only from offers this caller may see. A roster read from
    the `users` table would name colleagues whose offers they cannot open."""
    controller = OfferController(db)
    return await controller.filter_options(user=user)


@offers_router.get(
    "/{offer_id}", response_model=OfferFullDB, dependencies=[Depends(visible_offer)]
)
async def get_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
) -> OfferFullDB:
    """Everything persisted for one offer, structured by table, plus the count
    of required terms it fails to state and who uploaded it - so the offer
    header can flag a completeness gap and name an owner without the reviewer
    scrolling to find either."""
    controller = PersistController(db)
    try:
        offer = await controller.get_full_offer(offer_id)
    except OfferNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer {offer_id} not found.",
        ) from exc
    offer.completeness_mandatory_gaps = (await mandatory_gap_counts(db, [offer_id])).get(offer_id)
    # Both stitched in here rather than read off the offer row: the display name
    # is a join (there is no relationship() in this schema), and the label is
    # the same rule the offers list applies, kept in one place so the header and
    # the row it was clicked from cannot print different project names.
    offer.created_by_display_name = await OfferController(db).uploader_display_name(offer_id)
    offer.project_label = project_label_of(
        offer.offer.project_name_entered, offer.offer.project_name_original
    )
    return offer


@offers_router.get(
    "/{offer_id}/versions",
    response_model=list[OfferSummary],
    dependencies=[Depends(visible_offer)],
)
async def get_offer_versions(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> list[OfferSummary]:
    """Every offer in `offer_id`'s version chain that the caller may see,
    oldest first."""
    controller = OfferController(db)
    try:
        return await controller.get_offer_versions(offer_id, user=user)
    except OfferNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer {offer_id} not found.",
        ) from exc


@offers_router.get(
    "/{offer_id}/documents",
    response_model=OfferDocumentsResponse,
    dependencies=[Depends(visible_offer)],
)
async def get_offer_documents(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
) -> OfferDocumentsResponse:
    """The files this offer was read from, with page counts, sizes and how far
    each one got through parsing - the "3 files, 42 pages" line, and what is
    behind it."""
    controller = OfferController(db)
    return await controller.list_offer_documents(offer_id)


@offers_router.post(
    "/{offer_id}/archive",
    response_model=OfferSummary,
    dependencies=[Depends(visible_offer)],
)
async def archive_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> OfferSummary:
    """Take an offer out of the working list.

    Not a delete and not a lock: it stays readable, comparable and re-runnable,
    and every other version of its chain is untouched. Anyone who can open the
    offer can archive it - the activity log records who did, and unarchiving is
    one call away. Archiving an already-archived offer is accepted and changes
    nothing.
    """
    return await _set_archived(db, offer_id, archived=True, user=user)


@offers_router.post(
    "/{offer_id}/unarchive",
    response_model=OfferSummary,
    dependencies=[Depends(visible_offer)],
)
async def unarchive_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> OfferSummary:
    """Put an archived offer back in the working list."""
    return await _set_archived(db, offer_id, archived=False, user=user)


async def _set_archived(
    db: AsyncSession, offer_id: int, *, archived: bool, user: User
) -> OfferSummary:
    """Both directions answer with the updated list row, so the screen replaces
    the row it has instead of guessing what changed."""
    try:
        return await OfferController(db).set_archived(offer_id, archived=archived, user=user)
    except OfferNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer {offer_id} not found.",
        ) from exc


@offers_router.delete(
    "/{offer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(visible_offer)],
)
async def delete_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    """Permanently and irreversibly removes an offer, everything persisted
    under it, and its files on disk.

    Not another flavor of archive: there is no undo. Anyone who can already
    see the offer may delete it - the same permission level as archiving,
    with no extra admin gate. Refused with 409 when another offer's
    `parent_offer_id` still points at this one (delete the newer version
    first) or when a read is queued or running against this offer right now
    (wait for it to finish or cancel it first).
    """
    try:
        await OfferController(db).delete_offer(offer_id, user=user)
    except OfferNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer {offer_id} not found.",
        ) from exc
    except OfferHasNewerVersionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OfferHasActiveJobError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
