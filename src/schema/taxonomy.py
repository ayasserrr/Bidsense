from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from models.enums import ResponseSignal

# --- what the model is asked for -------------------------------------------


class TaxonomyAssignment(BaseModel):
    item_ref: str = Field(
        description="The reference number of the item being categorised, exactly as given in the list."
    )
    node_code: str | None = Field(
        default=None,
        description=(
            "The code of the category this item belongs to, chosen from the list of allowed "
            "codes. Prefer the most specific one that clearly fits. Use the discipline code "
            "alone when the item belongs to a discipline but to none of its equipment types. "
            "Null when the description genuinely does not say what the item is - guessing is "
            "worse than leaving it unresolved, because an unresolved item is visibly "
            "unresolved while a wrong one is not."
        ),
    )
    confidence: float = Field(
        default=0.0,
        description="How sure you are, 0.0 to 1.0. Below 0.6 the assignment is discarded.",
    )


class TaxonomyResolutionResult(BaseModel):
    assignments: list[TaxonomyAssignment] = Field(
        default_factory=list,
        description="One entry per item you were given. Omit an item rather than guessing at it.",
    )


# --- what the API returns --------------------------------------------------


class TaxonomyNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: int
    parent_node_id: int | None = None
    code: str
    label: str
    level: int
    sort_order: int
    is_active: bool


class TaxonomyTreeNode(TaxonomyNodeOut):
    children: list["TaxonomyTreeNode"] = Field(default_factory=list)
    # How many items across all offers currently resolve here. The number that
    # tells a reviewer whether a category is earning its place.
    item_count: int = 0


class TaxonomyAliasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alias_id: int
    node_id: int
    alias_display: str
    alias_normalized: str
    source: str
    is_approved: bool
    created_at: datetime


class ItemTaxonomyOut(BaseModel):
    """One line item and where the taxonomy put it."""

    item_id: int
    description: str
    equipment_type_original: str | None = None
    node_id: int | None = None
    node_code: str | None = None
    node_label: str | None = None
    discipline_code: str | None = None
    discipline_label: str | None = None


class OfferTaxonomyResponse(BaseModel):
    signal: ResponseSignal
    offer_id: int
    resolved_count: int
    unresolved_count: int
    # Discipline code -> number of this offer's items in it. This is what makes
    # the technical half of the completeness checklist answer itself.
    disciplines: dict[str, int] = Field(default_factory=dict)
    items: list[ItemTaxonomyOut] = Field(default_factory=list)


class ItemCategoryOverrideRequest(BaseModel):
    """A reviewer moving one item to the right category.

    The correction is stored as a learned alias keyed on the item's own source
    text, not just written onto the item: `offer_items` is wiped and rewritten
    on every re-persist, so an edit made only to the row would be lost the next
    time the offer is re-run.
    """

    node_id: int
    # Whether to remember this wording for future offers. Off by default -
    # a one-off fix to a badly-worded line should not become a global rule.
    learn_alias: bool = False
