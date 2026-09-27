from schema.offer import ExtractedItem


def order_items_topologically(items: list[ExtractedItem]) -> list[ExtractedItem]:
    """Reorders items so every item comes after its own parent (required
    before persisting, since a child row needs its parent's real database
    `item_id` to already exist). Acyclic and dangling-parent-free by the time
    this runs - `OfferExtractionPayload`'s own validator already rejects a
    cycle or an unknown parent_local_id, so no cycle guard is needed here.

    Otherwise preserves the original (document) order: an item is only
    pulled earlier than its natural position to satisfy its parent-first
    requirement, never reordered relative to unrelated siblings. This keeps
    insertion order - and therefore the item_id tiebreaker used when reading
    items back - matching the source document's own order.
    """
    items_by_id = {item.local_id: item for item in items}
    ordered: list[ExtractedItem] = []
    emitted: set[str] = set()

    def emit(item: ExtractedItem) -> None:
        if item.local_id in emitted:
            return
        if item.parent_local_id is not None:
            emit(items_by_id[item.parent_local_id])
        emitted.add(item.local_id)
        ordered.append(item)

    for item in items:
        emit(item)

    return ordered
