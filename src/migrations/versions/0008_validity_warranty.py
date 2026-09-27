"""add offers.validity_terms_original and offers.warranty_terms_original -
offer-wide validity period and warranty terms, verbatim, mirroring the
existing payment_terms_original/delivery_terms_original pattern

Revision ID: 0008_validity_warranty
Revises: 0007_verified_findings
Create Date: 2026-09-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_validity_warranty"
down_revision: Union[str, None] = "0007_verified_findings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("offers", sa.Column("validity_terms_original", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("warranty_terms_original", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("offers", "warranty_terms_original")
    op.drop_column("offers", "validity_terms_original")
