"""Writing one line of an offer's activity log.

Three screens read `offer_events` and one module writes it: this one. Every
sentence a reviewer will ever read in the timeline is composed here, so that
"uploaded 3 files" reads the same on the dashboard, in the offers-list hover
and on the offer page, and so that changing the wording is one edit rather
than a search across the pipeline.

Two rules shape everything below.

**A recording must never cost a run.** A log line is not worth a twenty-minute
extraction, a reviewer's correction, or a cancel that does not take. So every
write goes through `record_event`, which swallows its own failures, and every
write opens its OWN session instead of joining the caller's. The second half
matters more than it looks: a failed INSERT on a shared session poisons that
session's transaction, and the caller's own commit - the persist, the
override - would fail afterwards with an error about something it never did.

Because the write is a separate transaction it must be issued AFTER the caller
has committed, never while the caller still holds a lock on the offer row. An
INSERT here takes a FOR KEY SHARE lock on `offers`, which conflicts with the
FOR UPDATE that `UploadController.create_offer_version` takes - recording from
inside that lock would be a deadlock that no database can see, because one
side of it is a Python `await`. `_RECORD_TIMEOUT_SECONDS` is the backstop for
that mistake: the write gives up and logs rather than hanging the caller
forever.

**A sentence is written when it happens, never derived afterwards.** "parsed 42
pages across 3 files" stops being true the moment the offer is re-run, and
rebuilding it later out of ids that may since have been renamed is how a log
starts lying. That is also why the count goes into `payload` as well as into
the sentence: a screen that wants the number can read it without re-parsing
English.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_, select

from db import async_session_factory
from models.db_schema import Offer, OfferEvent, User
from models.enums import OfferEventKind

logger = logging.getLogger(__name__)

# What an event nobody performed is shown as. The row itself stores an EMPTY
# actor name (see `models/db_schema/offer_event.py`); this name is put back on
# at read time, so that the one thing the column has to distinguish - a person
# whose account was later deleted, whose name is snapshotted, from the system,
# which never had one - stays distinguishable.
SYSTEM_ACTOR_NAME = "Bidsense"

# A write that cannot finish in this long is one that is blocked, not one that
# is slow: the table has two indexes and the row is a few hundred bytes. Giving
# up is the only safe answer, because the caller is a pipeline stage or a
# reviewer's request that has already done its real work.
_RECORD_TIMEOUT_SECONDS = 10.0


def actor_name(actor_display_name: str | None) -> str:
    """The name to show for an event, given the name stored on the row.

    Read from the snapshot rather than from `actor_user_id`, which is ON DELETE
    SET NULL: after an account is deleted its events still name the person, and
    keying "was this the system?" on the NULL id would quietly re-attribute
    everything they ever did to Bidsense.
    """
    return (actor_display_name or "").strip() or SYSTEM_ACTOR_NAME


def is_system_actor(actor_display_name: str | None) -> bool:
    return not (actor_display_name or "").strip()


def _snapshot_name(actor: User | None) -> str:
    """The name to store. Empty means the system did it.

    Falls back to the username for a directory profile with no display name -
    a real person with a blank `displayName` in AD is not the system, and
    showing them as Bidsense would be inventing an actor rather than reporting
    a missing one.
    """
    if actor is None:
        return ""
    return (getattr(actor, "display_name", "") or "").strip() or (
        getattr(actor, "username", "") or ""
    ).strip()


def format_duration(seconds: float | None) -> str:
    """A run's length as the design writes it: "48s", "6m 12s", "1h 04m"."""
    if seconds is None or seconds < 0:
        return "unknown"
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, remainder = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {remainder}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


# --- the one write -----------------------------------------------------------


