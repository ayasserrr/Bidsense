"""Who can see which offers and jobs.

One policy, kept in one place so it can be changed in one place. Today it is:
your own department, plus anything left over from before accounts existed;
admins see everything.

It has two forms that must never disagree: `visibility_filter` scopes a query
that lists rows, and `can_see` decides a single row. Route handlers call
neither directly. An id-addressed route declares one of the `visible_*`
dependencies at the bottom of this file, and
tests/test_department_separation.py fails for any offer-, document- or
job-scoped route that does not - a hand-written check per route is how several
endpoints once shipped with no check at all.
"""

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import BinaryExpression

from db import get_db
from dependencies import current_user
from models.db_schema import Document, Offer, PipelineJob, User
from models.enums import UserRole


def is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN.value


def is_pre_sign_in(owner_id: int | None, department: str | None) -> bool:
    """Whether a row predates sign-in, and so belongs to nobody.

    A NULL owner alone does not say that. The owner columns are ON DELETE SET
    NULL, so deleting an account nulls the owner of everything it created -
    and reading those rows as pre-sign-in would open that department's offers
    to the whole company. What only a pre-sign-in row has is the empty
    department it was migrated with. (A deleted account that had no department
    either is the one case this cannot tell apart.)
    """
    return owner_id is None and not department


def can_see(user: User, owner_id: int | None, department: str | None) -> bool:
    """Whether `user` may see one row owned by `owner_id` in `department`.

    The single-row twin of `visibility_filter`, rule for rule, so a row a list
    hides can never be opened by its id instead.
    """
    if is_admin(user):
        return True
    return is_pre_sign_in(owner_id, department) or (department or "") == (user.department or "")


def visibility_filter(
    *,
    user: User,
    owner_id_column: ColumnElement,
    department_column: ColumnElement,
) -> BinaryExpression | None:
    """The WHERE clause scoping a query to what `user` may see, or None for an
    admin (who sees everything, so no clause is added at all).

    Pre-sign-in rows are visible to everyone on purpose: hiding them from every
    non-admin would make the app look empty after the upgrade. That is a NULL
    owner AND an empty department, never a NULL owner alone - see
    `is_pre_sign_in`. An owner with no department in AD is a different case -
    those rows carry an empty department string and stay scoped to other
    people in the same (empty) department, rather than becoming visible to the
    whole company.
    """
    if is_admin(user):
        return None
    return or_(
        and_(owner_id_column.is_(None), department_column == ""),
        department_column == (user.department or ""),
    )


async def ensure_offer_visible(
    db: AsyncSession, offer_id: int, user: User, *, missing_ok: bool = False
) -> None:
    """404 for an offer that does not exist, 403 for one in another department.

    Reads the two ownership columns rather than the `Offer` entity. Loading the
    entity would put it in the session's identity map ahead of
    `UploadController.create_offer_version`, whose `SELECT ... FOR UPDATE`
    would then return that pre-lock copy - a stale `is_active_latest` - and let
    two concurrent uploads both version the same offer.
    """
    row = (
        await db.execute(
            select(Offer.created_by_user_id, Offer.created_by_department).where(
                Offer.id == offer_id
            )
        )
    ).one_or_none()
    if row is None:
        if missing_ok:
            return
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Offer {offer_id} not found."
        )
    if not can_see(user, row.created_by_user_id, row.created_by_department):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This offer belongs to another department.",
        )


async def ensure_document_visible(db: AsyncSession, document_id: uuid.UUID, user: User) -> None:
    """A document has no owner of its own: it is visible exactly when the offer
    it was uploaded under is. One with no offer at all is treated like an
    ownerless offer - the outer join reports it with a NULL owner."""
    row = (
        await db.execute(
            select(Offer.created_by_user_id, Offer.created_by_department)
            .select_from(Document)
            .outerjoin(Offer, Offer.id == Document.offer_id)
            .where(Document.document_id == document_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {document_id} not found."
        )
    if not can_see(user, row.created_by_user_id, row.created_by_department):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This document belongs to another department.",
        )


async def ensure_job_visible(db: AsyncSession, job_id: uuid.UUID, user: User) -> None:
    row = (
        await db.execute(
            select(PipelineJob.created_by_user_id, PipelineJob.created_by_department).where(
                PipelineJob.job_id == job_id
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    if not can_see(user, row.created_by_user_id, row.created_by_department):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This job belongs to another department.",
        )


# The route-facing form. Declared on the route (`dependencies=[Depends(...)]`)
# rather than called inside the handler, because a dependency is recorded on
# the route object - which is what lets a test prove that every id-addressed
# route has one, instead of trusting each handler to remember.


async def visible_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    await ensure_offer_visible(db, offer_id, user)


async def visible_offer_if_exists(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    """For idempotent deletes: an offer that is already gone is not an error,
    but one that still exists has to be in the caller's department."""
    await ensure_offer_visible(db, offer_id, user, missing_ok=True)


async def visible_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    await ensure_document_visible(db, document_id, user)


async def visible_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    await ensure_job_visible(db, job_id, user)
