import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.enums import CompletenessVerdict, EvidenceKind, RequirementGroup

from .base import Base

REQUIREMENT_GROUP_VALUES = tuple(group.value for group in RequirementGroup)
VERDICT_VALUES = tuple(verdict.value for verdict in CompletenessVerdict)
EVIDENCE_KIND_VALUES = tuple(kind.value for kind in EvidenceKind)


class CompletenessRequirement(Base):
    """One row of the client's checklist.

    A table rather than a Python enum because the client will revise this list -
    he said as much in the meeting - and an admin editing a row must not require
    a deployment. `code` is the stable identity; the label and description are
    the editable parts.
    """

    __tablename__ = "completeness_requirements"
    __table_args__ = (
        CheckConstraint(
            f"requirement_group IN {REQUIREMENT_GROUP_VALUES}",
            name="ck_completeness_requirements_group",
        ),
    )

    requirement_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    requirement_group: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # Read by both the reviewer and the model: one definition of what "present"
    # means for this row, so the verdict is auditable against a rule someone
    # can actually read.
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CompletenessEvidence(Base):
    """A file a reviewer attached to justify overriding a verdict.

    Deliberately NOT a `documents` row. Two reasons, both load-bearing:
    `documents.file_checksum` is globally unique, so attaching an email that was
    already seen elsewhere would silently come back as a duplicate and the
    override would appear to fail for no reason; and every document under an
    offer is fed to extraction as source text, so evidence stored there would
    contaminate the very offer it is commenting on.
    """

    __tablename__ = "completeness_evidence"
    __table_args__ = (
        CheckConstraint(
            f"evidence_kind IN {EVIDENCE_KIND_VALUES}", name="ck_completeness_evidence_kind"
        ),
    )

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    offer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Which checklist row this file was attached for. Kept as the code rather
    # than a foreign key so the evidence survives the requirement being renamed
    # or retired.
    requirement_code: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    evidence_kind: Mapped[str] = mapped_column(
        Text, nullable=False, default=EvidenceKind.EMAIL.value
    )

    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # NOT unique, unlike documents.file_checksum: one forwarded email can
    # legitimately evidence several gaps on several offers.
    file_checksum: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class OfferCompletenessResult(Base):
    """What the checker concluded about one requirement for one offer.

    The requirement's label, group and mandatory flag are snapshotted onto this
    row. That is what makes an old report still readable after the checklist is
    edited: the verdict stays attached to the rule it was actually judged under
    rather than silently re-labelling itself.

    A reviewer's override sits alongside the machine verdict rather than
    replacing it - both are shown, so nobody has to wonder whether a "present"
    came from the supplier's document or from somebody's correction.
    """

    __tablename__ = "offer_completeness_results"
    __table_args__ = (
        UniqueConstraint("offer_id", "requirement_code", name="uq_completeness_offer_requirement"),
        CheckConstraint(f"verdict IN {VERDICT_VALUES}", name="ck_completeness_results_verdict"),
        CheckConstraint(
            f"override_verdict IS NULL OR override_verdict IN {VERDICT_VALUES}",
            name="ck_completeness_results_override_verdict",
        ),
        # The client's rule, enforced by the database rather than only by the
        # form: filling a gap requires a document. "He told me on the phone" is
        # not an override.
        CheckConstraint(
            "is_overridden = false OR override_evidence_id IS NOT NULL",
            name="ck_completeness_results_override_needs_evidence",
        ),
    )

    result_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    offer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    requirement_code: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    requirement_label: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_group: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    was_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    verdict: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    extracted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A normalised reading where one exists - the Incoterm code, the VAT status,
    # the scope answer. Null where the requirement has no canonical form.
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Resolved from the quote's position in the merged source text, never from
    # a filename the model claimed. Null means the quote could not be located,
    # which is reported as such rather than guessed at.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_id", ondelete="SET NULL"), nullable=True
    )
    source_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    override_verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("completeness_evidence.evidence_id", ondelete="RESTRICT"),
        nullable=True,
    )
    overridden_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def effective_verdict(self) -> str:
        """What the offer is actually judged to say - the reviewer's override
        where one exists, otherwise the checker's own verdict."""
        if self.is_overridden and self.override_verdict:
            return self.override_verdict
        return self.verdict

    @property
    def effective_value(self) -> str | None:
        if self.is_overridden and self.override_value:
            return self.override_value
        return self.extracted_value
