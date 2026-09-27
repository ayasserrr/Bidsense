from dataclasses import dataclass

from models.enums import PriceBasis, SanityCheckIssueType
from schema.offer import ExtractedItem, OfferExtractionPayload

# A mismatch counts as real only once it clears both a relative margin (to
# tolerate genuine rounding on large figures) and a small absolute floor (so
# two near-zero numbers don't get flagged over a fractional-unit rounding
# difference). 0.2% was chosen from real observed cases: genuine per-line
# rounding across many summed items lands at ~0.001-0.002% of the total
# (e.g. a $1 gap on an $83,041 subtotal, a $4.70 gap on $278,824.76) - a full
# two orders of magnitude below this threshold - while a real, material
# inconsistency the supplier's own document contains (e.g. a $949 gap on a
# $170,000 combined-section total, 0.56%) sits well above it. 1% was too
# loose to ever catch the latter kind of gap.
_RELATIVE_TOLERANCE = 0.002
_ABSOLUTE_TOLERANCE = 0.5


@dataclass(frozen=True)
class ArithmeticFlag:
    flag_type: SanityCheckIssueType
    field_path: str
    description: str


def _mismatch(expected: float, actual: float) -> bool:
    diff = abs(expected - actual)
    tolerance = max(_ABSOLUTE_TOLERANCE, _RELATIVE_TOLERANCE * max(abs(expected), abs(actual)))
    return diff > tolerance


def _children_by_parent(items: list[ExtractedItem]) -> dict[str, list[ExtractedItem]]:
    children: dict[str, list[ExtractedItem]] = {}
    for item in items:
        if item.parent_local_id:
            children.setdefault(item.parent_local_id, []).append(item)
    return children


def _subtree_total(
    local_id: str,
    items_by_id: dict[str, ExtractedItem],
    children_map: dict[str, list[ExtractedItem]],
    currency: str | None,
) -> float | None:
    """Sums this item's own total_price plus every descendant's, counting
    only entries priced in `currency` (a subtree mixing currencies can't be
    safely summed, so this returns None rather than guess)."""
    item = items_by_id[local_id]
    total = 0.0
    counted_any = False

    if item.total_price is not None:
        if item.price_currency != currency:
            return None
        total += item.total_price
        counted_any = True

    for child in children_map.get(local_id, []):
        child_total = _subtree_total(child.local_id, items_by_id, children_map, currency)
        if child_total is None:
            return None
        total += child_total
        counted_any = True

    return total if counted_any else None


def _children_total(
    local_id: str,
    items_by_id: dict[str, ExtractedItem],
    children_map: dict[str, list[ExtractedItem]],
    currency: str | None,
) -> float | None:
    """Sums only this item's descendants, excluding the item's own
    total_price - the reading that applies when the item is a rollup header
    whose own total_price restates the same money as its children rather
    than adding a genuinely separate charge on top of them."""
    total = 0.0
    counted_any = False
    for child in children_map.get(local_id, []):
        child_total = _subtree_total(child.local_id, items_by_id, children_map, currency)
        if child_total is None:
            return None
        total += child_total
        counted_any = True
    return total if counted_any else None


def _check_item_arithmetic(items: list[ExtractedItem]) -> list[ArithmeticFlag]:
    """quantity x unit_price (net of discount_amount) vs total_price, for
    items priced the ordinary way (fixed, not lump-sum)."""
    flags = []
    for item in items:
        if item.price_basis != PriceBasis.FIXED or item.is_lump_sum:
            continue
        if item.quantity is None or item.unit_price is None or item.total_price is None:
            continue

        expected = item.quantity * item.unit_price - (item.discount_amount or 0)
        if _mismatch(expected, item.total_price):
            discount_note = f" - discount_amount ({item.discount_amount:g})" if item.discount_amount else ""
            flags.append(
                ArithmeticFlag(
                    flag_type=SanityCheckIssueType.ARITHMETIC_MISMATCH,
                    field_path=f"items[{item.local_id}].total_price",
                    description=(
                        f"quantity ({item.quantity:g}) x unit_price ({item.unit_price:g})"
                        f"{discount_note} = {expected:g}, but total_price is {item.total_price:g}."
                    ),
                )
            )
    return flags


