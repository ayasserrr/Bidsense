"""checklist wording the new rules are judged under, and one ambiguous alias

Seeding is insert-only, on purpose: an admin's edit to a checklist row and a
reviewer's learned alias both live in the database and must survive a restart.
The cost is that a change to the SEEDED text never reaches a deployment that has
already been seeded - and two of these are read by the model on every run, so
leaving them behind would mean the checker judges by a rule the code no longer
holds.

Hence this migration, which changes only what is still exactly as it was
seeded:

  * COM_DELIVERY_LEAD_TIME now says that stock availability is not a lead time,
    matching `commercial_terms.states_lead_time`.
  * COM_MAINTENANCE now says that installation labour and maintenance-free parts
    are not a maintenance offering, matching `derive_scope_answer`.
  * the alias "copper pipe" is removed from Plumbing ▸ Piping. Copper is the
    material of both a water line and a refrigerant line, so the bare phrase
    names no discipline - and as a Plumbing alias it turned VRV refrigerant
    piping into Plumbing coverage on an offer that quotes no plumbing at all.
    Removed rather than moved: unmatched, the line reaches the model with its
    full description, which is where a genuinely ambiguous phrase belongs.

Every statement is guarded by the old value. A row an admin has since edited,
or an alias a reviewer has re-pointed, is left exactly as they left it.

Revision ID: 0016_checklist_rules
Revises: 0015_parsing_studio_method
Create Date: 2026-09-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016_checklist_rules"
down_revision: Union[str, None] = "0015_parsing_studio_method"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (code, text as it was seeded, text as it is seeded now)
DESCRIPTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "COM_DELIVERY_LEAD_TIME",
        "How long delivery takes - a number of days or weeks, a delivery date, or a "
        "period counted from a stated trigger such as order confirmation or receipt of "
        "the advance payment. A bare Incoterm is NOT a lead time.",
        "How long delivery takes - a number of days or weeks, a delivery date, or a "
        "period counted from a stated trigger such as order confirmation or receipt of "
        "the advance payment. A bare Incoterm is NOT a lead time. Neither is stock "
        "availability: 'Ex-stock', 'Based on the available stock' and 'Subject to prior "
        "sale' say where the goods are, not when they arrive.",
    ),
    (
        "COM_MAINTENANCE",
        "Whether after-sales maintenance or a service contract is offered, and on what "
        "terms - free during warranty, chargeable, or excluded.",
        "Whether after-sales maintenance or a service contract is offered, and on what "
        "terms - free during warranty, chargeable, or excluded. Installation or "
        "commissioning labour is NOT maintenance, and neither is a maintenance-free "
        "component or a maintenance bypass switch - those are parts, not a service.",
    ),
)

AMBIGUOUS_ALIAS = "copper pipe"
ALIAS_NODE_CODE = "TECH_PLUMBING__PIPING"

_UPDATE_DESCRIPTION = sa.text(
    "UPDATE completeness_requirements SET description = :new_text, updated_at = now() "
    "WHERE code = :code AND description = :old_text"
)


def _retext(bind, code: str, old_text: str, new_text: str) -> None:
    bind.execute(
        _UPDATE_DESCRIPTION, {"code": code, "old_text": old_text, "new_text": new_text}
    )


def upgrade() -> None:
    bind = op.get_bind()
    for code, old_text, new_text in DESCRIPTIONS:
        _retext(bind, code, old_text, new_text)

    # Only the seeded alias. A reviewer who learned this wording themselves made
    # a deliberate decision about their own offers, and it is not this
    # migration's place to overrule it.
    bind.execute(
        sa.text(
            "DELETE FROM taxonomy_aliases WHERE alias_normalized = :alias AND source = 'seed'"
        ),
        {"alias": AMBIGUOUS_ALIAS},
    )


def downgrade() -> None:
    bind = op.get_bind()
    for code, old_text, new_text in DESCRIPTIONS:
        _retext(bind, code, new_text, old_text)

    bind.execute(
        sa.text(
            "INSERT INTO taxonomy_aliases "
            "(node_id, alias_normalized, alias_display, source, is_approved, created_at) "
            "SELECT node_id, :alias, :alias, 'seed', true, now() FROM taxonomy_nodes "
            "WHERE code = :node_code "
            "ON CONFLICT (alias_normalized) DO NOTHING"
        ),
        {"alias": AMBIGUOUS_ALIAS, "node_code": ALIAS_NODE_CODE},
    )
