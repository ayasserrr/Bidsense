import logging
import shutil
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import ColumnElement, and_, delete, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from helpers.completeness_gaps import mandatory_gap_counts
from helpers.offer_events import record_offer_archived, record_offer_unarchived
from helpers.polymorphic_entities import delete_polymorphic_offer_rows
from helpers.visibility import visibility_filter
from models.db_schema import Document, DocumentPage, Offer, PipelineJob, Supplier, User
from models.enums import ExtractionMethod, JobKind, JobStatus, SanityCheckStatus, VerificationStatus
from schema.offer_summary import (
    DocumentParseState,
    OfferDocumentOut,
    OfferDocumentsResponse,
    OfferFilterOptions,
    OfferListPage,
    OfferListStatus,
    OfferReviewStatus,
    OfferSortKey,
    OfferSummary,
    ProjectFilterOption,
    RfqFilterOption,
    SortDirection,
    SupplierFilterOption,
    UploaderFilterOption,
)

from .BaseController import BaseController
from .PersistController import OfferNotFoundError

logger = logging.getLogger(__name__)


class OfferHasNewerVersionError(Exception):
    """Raised when trying to delete an offer that is not the current tip of
    its own version chain - some other offer's `parent_offer_id` still points
    at it. Deleting it out from under that pointer would leave the newer
    version referencing an offer that no longer exists, so this refuses
    outright rather than nulling the link or cascading further than asked."""

    def __init__(self, offer_id: int, child_offer_id: int):
        self.offer_id = offer_id
        self.child_offer_id = child_offer_id
        super().__init__(
            f"Offer {offer_id} has a newer version (offer {child_offer_id}). "
            "Delete the newer version first."
        )


class OfferHasActiveJobError(Exception):
    """Raised when trying to delete an offer with a read queued or running
    against it right now. Deleting the row out from under that job would let
    a task that is actively reading or writing it fail on rows that vanished
    mid-run instead of on a clean, reportable error."""

    def __init__(self, offer_id: int):
        self.offer_id = offer_id
        super().__init__(
            f"Offer {offer_id} has a read queued or in progress. Wait for it "
            "to finish or cancel it before deleting."
        )


# The offers list is the first screen a reviewer opens, and it has no "load
# more" today. A page is small enough to render at once and big enough that
# nobody pages through a normal week's uploads; the ceiling exists so a
# hand-written `limit=100000` cannot ask the server to build the whole table.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


# -- the derived values three screens have to agree about ---------------------


def project_label_of(project_name_entered: str | None, project_name_original: str | None) -> str | None:
    """What to print in a Project column, given the two names an offer carries.

    The typed name wins because it is the one a person chose for filing, and
    grouping by it is what the upload form promises. The extracted name is the
    fallback for every offer filed before there was a field to type into - and
    it is never overwritten, because `helpers.offer_versioning
    .check_same_offer_identity` compares THAT one to decide whether a new
    upload is a new version of this offer.
    """
    entered = (project_name_entered or "").strip()
    return entered or project_name_original


def project_label_column() -> ColumnElement:
    """The SQL twin of `project_label_of`, for the Project filter and sort."""
    return func.coalesce(func.nullif(Offer.project_name_entered, ""), Offer.project_name_original)


def uploader_name_column() -> ColumnElement:
    """The uploader's name for a list row.

    Falls back to the username because `users.display_name` defaults to empty
    and the directory does not always fill it - a blank cell in the Uploaded
    column reads as "nobody uploaded this", which is exactly what a
    pre-sign-in offer means and this is not.
    """
    return func.coalesce(func.nullif(User.display_name, ""), User.username)


def review_status_of(
    *, sanity_check_status: str | None, verification_status: str | None
) -> OfferReviewStatus:
    """One offer's Status word, from the two columns the pipeline writes.

    The rule the offers list used to apply in the browser. It is here because
    the Status filter needs the same rule in SQL (`review_status_clause`), and
    a filter that disagrees with the badge it filters on is worse than no
    filter at all.
    """
    if verification_status == VerificationStatus.NEEDS_HUMAN_REVIEW.value:
        return OfferReviewStatus.NEEDS_REVIEW
    if verification_status is None:
        # Verification never ran, so the sanity check is the last word there is.
        if sanity_check_status == SanityCheckStatus.NEEDS_REVIEW.value:
            return OfferReviewStatus.NEEDS_REVIEW
        if sanity_check_status is None:
            return OfferReviewStatus.UNCHECKED
    return OfferReviewStatus.CLEAR


