"""add offer_items payment/delivery terms overrides; convert
documents.debug_extraction_trace from json to jsonb for consistency with
every other structured column in the schema

Revision ID: 0004_item_terms_jsonb
Revises: 0003_extraction_tables
Create Date: 2026-09-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
# (kept <=32 chars: alembic_version.version_num is VARCHAR(32) by default)
revision: str = "0004_item_terms_jsonb"
down_revision: Union[str, None] = "0003_extraction_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "offer_items", sa.Column("payment_terms_override_original", sa.Text(), nullable=True)
    )
    op.add_column(
        "offer_items", sa.Column("delivery_terms_override_original", sa.Text(), nullable=True)
    )

    op.alter_column(
        "documents",
        "debug_extraction_trace",
        type_=JSONB(),
        postgresql_using="debug_extraction_trace::jsonb",
    )


def downgrade() -> None:
    op.alter_column(
        "documents",
        "debug_extraction_trace",
        type_=sa.JSON(),
        postgresql_using="debug_extraction_trace::json",
    )

    op.drop_column("offer_items", "delivery_terms_override_original")
    op.drop_column("offer_items", "payment_terms_override_original")
