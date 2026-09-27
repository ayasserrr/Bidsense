"""add offer_verified_findings table (persisted verification-node output,
one row per verified sanity-check finding) plus verification_status/
verification_summary columns on offers - offers are always persisted
regardless of this value; 'needs_human_review' marks an offer for review,
it never blocks the write

Revision ID: 0007_verified_findings
Revises: 0006_sanity_findings
Create Date: 2026-09-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_verified_findings"
down_revision: Union[str, None] = "0006_sanity_findings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VERIFICATION_STATUS_VALUES = ("skipped", "resolved", "needs_human_review")
ISSUE_TYPE_VALUES = (
    "arithmetic_mismatch", "percentage_mismatch", "subtotal_mismatch",
    "grand_total_mismatch", "payment_schedule_mismatch",
)
EXTRACTION_VERDICT_VALUES = ("confirmed", "incorrect", "insufficient_evidence")
FINDING_VERDICT_VALUES = ("confirmed", "explained", "insufficient_evidence")


def upgrade() -> None:
    op.add_column("offers", sa.Column("verification_status", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("verification_summary", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_offers_verification_status",
        "offers",
        f"verification_status IN {VERIFICATION_STATUS_VALUES}",
    )

    op.create_table(
        "offer_verified_findings",
        sa.Column("verified_finding_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("offer_id", sa.BigInteger(), nullable=False),
        sa.Column("issue_type", sa.Text(), nullable=False),
        sa.Column("field_path", sa.Text(), nullable=False),
        sa.Column("extraction_verdict", sa.Text(), nullable=False),
        sa.Column("extraction_correction", sa.Text(), nullable=True),
        sa.Column("finding_verdict", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            f"issue_type IN {ISSUE_TYPE_VALUES}", name="ck_offer_verified_findings_issue_type"
        ),
        sa.CheckConstraint(
            f"extraction_verdict IN {EXTRACTION_VERDICT_VALUES}",
            name="ck_offer_verified_findings_extraction_verdict",
        ),
        sa.CheckConstraint(
            f"finding_verdict IN {FINDING_VERDICT_VALUES}", name="ck_offer_verified_findings_finding_verdict"
        ),
        sa.PrimaryKeyConstraint("verified_finding_id"),
    )
    op.create_index("ix_offer_verified_findings_offer_id", "offer_verified_findings", ["offer_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_verified_findings_offer_id", table_name="offer_verified_findings")
    op.drop_table("offer_verified_findings")

    op.drop_constraint("ck_offers_verification_status", "offers", type_="check")
    op.drop_column("offers", "verification_summary")
    op.drop_column("offers", "verification_status")
