from datetime import datetime

from pydantic import BaseModel


class OfferEventOut(BaseModel):
    """One line of an offer's activity log, as the timeline draws it.

    The design splits every row into a bold `who` and a muted `what`, so this
    keeps them apart: `detail` is the sentence WITHOUT the actor's name, and
    `actor_name` is the name in front of it. Joining them here would make the
    dashboard's "Yara Kamal queued ..." impossible to render in two weights.
    """

    event_id: int
    offer_id: int

    # Deliberately a plain string and not `OfferEventKind`. The vocabulary
    # grows without a migration (see models/enums/OfferEventEnum.py), so a
    # server reading rows another version wrote can meet a kind this build has
    # never heard of - and validating it away would fail the whole page instead
    # of one row that already carries its own readable sentence.
    kind: str

    # NULL once the account is deleted; `actor_name` survives it, which is why
    # `is_system` is derived from the name and never from this.
    actor_user_id: int | None = None
    actor_name: str
    is_system: bool

    detail: str
    payload: dict | None = None
    created_at: datetime


class ActivityEventOut(OfferEventOut):
    """An event on the dashboard's company-wide timeline, where the reader has
    not opened an offer and needs to be told which one this is about.

    The design writes "confirmed 2 findings on QT-4471-R2" - the offer
    reference is appended by the screen rather than baked into `detail`, so the
    same event reads correctly on the offer page, where naming the offer again
    would be noise.
    """

    offer_ref: str | None = None
    project_name: str | None = None
    rfq_number: str | None = None


class OfferEventPage(BaseModel):
    """One page of a timeline, newest first.

    Keyset paging, not offset: the log grows at the top while somebody is
    scrolling it, and OFFSET would show them the same event twice. Hand the
    two `next_*` values back as `before`/`before_event_id` to get the next
    page; both are null when there is nothing older.
    """

    events: list[OfferEventOut]
    has_more: bool
    next_before: datetime | None = None
    next_before_event_id: int | None = None


class ActivityFeedPage(BaseModel):
    events: list[ActivityEventOut]
    has_more: bool
    next_before: datetime | None = None
    next_before_event_id: int | None = None
