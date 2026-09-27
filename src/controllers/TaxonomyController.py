import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from helpers.offer_events import record_item_recategorised
from helpers.taxonomy_match import fuzzy_best_match, normalize_alias
from helpers.taxonomy_seed import TAXONOMY_SEED
from helpers.visibility import visibility_filter
from models.db_schema import Offer, OfferItem, TaxonomyAlias, TaxonomyNode, User
from models.enums import ItemCategory
from schema.taxonomy import TaxonomyResolutionResult
from tools import resolve_item_categories
from tools._common import unpack_result

from .BaseController import BaseController

logger = logging.getLogger(__name__)

# (items_resolved, items_total)
ResolveProgressCallback = Callable[[int, int], Awaitable[None]]

# Below this the model's own answer is thrown away. A wrong discipline is worse
# than an unresolved item: an unresolved item is visibly unresolved and a
# reviewer fixes it in seconds, while a confidently wrong one quietly corrupts
# the completeness report that reads from it.
MINIMUM_MODEL_CONFIDENCE = 0.6

# How many items go into one batched model call. Big enough that a normal BOQ
# is a single request, small enough that the response cannot run past the
# output cap.
RESOLVE_BATCH_SIZE = 40

# Lines that describe work or parts attached to equipment rather than equipment
# itself. "Spare parts - 4,000 EURO", "Installation works (OPTION)", "Seismic
# supports" name no discipline of their own: on a generator offer they are
# Electrical, on a chiller offer they are HVAC, and the words in the line say
# nothing either way. These are the only items allowed to inherit a discipline
# rather than earn one from their own wording.
SUPPORT_CATEGORIES: frozenset[str] = frozenset(
    {
        ItemCategory.INSTALLATION.value,
        ItemCategory.SERVICE.value,
        ItemCategory.SPARE_PART.value,
        ItemCategory.ACCESSORY.value,
        ItemCategory.WARRANTY.value,
        ItemCategory.TRANSPORTATION.value,
    }
)