async def record_event(
    *,
    offer_id: int,
    kind: OfferEventKind,
    detail: str,
    actor: User | None = None,
    payload: dict | None = None,
    db=None,
) -> bool:
    """Writes one event. Returns whether it was written, and NEVER raises.

    Call it after your own work is committed. A `False` here means the log
    missed a line, which is a thing to fix in the logs, not a thing to fail a
    run over - see this module's docstring.

    `db` is the one documented exception to "its own transaction": pass a
    session and the event is added to it for the caller to commit, so that the
    change and the line describing it land together. Archiving is the case it
    exists for - `offers` records WHEN an offer was archived and has no column
    for by whom, so the event IS the record of who did it, and an archived
    offer with nobody's name against it is worse than an archive that never
    happened. Nothing else should use it: the whole point of the default is
    that a failed log write cannot take a run or a correction down with it.

    Cancellation is the one exception that still gets through: `CancelledError`
    is not an `Exception`, and swallowing it here would let a job that a
    reviewer asked to stop carry on into its next stage.
    """
    event = OfferEvent(
        offer_id=offer_id,
        actor_user_id=getattr(actor, "id", None),
        actor_display_name=_snapshot_name(actor),
        kind=kind.value,
        detail=detail,
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )
    try:
        if db is not None:
            # No I/O and no commit - the caller's own commit writes it.
            db.add(event)
            return True
        return await asyncio.wait_for(_write(event), timeout=_RECORD_TIMEOUT_SECONDS)
    except Exception:
        logger.warning(
            "could not record %s on offer %s - the activity log will be missing this line",
            kind.value,
            offer_id,
            exc_info=True,
        )
        return False


async def _write(event: OfferEvent) -> bool:
    async with async_session_factory() as db:
        db.add(event)
        await db.commit()
    return True


async def _version_number(root_offer_id: int | None, offer_id: int) -> int | None:
    """Which version of its chain `offer_id` is, counted at the time it was
    uploaded - the "as version 3" the design puts in the log line.

    Read once and written into the sentence rather than recomputed on the
    offer page, because a chain grows: by the time anyone reads this line, the
    offer it is about may be version 3 of seven.
    """
    if root_offer_id is None:
        return None
    async with async_session_factory() as db:
        return (
            await db.execute(
                select(func.count())
                .select_from(Offer)
                .where(or_(Offer.id == root_offer_id, Offer.root_offer_id == root_offer_id))
                .where(Offer.id <= offer_id)
            )
        ).scalar_one()


# --- the vocabulary ----------------------------------------------------------
# One function per kind, so that every sentence in the product is visible on
# one screen and none of them is composed at a call site. The examples in the
# comments are the design's own wording.


async def record_offer_uploaded(*, offer_id: int, actor: User | None, file_count: int) -> bool:
    """"Mohanad Hassan uploaded 3 files"."""
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.OFFER_UPLOADED,
        detail=f"uploaded {_count(file_count, 'file')}",
        actor=actor,
        payload={"files": file_count},
    )


async def record_version_uploaded(
    *,
    offer_id: int,
    actor: User | None,
    file_count: int,
    parent_offer_id: int | None = None,
    root_offer_id: int | None = None,
) -> bool:
    """"Tarek Nour uploaded QT-4512-R1 as version 3".

    Recorded against the NEW version's own id, which is the offer the reviewer
    will open. The chain ids go into the payload so a screen can link back
    without another round trip.
    """
    version = None
    try:
        version = await _version_number(root_offer_id, offer_id)
    except Exception:
        # The sentence is still worth writing without the number.
        logger.warning("could not number the new version of offer %s", offer_id, exc_info=True)
    detail = f"uploaded {_count(file_count, 'file')}"
    detail += f" as version {version}" if version else " as a new version"
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.VERSION_UPLOADED,
        detail=detail,
        actor=actor,
        payload={
            "files": file_count,
            "version": version,
            "parent_offer_id": parent_offer_id,
            "root_offer_id": root_offer_id,
        },
    )


