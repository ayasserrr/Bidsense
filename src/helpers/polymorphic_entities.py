"""Cleanup for the three tables that are never a foreign key.

`tech_specs`, `included_features` and `inclusions_exclusions` are keyed by a
plain `entity_type`/`entity_id` pair rather than a real `ForeignKey` - one row
can describe either an offer or one of its items, and a single column can't
point at two different tables. That also means nothing here is ever DB-
cascaded: dropping an `offers` row (or one `offer_items` row) leaves these
three tables' rows behind unless something deletes them itself.

Two callers need exactly that delete and must never disagree on how it's
done: `PersistController._clear_existing_offer_data`, clearing an offer's
children before a re-persist writes fresh ones, and
`OfferController.delete_offer`, removing them permanently along with
everything else. Both call this rather than keeping their own copy of the
same three statements.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_schema import IncludedFeature, InclusionExclusion, OfferItem, TechSpec
from models.enums import EntityType


async def delete_polymorphic_offer_rows(db: AsyncSession, offer_id: int) -> None:
    """Deletes every `tech_specs`/`included_features`/`inclusions_exclusions`
    row for one offer AND for every item currently under it.

    The item ids are read as a correlated subquery rather than fetched into
    Python first, so this works whether the caller runs it before or after
    reading `offer_items` itself - it only has to run before the items (or the
    offer) are actually deleted, since after that the subquery would find
    nothing to match against.
    """
    item_ids_subquery = select(OfferItem.item_id).where(OfferItem.offer_id == offer_id)

    await db.execute(
        delete(TechSpec).where(
            ((TechSpec.entity_type == EntityType.OFFER.value) & (TechSpec.entity_id == offer_id))
            | ((TechSpec.entity_type == EntityType.ITEM.value) & (TechSpec.entity_id.in_(item_ids_subquery)))
        )
    )
    await db.execute(
        delete(IncludedFeature).where(
            ((IncludedFeature.entity_type == EntityType.OFFER.value) & (IncludedFeature.entity_id == offer_id))
            | (
                (IncludedFeature.entity_type == EntityType.ITEM.value)
                & (IncludedFeature.entity_id.in_(item_ids_subquery))
            )
        )
    )
    # inclusions_exclusions has no item-level rows at all (its own CHECK
    # constraint enforces entity_type = 'offer'), so this one is never split
    # in two like the pair above.
    await db.execute(delete(InclusionExclusion).where(InclusionExclusion.entity_id == offer_id))
