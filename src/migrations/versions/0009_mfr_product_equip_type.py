"""add offers.manufacturer_original, offers.product_name_original,
offers.offer_date_original, and offer_items.equipment_type_original -
offer-wide manufacturer/product/issue-date, and a granular per-item
equipment type descriptor distinct from item_category's coarse bucket

Revision ID: 0009_mfr_product_equip_type
Revises: 0008_validity_warranty
Create Date: 2026-09-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_mfr_product_equip_type"
down_revision: Union[str, None] = "0008_validity_warranty"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("offers", sa.Column("manufacturer_original", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("product_name_original", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("offer_date_original", sa.Text(), nullable=True))
    op.add_column("offer_items", sa.Column("equipment_type_original", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("offer_items", "equipment_type_original")
    op.drop_column("offers", "offer_date_original")
    op.drop_column("offers", "product_name_original")
    op.drop_column("offers", "manufacturer_original")