async def record_offer_queued(
    *,
    offer_id: int,
    actor: User | None,
    position: int | None = None,
    job_id: str | None = None,
) -> bool:
    """"Yara Kamal queued New Capital Admin Towers - Chillers".

    Written by whoever puts the job on the queue; `position` is where it landed
    when it was queued, not where it is now - the queue is reordered, and a
    position read back later would describe a different afternoon.
    """
    detail = "queued the check"
    if position is not None:
        detail += f" (position {position})"
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.OFFER_QUEUED,
        detail=detail,
        actor=actor,
        payload={"queue_position": position, "job_id": job_id},
    )


async def record_documents_parsed(*, offer_id: int, file_count: int, page_count: int) -> bool:
    """"Bidsense parsed 42 pages across 3 files"."""
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.DOCUMENTS_PARSED,
        detail=f"parsed {_count(page_count, 'page')} across {_count(file_count, 'file')}",
        payload={"pages": page_count, "files": file_count},
    )


async def record_offer_extracted(*, offer_id: int, item_count: int) -> bool:
    """"Bidsense extracted 34 line items"."""
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.OFFER_EXTRACTED,
        detail=f"extracted {_count(item_count, 'line item')}",
        payload={"items": item_count},
    )


async def record_findings_confirmed(
    *, offer_id: int, confirmed_count: int, checked_count: int
) -> bool:
    """"Bidsense confirmed 2 findings against the source"."""
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.FINDINGS_CONFIRMED,
        detail=f"confirmed {_count(confirmed_count, 'finding')} against the source",
        payload={"confirmed": confirmed_count, "checked": checked_count},
    )


async def record_read_finished(
    *, offer_id: int, seconds: float | None, job_id: str | None = None
) -> bool:
    """"Bidsense finished reading (6m 12s)".

    The duration is `started_at` -> `finished_at`, never `created_at` ->
    `finished_at`: now that jobs wait in a queue, the second one measures the
    size of the backlog as well as the length of the read.
    """
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.READ_FINISHED,
        detail=f"finished reading ({format_duration(seconds)})",
        payload={
            "seconds": round(seconds, 1) if seconds is not None else None,
            "job_id": job_id,
        },
    )


async def record_read_failed(
    *,
    offer_id: int,
    stage_label: str | None,
    seconds: float | None = None,
    job_id: str | None = None,
) -> bool:
    """"Bidsense could not finish reading - it stopped at Extracting the details".

    Names the stage rather than quoting the error: the error message is already
    on the job row, in a sentence written for the person who started the run,
    and a log entry that repeats a gateway timeout verbatim tells a reviewer
    reading it a week later nothing they can use.
    """
    detail = "could not finish reading"
    if stage_label:
        detail += f" - it stopped at {stage_label}"
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.READ_FAILED,
        detail=detail,
        payload={
            "stage": stage_label,
            "seconds": round(seconds, 1) if seconds is not None else None,
            "job_id": job_id,
        },
    )


async def record_read_cancelled(
    *,
    offer_id: int,
    actor: User | None,
    was_waiting: bool = False,
    job_id: str | None = None,
) -> bool:
    """"Tarek Nour stopped the read".

    Written where the person is known - the cancel REQUEST - rather than where
    the run actually stops, which happens later, at the next stage boundary, on
    whichever worker notices the flag and has no idea who set it. That is also
    why the runner does not write this line: it would be a second entry for one
    reviewer's single click.

    A job taken off the queue before it ever started reads differently from a
    run stopped mid-flight, and the difference matters to whoever finds the
    offer afterwards: one of them never touched the files.
    """
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.READ_CANCELLED,
        detail=(
            "took this offer out of the queue before it started"
            if was_waiting
            else "stopped the read"
        ),
        actor=actor,
        payload={"was_waiting": was_waiting, "job_id": job_id},
    )


async def record_project_name_mismatch(
    *, offer_id: int, entered: str | None, extracted: str | None
) -> bool:
    """"Bidsense read a different project name than the one filed".

    A note about the filing, never a failure: the EXTRACTED name is what
    `helpers/offer_versioning.check_same_offer_identity` compares, and it is
    left exactly as the document stated it.
    """
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.PROJECT_NAME_MISMATCH,
        detail=(
            f"read the project as '{extracted}', but this offer was filed as '{entered}'"
        ),
        payload={"entered": entered, "extracted": extracted},
    )