def _check_percentage_of_parent(items: list[ExtractedItem], items_by_id: dict[str, ExtractedItem]) -> list[ArithmeticFlag]:
    flags = []
    for item in items:
        if item.price_basis != PriceBasis.PERCENTAGE_OF_PARENT:
            continue
        if item.percentage_value is None or item.total_price is None or not item.parent_local_id:
            continue
        parent = items_by_id.get(item.parent_local_id)
        if parent is None or parent.total_price is None:
            continue
        if item.price_currency != parent.price_currency:
            # Comparing raw figures across two different currencies without
            # a conversion rate isn't safe - skip rather than flag (or
            # silently miss) a mismatch we can't actually evaluate.
            continue

        expected = parent.total_price * (item.percentage_value / 100)
        if _mismatch(expected, item.total_price):
            flags.append(
                ArithmeticFlag(
                    flag_type=SanityCheckIssueType.PERCENTAGE_MISMATCH,
                    field_path=f"items[{item.local_id}].total_price",
                    description=(
                        f"{item.percentage_value:g}% of parent item ({item.parent_local_id})'s "
                        f"total_price ({parent.total_price:g}) = {expected:g}, but this item's "
                        f"total_price is {item.total_price:g}."
                    ),
                )
            )
    return flags


def _check_stated_subtotals(
    items: list[ExtractedItem],
    items_by_id: dict[str, ExtractedItem],
    children_map: dict[str, list[ExtractedItem]],
) -> list[ArithmeticFlag]:
    """Only ever triggers off an explicit `stated_subtotal_amount` - a
    tempting extension is to also treat a childless-of-its-own-price
    combination (children present + the item's own total_price, no
    stated_subtotal_amount) as an implied rollup to check the same way, but
    that's indistinguishable from the extremely common, entirely correct
    illustration A/D shape (a main unit's own genuinely separate total_price
    plus its own priced accessories, e.g. a generator + a percentage-of-
    parent installation charge) - tried this, it flagged both of those as
    false positives. Without stated_subtotal_amount actually present, there
    is no reliable signal to tell "rollup that should have used this field"
    apart from "normal item with real accessories", so this deliberately
    stays narrow rather than guess."""
    flags = []
    for item in items:
        if item.stated_subtotal_amount is None:
            continue
        currency = item.stated_subtotal_currency or item.price_currency

        # Two valid readings of "this group's total": additive (the item's
        # own line plus every child's - a header that carries a genuinely
        # separate price on top of priced accessories) and children-only
        # (the item's own total_price excluded - a header row whose own
        # total_price already restates the same money its children sum to).
        # Flag only if neither reading reconciles - a missing flag is
        # always safer than a false one.
        candidates = [
            total
            for total in (
                _subtree_total(item.local_id, items_by_id, children_map, currency),
                _children_total(item.local_id, items_by_id, children_map, currency),
            )
            if total is not None
        ]
        if not candidates:
            continue
        if all(_mismatch(candidate, item.stated_subtotal_amount) for candidate in candidates):
            closest = min(candidates, key=lambda candidate: abs(candidate - item.stated_subtotal_amount))
            flags.append(
                ArithmeticFlag(
                    flag_type=SanityCheckIssueType.SUBTOTAL_MISMATCH,
                    field_path=f"items[{item.local_id}].stated_subtotal_amount",
                    description=(
                        f"Sum of this item and its accessories' total_price in {currency} = "
                        f"{closest:g}, but stated_subtotal_amount is {item.stated_subtotal_amount:g}."
                    ),
                )
            )
    return flags


