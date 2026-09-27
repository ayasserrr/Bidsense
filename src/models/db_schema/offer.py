from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.enums import SanityCheckStatus, VerificationStatus

from .base import Base

SANITY_CHECK_STATUS_VALUES = tuple(status.value for status in SanityCheckStatus)
VERIFICATION_STATUS_VALUES = tuple(status.value for status in VerificationStatus)


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint(
            f"sanity_check_status IN {SANITY_CHECK_STATUS_VALUES}", name="ck_offers_sanity_check_status"
        ),
        CheckConstraint(
            f"verification_status IN {VERIFICATION_STATUS_VALUES}", name="ck_offers_verification_status"
        ),
        # The offers list is ordered by created_at DESC and paginated, always,
        # and filtered on top of that by uploader, by department (the
        # visibility_filter every list carries) and by date. These three cover
        # those shapes. None of them is partial on `persisted_at IS NOT NULL`
        # or `archived_at IS NULL`, on purpose: a partial index only serves a
        # query that repeats its predicate word for word, and the dashboard
        # counts and the archived view do not.
        Index("ix_offers_created_at", text("created_at DESC")),
        Index(
            "ix_offers_created_by_user_created_at",
            "created_by_user_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_offers_department_created_at",
            "created_by_department",
            text("created_at DESC"),
        ),
        # The list's free-text search is served by trigram (GIN) indexes on
        # offer_ref, rfq_number and both project names, created by migration
        # 0017 and NOT declared here. They exist only where the server has
        # pg_trgm, which is a contrib extension this application cannot assume,
        # so declaring them as metadata would claim an index that may not be
        # there. Search itself works either way - without them it is a scan.
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    root_offer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("offers.id"), nullable=True, index=True
    )
    parent_offer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("offers.id"), nullable=True, index=True
    )
    is_active_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Resolved (canonical) links - filled in by a later reconciliation stage,
    # not by extraction itself. Extraction only ever fills the "_original"
    # verbatim fields below.
    supplier_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("suppliers.supplier_id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.project_id", ondelete="SET NULL"), nullable=True, index=True
    )

    # --- filed by the person who uploaded it, not read out of the document --
    # The RFQ the offer answers. Typed at upload because no document reliably
    # prints it, and it is what groups the offers the compare screen puts side
    # by side.
    rfq_number: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    # The project name as a person typed it, kept separate from
    # `project_name_original` below - which is what the document itself says -
    # rather than overwriting it. Two different jobs: this one is for grouping
    # and display, and the extracted one is what
    # helpers/offer_versioning.check_same_offer_identity compares when a new
    # version is uploaded. Overwriting the extracted name with a typed one
    # would disarm that check without anyone noticing. When the two disagree
    # that is recorded as an OfferEventKind.PROJECT_NAME_MISMATCH event and
    # shown; it never stops a run.
    project_name_entered: Mapped[str | None] = mapped_column(Text, nullable=True)

    offer_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_name_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_name_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_location_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_terms_original: Mapped[str | None] = mapped_column(Text, nullable=True)

    price_currency_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency_primary: Mapped[str | None] = mapped_column(
        ForeignKey("currencies.code", ondelete="SET NULL"), nullable=True
    )
    grand_total: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    grand_total_currency: Mapped[str | None] = mapped_column(
        ForeignKey("currencies.code", ondelete="SET NULL"), nullable=True
    )

    tax_treatment_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    incoterm: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_terms_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    validity_terms_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    warranty_terms_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    manufacturer_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_name_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    offer_date_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    offer_signed_by_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    general_notes_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Filled in by the persist stage from the sanity-check node's output.
    # Null until this offer has actually been through a sanity check.
    sanity_check_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    sanity_check_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Filled in by the persist stage from the verification node's output.
    # Every offer is persisted regardless of this value - 'needs_human_review'
    # marks an offer for review, it never blocks the write. Null until this
    # offer has actually been through verification.
    verification_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pre-persist stage outputs from the most recent attempt on this offer, so
    # a run that fails partway (a chunk the gateway timed out on, a lost
    # connection during verification) can resume from where it actually got
    # to instead of re-parsing every file and re-running the whole (chunked,
    # most expensive) extraction from nothing. See `pipeline/resume.py`, the
    # one place that reads and writes this. Cleared once persist succeeds -
    # the offer itself is the durable record from that point on.
    pipeline_checkpoint: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pipeline_checkpoint_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # The detail screen's "read this first" panel and its clarification-email
    # draft, composed in `pipeline/node/summary.py` from findings and
    # completeness gaps this offer's own pipeline already verified - never a
    # fresh LLM paragraph. `review_chase_items` is a JSON list of
    # `{title, detail}` objects and is often empty, which means "nothing to
    # chase", not "not generated yet" - `review_summary_generated_at` is null
    # only in that second case.
    review_chase_items: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    review_headline: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_email_subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_email_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_summary_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Who uploaded this offer, and the department they were in at the time.
    # The department is copied rather than read through the user so that
    # somebody transferring between departments does not drag their old offers
    # with them. A NULL owner with an empty department means "created before
    # sign-in existed" and stays visible to everyone - see is_pre_sign_in in
    # helpers/visibility.py.
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_department: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="", index=True
    )

    # Set the first time this offer completes the persist stage. Until then the
    # row exists but holds nothing worth showing - a failed or still-running
    # pipeline leaves one behind on purpose, so the files do not have to be
    # uploaded again for a retry, and the offers list filters on this rather
    # than on an offer having been deleted to keep itself clean.
    persisted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Retired by a reviewer: kept, readable and still comparable, but out of
    # the working list. Deliberately not a delete and deliberately not
    # `is_active_latest`, which means something else entirely (this row is the
    # newest version of its chain). Who archived it is an offer_events row -
    # one activity log rather than another pair of by/at columns here.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
