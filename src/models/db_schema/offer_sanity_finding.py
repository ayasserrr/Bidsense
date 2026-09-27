from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.enums import SanityCheckIssueType, SanityCheckSeverity

from .base import Base

SANITY_CHECK_ISSUE_TYPE_VALUES = tuple(issue_type.value for issue_type in SanityCheckIssueType)
SANITY_CHECK_SEVERITY_VALUES = tuple(severity.value for severity in SanityCheckSeverity)


class OfferSanityFinding(Base):
    __tablename__ = "offer_sanity_findings"
    __table_args__ = (
        CheckConstraint(
            f"issue_type IN {SANITY_CHECK_ISSUE_TYPE_VALUES}", name="ck_offer_sanity_findings_issue_type"
        ),
        CheckConstraint(
            f"severity IN {SANITY_CHECK_SEVERITY_VALUES}", name="ck_offer_sanity_findings_severity"
        ),
    )

    finding_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    offer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issue_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    field_path: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
