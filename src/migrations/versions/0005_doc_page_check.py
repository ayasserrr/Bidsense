"""add missing CHECK constraint on document_pages.extraction_method (every
other enum-backed text column already has one) and align its declared type
with the rest of the schema (varchar -> text; identical storage in
Postgres, this is purely for model/DB consistency)

Revision ID: 0005_doc_page_check
Revises: 0004_item_terms_jsonb
Create Date: 2026-09-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_doc_page_check"
down_revision: Union[str, None] = "0004_item_terms_jsonb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXTRACTION_METHOD_VALUES = ("pdfplumber", "plain_text", "failed")


def upgrade() -> None:
    op.alter_column("document_pages", "extraction_method", type_=sa.Text())
    op.create_check_constraint(
        "ck_document_pages_extraction_method",
        "document_pages",
        f"extraction_method IN {EXTRACTION_METHOD_VALUES}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_document_pages_extraction_method", "document_pages", type_="check")
    op.alter_column("document_pages", "extraction_method", type_=sa.String())
