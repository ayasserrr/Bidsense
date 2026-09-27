import logging
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from helpers.offer_item_hierarchy import order_items_topologically
from helpers.offer_versioning import check_same_offer_identity
from helpers.polymorphic_entities import delete_polymorphic_offer_rows
from helpers.source_text import build_indexed_page_text, get_offer_documents, get_ordered_pages
from models.db_schema import (
    IncludedFeature,
    InclusionExclusion,
    Offer,
    OfferAttachment,
    OfferItem,
    OfferPaymentSchedule,
    OfferSanityFinding,
    OfferVerifiedFinding,
    Project,
    Supplier,
    SupplierContact,
    TechSpec,
)
from models.enums import EntityType
from schema.offer import ExtractedContact, ExtractedSupplier, OfferExtractionPayload
from schema.persist import (
    IncludedFeatureDB,
    InclusionExclusionDB,
    OfferAttachmentDB,
    OfferDB,
    OfferFullDB,
    OfferItemDB,
    OfferPaymentScheduleDB,
    OfferSanityFindingDB,
    OfferVerifiedFindingDB,
    ProjectDB,
    SupplierContactDB,
    SupplierDB,
    TechSpecDB,
)
from schema.sanity_check import SanityCheckResult
from schema.verification import VerificationResult

from .BaseController import BaseController

logger = logging.getLogger(__name__)


class OfferNotFoundError(Exception):
    def __init__(self, offer_id: int):
        self.offer_id = offer_id
        super().__init__(f"Offer {offer_id} does not exist")


class PersistIntegrityError(Exception):
    """Raised when the DB rejects a write on a constraint (FK/unique/check)
    that upstream validation didn't already catch - carries the DB's own
    `DETAIL` line rather than the full raw SQL/parameters dump."""


class OfferIdentityMismatchError(Exception):
    """Raised when persisting a "new version" offer (one with a
    `parent_offer_id`) whose newly extracted supplier/project doesn't match
    the parent's - this is a structural mismatch (the uploaded document
    likely isn't really a new version of that offer at all), not a
    content-quality issue, so it's rejected outright rather than persisted
    and flagged for review."""

    def __init__(self, offer_id: int, reason: str):
        self.offer_id = offer_id
        self.reason = reason
        super().__init__(reason)