def _check_grand_total(
    payload: OfferExtractionPayload,
    items_by_id: dict[str, ExtractedItem],
    children_map: dict[str, list[ExtractedItem]],
) -> list[ArithmeticFlag]:
    """Compares grand_total against the sum of every top-level item's own
    *effective* amount - its stated_subtotal_amount if the document prints
    one for that group (the more authoritative figure when present), else
    the full subtree sum of that item plus all its descendants (an
    accessory/child's separately-priced total_price is still part of the
    offer's total even though it isn't itself top-level - only using the
    top-level item's own total_price and ignoring priced children would
    silently exclude real money from the comparison)."""
    if payload.grand_total is None:
        return []

    currency = payload.grand_total_currency
    top_level = [item for item in payload.items if item.parent_local_id is None]

    additive_amounts: list[float] = []
    alt_amounts: list[float] = []
    for item in top_level:
        if item.stated_subtotal_amount is not None:
            if item.stated_subtotal_currency != currency:
                return []
            additive_amounts.append(item.stated_subtotal_amount)
            alt_amounts.append(item.stated_subtotal_amount)
            continue

        subtree_amount = _subtree_total(item.local_id, items_by_id, children_map, currency)
        if subtree_amount is None:
            # Mixed currency, or nothing priced in this subtree - can't
            # safely fold it into the comparison, so skip the check
            # entirely rather than compute a partial, misleading total.
            return []
        additive_amounts.append(subtree_amount)

        # Same ambiguity _check_stated_subtotals guards against: a
        # top-level item with children AND its own total_price might be a
        # rollup header that was left with a non-null total_price instead
        # of using stated_subtotal_amount (a real, observed extraction
        # defect) - the additive reading above would then double-count it
        # against its own children. Offer the children-only reading as an
        # alternative for items where this ambiguity actually applies, so
        # one misplaced figure doesn't inflate the whole grand-total
        # comparison into a confusing, much-too-large mismatch.
        children = children_map.get(item.local_id, [])
        if children and item.total_price is not None:
            children_only = _children_total(item.local_id, items_by_id, children_map, currency)
            alt_amounts.append(children_only if children_only is not None else subtree_amount)
        else:
            alt_amounts.append(subtree_amount)

    if not additive_amounts:
        return []

    candidates = [sum(additive_amounts)]
    if alt_amounts != additive_amounts:
        candidates.append(sum(alt_amounts))

    if all(_mismatch(candidate, payload.grand_total) for candidate in candidates):
        computed = min(candidates, key=lambda candidate: abs(candidate - payload.grand_total))
        return [
            ArithmeticFlag(
                flag_type=SanityCheckIssueType.GRAND_TOTAL_MISMATCH,
                field_path="grand_total",
                description=(
                    f"Sum of top-level items' amounts (including their priced accessories) in "
                    f"{currency} = {computed:g}, but grand_total is {payload.grand_total:g}."
                ),
            )
        ]
    return []


def _check_payment_schedule_percentages(payload: OfferExtractionPayload) -> list[ArithmeticFlag]:
    groups: dict[str | None, list[float]] = {}
    for schedule in payload.payment_schedules:
        groups.setdefault(schedule.scope_label, []).append(schedule.percentage)

    flags = []
    for scope_label, percentages in groups.items():
        if not percentages or any(pct is None for pct in percentages):
            continue
        total_pct = sum(percentages)
        if _mismatch(100.0, total_pct):
            scope_desc = f"scope '{scope_label}'" if scope_label else "the offer-wide schedule"
            flags.append(
                ArithmeticFlag(
                    flag_type=SanityCheckIssueType.PAYMENT_SCHEDULE_MISMATCH,
                    field_path=f"payment_schedules[{scope_label or 'offer'}]",
                    description=f"Payment schedule percentages for {scope_desc} sum to {total_pct:g}%, not 100%.",
                )
            )
    return flags


def find_sanity_flags(payload: OfferExtractionPayload) -> list[ArithmeticFlag]:
    """Deterministic (non-LLM) pricing/arithmetic checks over an extracted
    offer: quantity x unit_price vs total_price, percentage-of-parent
    pricing, a stated subtotal vs the items it should cover, and grand_total
    vs the sum of top-level items. Payment-schedule percentages summing to
    100% is deliberately left disabled below (not called) - a document can
    legitimately state a payment schedule that only covers part of the
    total (e.g. a remaining balance left undefined pending a later
    agreement), which this deterministic layer can't tell apart from a
    real extraction defect without judgment a plain percentage-sum check
    can't make. Every other check here is skipped rather than guessed at
    wherever the data doesn't unambiguously support it (mixed currencies,
    missing fields, non-fixed pricing) - a missing flag is always safer
    than a false one."""
    items_by_id = {item.local_id: item for item in payload.items}
    children_map = _children_by_parent(payload.items)

    return [
        *_check_item_arithmetic(payload.items),
        *_check_percentage_of_parent(payload.items, items_by_id),
        *_check_stated_subtotals(payload.items, items_by_id, children_map),
        *_check_grand_total(payload, items_by_id, children_map),
    ]
