"""initial: offers, documents

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "offers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("root_offer_id", sa.BigInteger(), nullable=True),
        sa.Column("parent_offer_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active_latest", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["root_offer_id"], ["offers.id"]),
        sa.ForeignKeyConstraint(["parent_offer_id"], ["offers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_offers_root_offer_id", "offers", ["root_offer_id"])
    op.create_index("ix_offers_parent_offer_id", "offers", ["parent_offer_id"])

    op.create_table(
        "documents",
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("file_type", sa.Text(), nullable=False),
        sa.Column("file_checksum", sa.Text(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("offer_id", sa.BigInteger(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("debug_extraction_trace", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"]),
        sa.PrimaryKeyConstraint("document_id"),
        sa.UniqueConstraint("file_checksum"),
    )
    op.create_index("ix_documents_file_checksum", "documents", ["file_checksum"])
    op.create_index("ix_documents_offer_id", "documents", ["offer_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_offer_id", table_name="documents")
    op.drop_index("ix_documents_file_checksum", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_offers_parent_offer_id", table_name="offers")
    op.drop_index("ix_offers_root_offer_id", table_name="offers")
    op.drop_table("offers")
