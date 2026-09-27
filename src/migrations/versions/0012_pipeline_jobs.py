"""background pipeline jobs, offer ownership, and a persisted marker

Three related changes, all in service of running the pipeline server-side
instead of from the browser:

1. `pipeline_jobs` - the record of a backgrounded run. This row, not an
   in-memory task handle, is what a status poll reads, which is what lets a
   reviewer close the tab during a twenty-minute extraction and come back to
   find it finished.

2. `offers.created_by_user_id` / `created_by_department` - the offer's owner,
   for the department scoping the client asked for. Existing rows keep a NULL
   owner and stay visible to everyone: they predate sign-in, and hiding them
   from every non-admin would make the app look empty after the upgrade.

3. `offers.persisted_at` - set when an offer completes the persist stage.
   Until now the offers list stayed clean only because a failed run deleted its
   offer outright from the browser; with the run server-side the offer and its
   files are kept so a retry does not mean uploading everything again, and this
   column is what keeps a half-finished one out of the list.

Existing offers are backfilled as persisted - they are all finished offers, and
leaving them NULL would empty the list.

Revision ID: 0012_pipeline_jobs
Revises: 0011_users_auth
Create Date: 2026-09-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_pipeline_jobs"
down_revision: Union[str, None] = "0011_users_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JOB_KINDS = ("offer_pipeline", "completeness", "taxonomy")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")


def upgrade() -> None:
    op.create_table(
        "pipeline_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "offer_id",
            sa.BigInteger(),
            sa.ForeignKey("offers.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("stages", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("current_stage", sa.Text(), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_stage", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by_department", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"kind IN {JOB_KINDS}", name="ck_pipeline_jobs_kind"),
        sa.CheckConstraint(f"status IN {JOB_STATUSES}", name="ck_pipeline_jobs_status"),
    )
    op.create_index("ix_pipeline_jobs_kind", "pipeline_jobs", ["kind"])
    op.create_index("ix_pipeline_jobs_status", "pipeline_jobs", ["status"])
    op.create_index("ix_pipeline_jobs_offer_id", "pipeline_jobs", ["offer_id"])
    op.create_index("ix_pipeline_jobs_created_at", "pipeline_jobs", ["created_at"])
    op.create_index(
        "ix_pipeline_jobs_created_by_user_id", "pipeline_jobs", ["created_by_user_id"]
    )
    op.create_index(
        "ix_pipeline_jobs_created_by_department", "pipeline_jobs", ["created_by_department"]
    )

    op.add_column(
        "offers",
        sa.Column(
            "created_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "offers",
        sa.Column("created_by_department", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column("offers", sa.Column("persisted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_offers_created_by_user_id", "offers", ["created_by_user_id"])
    op.create_index("ix_offers_created_by_department", "offers", ["created_by_department"])
    op.create_index("ix_offers_persisted_at", "offers", ["persisted_at"])

    # Every offer that already exists got there by completing persist, back
    # when that was the only way an offer row survived at all.
    op.execute("UPDATE offers SET persisted_at = created_at WHERE persisted_at IS NULL")


def downgrade() -> None:
    op.drop_index("ix_offers_persisted_at", table_name="offers")
    op.drop_index("ix_offers_created_by_department", table_name="offers")
    op.drop_index("ix_offers_created_by_user_id", table_name="offers")
    op.drop_column("offers", "persisted_at")
    op.drop_column("offers", "created_by_department")
    op.drop_column("offers", "created_by_user_id")

    op.drop_index("ix_pipeline_jobs_created_by_department", table_name="pipeline_jobs")
    op.drop_index("ix_pipeline_jobs_created_by_user_id", table_name="pipeline_jobs")
    op.drop_index("ix_pipeline_jobs_created_at", table_name="pipeline_jobs")
    op.drop_index("ix_pipeline_jobs_offer_id", table_name="pipeline_jobs")
    op.drop_index("ix_pipeline_jobs_status", table_name="pipeline_jobs")
    op.drop_index("ix_pipeline_jobs_kind", table_name="pipeline_jobs")
    op.drop_table("pipeline_jobs")
