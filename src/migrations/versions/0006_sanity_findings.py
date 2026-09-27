"""add offer_sanity_findings table (persisted sanity-check findings, one row
per finding) plus sanity_check_status/sanity_check_summary columns on offers
- the persist stage's write-side counterpart to the sanity-check node's
in-memory SanityCheckResult

Revision ID: 0006_sanity_findings
Revises: 0005_doc_page_check
Create Date: 2026-09-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_sanity_findings"
down_revision: Union[str, None] = "0005_doc_page_check"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SANITY_CHECK_STATUS_VALUES = ("passed", "needs_review")
SANITY_CHECK_ISSUE_TYPE_VALUES = (
    "arithmetic_mismatch", "percentage_mismatch", "subtotal_mismatch",
    "grand_total_mismatch", "payment_schedule_mismatch",
)
SANITY_CHECK_SEVERITY_VALUES = ("warning", "critical")


def upgrade() -> None:
    op.add_column("offers", sa.Column("sanity_check_status", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("sanity_check_summary", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_offers_sanity_check_status",
        "offers",
        f"sanity_check_status IN {SANITY_CHECK_STATUS_VALUES}",
    )

    op.create_table(
        "offer_sanity_findings",
        sa.Column("finding_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("offer_id", sa.BigInteger(), nullable=False),
        sa.Column("issue_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("field_path", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            f"issue_type IN {SANITY_CHECK_ISSUE_TYPE_VALUES}", name="ck_offer_sanity_findings_issue_type"
        ),
        sa.CheckConstraint(
            f"severity IN {SANITY_CHECK_SEVERITY_VALUES}", name="ck_offer_sanity_findings_severity"
        ),
        sa.PrimaryKeyConstraint("finding_id"),
    )
    op.create_index("ix_offer_sanity_findings_offer_id", "offer_sanity_findings", ["offer_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_sanity_findings_offer_id", table_name="offer_sanity_findings")
    op.drop_table("offer_sanity_findings")

    op.drop_constraint("ck_offers_sanity_check_status", "offers", type_="check")
    op.drop_column("offers", "sanity_check_summary")
    op.drop_column("offers", "sanity_check_status")
