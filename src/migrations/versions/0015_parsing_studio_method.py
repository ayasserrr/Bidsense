"""document pages read by Parsing Studio

Parsing moved from a local pdfplumber process pool to the corporate Parsing
Studio service, so a page can now carry `extraction_method = 'parsing_studio'`.
The old values stay allowed: pages parsed before the move still exist and must
still load.

Revision ID: 0015_parsing_studio_method
Revises: 0014_taxonomy
Create Date: 2026-09-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015_parsing_studio_method"
down_revision: Union[str, None] = "0014_taxonomy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "ck_document_pages_extraction_method"
PREVIOUS_VALUES = ("pdfplumber", "plain_text", "failed")
CURRENT_VALUES = ("parsing_studio", "pdfplumber", "plain_text", "failed")


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "document_pages", type_="check")
    op.create_check_constraint(
        CONSTRAINT, "document_pages", f"extraction_method IN {CURRENT_VALUES}"
    )


def downgrade() -> None:
    # Refuse rather than rewrite: relabelling Parsing Studio pages as
    # 'pdfplumber' would be a lie about how they were read, and 'failed' would
    # destroy text that is perfectly good. Re-parse or delete them first.
    remaining = op.get_bind().execute(
        sa.text("SELECT count(*) FROM document_pages WHERE extraction_method = 'parsing_studio'")
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} document page(s) were read by Parsing Studio; the previous schema "
            f"cannot represent them. Delete or re-parse those documents before downgrading."
        )
    op.drop_constraint(CONSTRAINT, "document_pages", type_="check")
    op.create_check_constraint(
        CONSTRAINT, "document_pages", f"extraction_method IN {PREVIOUS_VALUES}"
    )
