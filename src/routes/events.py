import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from dependencies import current_user
from helpers.offer_events import actor_name, is_system_actor
from helpers.visibility import visibility_filter, visible_offer
from models.db_schema import Offer, OfferEvent, User
from schema.events import ActivityEventOut, ActivityFeedPage, OfferEventOut, OfferEventPage

logger = logging.getLogger(__name__)

events_router = APIRouter(
    prefix="/api/v1",
    tags=["events"],
    dependencies=[Depends(current_user)],
)

# A timeline is read a screenful at a time. The ceiling exists because the feed
# is a hand-join over every offer the caller may see, and "give me everything"
# is not a request this endpoint should be able to serve by accident.
MAX_PAGE = 200


def _clamp(limit: int, default: int) -> int:
    if limit <= 0:
        return default
    return min(limit, MAX_PAGE)


def _older_than(before: datetime | None, before_event_id: int | None):
    """The keyset predicate: everything strictly older than the cursor.

    Ordering is (created_at DESC, event_id DESC), so the cursor has to be the
    same pair - two events written in the same millisecond are ordinary here (a
    stage that finishes and a run that ends), and a cursor on the timestamp
    alone would either repeat them across pages or skip them.
    """
    if before is None:
        return None
    if before_event_id is None:
        return OfferEvent.created_at < before
    return tuple_(OfferEvent.created_at, OfferEvent.event_id) < tuple_(before, before_event_id)


def _to_out(event: OfferEvent) -> OfferEventOut:
    return OfferEventOut(
        event_id=event.event_id,
        offer_id=event.offer_id,
        kind=event.kind,
        actor_user_id=event.actor_user_id,
        actor_name=actor_name(event.actor_display_name),
        is_system=is_system_actor(event.actor_display_name),
        detail=event.detail,
        payload=event.payload,
        created_at=event.created_at,
    )


def _split_page(rows: list, limit: int) -> tuple[list, bool]:
    """One row more than asked for is fetched, purely to answer "is there more"
    without a second COUNT over the same join."""
    if len(rows) > limit:
        return rows[:limit], True
    return rows, False


@events_router.get(
    "/offers/{offer_id}/events",
    response_model=OfferEventPage,
    dependencies=[Depends(visible_offer)],
)
async def list_offer_events(
    offer_id: int,
    limit: int = 50,
    before: datetime | None = None,
    before_event_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> OfferEventPage:
    """One offer's activity log, newest first.

    Two screens read this: the offer page's Activity log section, and the
    offers list's hover card, which asks for the last few with `limit=4`.

    Scoped by `visible_offer` and nothing else - `offer_events` carries no
    owner columns on purpose, because an event is visible exactly when its
    offer is, and a second copy of the department rule here would be free to
    drift from the first.
    """
    size = _clamp(limit, 50)
    query = (
        select(OfferEvent)
        .where(OfferEvent.offer_id == offer_id)
        .order_by(OfferEvent.created_at.desc(), OfferEvent.event_id.desc())
        .limit(size + 1)
    )
    cursor = _older_than(before, before_event_id)
    if cursor is not None:
        query = query.where(cursor)

    rows, has_more = _split_page(list((await db.execute(query)).scalars().all()), size)
    events = [_to_out(event) for event in rows]
    return OfferEventPage(
        events=events,
        has_more=has_more,
        next_before=events[-1].created_at if has_more else None,
        next_before_event_id=events[-1].event_id if has_more else None,
    )


@events_router.get("/events/recent", response_model=ActivityFeedPage)
async def recent_events(
    limit: int = 20,
    before: datetime | None = None,
    before_event_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> ActivityFeedPage:
    """The dashboard's Activity timeline: what happened across every offer the
    caller may see, newest first.

    The join to `offers` is what scopes it - hand-written, like every join in
    this codebase, and carrying the same `visibility_filter` the offers list
    does, so the timeline can never mention an offer the reader could not open.
    An inner join deliberately: an event whose offer was discarded no longer
    exists (the FK cascades), so there is nothing to fall through to.
    """
    size = _clamp(limit, 20)
    query = (
        select(
            OfferEvent,
            Offer.offer_ref,
            Offer.project_name_entered,
            Offer.project_name_original,
            Offer.rfq_number,
        )
        .join(Offer, Offer.id == OfferEvent.offer_id)
        .order_by(OfferEvent.created_at.desc(), OfferEvent.event_id.desc())
        .limit(size + 1)
    )
    scope = visibility_filter(
        user=user,
        owner_id_column=Offer.created_by_user_id,
        department_column=Offer.created_by_department,
    )
    if scope is not None:
        query = query.where(scope)
    cursor = _older_than(before, before_event_id)
    if cursor is not None:
        query = query.where(cursor)

    rows, has_more = _split_page(list((await db.execute(query)).all()), size)
    events = [
        ActivityEventOut(
            **_to_out(event).model_dump(),
            offer_ref=offer_ref,
            # The typed name wins for display - it is the one a person chose,
            # and the one the rest of the app groups by. The extracted name is
            # only the fallback here; it stays the name version identity is
            # decided on.
            project_name=project_name_entered or project_name_original,
            rfq_number=rfq_number,
        )
        for event, offer_ref, project_name_entered, project_name_original, rfq_number in rows
    ]
    return ActivityFeedPage(
        events=events,
        has_more=has_more,
        next_before=events[-1].created_at if has_more else None,
        next_before_event_id=events[-1].event_id if has_more else None,
    )
