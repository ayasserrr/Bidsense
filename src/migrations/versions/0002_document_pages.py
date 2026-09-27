"""add document_pages table

Revision ID: 0002_document_pages
Revises: 0001_initial
Create Date: 2026-09-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "0002_document_pages"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_pages",
        sa.Column("page_id", UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("unit_location", JSONB(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("raw_tables", JSONB(), nullable=True),
        sa.Column("extraction_method", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["documents.document_id"]),
        sa.PrimaryKeyConstraint("page_id"),
    )
    op.create_index("ix_document_pages_file_id", "document_pages", ["file_id"])


def downgrade() -> None:
    op.drop_index("ix_document_pages_file_id", table_name="document_pages")
    op.drop_table("document_pages")