def review_status_clause(status: OfferReviewStatus) -> ColumnElement:
    """The SQL twin of `review_status_of`, as a WHERE clause.

    Both columns are read through COALESCE rather than compared directly. In
    SQL `verification_status = 'needs_human_review'` is NULL - not false - for
    an offer that never reached verification, so `NOT (that OR ...)` would be
    NULL too and the "clear" filter would silently drop every offer whose
    verification status is null: most of them.
    """
    verification = func.coalesce(Offer.verification_status, "")
    sanity = func.coalesce(Offer.sanity_check_status, "")
    needs_review = or_(
        verification == VerificationStatus.NEEDS_HUMAN_REVIEW.value,
        and_(verification == "", sanity == SanityCheckStatus.NEEDS_REVIEW.value),
    )
    unchecked = and_(verification == "", sanity == "")
    if status is OfferReviewStatus.NEEDS_REVIEW:
        return needs_review
    if status is OfferReviewStatus.UNCHECKED:
        return unchecked
    return and_(not_(needs_review), not_(unchecked))


def like_pattern(term: str) -> str:
    """`term` as a contains-pattern, with the wildcards a person typed defused.

    Backslash is PostgreSQL's default LIKE escape, so escaping by hand here
    keeps the comparison a plain ILIKE with no ESCAPE clause - which is what
    the trigram indexes on these columns are built to serve.
    """
    escaped = term.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_clause(term: str) -> ColumnElement:
    """The one search box, over the five things people search offers by.

    Written as a plain ILIKE with no lower() around the column on purpose:
    where pg_trgm is installed these five columns carry GIN trigram indexes
    that match this shape exactly, and pg_trgm folds case itself. Wrapping the
    column would throw the index away for no gain. Where the extension is
    absent the same query still works, unindexed.
    """
    pattern = like_pattern(term)
    return or_(
        Offer.offer_ref.ilike(pattern),
        Offer.rfq_number.ilike(pattern),
        Offer.project_name_entered.ilike(pattern),
        Offer.project_name_original.ilike(pattern),
        Supplier.supplier_name.ilike(pattern),
    )


def parse_state_of(page_rows: int | None, failed_rows: int | None) -> DocumentParseState:
    """How far one document got, from its page rows.

    A document with no page rows has not been parsed - which is not the same as
    a document whose every page failed, and the file list has to be able to say
    which. A partly-failed document is the one worth naming: it has text, so
    the offer reads as complete, and the missing term may simply be on the page
    nobody could read.
    """
    pages = page_rows or 0
    failed = failed_rows or 0
    if pages == 0:
        return DocumentParseState.NOT_PARSED
    if failed == 0:
        return DocumentParseState.PARSED
    if failed >= pages:
        return DocumentParseState.FAILED
    return DocumentParseState.PARTLY_FAILED


@dataclass(frozen=True)
class OfferListQuery:
    """Everything the offers screen's filter bar can ask for.

    One object rather than thirteen parameters, so the route reads as the form
    it serves and the controller's shape does not change every time a control
    is added.
    """

    q: str | None = None
    supplier_id: int | None = None
    # The Project dropdown sends back a label, not an id: an offer can name a
    # project the reconciliation stage never matched to a `projects` row, and
    # filtering by id would hide exactly those.
    project: str | None = None
    # A contains-match, like the design's RFQ box - people type "RFQ-2026-" to
    # see the year.
    rfq: str | None = None
    uploaded_by_user_id: int | None = None
    # Whole days, inclusive at both ends, in UTC - which is what created_at is
    # stamped in.
    uploaded_from: date | None = None
    uploaded_to: date | None = None
    status: OfferListStatus | None = None
    include_superseded: bool = False
    sort: OfferSortKey = OfferSortKey.UPLOADED_AT
    direction: SortDirection = SortDirection.DESC
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0


