import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from controllers import JobController, TaxonomyController
from db import get_db
from dependencies import governed_user, require_admin
from helpers.visibility import visible_offer
from models.db_schema import Offer, OfferItem, User
from models.enums import JobKind, ResponseSignal
from pipeline import runner
from schema.jobs import JobOut, JobStage
from schema.taxonomy import (
    ItemCategoryOverrideRequest,
    ItemTaxonomyOut,
    OfferTaxonomyResponse,
    TaxonomyAliasOut,
    TaxonomyTreeNode,
)

logger = logging.getLogger(__name__)

taxonomy_router = APIRouter(
    prefix="/api/v1",
    tags=["taxonomy"],
    dependencies=[Depends(governed_user)],
)


@taxonomy_router.get("/taxonomy", response_model=list[TaxonomyTreeNode])
async def get_taxonomy(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> list[TaxonomyTreeNode]:
    """The category tree: ten disciplines and the equipment under each, with
    how many items from offers the caller may see sit in each one."""
    controller = TaxonomyController(db)
    nodes = await controller.get_nodes()
    counts = await controller.item_counts(user)

    by_id = {
        node.node_id: TaxonomyTreeNode(
            node_id=node.node_id,
            parent_node_id=node.parent_node_id,
            code=node.code,
            label=node.label,
            level=node.level,
            sort_order=node.sort_order,
            is_active=node.is_active,
            item_count=counts.get(node.node_id, 0),
        )
        for node in nodes
    }
    roots: list[TaxonomyTreeNode] = []
    for node in nodes:
        out = by_id[node.node_id]
        parent = by_id.get(node.parent_node_id) if node.parent_node_id else None
        if parent is None:
            roots.append(out)
        else:
            parent.children.append(out)
            # A discipline's count includes everything filed underneath it -
            # that is the number the completeness report is really asking about.
            parent.item_count += out.item_count
    return roots


@taxonomy_router.get(
    "/offers/{offer_id}/taxonomy",
    response_model=OfferTaxonomyResponse,
    dependencies=[Depends(visible_offer)],
)
async def get_offer_taxonomy(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
) -> OfferTaxonomyResponse:
    """Every line item of one offer and the discipline it was sorted into."""
    controller = TaxonomyController(db)
    items = await controller.get_offer_items(offer_id)
    nodes = {node.node_id: node for node in await controller.get_nodes()}

    def discipline_of(node_id):
        node = nodes.get(node_id)
        while node is not None and node.parent_node_id is not None:
            node = nodes.get(node.parent_node_id)
        return node

    out_items: list[ItemTaxonomyOut] = []
    disciplines: dict[str, int] = {}
    resolved = 0
    for item in items:
        node = nodes.get(item.taxonomy_node_id) if item.taxonomy_node_id else None
        root = discipline_of(item.taxonomy_node_id)
        if node is not None:
            resolved += 1
        if root is not None:
            disciplines[root.code] = disciplines.get(root.code, 0) + 1
        out_items.append(
            ItemTaxonomyOut(
                item_id=item.item_id,
                description=item.description,
                equipment_type_original=item.equipment_type_original,
                node_id=node.node_id if node else None,
                node_code=node.code if node else None,
                node_label=node.label if node else None,
                discipline_code=root.code if root else None,
                discipline_label=root.label if root else None,
            )
        )

    return OfferTaxonomyResponse(
        signal=ResponseSignal.TAXONOMY_RESOLVED,
        offer_id=offer_id,
        resolved_count=resolved,
        unresolved_count=len(items) - resolved,
        disciplines=disciplines,
        items=out_items,
    )


@taxonomy_router.post(
    "/offers/{offer_id}/taxonomy/recheck",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(visible_offer)],
)
async def recheck_taxonomy(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> JobOut:
    """Sorts the offer's items again - worth doing after an admin approves new
    aliases, which is when previously unresolved items start resolving."""
    offer = await db.get(Offer, offer_id)
    # None only if the offer was discarded mid-request, and only unfinished
    # offers can be discarded - so "not finished" is the right answer for it.
    if offer is None or offer.persisted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This offer has not finished processing yet, so it has no items to sort.",
        )

    job = await JobController(db).create_job(kind=JobKind.TAXONOMY, offer_id=offer_id, user=user)
    runner.start_job(job.job_id, JobKind.TAXONOMY, offer_id, [])
    return JobOut(
        job_id=job.job_id,
        kind=JobKind.TAXONOMY,
        status=job.status,
        offer_id=offer_id,
        stages=[JobStage.model_validate(stage) for stage in (job.stages or [])],
        current_stage=job.current_stage,
        progress_percent=job.progress_percent,
        created_at=job.created_at,
        updated_at=job.updated_at,
        offer_persisted=True,
    )


@taxonomy_router.post(
    "/offers/{offer_id}/items/{item_id}/category",
    response_model=ItemTaxonomyOut,
    dependencies=[Depends(visible_offer)],
)
async def override_item_category(
    offer_id: int,
    item_id: int,
    body: ItemCategoryOverrideRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> ItemTaxonomyOut:
    """Moves one item into the right category.

    With `learn_alias`, the wording is remembered so future offers using the
    same phrase resolve automatically - but the new alias starts UNAPPROVED and
    an admin has to accept it. One reviewer's correction becoming an instant,
    global, permanent rule is how a taxonomy quietly rots.
    """
    controller = TaxonomyController(db)

    item = await db.get(OfferItem, item_id)
    if item is None or item.offer_id != offer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="That item is not part of this offer."
        )
    nodes = {node.node_id: node for node in await controller.get_nodes()}
    if body.node_id not in nodes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown category."
        )

    item = await controller.override_item_category(
        item=item, node_id=body.node_id, learn_alias=body.learn_alias, user=user
    )

    node = nodes[item.taxonomy_node_id]
    root = node
    while root.parent_node_id is not None and root.parent_node_id in nodes:
        root = nodes[root.parent_node_id]
    return ItemTaxonomyOut(
        item_id=item.item_id,
        description=item.description,
        equipment_type_original=item.equipment_type_original,
        node_id=node.node_id,
        node_code=node.code,
        node_label=node.label,
        discipline_code=root.code,
        discipline_label=root.label,
    )


@taxonomy_router.get(
    "/taxonomy/aliases", response_model=list[TaxonomyAliasOut], dependencies=[Depends(require_admin)]
)
async def list_aliases(
    pending_only: bool = False, db: AsyncSession = Depends(get_db)
) -> list[TaxonomyAliasOut]:
    """The alias table. `pending_only` shows the reviewer corrections waiting
    for approval - the queue an admin works through."""
    rows = await TaxonomyController(db).list_aliases(pending_only=pending_only)
    return [TaxonomyAliasOut.model_validate(row) for row in rows]


@taxonomy_router.post(
    "/taxonomy/aliases/{alias_id}/approve",
    response_model=TaxonomyAliasOut,
    dependencies=[Depends(require_admin)],
)
async def approve_alias(alias_id: int, db: AsyncSession = Depends(get_db)) -> TaxonomyAliasOut:
    alias = await TaxonomyController(db).set_alias_approval(alias_id, True)
    if alias is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alias not found.")
    return TaxonomyAliasOut.model_validate(alias)


@taxonomy_router.post(
    "/taxonomy/aliases/{alias_id}/reject", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def reject_alias(alias_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Discards a suggested alias. The item it was created from keeps the
    category the reviewer gave it - only the global rule is dropped."""
    if not await TaxonomyController(db).delete_alias(alias_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alias not found.")
