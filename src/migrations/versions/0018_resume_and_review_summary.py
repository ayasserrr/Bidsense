"""pipeline checkpoints, the summary/chase-list stage, its queue reads

Two things, both schema, nothing runtime.

1. `offers.pipeline_checkpoint` / `pipeline_checkpoint_updated_at`. Today a
   mid-pipeline failure - a chunk the gateway timed out on, verification
   losing the connection - means the ONLY recovery is re-running the whole
   pipeline from `parse`: every file goes back through Parsing Studio, and the
   entire (chunked, most expensive) extraction runs again, even when
   extraction itself succeeded and the failure was three stages later. This
   column is where `pipeline.resume` caches whatever pre-persist artifacts a
   run has produced so far - the extraction payload, then the sanity-check
   result, then the verification result - so the next attempt on this offer
   can start from wherever the last one actually got to. It is cleared the
   moment `persist` succeeds: the offer itself is the durable record after
   that, and post-persist stages (taxonomy, completeness, summary) already
   have their own re-run endpoints and never needed this.

2. `offers.review_chase_items` / `review_headline` / `review_email_subject` /
   `review_email_body` / `review_summary_generated_at` - the detail screen's
   "read this first" panel and its clarification-email draft. Deliberately
   NOT a new LLM output: both are composed from findings and completeness
   gaps this offer's own pipeline already verified, in `pipeline/node/
   summary.py`. A fresh LLM paragraph summarising the offer would be the
   first thing a reviewer reads and the one part of it nothing downstream
   re-checks - worse wrong than absent. `review_chase_items` is a JSON list
   because it just as often has zero items ("nothing to chase") as three, and
   the design's fixed count of three was never a real constraint.

3. `ck_pipeline_jobs_kind` gains `'summary'` - a job kind of its own so a
   reviewer can regenerate this after correcting a completeness override,
   the same way completeness and taxonomy are already independently
   re-runnable, without re-reading the offer's documents.

Revision ID: 0018_resume_and_review_summary
Revises: 0017_revamp_schema
Create Date: 2026-09-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0018_resume_and_review_summary"
down_revision: Union[str, None] = "0017_revamp_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JOB_KIND_CONSTRAINT = "ck_pipeline_jobs_kind"
PREVIOUS_KINDS = ("offer_pipeline", "completeness", "taxonomy")
CURRENT_KINDS = ("offer_pipeline", "completeness", "taxonomy", "summary")


def upgrade() -> None:
    op.add_column(
        "offers",
        sa.Column(
            "pipeline_checkpoint",
            JSONB,
            nullable=True,
            comment=(
                "Pre-persist stage outputs from the most recent attempt on this offer - "
                "extraction_payload, sanity_check_result, verification_result, each present only "
                "once that stage has succeeded. Cleared when persist succeeds."
            ),
        ),
    )
    op.add_column(
        "offers",
        sa.Column("pipeline_checkpoint_updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("offers", sa.Column("review_chase_items", JSONB, nullable=True))
    op.add_column("offers", sa.Column("review_headline", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("review_email_subject", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("review_email_body", sa.Text(), nullable=True))
    op.add_column(
        "offers", sa.Column("review_summary_generated_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.drop_constraint(JOB_KIND_CONSTRAINT, "pipeline_jobs", type_="check")
    op.create_check_constraint(JOB_KIND_CONSTRAINT, "pipeline_jobs", f"kind IN {CURRENT_KINDS}")


def downgrade() -> None:
    remaining = op.get_bind().execute(
        sa.text("SELECT count(*) FROM pipeline_jobs WHERE kind = 'summary'")
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} job(s) of kind 'summary' exist; the previous schema cannot represent "
            f"them. Delete those rows before downgrading."
        )
    op.drop_constraint(JOB_KIND_CONSTRAINT, "pipeline_jobs", type_="check")
    op.create_check_constraint(JOB_KIND_CONSTRAINT, "pipeline_jobs", f"kind IN {PREVIOUS_KINDS}")

    op.drop_column("offers", "review_summary_generated_at")
    op.drop_column("offers", "review_email_body")
    op.drop_column("offers", "review_email_subject")
    op.drop_column("offers", "review_headline")
    op.drop_column("offers", "review_chase_items")

    op.drop_column("offers", "pipeline_checkpoint_updated_at")
    op.drop_column("offers", "pipeline_checkpoint")