class PersistController(BaseController):
    """Writes a validated `OfferExtractionPayload` (and, once available, its
    `SanityCheckResult`/`VerificationResult`) into the real tables. This is
    the curation step deliberately left out of extraction: it resolves
    `supplier`/`project` to existing rows (or creates new ones), fills in
    the `offers` row that was created empty at upload time, and (re)creates
    every child row from the payload. Re-running it for the same offer
    (e.g. after a re-extraction) is safe - every child table this stage
    owns is cleared and rewritten from scratch each time, never appended to.

    An offer is always persisted regardless of its sanity-check/verification
    outcome - 'needs_human_review' marks an offer for review, it never
    blocks or reverts the write. The database is meant to hold every offer
    that came through the pipeline, clearly labeled by how much it can be
    trusted, not just the ones that passed every check."""

    def __init__(self, db: AsyncSession):
        super().__init__()
        self.db = db

    async def _resolve_supplier(self, signal: ExtractedSupplier) -> Supplier | None:
        """Matches by exact name (case-insensitive) or a known alias first,
        so the same real-world supplier doesn't get a duplicate row every
        time its name is capitalized differently across offers. Returns
        `None` without touching the DB when extraction found no supplier
        name at all - a valid, common result, not an error."""
        if not signal.supplier_name_original:
            return None

        result = await self.db.execute(
            select(Supplier).where(func.lower(Supplier.supplier_name) == signal.supplier_name_original.lower())
        )
        supplier = result.scalar_one_or_none()

        if supplier is None:
            result = await self.db.execute(
                select(Supplier).where(Supplier.supplier_aliases.any(signal.supplier_name_original))
            )
            supplier = result.scalar_one_or_none()

        if supplier is None:
            supplier = Supplier(
                supplier_name=signal.supplier_name_original,
                supplier_aliases=signal.supplier_aliases_seen or None,
                is_sole_agent_for=[signal.sole_agent_for_original] if signal.sole_agent_for_original else None,
            )
            self.db.add(supplier)
            await self.db.flush()
            return supplier

        existing_aliases = supplier.supplier_aliases or []
        new_aliases = [alias for alias in signal.supplier_aliases_seen if alias not in existing_aliases]
        if new_aliases:
            supplier.supplier_aliases = [*existing_aliases, *new_aliases]

        if signal.sole_agent_for_original:
            existing_claims = supplier.is_sole_agent_for or []
            if signal.sole_agent_for_original not in existing_claims:
                supplier.is_sole_agent_for = [*existing_claims, signal.sole_agent_for_original]

        return supplier

    async def _sync_contacts(self, supplier: Supplier, contacts: list[ExtractedContact]) -> None:
        """Adds any contact not already on file for this supplier. Contacts
        are never removed here even if a later extraction omits one - a
        supplier's contact list only grows across offers, since one offer
        simply not repeating a previously-seen contact isn't evidence that
        contact is no longer valid.

        `source_document_id` is intentionally left unset: extraction is
        already merged across every document uploaded under one offer by
        the time it reaches this stage, so there is no single document a
        contact can be attributed to."""
        result = await self.db.execute(select(SupplierContact).where(SupplierContact.supplier_id == supplier.supplier_id))
        existing_keys = {(c.contact_name, c.phone, c.email) for c in result.scalars().all()}

        for contact in contacts:
            key = (contact.contact_name, contact.phone, contact.email)
            if key in existing_keys:
                continue
            self.db.add(
                SupplierContact(
                    supplier_id=supplier.supplier_id,
                    contact_name=contact.contact_name,
                    role=contact.role,
                    phone=contact.phone,
                    email=contact.email,
                )
            )
            existing_keys.add(key)

    async def _resolve_project(self, payload: OfferExtractionPayload) -> Project | None:
        if not payload.project_name_original:
            return None

        result = await self.db.execute(
            select(Project).where(func.lower(Project.project_name) == payload.project_name_original.lower())
        )
        project = result.scalar_one_or_none()

        if project is None:
            result = await self.db.execute(
                select(Project).where(Project.project_aliases.any(payload.project_name_original))
            )
            project = result.scalar_one_or_none()

        if project is None:
            project = Project(
                project_name=payload.project_name_original,
                client_name=payload.client_name_original,
                location=payload.project_location_original,
            )
            self.db.add(project)
            await self.db.flush()
            return project

        if project.location is None and payload.project_location_original:
            project.location = payload.project_location_original

        return project

    async def _check_version_identity(self, offer: Offer, payload: OfferExtractionPayload) -> None:
        """Only called for a "new version" offer (one with a
        `parent_offer_id`). Compares the newly extracted supplier/project
        against the parent's already-linked ones *before* resolving or
        creating anything from this payload - an identity mismatch means
        this document probably isn't really a new version of that offer at
        all, so nothing should be speculatively created or linked from it."""
        parent = await self.db.get(Offer, offer.parent_offer_id)
        parent_supplier = await self.db.get(Supplier, parent.supplier_id) if parent and parent.supplier_id else None
        parent_project = await self.db.get(Project, parent.project_id) if parent and parent.project_id else None

        mismatch = check_same_offer_identity(payload, parent_supplier, parent_project)
        if mismatch is not None:
            raise OfferIdentityMismatchError(offer.id, mismatch)

    async def _clear_existing_offer_data(self, offer_id: int) -> None:
        """Deletes every child row this stage owns for one offer, so a
        re-persist (e.g. after a corrected re-extraction) fully replaces
        rather than appends to what's there. `offer_items` is deleted last
        since `delete_polymorphic_offer_rows` above still needs the item ids
        beforehand - it reads them itself, as a subquery, so nothing here has
        to collect them first."""
        await delete_polymorphic_offer_rows(self.db, offer_id)
        await self.db.execute(delete(OfferPaymentSchedule).where(OfferPaymentSchedule.offer_id == offer_id))
        await self.db.execute(delete(OfferAttachment).where(OfferAttachment.offer_id == offer_id))
        await self.db.execute(delete(OfferSanityFinding).where(OfferSanityFinding.offer_id == offer_id))
        await self.db.execute(delete(OfferVerifiedFinding).where(OfferVerifiedFinding.offer_id == offer_id))
        await self.db.execute(delete(OfferItem).where(OfferItem.offer_id == offer_id))

    async def persist_offer(
        self,
        offer_id: int,
        payload: OfferExtractionPayload,
        sanity_check_result: SanityCheckResult | None = None,
        verification_result: VerificationResult | None = None,
        commit: bool = True,
    ) -> Offer:
        offer = await self.db.get(Offer, offer_id)
        if offer is None:
            raise OfferNotFoundError(offer_id)

        if offer.parent_offer_id is not None:
            await self._check_version_identity(offer, payload)

        supplier = await self._resolve_supplier(payload.supplier)
        if supplier is not None:
            await self._sync_contacts(supplier, payload.contacts)
        project = await self._resolve_project(payload)

        # mode="json" so enum fields (currency_primary, grand_total_currency)
        # serialize to their plain string .value rather than being handed to
        # the DB driver as (str, Enum) instances.
        offer_fields = payload.model_dump(
            mode="json",
            exclude={"supplier", "contacts", "attachments", "items", "tech_specs",
                     "included_features", "inclusions_exclusions", "payment_schedules"},
        )
        for field, value in offer_fields.items():
            setattr(offer, field, value)

        # Only overwrite a resolved link - a run that doesn't turn up a
        # supplier/project name (e.g. a re-extraction chunking artifact)
        # must not wipe out a previously-resolved one.
        if supplier is not None:
            offer.supplier_id = supplier.supplier_id
        if project is not None:
            offer.project_id = project.project_id

        if sanity_check_result is not None:
            offer.sanity_check_status = sanity_check_result.status.value
            offer.sanity_check_summary = sanity_check_result.summary

        if verification_result is not None:
            offer.verification_status = verification_result.status.value
            offer.verification_summary = verification_result.summary

        # The line between "an offer" and "a row left behind by a run that did
        # not finish". A failed background run now KEEPS its offer and files so
        # a retry does not mean re-uploading; this is what keeps such a row out
        # of the offers list until it is real.
        offer.persisted_at = datetime.now(timezone.utc)

        await self.db.flush()
        await self._clear_existing_offer_data(offer.id)

        local_id_to_item_id: dict[str, int] = {}
        # extraction's alternate_group_id is a string tag (chunk-namespaced,
        # e.g. "c0_group_a") - offer_items.alternate_group_id is a real
        # Integer column, so each unique tag gets remapped to a stable
        # sequential id, the same way parent_local_id is remapped via
        # local_id_to_item_id above.
        alternate_group_id_map: dict[str, int] = {}
        for sort_order, item in enumerate(order_items_topologically(payload.items)):
            parent_item_id = (
                local_id_to_item_id[item.parent_local_id] if item.parent_local_id is not None else None
            )
            alternate_group_id: int | None = None
            if item.alternate_group_id is not None:
                alternate_group_id = alternate_group_id_map.setdefault(
                    item.alternate_group_id, len(alternate_group_id_map) + 1
                )
            db_item = OfferItem(
                offer_id=offer.id,
                parent_item_id=parent_item_id,
                alternate_group_id=alternate_group_id,
                sort_order=sort_order,
                **item.model_dump(
                    mode="json", exclude={"local_id", "parent_local_id", "alternate_group_id"}
                ),
            )
            self.db.add(db_item)
            await self.db.flush()
            local_id_to_item_id[item.local_id] = db_item.item_id

        for schedule in payload.payment_schedules:
            scope_item_ids = (
                [local_id_to_item_id[local_id] for local_id in schedule.scope_item_local_ids]
                if schedule.scope_item_local_ids
                else None
            )
            self.db.add(
                OfferPaymentSchedule(
                    offer_id=offer.id,
                    scope_item_ids=scope_item_ids,
                    **schedule.model_dump(exclude={"scope_item_local_ids"}),
                )
            )

        for sort_order, spec in enumerate(payload.tech_specs):
            entity_id = offer.id if spec.entity_type == EntityType.OFFER else local_id_to_item_id[spec.entity_local_id]
            self.db.add(
                TechSpec(
                    entity_type=spec.entity_type.value,
                    entity_id=entity_id,
                    spec_group=spec.spec_group,
                    spec_name=spec.spec_name,
                    spec_value=spec.spec_value,
                    spec_unit=spec.spec_unit,
                    sort_order=sort_order,
                )
            )

        for sort_order, feature in enumerate(payload.included_features):
            entity_id = (
                offer.id if feature.entity_type == EntityType.OFFER else local_id_to_item_id[feature.entity_local_id]
            )
            self.db.add(
                IncludedFeature(
                    entity_type=feature.entity_type.value,
                    entity_id=entity_id,
                    feature_text=feature.feature_text,
                    feature_category=feature.feature_category,
                    sort_order=sort_order,
                )
            )

        for sort_order, entry in enumerate(payload.inclusions_exclusions):
            self.db.add(
                InclusionExclusion(
                    entity_type="offer",
                    entity_id=offer.id,
                    entry_type=entry.entry_type.value,
                    description=entry.description,
                    sort_order=sort_order,
                )
            )

        for attachment in payload.attachments:
            self.db.add(OfferAttachment(offer_id=offer.id, attachment_label=attachment.attachment_label))

        if sanity_check_result is not None:
            for sort_order, finding in enumerate(sanity_check_result.findings):
                self.db.add(
                    OfferSanityFinding(
                        offer_id=offer.id,
                        issue_type=finding.issue_type.value,
                        severity=finding.severity.value,
                        field_path=finding.field_path,
                        description=finding.description,
                        sort_order=sort_order,
                    )
                )

        if verification_result is not None:
            for sort_order, finding in enumerate(verification_result.verified_findings):
                self.db.add(
                    OfferVerifiedFinding(
                        offer_id=offer.id,
                        issue_type=finding.issue_type.value,
                        field_path=finding.field_path,
                        extraction_verdict=finding.extraction_verdict.value,
                        extraction_correction=finding.extraction_correction,
                        finding_verdict=finding.finding_verdict.value,
                        explanation=finding.explanation,
                        evidence_quote=finding.evidence_quote,
                        reasoning=finding.reasoning,
                        sort_order=sort_order,
                    )
                )

        try:
            if commit:
                await self.db.commit()
            else:
                await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            detail = getattr(getattr(exc, "orig", None), "detail", None)
            raise PersistIntegrityError(detail or "This offer's data violates a database constraint.") from exc
        except Exception:
            await self.db.rollback()
            raise

        await self.db.refresh(offer)
        return offer

    async def attribute_item_sources(self, offer_id: int) -> int:
        """Records which uploaded file each line item came from.

        Extraction is never asked for this. It reads several files merged into
        one text and has no reliable idea which was which - and a filename it
        guessed at would be indistinguishable from one it read. Instead each
        item's own words are looked up in the merged source text and the
        position gives the answer, the same mechanism the completeness report
        uses for its evidence quotes.

        A single-file offer skips the search entirely: there is only one
        possible answer. Items whose text cannot be located keep a null source,
        which is reported as unknown rather than guessed.
        """
        documents = await get_offer_documents(self.db, offer_id)
        if not documents:
            return 0

        items = list(
            (
                await self.db.execute(select(OfferItem).where(OfferItem.offer_id == offer_id))
            )
            .scalars()
            .all()
        )
        if not items:
            return 0

        if len(documents) == 1:
            only_id = documents[0]["document_id"]
            for item in items:
                item.source_document_id = only_id
            await self.db.commit()
            return len(items)

        filenames = {doc["document_id"]: doc["filename"] for doc in documents}
        pages = []
        for document in documents:
            pages.extend(await get_ordered_pages(self.db, document["document_id"]))
        index = build_indexed_page_text(pages, filenames)

        attributed = 0
        for item in items:
            segment = None
            for candidate in (item.description, item.model_number, item.item_code):
                if not candidate:
                    continue
                # A long description may be reflowed in the source; the opening
                # words are the part that survives verbatim.
                needle = candidate.strip()[:120]
                segment = index.locate(needle)
                if segment is not None:
                    break
            if segment is None:
                continue
            item.source_document_id = segment.document_id
            if item.source_page_number is None:
                item.source_page_number = segment.page_number
            attributed += 1

        await self.db.commit()
        return attributed

    async def get_full_offer(self, offer_id: int) -> OfferFullDB:
        """Reads back everything persisted for one offer, structured by
        table - the counterpart to `persist_offer`'s writes."""
        offer = await self.db.get(Offer, offer_id)
        if offer is None:
            raise OfferNotFoundError(offer_id)

        supplier = await self.db.get(Supplier, offer.supplier_id) if offer.supplier_id else None
        project = await self.db.get(Project, offer.project_id) if offer.project_id else None

        contacts = []
        if supplier is not None:
            result = await self.db.execute(
                select(SupplierContact)
                .where(SupplierContact.supplier_id == supplier.supplier_id)
                .order_by(SupplierContact.contact_id)
            )
            contacts = result.scalars().all()

        # sort_order is rarely populated by extraction (it's derived at
        # persist time from list position, not part of the extracted
        # schema) - item_id as a tiebreaker keeps ties in insertion order
        # (which is topological/document order) instead of leaving them to
        # the database's unspecified tie-break.
        result = await self.db.execute(
            select(OfferItem).where(OfferItem.offer_id == offer_id).order_by(OfferItem.sort_order, OfferItem.item_id)
        )
        items = result.scalars().all()
        item_ids = [item.item_id for item in items]

        result = await self.db.execute(
            select(OfferPaymentSchedule)
            .where(OfferPaymentSchedule.offer_id == offer_id)
            .order_by(OfferPaymentSchedule.sequence_no)
        )
        payment_schedules = result.scalars().all()

        tech_specs_filter = (TechSpec.entity_type == EntityType.OFFER.value) & (TechSpec.entity_id == offer_id)
        if item_ids:
            tech_specs_filter = tech_specs_filter | (
                (TechSpec.entity_type == EntityType.ITEM.value) & (TechSpec.entity_id.in_(item_ids))
            )
        result = await self.db.execute(
            select(TechSpec).where(tech_specs_filter).order_by(TechSpec.sort_order, TechSpec.spec_id)
        )
        tech_specs = result.scalars().all()

        features_filter = (IncludedFeature.entity_type == EntityType.OFFER.value) & (
            IncludedFeature.entity_id == offer_id
        )
        if item_ids:
            features_filter = features_filter | (
                (IncludedFeature.entity_type == EntityType.ITEM.value) & (IncludedFeature.entity_id.in_(item_ids))
            )
        result = await self.db.execute(
            select(IncludedFeature).where(features_filter).order_by(IncludedFeature.sort_order, IncludedFeature.feature_id)
        )
        included_features = result.scalars().all()

        result = await self.db.execute(
            select(InclusionExclusion)
            .where(InclusionExclusion.entity_id == offer_id)
            .order_by(InclusionExclusion.sort_order, InclusionExclusion.entry_id)
        )
        inclusions_exclusions = result.scalars().all()

        result = await self.db.execute(
            select(OfferAttachment).where(OfferAttachment.offer_id == offer_id).order_by(OfferAttachment.attachment_id)
        )
        attachments = result.scalars().all()

        result = await self.db.execute(
            select(OfferSanityFinding)
            .where(OfferSanityFinding.offer_id == offer_id)
            .order_by(OfferSanityFinding.sort_order, OfferSanityFinding.finding_id)
        )
        sanity_findings = result.scalars().all()

        result = await self.db.execute(
            select(OfferVerifiedFinding)
            .where(OfferVerifiedFinding.offer_id == offer_id)
            .order_by(OfferVerifiedFinding.sort_order, OfferVerifiedFinding.verified_finding_id)
        )
        verified_findings = result.scalars().all()

        return OfferFullDB(
            offer=OfferDB.model_validate(offer),
            supplier=SupplierDB.model_validate(supplier) if supplier is not None else None,
            project=ProjectDB.model_validate(project) if project is not None else None,
            contacts=[SupplierContactDB.model_validate(c) for c in contacts],
            items=[OfferItemDB.model_validate(i) for i in items],
            payment_schedules=[OfferPaymentScheduleDB.model_validate(p) for p in payment_schedules],
            tech_specs=[TechSpecDB.model_validate(t) for t in tech_specs],
            included_features=[IncludedFeatureDB.model_validate(f) for f in included_features],
            inclusions_exclusions=[InclusionExclusionDB.model_validate(e) for e in inclusions_exclusions],
            attachments=[OfferAttachmentDB.model_validate(a) for a in attachments],
            sanity_findings=[OfferSanityFindingDB.model_validate(f) for f in sanity_findings],
            verified_findings=[OfferVerifiedFindingDB.model_validate(f) for f in verified_findings],
        )
