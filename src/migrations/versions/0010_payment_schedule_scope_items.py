"""add offer_payment_schedules.scope_item_ids - which real offer_items a
payment milestone's scope actually covers, resolved by extraction from the
document's own reference (a row-number range, a named section) rather than
left as a free-text scope_label a reader has to manually cross-reference

Revision ID: 0010_payment_schedule_scope
Revises: 0009_mfr_product_equip_type
Create Date: 2026-09-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010_payment_schedule_scope"
down_revision: Union[str, None] = "0009_mfr_product_equip_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "offer_payment_schedules",
        sa.Column("scope_item_ids", postgresql.ARRAY(sa.BigInteger()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("offer_payment_schedules", "scope_item_ids")
