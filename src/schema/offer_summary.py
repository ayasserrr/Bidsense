"""What the offers screen reads: the list row, the page it arrives in, the
dropdowns that filter it, and the per-offer reads behind the detail header.

They live together because they are one contract. The list's idea of "the
project" and the detail header's have to be the same idea, and so does the
list's idea of "needs review" and the filter's - split across modules, the two
halves drift, and the number on the badge is the one nobody re-reads.
"""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

from models.enums import CurrencyCode, SanityCheckStatus, VerificationStatus


class OfferReviewStatus(str, Enum):
    """The one word the list's Status column shows for an offer.

    Derived, never stored. It lives in the schema rather than in models/enums
    because no column in the database holds these values: they are read out of
    `sanity_check_status` and `verification_status` by
    `OfferController.review_status_of`, whose SQL twin
    `OfferController.review_status_clause` backs the Status filter. The two are
    tested against each other, which is the whole reason the rule is written
    once on the server instead of once here and once in the browser.
    """

    # Something was flagged, or the sanity check flagged something and
    # verification never got to it. The rule the offers list already applied in
    # the browser, moved to where the filter can use the same one.
    NEEDS_REVIEW = "needs_review"
    # Checked, nothing flagged.
    CLEAR = "clear"
    # Never checked. Deliberately not "clear": the same distinction
    # `completeness_mandatory_gaps = None` makes for the gap badge, for the same
    # reason - a green word on an offer nobody has read is a lie.
    UNCHECKED = "unchecked"


class OfferListStatus(str, Enum):
    """The Status control on the filter bar.

    Three of these are review states and two are about the shelf: `archived`
    asks for archived offers whatever their review state, `all` asks for
    everything. Leaving the parameter off means the working list - everything
    that is not archived - and `OfferListPage.archived_matching` then says how
    many were left out, so they never vanish without the screen being able to
    say so.
    """

    NEEDS_REVIEW = "needs_review"
    CLEAR = "clear"
    UNCHECKED = "unchecked"
    ARCHIVED = "archived"
    ALL = "all"


class OfferSortKey(str, Enum):
    """Which column the list is ordered by.

    `value` sorts on `grand_total` as the offer states it, in the offer's own
    currency - it does NOT convert. Two offers priced in different currencies
    sort by the size of their numbers, which is why every row carries
    `grand_total_currency` and why the screen has to print it next to the
    figure.
    """

    UPLOADED_AT = "uploaded_at"
    VALUE = "value"
    SUPPLIER = "supplier"
    PROJECT = "project"


class SortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class OfferSummary(BaseModel):
    """A lightweight row for the offers list / version picker - not the full
    `OfferFullDB`, just enough to identify, browse, and pick an offer."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    offer_ref: str | None
    # The RFQ this offer answers, as the uploader typed it. Null for every offer
    # filed before there was a field to type it into.
    rfq_number: str | None = None
    # Both names, and the one to print. `project_name_original` is what the
    # document says, and is what decides version identity;
    # `project_name_entered` is what a person typed when filing it.
    # `project_label` is the typed one where there is one, so the list groups
    # the way the person filing expected - without the extracted name being
    # overwritten or lost.
    project_name_original: str | None
    project_name_entered: str | None = None
    project_label: str | None = None
    client_name_original: str | None
    supplier_name: str | None
    grand_total: float | None
    grand_total_currency: CurrencyCode | None
    is_active_latest: bool
    root_offer_id: int | None
    parent_offer_id: int | None
    sanity_check_status: SanityCheckStatus | None
    verification_status: VerificationStatus | None
    # The two raw statuses above turned into the one word the Status column
    # shows. Sent as well as, not instead of, them - the detail screen still
    # reads the raw pair.
    review_status: OfferReviewStatus = OfferReviewStatus.UNCHECKED
    # Required terms this offer does not state, or states too vaguely to act on -
    # the same number the completeness section headlines. None means the check
    # has never run for this offer, which is not the same as "nothing missing"
    # and must not be shown as a clean result.
    completeness_mandatory_gaps: int | None = None
    version_count: int
    # Who uploaded it. Null together for an offer from before sign-in existed,
    # and the id can survive alone if the account is later deleted - the column
    # is ON DELETE SET NULL, so there is then no name left to join.
    created_by_user_id: int | None = None
    created_by_display_name: str | None = None
    # When it was uploaded: this IS the "Uploaded" column. There is no separate
    # uploaded_at, because the offer row is created by the upload.
    created_at: datetime
    # Retired by a reviewer. Still readable, still comparable, still re-runnable;
    # just out of the working list. Null means not archived.
    archived_at: datetime | None = None
    is_archived: bool = False


class OfferListPage(BaseModel):
    """One page of the offers list, with the counts its footer needs.

    `total` counts everything the filters match, not just this page, so "25 of
    312 offers" is answerable without asking for all 312.
    """

    items: list[OfferSummary]
    total: int
    limit: int
    offset: int
    # How many ARCHIVED offers the same filters match, ignoring the status
    # filter itself. The default list leaves archived offers out; this is what
    # lets the screen say "and 4 archived" rather than dropping them in silence.
    # It overlaps `total` only when archived offers were actually asked for.
    archived_matching: int = 0


class SupplierFilterOption(BaseModel):
    supplier_id: int
    supplier_name: str
    offer_count: int


class ProjectFilterOption(BaseModel):
    # Exactly the string to send back as the `project` filter, and exactly what
    # `OfferSummary.project_label` holds.
    project_label: str
    offer_count: int


class UploaderFilterOption(BaseModel):
    user_id: int
    display_name: str
    offer_count: int


class RfqFilterOption(BaseModel):
    rfq_number: str
    offer_count: int


class OfferFilterOptions(BaseModel):
    """The filter bar's dropdowns.

    Every option is read out of the offers the caller may see, never out of the
    suppliers, projects or users tables at large. A roster built from `users`
    would name people from departments whose offers this caller cannot open -
    the filter list would leak exactly what the offers list is careful not to.
    """

    suppliers: list[SupplierFilterOption]
    projects: list[ProjectFilterOption]
    uploaders: list[UploaderFilterOption]
    rfq_numbers: list[RfqFilterOption]


class DocumentParseState(str, Enum):
    """How far a document got through parsing, read back from its pages.

    Derived rather than stored: `documents` has no status column, and the page
    rows are the record of what actually happened. A page Parsing Studio could
    not read is written with `extraction_method = 'failed'`, so a document with
    some of those still has text - just not all of it - and saying so is the
    difference between "this offer never states a warranty" and "we could not
    read the page the warranty is on".
    """

    NOT_PARSED = "not_parsed"
    PARSED = "parsed"
    PARTLY_FAILED = "partly_failed"
    FAILED = "failed"


class OfferDocumentOut(BaseModel):
    document_id: uuid.UUID
    original_filename: str
    file_type: str
    # Pages actually written by the parse. Null before it has run.
    page_count: int | None
    # Read off the file on disk, because `documents` stores no size. Null when
    # the file is no longer there - a fact worth showing, rather than a zero
    # worth trusting.
    size_bytes: int | None
    language: str | None
    parse_state: DocumentParseState
    uploaded_at: datetime


class OfferDocumentsResponse(BaseModel):
    """The offer's files - the "3 files, 42 pages" line, with the files under
    it."""

    offer_id: int
    documents: list[OfferDocumentOut]
    file_count: int
    total_pages: int
    # The sum of the sizes that could be read. A file whose size could not be
    # read contributes nothing here and reports `size_bytes: null` of its own,
    # so the two can be compared instead of the total quietly under-counting.
    total_size_bytes: int
