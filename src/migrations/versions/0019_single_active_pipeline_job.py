"""one active OFFER_PIPELINE job per offer

An adversarial review of this session's pipeline-resume work found that
nothing stopped two OFFER_PIPELINE jobs from being QUEUED/RUNNING for the
same offer at once - a double-click on "rerun", or two people acting on the
same failed offer together, and nothing in the route, controller or
dispatcher would refuse the second one. Two such jobs racing would both call
`determine_resume_point`, both write to the same `offers.pipeline_checkpoint`
(an unlocked read-modify-write - see `pipeline/resume.py`), and both run
`PersistController.persist_offer`'s delete-then-insert of the offer's child
rows, with no `SELECT ... FOR UPDATE` - a real risk of lost updates or
interleaved rows, not just a checkpoint oddity.

`JobController.create_job` now checks for an existing active job first (see
`OfferPipelineAlreadyRunningError`), but that check and the INSERT are not
atomic on their own - two requests can both pass the check before either
commits. This partial unique index is what actually closes the race: the
second INSERT hits it and fails with an IntegrityError, which `create_job`
catches and turns into the same clean error as the pre-check.

Only OFFER_PIPELINE jobs are covered. Completeness/taxonomy/summary rechecks
are cheap, single-request, non-file-touching jobs (see `JobController`'s own
QUEUED_KIND comment) and were never part of what this review flagged.

If this fails to apply against an existing deployment, it means that
deployment already has two QUEUED/RUNNING OFFER_PIPELINE jobs sitting against
the same offer_id - itself evidence of the bug this migration closes. Resolve
those rows (cancel or fail one of each pair) before retrying the upgrade.

Revision ID: 0019_single_active_pipeline_job
Revises: 0018_resume_and_review_summary
Create Date: 2026-09-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019_single_active_pipeline_job"
down_revision: Union[str, None] = "0018_resume_and_review_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ux_pipeline_jobs_active_offer_pipeline"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "pipeline_jobs",
        ["offer_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'offer_pipeline' AND status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="pipeline_jobs")
