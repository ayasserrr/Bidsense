"""equipment taxonomy - the ten disciplines and what sits under them

The client's early example ("HVAC > Chiller / VRF / VRV / Fan Coil") turned out
to describe the same ten disciplines his checklist asks about, so this is one
axis rather than two: `taxonomy_nodes` roots share their codes with
`completeness_requirements`, and a resolved item is direct evidence that its
discipline is covered.

`taxonomy_aliases` is the resolution table. Seeded aliases carry the obvious
synonyms; a reviewer's correction is stored as a LEARNED alias keyed on the
normalised source text, which is what makes the correction survive re-persist -
`_clear_existing_offer_data` wipes and rewrites `offer_items` every time, so a
fix written onto the item itself would be lost on the next run.

Learned aliases start unapproved on purpose. One reviewer's correction becoming
an instant, global, permanent rule is how a taxonomy quietly rots.

`offer_items.taxonomy_node_id` is the resolved link. The taxonomy deliberately
never enters the extraction schema - adding a category enum to every line item
would lengthen the output and make the measured null-scalar collapse worse.

Revision ID: 0014_taxonomy
Revises: 0013_completeness
Create Date: 2026-09-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_taxonomy"
down_revision: Union[str, None] = "0013_completeness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "taxonomy_nodes",
        sa.Column("node_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "parent_node_id",
            sa.BigInteger(),
            sa.ForeignKey("taxonomy_nodes.node_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_taxonomy_nodes_parent", "taxonomy_nodes", ["parent_node_id"])
    op.create_index("ix_taxonomy_nodes_code", "taxonomy_nodes", ["code"])
    op.create_index("ix_taxonomy_nodes_level", "taxonomy_nodes", ["level"])
    op.create_index("ix_taxonomy_nodes_is_active", "taxonomy_nodes", ["is_active"])

    op.create_table(
        "taxonomy_aliases",
        sa.Column("alias_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("taxonomy_nodes.node_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias_normalized", sa.Text(), nullable=False),
        sa.Column("alias_display", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.Text(), nullable=False, server_default="seed"),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("alias_normalized", name="uq_taxonomy_alias_normalized"),
    )
    op.create_index("ix_taxonomy_aliases_node_id", "taxonomy_aliases", ["node_id"])
    op.create_index("ix_taxonomy_aliases_normalized", "taxonomy_aliases", ["alias_normalized"])
    op.create_index("ix_taxonomy_aliases_source", "taxonomy_aliases", ["source"])
    op.create_index("ix_taxonomy_aliases_is_approved", "taxonomy_aliases", ["is_approved"])

    op.add_column(
        "offer_items",
        sa.Column(
            "taxonomy_node_id",
            sa.BigInteger(),
            sa.ForeignKey("taxonomy_nodes.node_id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_offer_items_taxonomy_node_id", "offer_items", ["taxonomy_node_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_items_taxonomy_node_id", table_name="offer_items")
    op.drop_column("offer_items", "taxonomy_node_id")
    op.drop_index("ix_taxonomy_aliases_is_approved", table_name="taxonomy_aliases")
    op.drop_index("ix_taxonomy_aliases_source", table_name="taxonomy_aliases")
    op.drop_index("ix_taxonomy_aliases_normalized", table_name="taxonomy_aliases")
    op.drop_index("ix_taxonomy_aliases_node_id", table_name="taxonomy_aliases")
    op.drop_table("taxonomy_aliases")
    op.drop_index("ix_taxonomy_nodes_is_active", table_name="taxonomy_nodes")
    op.drop_index("ix_taxonomy_nodes_level", table_name="taxonomy_nodes")
    op.drop_index("ix_taxonomy_nodes_code", table_name="taxonomy_nodes")
    op.drop_index("ix_taxonomy_nodes_parent", table_name="taxonomy_nodes")
    op.drop_table("taxonomy_nodes")
