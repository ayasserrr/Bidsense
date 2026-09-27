import uuid

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.enums import ItemCategory, PriceBasis

from .base import Base

ITEM_CATEGORY_VALUES = tuple(category.value for category in ItemCategory)
PRICE_BASIS_VALUES = tuple(basis.value for basis in PriceBasis)


class OfferItem(Base):
    __tablename__ = "offer_items"
    __table_args__ = (
        CheckConstraint(
            f"item_category IN {ITEM_CATEGORY_VALUES}", name="ck_offer_items_item_category"
        ),
        CheckConstraint(f"price_basis IN {PRICE_BASIS_VALUES}", name="ck_offer_items_price_basis"),
    )

    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    offer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("offer_items.item_id", ondelete="CASCADE"), nullable=True, index=True
    )
    item_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_group_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_category: Mapped[str] = mapped_column(Text, nullable=False)
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_alternate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alternate_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_lump_sum: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price_basis: Mapped[str] = mapped_column(Text, nullable=False, default="fixed")
    percentage_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    discount_amount: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    model_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    equipment_type_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric, nullable=False)
    unit_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    total_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    price_currency: Mapped[str | None] = mapped_column(
        ForeignKey("currencies.code", ondelete="SET NULL"), nullable=True
    )
    price_currency_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    stated_subtotal_amount: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    stated_subtotal_currency: Mapped[str | None] = mapped_column(
        ForeignKey("currencies.code", ondelete="SET NULL"), nullable=True
    )
    tax_treatment_override_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    incoterm_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_terms_override_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_terms_override_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    availability_original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The file this row was read out of. Needed by both new features: the
    # completeness report says which document evidences a discipline, and the
    # taxonomy view groups an offer's items by file when several were uploaded.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.document_id", ondelete="SET NULL"), nullable=True
    )
    # Resolved after extraction, never asked for as part of it: putting a
    # category enum into the extraction schema would lengthen every item and
    # make the measured null-scalar collapse worse.
    taxonomy_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("taxonomy_nodes.node_id", ondelete="SET NULL"), nullable=True, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
