"""offer completeness checklist, its results, and override evidence

The client's headline requirement: the system reports what an offer FAILS to
state, not only what it does. Three tables:

`completeness_requirements` holds the twenty-item checklist as data rather than
code, because he will revise it and an edit must not need a deployment. It is
seeded from helpers/completeness_checklist.py at startup.

`offer_completeness_results` holds one verdict per requirement per offer, with
the requirement's label and mandatory flag snapshotted onto the row - so an old
report stays readable against the rule it was actually judged under, instead of
silently re-labelling itself when the checklist changes.

`completeness_evidence` holds the files a reviewer attaches when overriding a
verdict. Deliberately not `documents` rows: that table's checksum is globally
unique (so an email already seen elsewhere would silently fail to attach) and
everything under it is fed to extraction as source text (so evidence stored
there would contaminate the offer it comments on).

The check constraint `override_needs_evidence` is the client's own rule in the
database: filling a gap requires a document. "He told me on the phone" is not
an override.

`offer_items.source_document_id` lands here too - it is what lets the report
say which file evidenced a discipline when several were uploaded together.

Revision ID: 0013_completeness
Revises: 0012_pipeline_jobs
Create Date: 2026-09-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_completeness"
down_revision: Union[str, None] = "0012_pipeline_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GROUPS = ("technical", "commercial")
VERDICTS = ("present", "missing", "not_applicable", "unclear")
EVIDENCE_KINDS = ("email", "letter", "revised_offer", "other")


def upgrade() -> None:
    op.create_table(
        "completeness_requirements",
        sa.Column("requirement_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("requirement_group", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"requirement_group IN {GROUPS}", name="ck_completeness_requirements_group"
        ),
    )
    op.create_index("ix_completeness_requirements_code", "completeness_requirements", ["code"])
    op.create_index(
        "ix_completeness_requirements_group", "completeness_requirements", ["requirement_group"]
    )
    op.create_index(
        "ix_completeness_requirements_is_active", "completeness_requirements", ["is_active"]
    )

    op.create_table(
        "completeness_evidence",
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "offer_id",
            sa.BigInteger(),
            sa.ForeignKey("offers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requirement_code", sa.Text(), nullable=False),
        sa.Column("evidence_kind", sa.Text(), nullable=False, server_default="email"),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("file_type", sa.Text(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        # Deliberately NOT unique - one forwarded email can evidence several
        # gaps on several offers.
        sa.Column("file_checksum", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"evidence_kind IN {EVIDENCE_KINDS}", name="ck_completeness_evidence_kind"
        ),
    )
    op.create_index("ix_completeness_evidence_offer_id", "completeness_evidence", ["offer_id"])
    op.create_index(
        "ix_completeness_evidence_requirement_code", "completeness_evidence", ["requirement_code"]
    )
    op.create_index(
        "ix_completeness_evidence_file_checksum", "completeness_evidence", ["file_checksum"]
    )

    op.create_table(
        "offer_completeness_results",
        sa.Column("result_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "offer_id",
            sa.BigInteger(),
            sa.ForeignKey("offers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requirement_code", sa.Text(), nullable=False),
        sa.Column("requirement_label", sa.Text(), nullable=False),
        sa.Column("requirement_group", sa.Text(), nullable=False),
        sa.Column("was_mandatory", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("extracted_value", sa.Text(), nullable=True),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=True),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.document_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_filename", sa.Text(), nullable=True),
        sa.Column("source_page_number", sa.Integer(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("is_overridden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("override_verdict", sa.Text(), nullable=True),
        sa.Column("override_value", sa.Text(), nullable=True),
        sa.Column("override_note", sa.Text(), nullable=True),
        sa.Column(
            "override_evidence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("completeness_evidence.evidence_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "overridden_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("overridden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "offer_id", "requirement_code", name="uq_completeness_offer_requirement"
        ),
        sa.CheckConstraint(f"verdict IN {VERDICTS}", name="ck_completeness_results_verdict"),
        sa.CheckConstraint(
            f"override_verdict IS NULL OR override_verdict IN {VERDICTS}",
            name="ck_completeness_results_override_verdict",
        ),
        sa.CheckConstraint(
            "is_overridden = false OR override_evidence_id IS NOT NULL",
            name="ck_completeness_results_override_needs_evidence",
        ),
    )
    op.create_index(
        "ix_offer_completeness_results_offer_id", "offer_completeness_results", ["offer_id"]
    )
    op.create_index(
        "ix_offer_completeness_results_code", "offer_completeness_results", ["requirement_code"]
    )
    op.create_index(
        "ix_offer_completeness_results_group", "offer_completeness_results", ["requirement_group"]
    )
    op.create_index(
        "ix_offer_completeness_results_verdict", "offer_completeness_results", ["verdict"]
    )

    op.add_column(
        "offer_items",
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.document_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("offer_items", "source_document_id")
    op.drop_index("ix_offer_completeness_results_verdict", table_name="offer_completeness_results")
    op.drop_index("ix_offer_completeness_results_group", table_name="offer_completeness_results")
    op.drop_index("ix_offer_completeness_results_code", table_name="offer_completeness_results")
    op.drop_index("ix_offer_completeness_results_offer_id", table_name="offer_completeness_results")
    op.drop_table("offer_completeness_results")
    op.drop_index("ix_completeness_evidence_file_checksum", table_name="completeness_evidence")
    op.drop_index("ix_completeness_evidence_requirement_code", table_name="completeness_evidence")
    op.drop_index("ix_completeness_evidence_offer_id", table_name="completeness_evidence")
    op.drop_table("completeness_evidence")
    op.drop_index("ix_completeness_requirements_is_active", table_name="completeness_requirements")
    op.drop_index("ix_completeness_requirements_group", table_name="completeness_requirements")
    op.drop_index("ix_completeness_requirements_code", table_name="completeness_requirements")
    op.drop_table("completeness_requirements")
