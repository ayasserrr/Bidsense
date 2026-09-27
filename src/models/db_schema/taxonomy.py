from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TaxonomyNode(Base):
    """A category a line item can belong to.

    The ten roots are the client's ten engineering disciplines - the same ten
    the completeness checklist asks about, sharing the same codes - so "does
    this offer cover Electrical?" and "which discipline is this item?" are one
    vocabulary rather than two that can drift apart.

    Self-referencing parent rather than a fixed two-level shape: today the tree
    is discipline > equipment type (HVAC > Chiller), but nothing here stops a
    third level being added when a reviewer needs one.
    """

    __tablename__ = "taxonomy_nodes"

    node_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parent_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("taxonomy_nodes.node_id", ondelete="CASCADE"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # 1 for a discipline, 2 for an equipment type under it. Stored rather than
    # computed so a list query can filter to roots without a recursive CTE.
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class TaxonomyAlias(Base):
    """A form of words that resolves to a taxonomy node.

    Seeded aliases carry the obvious synonyms ("VRF", "VRV", "split unit").
    Learned aliases are reviewer corrections, keyed on the normalised source
    text so they survive `_clear_existing_offer_data` wiping and rewriting
    `offer_items` on every re-persist - the correction lives here, not on the
    item it was made against.

    A learned alias starts unapproved. One reviewer's correction becoming an
    instant, global, permanent rule is how a taxonomy quietly rots; an admin
    approves it before it starts resolving other people's offers.
    """

    __tablename__ = "taxonomy_aliases"
    __table_args__ = (
        UniqueConstraint("alias_normalized", name="uq_taxonomy_alias_normalized"),
    )

    alias_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("taxonomy_nodes.node_id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Lowercased, punctuation-stripped, whitespace-collapsed. Matching happens
    # on this, never on the raw text, so "VRV-System" and "vrv system" are one
    # alias rather than two.
    alias_normalized: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    alias_display: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # "seed" | "learned" | "model"
    source: Mapped[str] = mapped_column(Text, nullable=False, default="seed", index=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