async def record_completeness_rechecked(*, offer_id: int, actor: User | None) -> bool:
    """"Tarek Nour re-ran the completeness check"."""
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.COMPLETENESS_RECHECKED,
        detail="re-ran the completeness check",
        actor=actor,
    )


async def record_summary_regenerated(*, offer_id: int, actor: User | None) -> bool:
    """"Yara Kamal regenerated the summary"."""
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.SUMMARY_REGENERATED,
        detail="regenerated the summary",
        actor=actor,
    )


async def record_completeness_overridden(
    *,
    offer_id: int,
    actor: User | None,
    requirement_label: str,
    requirement_code: str,
    verdict: str,
    evidence_filename: str,
    evidence_kind: str,
) -> bool:
    """"Yara Kamal corrected 'Warranty period' with an email".

    Says the evidence was attached, and names the file in the payload. The
    attachment is not decoration: an override without one is rejected by a
    CHECK constraint on the table, so an entry here that did not mention it
    would be describing something that cannot happen.
    """
    articles = {"email": "an email", "letter": "a letter", "revised_offer": "a revised offer"}
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.COMPLETENESS_OVERRIDDEN,
        detail=(
            f"corrected '{requirement_label}' with "
            f"{articles.get(evidence_kind, 'an attached document')}"
        ),
        actor=actor,
        payload={
            "requirement_code": requirement_code,
            "requirement_label": requirement_label,
            "verdict": verdict,
            "evidence_filename": evidence_filename,
            "evidence_kind": evidence_kind,
        },
    )


async def record_completeness_override_cleared(
    *, offer_id: int, actor: User | None, requirement_label: str, requirement_code: str
) -> bool:
    """"Yara Kamal removed the correction on 'Warranty period'"."""
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.COMPLETENESS_OVERRIDE_CLEARED,
        detail=f"removed the correction on '{requirement_label}'",
        actor=actor,
        payload={"requirement_code": requirement_code, "requirement_label": requirement_label},
    )


async def record_taxonomy_resorted(*, offer_id: int, resolved: int, unresolved: int) -> bool:
    """"Bidsense sorted 34 items into disciplines, 2 left uncategorised"."""
    detail = f"sorted {_count(resolved, 'item')} into disciplines"
    if unresolved:
        detail += f", {unresolved} left uncategorised"
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.TAXONOMY_RESORTED,
        detail=detail,
        payload={"resolved": resolved, "unresolved": unresolved},
    )


async def record_item_recategorised(
    *,
    offer_id: int,
    actor: User | None,
    item_id: int,
    description: str | None,
    node_label: str,
    discipline_label: str | None = None,
) -> bool:
    """"Yara Kamal moved 'Cable laying supervision' to Civil works"."""
    subject = (description or "").strip() or f"item #{item_id}"
    if len(subject) > 80:
        subject = subject[:77].rstrip() + "..."
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.ITEM_RECATEGORISED,
        detail=f"moved '{subject}' to {node_label}",
        actor=actor,
        payload={
            "item_id": item_id,
            "node_label": node_label,
            "discipline_label": discipline_label,
        },
    )


async def record_offer_archived(*, offer_id: int, actor: User | None, db=None) -> bool:
    """"Tarek Nour archived the offer".

    Takes `db` so the line lands in the same transaction as `archived_at` -
    see `record_event` for why this one does and the others do not.
    """
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.OFFER_ARCHIVED,
        detail="archived this offer",
        actor=actor,
        db=db,
    )


async def record_offer_unarchived(*, offer_id: int, actor: User | None, db=None) -> bool:
    """"Tarek Nour brought this offer back from the archive"."""
    return await record_event(
        offer_id=offer_id,
        kind=OfferEventKind.OFFER_UNARCHIVED,
        detail="brought this offer back from the archive",
        actor=actor,
        db=db,
    )