class OfferController(BaseController):
    """Read-only queries over the `offers` table for browsing/discovery -
    listing offers, one offer's version chain, one offer's files - plus the one
    thing the list can change about an offer: archiving it. The single-offer
    full-detail read (`GET /api/v1/offers/{offer_id}`) reuses
    `PersistController.get_full_offer` directly rather than duplicating it
    here."""

    def __init__(self, db: AsyncSession):
        super().__init__()
        self.db = db

    @staticmethod
    def _to_summary(
        offer: Offer,
        supplier_name: str | None,
        uploader_name: str | None,
        version_count: int,
        completeness_gaps: int | None = None,
    ) -> OfferSummary:
        return OfferSummary(
            id=offer.id,
            offer_ref=offer.offer_ref,
            rfq_number=offer.rfq_number,
            project_name_original=offer.project_name_original,
            project_name_entered=offer.project_name_entered,
            project_label=project_label_of(offer.project_name_entered, offer.project_name_original),
            client_name_original=offer.client_name_original,
            supplier_name=supplier_name,
            grand_total=offer.grand_total,
            grand_total_currency=offer.grand_total_currency,
            is_active_latest=offer.is_active_latest,
            root_offer_id=offer.root_offer_id,
            parent_offer_id=offer.parent_offer_id,
            sanity_check_status=offer.sanity_check_status,
            verification_status=offer.verification_status,
            review_status=review_status_of(
                sanity_check_status=offer.sanity_check_status,
                verification_status=offer.verification_status,
            ),
            completeness_mandatory_gaps=completeness_gaps,
            version_count=version_count,
            created_by_user_id=offer.created_by_user_id,
            created_by_display_name=uploader_name,
            created_at=offer.created_at,
            archived_at=offer.archived_at,
            is_archived=offer.archived_at is not None,
        )

    # -- the list ------------------------------------------------------------

    def _version_count_subquery(self, user: User | None):
        """How many versions this offer's chain has, per row.

        A correlated subquery rather than a join, so a chain's version count is
        visible even when only its latest version is being listed. Scoped per
        version, like get_offer_versions: the count has to agree with the list
        it leads to, and must not reveal versions the caller cannot open.
        """
        chain_root = func.coalesce(Offer.root_offer_id, Offer.id)
        other = aliased(Offer)
        query = select(func.count(other.id)).where(
            or_(other.id == chain_root, other.root_offer_id == chain_root)
        )
        if user is not None:
            version_scope = visibility_filter(
                user=user,
                owner_id_column=other.created_by_user_id,
                department_column=other.created_by_department,
            )
            if version_scope is not None:
                query = query.where(version_scope)
        return query.correlate(Offer).scalar_subquery()

    def _summary_select(self, user: User | None):
        """`select(offer, supplier name, uploader name, version count)`.

        Both joins are written out by hand - there is no relationship() in this
        schema - and both are outer joins: an offer keeps its row when its
        supplier was deleted, and an offer uploaded before sign-in existed has
        no uploader at all.
        """
        return (
            select(Offer, Supplier.supplier_name, uploader_name_column(), self._version_count_subquery(user))
            .outerjoin(Supplier, Offer.supplier_id == Supplier.supplier_id)
            .outerjoin(User, User.id == Offer.created_by_user_id)
        )

    @staticmethod
    def _filter_clauses(query: OfferListQuery, user: User | None) -> list[ColumnElement]:
        """Everything the filter bar asks for EXCEPT the status control.

        Status is left out so the same clause list can answer two questions at
        once: how many offers this filter matches, and how many archived ones
        it is hiding.
        """
        clauses: list[ColumnElement] = [
            # Only offers that actually finished. A run that failed now KEEPS
            # its offer row and files so a retry does not mean re-uploading -
            # this is what stops those half-built rows appearing in the list as
            # blank offers with no supplier and no total.
            Offer.persisted_at.is_not(None),
        ]
        if not query.include_superseded:
            clauses.append(Offer.is_active_latest.is_(True))
        if user is not None:
            scope = visibility_filter(
                user=user,
                owner_id_column=Offer.created_by_user_id,
                department_column=Offer.created_by_department,
            )
            if scope is not None:
                clauses.append(scope)
        if query.q and query.q.strip():
            clauses.append(search_clause(query.q))
        if query.supplier_id is not None:
            clauses.append(Offer.supplier_id == query.supplier_id)
        if query.project and query.project.strip():
            clauses.append(project_label_column() == query.project.strip())
        if query.rfq and query.rfq.strip():
            clauses.append(Offer.rfq_number.ilike(like_pattern(query.rfq)))
        if query.uploaded_by_user_id is not None:
            clauses.append(Offer.created_by_user_id == query.uploaded_by_user_id)
        if query.uploaded_from is not None:
            clauses.append(
                Offer.created_at >= datetime.combine(query.uploaded_from, time.min, tzinfo=timezone.utc)
            )
        if query.uploaded_to is not None:
            # Inclusive of the whole closing day: a range typed as 1-3 Sep that
            # dropped everything uploaded on the 3rd after midnight would look
            # like data loss.
            clauses.append(
                Offer.created_at
                < datetime.combine(query.uploaded_to, time.min, tzinfo=timezone.utc) + timedelta(days=1)
            )
        return clauses

    @staticmethod
    def _status_clause(status: OfferListStatus | None) -> ColumnElement | None:
        """The Status control, including what "no status" means.

        No status at all is the working list: everything that is not archived.
        `ALL` is the only way to see archived and unarchived offers together,
        and it is a choice someone has to make rather than the default.
        """
        if status is OfferListStatus.ALL:
            return None
        if status is OfferListStatus.ARCHIVED:
            return Offer.archived_at.is_not(None)
        not_archived = Offer.archived_at.is_(None)
        if status is None:
            return not_archived
        return and_(not_archived, review_status_clause(OfferReviewStatus(status.value)))

    @staticmethod
    def _order_by(query: OfferListQuery) -> list[ColumnElement]:
        """The ORDER BY, plus the tie-break that makes paging stable.

        NULLS LAST is applied only to the nullable sort columns. Adding it to
        `created_at` would cost the index: ix_offers_created_at is declared
        `created_at DESC`, which is NULLS FIRST, and an ORDER BY that asks for
        NULLS LAST cannot use it - for a column that is NOT NULL and so has no
        nulls to place.
        """
        columns = {
            OfferSortKey.UPLOADED_AT: Offer.created_at,
            OfferSortKey.VALUE: Offer.grand_total,
            OfferSortKey.SUPPLIER: Supplier.supplier_name,
            OfferSortKey.PROJECT: project_label_column(),
        }
        column = columns[query.sort]
        ordered = column.asc() if query.direction is SortDirection.ASC else column.desc()
        if query.sort is not OfferSortKey.UPLOADED_AT:
            ordered = ordered.nulls_last()
        # Without a unique tie-break, two offers uploaded in the same second (or
        # priced the same) can swap places between page 1 and page 2, and one of
        # them is then never shown.
        return [ordered, Offer.id.desc()]

    async def list_offers_page(
        self, query: OfferListQuery, *, user: User | None = None
    ) -> OfferListPage:
        """One page of the offers list, with the counts its footer needs."""
        clauses = self._filter_clauses(query, user)
        status_clause = self._status_clause(query.status)

        # Both counts in one pass over the same filtered set: what this page is
        # a slice of, and how many archived offers the status control is
        # keeping out of it.
        counted = func.count() if status_clause is None else func.count().filter(status_clause)
        counts_query = (
            select(counted, func.count().filter(Offer.archived_at.is_not(None)))
            .select_from(Offer)
            .outerjoin(Supplier, Offer.supplier_id == Supplier.supplier_id)
            .where(*clauses)
        )
        total, archived_matching = (await self.db.execute(counts_query)).one()

        limit = max(1, min(query.limit, MAX_PAGE_SIZE))
        offset = max(0, query.offset)
        rows_query = self._summary_select(user).where(*clauses)
        if status_clause is not None:
            rows_query = rows_query.where(status_clause)
        rows_query = rows_query.order_by(*self._order_by(query)).limit(limit).offset(offset)
        rows = (await self.db.execute(rows_query)).all()

        # One grouped query for the whole page rather than one per row: the
        # offers list is the screen a reviewer opens first and it must not get
        # slower for carrying the gap count.
        gaps = await mandatory_gap_counts(self.db, [offer.id for offer, _, _, _ in rows])
        return OfferListPage(
            items=[
                self._to_summary(offer, supplier_name, uploader_name, version_count, gaps.get(offer.id))
                for offer, supplier_name, uploader_name, version_count in rows
            ],
            total=int(total or 0),
            limit=limit,
            offset=offset,
            archived_matching=int(archived_matching or 0),
        )

    async def get_offer_summary(self, offer_id: int, *, user: User | None = None) -> OfferSummary:
        """The list row for one offer - what the screen puts back in the table
        after archiving it, so the row cannot drift from the list it sits in."""
        rows_query = self._summary_select(user).where(Offer.id == offer_id)
        row = (await self.db.execute(rows_query)).first()
        if row is None:
            raise OfferNotFoundError(offer_id)
        offer, supplier_name, uploader_name, version_count = row
        gaps = await mandatory_gap_counts(self.db, [offer.id])
        return self._to_summary(offer, supplier_name, uploader_name, version_count, gaps.get(offer.id))

    async def filter_options(self, *, user: User | None = None) -> OfferFilterOptions:
        """The filter bar's four dropdowns, built from the offers the caller
        may see.

        Scoped exactly like the list's default page - visible, finished, latest
        version - so no dropdown can offer a choice that returns nothing.
        Building the uploader list from `users` instead would put colleagues
        from departments whose offers this caller cannot open into a dropdown
        on their screen.
        """
        base: list[ColumnElement] = [Offer.persisted_at.is_not(None), Offer.is_active_latest.is_(True)]
        if user is not None:
            scope = visibility_filter(
                user=user,
                owner_id_column=Offer.created_by_user_id,
                department_column=Offer.created_by_department,
            )
            if scope is not None:
                base.append(scope)

        supplier_rows = (
            await self.db.execute(
                select(Supplier.supplier_id, Supplier.supplier_name, func.count(Offer.id))
                .select_from(Offer)
                .join(Supplier, Offer.supplier_id == Supplier.supplier_id)
                .where(*base)
                .group_by(Supplier.supplier_id, Supplier.supplier_name)
                .order_by(Supplier.supplier_name)
            )
        ).all()

        label = project_label_column()
        project_rows = (
            await self.db.execute(
                select(label, func.count(Offer.id))
                .where(*base, label.is_not(None), label != "")
                .group_by(label)
                .order_by(label)
            )
        ).all()

        uploader_name = uploader_name_column()
        uploader_rows = (
            await self.db.execute(
                select(User.id, uploader_name, func.count(Offer.id))
                .select_from(Offer)
                .join(User, User.id == Offer.created_by_user_id)
                .where(*base)
                .group_by(User.id, User.display_name, User.username)
                .order_by(uploader_name)
            )
        ).all()

        rfq_rows = (
            await self.db.execute(
                select(Offer.rfq_number, func.count(Offer.id))
                .where(*base, Offer.rfq_number.is_not(None), Offer.rfq_number != "")
                .group_by(Offer.rfq_number)
                # Newest RFQ first: the numbers carry the year, and the one
                # being worked on this week is the one being filtered for.
                .order_by(Offer.rfq_number.desc())
            )
        ).all()

        return OfferFilterOptions(
            suppliers=[
                SupplierFilterOption(supplier_id=row[0], supplier_name=row[1], offer_count=row[2])
                for row in supplier_rows
            ],
            projects=[
                ProjectFilterOption(project_label=row[0], offer_count=row[1]) for row in project_rows
            ],
            uploaders=[
                UploaderFilterOption(user_id=row[0], display_name=row[1], offer_count=row[2])
                for row in uploader_rows
            ],
            rfq_numbers=[RfqFilterOption(rfq_number=row[0], offer_count=row[1]) for row in rfq_rows],
        )

    # -- one offer -----------------------------------------------------------

    async def get_offer_versions(self, offer_id: int, user: User | None = None) -> list[OfferSummary]:
        """Every offer in `offer_id`'s version chain, oldest first.

        Scoped per version, not just by the offer asked about: a chain can
        cross departments (a pre-sign-in offer, visible to everyone, versioned
        by one department), and being allowed to open one version is not
        permission to read the others."""
        target = await self.db.get(Offer, offer_id)
        if target is None:
            raise OfferNotFoundError(offer_id)
        chain_root_id = target.root_offer_id or target.id

        query = (
            select(Offer, Supplier.supplier_name, uploader_name_column())
            .outerjoin(Supplier, Offer.supplier_id == Supplier.supplier_id)
            .outerjoin(User, User.id == Offer.created_by_user_id)
            .where(or_(Offer.id == chain_root_id, Offer.root_offer_id == chain_root_id))
            .order_by(Offer.created_at.asc())
        )
        if user is not None:
            scope = visibility_filter(
                user=user,
                owner_id_column=Offer.created_by_user_id,
                department_column=Offer.created_by_department,
            )
            if scope is not None:
                query = query.where(scope)
        result = await self.db.execute(query)
        rows = result.all()
        version_count = len(rows)
        gaps = await mandatory_gap_counts(self.db, [offer.id for offer, _, _ in rows])
        return [
            self._to_summary(offer, supplier_name, uploader_name, version_count, gaps.get(offer.id))
            for offer, supplier_name, uploader_name in rows
        ]

    async def uploader_display_name(self, offer_id: int) -> str | None:
        """Who uploaded this offer, for the detail header.

        None for an offer created before sign-in existed, and for one whose
        uploader's account has since been deleted - `created_by_user_id` is ON
        DELETE SET NULL, so there is then no name left to join to. The header
        says "uploaded by" only when it can name somebody.
        """
        return (
            await self.db.execute(
                select(uploader_name_column())
                .select_from(Offer)
                .join(User, User.id == Offer.created_by_user_id)
                .where(Offer.id == offer_id)
            )
        ).scalar_one_or_none()

    async def list_offer_documents(self, offer_id: int) -> OfferDocumentsResponse:
        """The offer's files, with what is known about each one.

        The page counts come from the page rows rather than from
        `documents.page_count`, because the same rows are what says whether the
        parse actually worked - counting them once answers both questions.
        """
        document_ids = select(Document.document_id).where(Document.offer_id == offer_id)
        page_stats = (
            select(
                DocumentPage.file_id.label("file_id"),
                func.count().label("page_rows"),
                func.count()
                .filter(DocumentPage.extraction_method == ExtractionMethod.FAILED.value)
                .label("failed_rows"),
            )
            .where(DocumentPage.file_id.in_(document_ids))
            .group_by(DocumentPage.file_id)
            .subquery()
        )
        rows = (
            await self.db.execute(
                select(Document, page_stats.c.page_rows, page_stats.c.failed_rows)
                .outerjoin(page_stats, page_stats.c.file_id == Document.document_id)
                .where(Document.offer_id == offer_id)
                # Upload order, which is the order the reviewer dropped them in.
                .order_by(Document.uploaded_at, Document.original_filename)
            )
        ).all()

        documents = [
            OfferDocumentOut(
                document_id=document.document_id,
                original_filename=document.original_filename,
                file_type=document.file_type,
                page_count=document.page_count,
                size_bytes=self._file_size(document.storage_path),
                language=document.language,
                parse_state=parse_state_of(page_rows, failed_rows),
                uploaded_at=document.uploaded_at,
            )
            for document, page_rows, failed_rows in rows
        ]
        return OfferDocumentsResponse(
            offer_id=offer_id,
            documents=documents,
            file_count=len(documents),
            total_pages=sum(document.page_count or 0 for document in documents),
            total_size_bytes=sum(document.size_bytes or 0 for document in documents),
        )

    def _file_size(self, storage_path: str) -> int | None:
        """The file's size on disk, or None if it is not there any more.

        `documents` has no size column, so the only honest source is the file
        itself. A handful of local stat() calls per offer is cheaper than a
        migration that would have to invent sizes for every document already
        uploaded.
        """
        try:
            return (Path(self.base_dir) / storage_path).stat().st_size
        except OSError:
            return None

    # -- archiving -----------------------------------------------------------

    async def set_archived(self, offer_id: int, *, archived: bool, user: User) -> OfferSummary:
        """Put an offer on the shelf, or take it back off.

        Archiving is not a delete and not a lock. The offer stays readable,
        comparable, re-runnable and re-checkable; the single thing that changes
        is that the default list leaves it out - and says how many it left out.
        Each version of a chain archives on its own, because retiring one
        superseded revision is the common case and retiring the whole history
        with it is not.

        Idempotent: archiving an archived offer changes nothing and writes no
        second event, so a double-click does not put two lines in the log.
        `with_for_update` is what actually makes that true - without it, two
        genuinely concurrent requests (two tabs, a retried click) can both
        read `archived_at is None` before either writes, both pass the check
        below, and both commit - the exact double-click this docstring says
        cannot happen. Same intent as `UploadController.create_offer_version`'s
        `SELECT ... FOR UPDATE`.
        """
        offer = await self.db.get(Offer, offer_id, with_for_update=True)
        if offer is None:
            raise OfferNotFoundError(offer_id)

        if (offer.archived_at is not None) != archived:
            offer.archived_at = datetime.now(timezone.utc) if archived else None
            # In THIS transaction, unlike every other entry in the activity log
            # (helpers/offer_events.py): `offers` records when an offer was
            # archived and has no column for by whom, so this line is the only
            # record of who did it - the two have to land together.
            record = record_offer_archived if archived else record_offer_unarchived
            await record(offer_id=offer_id, actor=user, db=self.db)
            await self.db.commit()

        return await self.get_offer_summary(offer_id, user=user)

    # -- deleting --------------------------------------------------------

    async def delete_offer(self, offer_id: int, *, user: User) -> None:
        """Permanently and irreversibly removes an offer, everything
        persisted under it, and its files on disk.

        Unlike `set_archived` this has no undo, so it is refused outright in
        two situations rather than left to do something surprising: when
        another offer's `parent_offer_id` still points at this one (delete the
        newer version first), and when a read is queued or running against
        this offer right now (deleting the row out from under it would fail
        that job on rows that vanished mid-run). Anyone who can already see
        the offer may delete it - same permission level as archiving, checked
        by the route's `visible_offer` dependency, not by an extra admin gate
        here.

        The delete order matters and mirrors what
        `UploadController.abandon_offer` already does for a pre-persist
        offer, plus what a persisted one needs on top of that:
        `tech_specs`/`included_features`/`inclusions_exclusions` first (no
        real FK, never DB-cascaded - see `helpers.polymorphic_entities`),
        then `document_pages`/`documents` (a plain FK with no ON DELETE
        behaviour, which would otherwise fail the offer row's own delete),
        then the offer row itself - which lets the database's own
        `ON DELETE CASCADE` remove `offer_items`, `offer_events`,
        `offer_attachments`, `offer_payment_schedules`,
        `offer_sanity_findings`, `offer_verified_findings`, `pipeline_jobs`,
        `completeness_evidence` and `offer_completeness_results` for it. If
        this offer was the latest version of a multi-version chain, its
        parent's `is_active_latest` is restored, exactly like abandoning a
        version upload restores it.

        `offer_events` is one of the rows that cascades away with the offer,
        which means there is no way to leave a persisted activity-log entry
        for the deletion itself inside this app's own history - the row that
        would describe it disappears along with everything else. That is a
        deliberate tradeoff, not an oversight the way archiving's own history
        entry is: the only durable record of who deleted what is the
        WARNING-level log line below.
        """
        offer = await self.db.get(Offer, offer_id, with_for_update=True)
        if offer is None:
            raise OfferNotFoundError(offer_id)

        child_offer_id = (
            await self.db.execute(select(Offer.id).where(Offer.parent_offer_id == offer_id))
        ).scalar_one_or_none()
        if child_offer_id is not None:
            raise OfferHasNewerVersionError(offer_id, child_offer_id)

        active_job_id = (
            await self.db.execute(
                select(PipelineJob.job_id).where(
                    PipelineJob.offer_id == offer_id,
                    PipelineJob.kind == JobKind.OFFER_PIPELINE.value,
                    PipelineJob.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
                )
            )
        ).scalar_one_or_none()
        if active_job_id is not None:
            raise OfferHasActiveJobError(offer_id)

        # Collected before anything is deleted - once these rows are gone
        # there is no going back to ask what files they pointed at.
        document_ids = (
            (await self.db.execute(select(Document.document_id).where(Document.offer_id == offer_id)))
            .scalars()
            .all()
        )

        await delete_polymorphic_offer_rows(self.db, offer_id)

        if document_ids:
            await self.db.execute(delete(DocumentPage).where(DocumentPage.file_id.in_(document_ids)))
            await self.db.execute(delete(Document).where(Document.offer_id == offer_id))

        parent_offer_id = offer.parent_offer_id
        await self.db.delete(offer)

        if parent_offer_id is not None:
            parent = await self.db.get(Offer, parent_offer_id, with_for_update=True)
            if parent is not None:
                parent.is_active_latest = True

        await self.db.commit()

        logger.warning(
            "Offer %s permanently deleted by user_id=%s (%s)",
            offer_id,
            user.id,
            user.username,
        )

        # Only after a successful commit, and best-effort from here on - a
        # file already gone is logged, not raised, the same rule
        # `UploadController.abandon_offer`'s own `ignore_errors=True` follows.
        # This one `rmtree` also covers completeness evidence files: they are
        # always saved under this same `assets/offers/{offer_id}/evidence/`
        # tree (see `routes.completeness.upload_evidence`), so there is
        # nothing left under it to unlink individually afterwards.
        shutil.rmtree(Path(self.files_dir) / str(offer_id), ignore_errors=True)
