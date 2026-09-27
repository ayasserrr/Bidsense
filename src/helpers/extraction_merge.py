from models.db_schema import DocumentPage
from models.enums import EntityType
from schema.offer import (
    ExtractedContact,
    ExtractedItem,
    ExtractedPaymentSchedule,
    ExtractedSupplier,
    OfferExtractionPayload,
)

_OFFER_SCALAR_FIELDS = [
    "offer_ref",
    "project_name_original",
    "client_name_original",
    "project_location_original",
    "payment_terms_original",
    "price_currency_original",
    "currency_primary",
    "grand_total",
    "grand_total_currency",
    "tax_treatment_original",
    "incoterm",
    "delivery_terms_original",
    "validity_terms_original",
    "warranty_terms_original",
    "manufacturer_original",
    "product_name_original",
    "offer_date_original",
    "offer_signed_by_original",
]


def chunk_pages(pages: list[DocumentPage], max_pages: int, overlap: int) -> list[list[DocumentPage]]:
    """Splits `pages` (already ordered) into chunks of at most `max_pages`,
    with `overlap` pages repeated between consecutive chunks so a cut
    mid-item/mid-table still leaves context on both sides of the split."""
    if len(pages) <= max_pages:
        return [pages]

    step = max(max_pages - overlap, 1)
    chunks: list[list[DocumentPage]] = []
    start = 0
    while start < len(pages):
        end = min(start + max_pages, len(pages))
        chunks.append(pages[start:end])
        if end == len(pages):
            break
        start += step
    return chunks


def _namespace_items(items: list[ExtractedItem], prefix: str) -> list[ExtractedItem]:
    """Each chunk's LLM call independently numbers local_id from item_1, so
    two chunks' items collide on the same id unless remapped before merging.
    Every local_id, parent_local_id, and alternate_group_id an item carries
    is scoped to its own chunk only (a chunk's model never sees another
    chunk's ids to reference), so prefixing all three by chunk index is
    always safe - it can't accidentally sever or misroute a real link."""
    namespaced = []
    for item in items:
        data = item.model_dump()
        data["local_id"] = prefix + data["local_id"]
        if data["parent_local_id"] is not None:
            data["parent_local_id"] = prefix + data["parent_local_id"]
        if data["alternate_group_id"] is not None:
            data["alternate_group_id"] = prefix + data["alternate_group_id"]
        namespaced.append(ExtractedItem(**data))
    return namespaced


def _namespace_entity_refs(entries: list, prefix: str) -> list:
    namespaced = []
    for entry in entries:
        data = entry.model_dump()
        if data["entity_type"] == EntityType.ITEM and data["entity_local_id"] is not None:
            data["entity_local_id"] = prefix + data["entity_local_id"]
        namespaced.append(type(entry)(**data))
    return namespaced


def _namespace_payment_schedules(schedules: list[ExtractedPaymentSchedule], prefix: str) -> list[ExtractedPaymentSchedule]:
    namespaced = []
    for schedule in schedules:
        data = schedule.model_dump()
        if data["scope_item_local_ids"]:
            data["scope_item_local_ids"] = [prefix + local_id for local_id in data["scope_item_local_ids"]]
        namespaced.append(ExtractedPaymentSchedule(**data))
    return namespaced


def _merge_supplier(payloads: list[OfferExtractionPayload]) -> ExtractedSupplier:
    name_original: str | None = None
    sole_agent_for_original: str | None = None
    aliases_seen: list[str] = []

    for payload in payloads:
        if name_original is None and payload.supplier.supplier_name_original:
            name_original = payload.supplier.supplier_name_original
            sole_agent_for_original = payload.supplier.sole_agent_for_original
        for alias in payload.supplier.supplier_aliases_seen:
            if alias not in aliases_seen:
                aliases_seen.append(alias)

    return ExtractedSupplier(
        supplier_name_original=name_original,
        sole_agent_for_original=sole_agent_for_original,
        supplier_aliases_seen=aliases_seen,
    )


def merge_chunk_payloads(payloads: list[OfferExtractionPayload]) -> OfferExtractionPayload:
    """Stitches per-chunk payloads back into one. List fields concatenate
    (after remapping item ids so they don't collide across chunks); offer-
    level scalars take the first non-null value seen, in chunk order, since
    an offer-wide field like `payment_terms_original` should only ever be
    stated once and any chunk that saw it will have filled it in the same
    way."""
    if not payloads:
        raise ValueError("merge_chunk_payloads requires at least one payload")
    if len(payloads) == 1:
        return payloads[0]

    merged_items: list[ExtractedItem] = []
    merged_tech_specs = []
    merged_included_features = []
    merged_inclusions_exclusions = []
    merged_payment_schedules = []
    merged_contacts: list[ExtractedContact] = []
    merged_attachments = []

    for index, payload in enumerate(payloads):
        prefix = f"c{index}_"
        merged_items.extend(_namespace_items(payload.items, prefix))
        merged_tech_specs.extend(_namespace_entity_refs(payload.tech_specs, prefix))
        merged_included_features.extend(_namespace_entity_refs(payload.included_features, prefix))
        merged_inclusions_exclusions.extend(payload.inclusions_exclusions)
        merged_payment_schedules.extend(_namespace_payment_schedules(payload.payment_schedules, prefix))
        merged_contacts.extend(payload.contacts)
        merged_attachments.extend(payload.attachments)

    # Re-sequence payment milestones 1..N regardless of what each chunk
    # numbered them, since chunk-local numbering has no cross-chunk meaning.
    merged_payment_schedules = [
        schedule.model_copy(update={"sequence_no": position + 1})
        for position, schedule in enumerate(merged_payment_schedules)
    ]

    merged_scalars: dict = {}
    for field in _OFFER_SCALAR_FIELDS:
        merged_scalars[field] = next(
            (getattr(payload, field) for payload in payloads if getattr(payload, field) is not None),
            None,
        )

    # A standalone note is real, distinct information wherever it appears -
    # concatenate rather than pick one chunk's notes over another's.
    notes = [payload.general_notes_original for payload in payloads if payload.general_notes_original]
    merged_scalars["general_notes_original"] = "\n".join(notes) if notes else None

    merged_extra_attributes: dict[str, str] = {}
    for payload in reversed(payloads):
        if payload.extra_attributes:
            merged_extra_attributes.update(payload.extra_attributes)

    return OfferExtractionPayload(
        **merged_scalars,
        extra_attributes=merged_extra_attributes or None,
        supplier=_merge_supplier(payloads),
        contacts=merged_contacts,
        attachments=merged_attachments,
        items=merged_items,
        tech_specs=merged_tech_specs,
        included_features=merged_included_features,
        inclusions_exclusions=merged_inclusions_exclusions,
        payment_schedules=merged_payment_schedules,
    )


def drop_signature_only_contact_duplicate(payload: OfferExtractionPayload) -> OfferExtractionPayload:
    """A closing signature ("Regards, [Name]") must never also appear as a
    `contacts` entry per SYSTEM_PROMPT - this is defense-in-depth for when
    the model does it anyway despite the instruction."""
    signed_by = (payload.offer_signed_by_original or "").strip().casefold()
    if not signed_by:
        return payload

    def is_signature_duplicate(contact: ExtractedContact) -> bool:
        return (
            contact.contact_name.strip().casefold() == signed_by
            and contact.role is None
            and contact.phone is None
            and contact.email is None
        )

    filtered_contacts = [c for c in payload.contacts if not is_signature_duplicate(c)]
    if len(filtered_contacts) == len(payload.contacts):
        return payload
    return payload.model_copy(update={"contacts": filtered_contacts})
