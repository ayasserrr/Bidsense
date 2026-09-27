from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.enums import ExtractionVerdict, FindingVerdict, SanityCheckIssueType

from .base import Base

VERIFIED_FINDING_ISSUE_TYPE_VALUES = tuple(issue_type.value for issue_type in SanityCheckIssueType)
EXTRACTION_VERDICT_VALUES = tuple(verdict.value for verdict in ExtractionVerdict)
FINDING_VERDICT_VALUES = tuple(verdict.value for verdict in FindingVerdict)


class OfferVerifiedFinding(Base):
    __tablename__ = "offer_verified_findings"
    __table_args__ = (
        CheckConstraint(
            f"issue_type IN {VERIFIED_FINDING_ISSUE_TYPE_VALUES}",
            name="ck_offer_verified_findings_issue_type",
        ),
        CheckConstraint(
            f"extraction_verdict IN {EXTRACTION_VERDICT_VALUES}",
            name="ck_offer_verified_findings_extraction_verdict",
        ),
        CheckConstraint(
            f"finding_verdict IN {FINDING_VERDICT_VALUES}", name="ck_offer_verified_findings_finding_verdict"
        ),
    )

    verified_finding_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    offer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issue_type: Mapped[str] = mapped_column(Text, nullable=False)
    field_path: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_verdict: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    finding_verdict: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