class TaxonomyController(BaseController):
    """Puts each line item into one of the client's ten disciplines.

    Resolution is cheapest-first: an exact alias, then a fuzzy match, and only
    what survives both is batched into one model call. On a real bill of
    quantities most rows never reach the model at all.

    The taxonomy deliberately never enters the extraction schema. Asking for a
    category on every line item would lengthen the output of the stage whose
    measured failure was closing the object early, and make that worse.
    """

    def __init__(self, db: AsyncSession):
        super().__init__()
        self.db = db

    # --- seed and read -----------------------------------------------------

    async def seed_taxonomy(self) -> tuple[int, int]:
        """Writes any node or alias that is not there yet. Returns (nodes, aliases).

        Insert-only, like the checklist seed: a reviewer's edits and learned
        aliases live in the database and must survive a restart.
        """
        existing_nodes = {
            node.code: node
            for node in (await self.db.execute(select(TaxonomyNode))).scalars().all()
        }
        existing_aliases = set(
            (await self.db.execute(select(TaxonomyAlias.alias_normalized))).scalars().all()
        )

        added_nodes = 0
        added_aliases = 0

        async def ensure_node(seed, parent_id: int | None, level: int, order: int) -> TaxonomyNode:
            nonlocal added_nodes
            node = existing_nodes.get(seed.code)
            if node is None:
                node = TaxonomyNode(
                    parent_node_id=parent_id,
                    code=seed.code,
                    label=seed.label,
                    level=level,
                    sort_order=order,
                    is_active=True,
                )
                self.db.add(node)
                await self.db.flush()
                existing_nodes[seed.code] = node
                added_nodes += 1
            return node

        def ensure_aliases(node: TaxonomyNode, seed) -> None:
            nonlocal added_aliases
            # The node's own label is always an alias for it - otherwise "HVAC"
            # written verbatim in a description would fail to match HVAC.
            for text in (seed.label, *seed.aliases):
                key = normalize_alias(text)
                if not key or key in existing_aliases:
                    continue
                self.db.add(
                    TaxonomyAlias(
                        node_id=node.node_id,
                        alias_normalized=key,
                        alias_display=text,
                        source="seed",
                        is_approved=True,
                    )
                )
                existing_aliases.add(key)
                added_aliases += 1

        for root_order, root_seed in enumerate(TAXONOMY_SEED):
            root = await ensure_node(root_seed, None, 1, root_order)
            ensure_aliases(root, root_seed)
            for child_order, child_seed in enumerate(root_seed.children):
                child = await ensure_node(child_seed, root.node_id, 2, child_order)
                ensure_aliases(child, child_seed)

        if added_nodes or added_aliases:
            await self.db.commit()
        return added_nodes, added_aliases

    async def get_nodes(self) -> list[TaxonomyNode]:
        result = await self.db.execute(
            select(TaxonomyNode).order_by(TaxonomyNode.level, TaxonomyNode.sort_order, TaxonomyNode.code)
        )
        return list(result.scalars().all())

    async def item_counts(self, user: User) -> dict[int, int]:
        """Items per category, counting only offers `user` may see - counted
        company-wide, the tree would tell one department how much another
        holds in each discipline."""
        query = (
            select(OfferItem.taxonomy_node_id, func.count(OfferItem.item_id))
            .join(Offer, Offer.id == OfferItem.offer_id)
            .where(OfferItem.taxonomy_node_id.is_not(None))
            .group_by(OfferItem.taxonomy_node_id)
        )
        scope = visibility_filter(
            user=user,
            owner_id_column=Offer.created_by_user_id,
            department_column=Offer.created_by_department,
        )
        if scope is not None:
            query = query.where(scope)
        rows = (await self.db.execute(query)).all()
        return {row[0]: row[1] for row in rows}

    async def _alias_map(self) -> dict[str, int]:
        """Every approved alias, normalised, mapped to its node.

        Unapproved learned aliases are excluded on purpose: one reviewer's
        correction should not start silently re-categorising other people's
        offers before an admin has looked at it.
        """
        rows = (
            await self.db.execute(
                select(TaxonomyAlias.alias_normalized, TaxonomyAlias.node_id).where(
                    TaxonomyAlias.is_approved.is_(True)
                )
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    # --- resolution --------------------------------------------------------

    async def resolve_offer_items(
        self,
        offer_id: int,
        on_progress: ResolveProgressCallback | None = None,
    ) -> tuple[int, int]:
        """Assigns a taxonomy node to every item of one offer.

        Returns (resolved, unresolved). Safe to run again - it recomputes from
        the item's own text every time, which is what makes it correct after a
        reviewer approves a new alias.
        """
        items = list(
            (
                await self.db.execute(
                    select(OfferItem)
                    .where(OfferItem.offer_id == offer_id)
                    .order_by(OfferItem.sort_order)
                )
            )
            .scalars()
            .all()
        )
        if not items:
            return 0, 0

        aliases = await self._alias_map()
        nodes = {node.node_id: node for node in await self.get_nodes()}
        total = len(items)

        unresolved: list[OfferItem] = []
        resolved = 0

        for item in items:
            node_id = self._match_locally(item, aliases)
            if node_id is not None and node_id in nodes:
                item.taxonomy_node_id = node_id
                resolved += 1
            else:
                item.taxonomy_node_id = None
                unresolved.append(item)

        # Labour, spares and accessories take the discipline of the equipment
        # they belong to before anything is sent to the model - the model would
        # be reading the same wordless line and guessing from it.
        resolved += self._inherit_discipline(items, unresolved, nodes)
        unresolved = [item for item in unresolved if item.taxonomy_node_id is None]

        if on_progress is not None:
            await on_progress(resolved, total)

        if unresolved:
            resolved += await self._resolve_with_model(offer_id, unresolved, nodes)
            if on_progress is not None:
                await on_progress(resolved, total)

        await self.db.commit()
        logger.info(
            "taxonomy offer_id=%s resolved=%s/%s", offer_id, resolved, total
        )
        return resolved, total - resolved

    @staticmethod
    def _match_locally(item: OfferItem, aliases: dict[str, int]) -> int | None:
        """Exact alias first, then fuzzy, over the item's own words.

        `equipment_type_original` is tried before `description` because it is
        the field extraction fills with what the thing actually is, while the
        description usually opens with "Supply and installation of..." and buries
        the noun.
        """
        candidates = [item.equipment_type_original, item.description, item.model_number]
        for text in candidates:
            key = normalize_alias(text)
            if key and key in aliases:
                return aliases[key]
        for text in candidates:
            if not text:
                continue
            hit = fuzzy_best_match(text, aliases)
            if hit is not None:
                return hit[0]
        return None

    @staticmethod
    def _root_of(node_id: int | None, nodes: dict[int, TaxonomyNode]) -> TaxonomyNode | None:
        """The discipline a node sits under, walking the cached tree."""
        node = nodes.get(node_id) if node_id is not None else None
        while node is not None and node.parent_node_id is not None:
            node = nodes.get(node.parent_node_id)
        return node

    @classmethod
    def _inherit_discipline(
        cls,
        items: list[OfferItem],
        unresolved: list[OfferItem],
        nodes: dict[int, TaxonomyNode],
    ) -> int:
        """Gives a support line the discipline of the equipment it belongs to.

        A "Spare parts" or "Installation works" line is not uncategorisable - it
        is a line whose category lives somewhere else, on the equipment it is
        attached to. Two sources, in order of how directly they say so:

          1. Its parent item, when the offer's own indentation ties them.
          2. The offer itself, but ONLY when every item that resolved landed in
             one discipline. A generator offer's spares are generator spares.
             The moment an offer spans two disciplines this says nothing and the
             line is left for the model, because guessing between them is how a
             wrong discipline gets in - and a wrong discipline is worse than an
             unresolved one.

        Equipment lines never inherit. An unmatched thing-in-a-box may genuinely
        be from another discipline (the plinth in a UPS quotation), and that is
        exactly the case the model is there to read.
        """
        by_item_id = {item.item_id: item for item in items}
        resolved_roots = {
            root.node_id
            for item in items
            if item.taxonomy_node_id is not None
            and (root := cls._root_of(item.taxonomy_node_id, nodes)) is not None
        }
        sole_discipline = next(iter(resolved_roots)) if len(resolved_roots) == 1 else None

        inherited = 0
        for item in unresolved:
            if (item.item_category or "") not in SUPPORT_CATEGORIES:
                continue
            target: int | None = None
            parent = by_item_id.get(item.parent_item_id) if item.parent_item_id else None
            if parent is not None:
                parent_root = cls._root_of(parent.taxonomy_node_id, nodes)
                target = parent_root.node_id if parent_root is not None else None
            if target is None:
                target = sole_discipline
            if target is None:
                continue
            item.taxonomy_node_id = target
            inherited += 1
        return inherited

    async def _resolve_with_model(
        self, offer_id: int, items: list[OfferItem], nodes: dict[int, TaxonomyNode]
    ) -> int:
        """One batched call for whatever alias matching could not place."""
        by_code = {node.code: node for node in nodes.values()}
        categories = [
            {
                "code": node.code,
                "label": node.label,
                "discipline": (
                    nodes[node.parent_node_id].label if node.parent_node_id in nodes else None
                ),
            }
            for node in sorted(nodes.values(), key=lambda n: (n.level, n.sort_order))
            if node.is_active
        ]
        categories_json = json.dumps(categories)

        resolved = 0
        for start in range(0, len(items), RESOLVE_BATCH_SIZE):
            batch = items[start : start + RESOLVE_BATCH_SIZE]
            by_ref = {str(item.item_id): item for item in batch}
            items_json = json.dumps(
                [
                    {
                        "ref": str(item.item_id),
                        "description": (item.description or "")[:400],
                        "equipment_type": item.equipment_type_original,
                        "model": item.model_number,
                    }
                    for item in batch
                ]
            )
            try:
                raw = await resolve_item_categories.ainvoke(
                    {
                        "items_json": items_json,
                        "categories_json": categories_json,
                        "log_id": str(offer_id),
                    }
                )
                result, _telemetry = unpack_result(raw, TaxonomyResolutionResult)
            except Exception as exc:
                # Unresolved items are a visible, fixable state - the report
                # shows them as uncategorised and a reviewer assigns them. A
                # failed batch is therefore a degradation, not a failure.
                logger.warning(
                    "taxonomy offer_id=%s batch at %s failed: %s", offer_id, start, exc
                )
                continue

            for assignment in result.assignments:
                item = by_ref.get(assignment.item_ref)
                node = by_code.get(assignment.node_code or "")
                if item is None or node is None:
                    continue
                if assignment.confidence < MINIMUM_MODEL_CONFIDENCE:
                    continue
                item.taxonomy_node_id = node.node_id
                resolved += 1
        return resolved

    # --- reviewer corrections ----------------------------------------------

    async def override_item_category(
        self,
        *,
        item: OfferItem,
        node_id: int,
        learn_alias: bool,
        user: User,
    ) -> OfferItem:
        """Moves one item, and optionally remembers the wording that got it wrong.

        The alias is keyed on the item's own source text rather than written
        onto the item, because `PersistController._clear_existing_offer_data`
        wipes and rewrites `offer_items` on every re-persist - a correction
        stored only on the row would vanish the next time the offer is re-run.

        A learned alias starts UNAPPROVED. One reviewer's fix becoming an
        instant, global, permanent rule is how a taxonomy quietly rots.
        """
        item.taxonomy_node_id = node_id

        if learn_alias:
            source_text = item.equipment_type_original or item.description
            key = normalize_alias(source_text)
            if key:
                existing = (
                    await self.db.execute(
                        select(TaxonomyAlias).where(TaxonomyAlias.alias_normalized == key)
                    )
                ).scalar_one_or_none()
                if existing is None:
                    self.db.add(
                        TaxonomyAlias(
                            node_id=node_id,
                            alias_normalized=key,
                            alias_display=(source_text or "")[:200],
                            source="learned",
                            is_approved=False,
                            created_by_user_id=user.id,
                            created_at=datetime.now(timezone.utc),
                        )
                    )
                elif existing.source == "learned" and not existing.is_approved:
                    # Same wording corrected again, to somewhere else - the most
                    # recent reviewer wins, since the old suggestion was never
                    # approved and nothing has been resolved by it.
                    existing.node_id = node_id
                    existing.created_by_user_id = user.id

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise
        await self.db.refresh(item)

        # "Yara Kamal moved 'Cable laying supervision' to Civil works". The
        # labels are read now and written into the sentence: the taxonomy is
        # editable, and a log line that resolved its own node id later would
        # start describing a category that has since been renamed.
        node = await self.db.get(TaxonomyNode, node_id)
        discipline = await self.discipline_of(node_id)
        await record_item_recategorised(
            offer_id=item.offer_id,
            actor=user,
            item_id=item.item_id,
            description=item.description,
            node_label=node.label if node is not None else str(node_id),
            discipline_label=discipline.label if discipline is not None else None,
        )
        return item

    async def list_aliases(self, *, pending_only: bool = False) -> list[TaxonomyAlias]:
        query = select(TaxonomyAlias).order_by(TaxonomyAlias.created_at.desc())
        if pending_only:
            query = query.where(TaxonomyAlias.is_approved.is_(False))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def set_alias_approval(self, alias_id: int, approved: bool) -> TaxonomyAlias | None:
        alias = await self.db.get(TaxonomyAlias, alias_id)
        if alias is None:
            return None
        alias.is_approved = approved
        await self.db.commit()
        await self.db.refresh(alias)
        return alias

    async def delete_alias(self, alias_id: int) -> bool:
        alias = await self.db.get(TaxonomyAlias, alias_id)
        if alias is None:
            return False
        await self.db.delete(alias)
        await self.db.commit()
        return True

    async def get_offer_items(self, offer_id: int) -> list[OfferItem]:
        result = await self.db.execute(
            select(OfferItem).where(OfferItem.offer_id == offer_id).order_by(OfferItem.sort_order)
        )
        return list(result.scalars().all())

    async def discipline_of(self, node_id: int | None) -> TaxonomyNode | None:
        """The discipline root a node sits under (or the node itself if it is one)."""
        if node_id is None:
            return None
        node = await self.db.get(TaxonomyNode, node_id)
        while node is not None and node.parent_node_id is not None:
            node = await self.db.get(TaxonomyNode, node.parent_node_id)
        return node
