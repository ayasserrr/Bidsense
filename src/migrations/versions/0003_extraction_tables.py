"""add extraction-stage tables (currencies, suppliers, projects, offer_items,
tech_specs, included_features, inclusions_exclusions, offer_payment_schedules,
offer_attachments, supplier_contacts) and offer-level extraction columns

Revision ID: 0003_extraction_tables
Revises: 0002_document_pages
Create Date: 2026-09-04

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "0003_extraction_tables"
down_revision: Union[str, None] = "0002_document_pages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The fixed ISO-4217 set the extraction prompts are constrained to - kept in
# sync with models.enums.OfferEnum.CurrencyCode by hand since a migration
# can't safely import live application code (the enum may change after this
# migration is history).
CURRENCY_SEED = [
    ("USD", "US Dollar", "$"),
    ("EUR", "Euro", "€"),
    ("GBP", "British Pound", "£"),
    ("EGP", "Egyptian Pound", "E£"),
    ("SAR", "Saudi Riyal", None),
    ("AED", "UAE Dirham", None),
    ("QAR", "Qatari Riyal", None),
    ("KWD", "Kuwaiti Dinar", None),
    ("BHD", "Bahraini Dinar", None),
    ("OMR", "Omani Rial", None),
    ("JOD", "Jordanian Dinar", None),
    ("LYD", "Libyan Dinar", None),
    ("IQD", "Iraqi Dinar", None),
    ("LBP", "Lebanese Pound", None),
    ("CHF", "Swiss Franc", None),
    ("JPY", "Japanese Yen", "¥"),
    ("CNY", "Chinese Yuan", "¥"),
    ("INR", "Indian Rupee", "₹"),
    ("TRY", "Turkish Lira", None),
    ("CAD", "Canadian Dollar", "$"),
    ("AUD", "Australian Dollar", "$"),
    ("ZAR", "South African Rand", None),
    ("SEK", "Swedish Krona", None),
    ("NOK", "Norwegian Krone", None),
    ("DKK", "Danish Krone", None),
    ("KRW", "South Korean Won", "₩"),
    ("SGD", "Singapore Dollar", "$"),
]

ITEM_CATEGORY_VALUES = (
    "equipment", "accessory", "spare_part", "installation", "service",
    "warranty", "training", "software", "civil_works", "transportation", "other",
)
PRICE_BASIS_VALUES = ("fixed", "percentage_of_parent", "included_no_charge", "tbd")
ENTITY_TYPE_VALUES = ("item", "offer")
ENTRY_TYPE_VALUES = ("include", "exclude")


def upgrade() -> None:
    currencies_table = op.create_table(
        "currencies",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("code"),
    )
    op.bulk_insert(
        currencies_table,
        [{"code": code, "name": name, "symbol": symbol} for code, name, symbol in CURRENCY_SEED],
    )

    op.create_table(
        "suppliers",
        sa.Column("supplier_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("supplier_name", sa.Text(), nullable=False),
        sa.Column("supplier_code", sa.Text(), nullable=True),
        sa.Column("supplier_aliases", ARRAY(sa.Text()), nullable=True),
        sa.Column("is_sole_agent_for", ARRAY(sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("supplier_id"),
    )

    op.create_table(
        "projects",
        sa.Column("project_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_name", sa.Text(), nullable=False),
        sa.Column("project_aliases", ARRAY(sa.Text()), nullable=True),
        sa.Column("client_name", sa.Text(), nullable=True),
        sa.Column("client_aliases", ARRAY(sa.Text()), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("project_id"),
    )

    op.create_table(
        "supplier_contacts",
        sa.Column("contact_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), nullable=False),
        sa.Column("contact_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("source_document_id", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.supplier_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["documents.document_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("contact_id"),
    )
    op.create_index("ix_supplier_contacts_supplier_id", "supplier_contacts", ["supplier_id"])

    # --- offers: add extraction-stage columns to the existing table ---
    op.add_column("offers", sa.Column("supplier_id", sa.BigInteger(), nullable=True))
    op.add_column("offers", sa.Column("project_id", sa.BigInteger(), nullable=True))
    op.add_column("offers", sa.Column("offer_ref", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("project_name_original", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("client_name_original", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("project_location_original", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("payment_terms_original", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("price_currency_original", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("currency_primary", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("grand_total", sa.Numeric(), nullable=True))
    op.add_column("offers", sa.Column("grand_total_currency", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("tax_treatment_original", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("incoterm", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("delivery_terms_original", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("offer_signed_by_original", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("general_notes_original", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("extra_attributes", JSONB(), nullable=True))

    op.create_foreign_key(
        "fk_offers_supplier_id", "offers", "suppliers", ["supplier_id"], ["supplier_id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_offers_project_id", "offers", "projects", ["project_id"], ["project_id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_offers_currency_primary", "offers", "currencies", ["currency_primary"], ["code"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_offers_grand_total_currency", "offers", "currencies", ["grand_total_currency"], ["code"],
        ondelete="SET NULL",
    )
    op.create_index("ix_offers_supplier_id", "offers", ["supplier_id"])
    op.create_index("ix_offers_project_id", "offers", ["project_id"])

    # --- offer_items ---
    op.create_table(
        "offer_items",
        sa.Column("item_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("offer_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_item_id", sa.BigInteger(), nullable=True),
        sa.Column("item_code", sa.Text(), nullable=True),
        sa.Column("item_group_label", sa.Text(), nullable=True),
        sa.Column("item_category", sa.Text(), nullable=False),
        sa.Column("is_optional", sa.Boolean(), nullable=False),
        sa.Column("is_alternate", sa.Boolean(), nullable=False),
        sa.Column("alternate_group_id", sa.Integer(), nullable=True),
        sa.Column("is_lump_sum", sa.Boolean(), nullable=False),
        sa.Column("price_basis", sa.Text(), nullable=False),
        sa.Column("percentage_value", sa.Numeric(), nullable=True),
        sa.Column("discount_amount", sa.Numeric(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("model_number", sa.Text(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("unit_price", sa.Numeric(), nullable=True),
        sa.Column("total_price", sa.Numeric(), nullable=True),
        sa.Column("price_currency", sa.Text(), nullable=True),
        sa.Column("price_currency_original", sa.Text(), nullable=True),
        sa.Column("stated_subtotal_amount", sa.Numeric(), nullable=True),
        sa.Column("stated_subtotal_currency", sa.Text(), nullable=True),
        sa.Column("tax_treatment_override_original", sa.Text(), nullable=True),
        sa.Column("incoterm_override", sa.Text(), nullable=True),
        sa.Column("availability_original_text", sa.Text(), nullable=True),
        sa.Column("extra_attributes", JSONB(), nullable=True),
        sa.Column("source_page_number", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_item_id"], ["offer_items.item_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["price_currency"], ["currencies.code"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["stated_subtotal_currency"], ["currencies.code"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            f"item_category IN {ITEM_CATEGORY_VALUES}", name="ck_offer_items_item_category"
        ),
        sa.CheckConstraint(f"price_basis IN {PRICE_BASIS_VALUES}", name="ck_offer_items_price_basis"),
        sa.PrimaryKeyConstraint("item_id"),
    )
    op.create_index("ix_offer_items_offer_id", "offer_items", ["offer_id"])
    op.create_index("ix_offer_items_parent_item_id", "offer_items", ["parent_item_id"])

    # --- tech_specs ---
    op.create_table(
        "tech_specs",
        sa.Column("spec_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("spec_group", sa.Text(), nullable=False),
        sa.Column("spec_name", sa.Text(), nullable=False),
        sa.Column("spec_value", sa.Text(), nullable=False),
        sa.Column("spec_unit", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(f"entity_type IN {ENTITY_TYPE_VALUES}", name="ck_tech_specs_entity_type"),
        sa.PrimaryKeyConstraint("spec_id"),
    )
    op.create_index("ix_tech_specs_entity", "tech_specs", ["entity_type", "entity_id"])

    # --- included_features ---
    op.create_table(
        "included_features",
        sa.Column("feature_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("feature_text", sa.Text(), nullable=False),
        sa.Column("feature_category", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            f"entity_type IN {ENTITY_TYPE_VALUES}", name="ck_included_features_entity_type"
        ),
        sa.PrimaryKeyConstraint("feature_id"),
    )
    op.create_index("ix_included_features_entity", "included_features", ["entity_type", "entity_id"])

    # --- inclusions_exclusions ---
    op.create_table(
        "inclusions_exclusions",
        sa.Column("entry_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("entry_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('offer')", name="ck_inclusions_exclusions_entity_type"
        ),
        sa.CheckConstraint(
            f"entry_type IN {ENTRY_TYPE_VALUES}", name="ck_inclusions_exclusions_entry_type"
        ),
        sa.PrimaryKeyConstraint("entry_id"),
    )
    op.create_index(
        "ix_inclusions_exclusions_entity", "inclusions_exclusions", ["entity_type", "entity_id"]
    )

    # --- offer_payment_schedules ---
    op.create_table(
        "offer_payment_schedules",
        sa.Column("schedule_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("offer_id", sa.BigInteger(), nullable=False),
        sa.Column("scope_label", sa.Text(), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("trigger_event", sa.Text(), nullable=False),
        sa.Column("percentage", sa.Numeric(), nullable=True),
        sa.Column("description_original", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("schedule_id"),
    )
    op.create_index(
        "ix_offer_payment_schedules_offer_id", "offer_payment_schedules", ["offer_id"]
    )

    # --- offer_attachments ---
    op.create_table(
        "offer_attachments",
        sa.Column("attachment_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("offer_id", sa.BigInteger(), nullable=False),
        sa.Column("attachment_label", sa.Text(), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.document_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("attachment_id"),
    )
    op.create_index("ix_offer_attachments_offer_id", "offer_attachments", ["offer_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_attachments_offer_id", table_name="offer_attachments")
    op.drop_table("offer_attachments")

    op.drop_index("ix_offer_payment_schedules_offer_id", table_name="offer_payment_schedules")
    op.drop_table("offer_payment_schedules")

    op.drop_index("ix_inclusions_exclusions_entity", table_name="inclusions_exclusions")
    op.drop_table("inclusions_exclusions")

    op.drop_index("ix_included_features_entity", table_name="included_features")
    op.drop_table("included_features")

    op.drop_index("ix_tech_specs_entity", table_name="tech_specs")
    op.drop_table("tech_specs")

    op.drop_index("ix_offer_items_parent_item_id", table_name="offer_items")
    op.drop_index("ix_offer_items_offer_id", table_name="offer_items")
    op.drop_table("offer_items")

    op.drop_index("ix_offers_project_id", table_name="offers")
    op.drop_index("ix_offers_supplier_id", table_name="offers")
    op.drop_constraint("fk_offers_grand_total_currency", "offers", type_="foreignkey")
    op.drop_constraint("fk_offers_currency_primary", "offers", type_="foreignkey")
    op.drop_constraint("fk_offers_project_id", "offers", type_="foreignkey")
    op.drop_constraint("fk_offers_supplier_id", "offers", type_="foreignkey")
    for column in [
        "extra_attributes", "general_notes_original", "offer_signed_by_original",
        "delivery_terms_original", "incoterm", "tax_treatment_original",
        "grand_total_currency", "grand_total", "currency_primary",
        "price_currency_original", "payment_terms_original", "project_location_original",
        "client_name_original", "project_name_original", "offer_ref",
        "project_id", "supplier_id",
    ]:
        op.drop_column("offers", column)

    op.drop_index("ix_supplier_contacts_supplier_id", table_name="supplier_contacts")
    op.drop_table("supplier_contacts")

    op.drop_table("projects")
    op.drop_table("suppliers")
    op.drop_table("currencies")
