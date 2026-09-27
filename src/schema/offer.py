from pydantic import BaseModel, Field, model_validator

from models.enums import CurrencyCode, EntityType, EntryType, ItemCategory, PriceBasis, ResponseSignal


class ExtractedSupplier(BaseModel):
    supplier_name_original: str | None = Field(
        default=None,
        description=(
            "The supplier's own name exactly as printed on its letterhead/header, verbatim. "
            "Null if the document never names its own issuing supplier."
        ),
    )
    supplier_aliases_seen: list[str] = Field(
        default_factory=list,
        description=(
            "Other spellings or abbreviations of this same supplier's name used elsewhere in "
            "this document (e.g. a full English name on the letterhead vs. an abbreviated form "
            "in a footer or stamp). Empty list if the document only ever uses one form."
        ),
    )
    sole_agent_for_original: str | None = Field(
        default=None,
        description=(
            "Verbatim text of an exclusivity/agency claim, if the document opens or closes with "
            "one (e.g. 'sole agent for X in Egypt', 'authorized distributor of Y'). Null if no "
            "such claim is made - do not infer agency from a brand name appearing in the "
            "equipment description alone."
        ),
    )


class ExtractedContact(BaseModel):
    contact_name: str = Field(
        description=(
            "Full name of a person named as an actual point of contact - someone given a role "
            "and/or a phone/email in a letterhead, header block, or 'prepared by/contact' line. "
            "Do not include a closing signature with no role/phone/email here - that belongs in "
            "the offer's own offer_signed_by_original field, not contacts."
        )
    )
    role: str | None = Field(default=None, description="The contact's stated role/title, verbatim, if given.")
    phone: str | None = Field(default=None, description="The contact's phone number as printed, if given.")
    email: str | None = Field(default=None, description="The contact's email address as printed, if given.")


class ExtractedAttachment(BaseModel):
    attachment_label: str = Field(
        description=(
            "The label/description of an attachment exactly as the document's own text "
            "references it (e.g. 'Annex A - Technical Specifications', 'attached datasheet'). "
            "Only for attachments mentioned in the source text itself, not files that might "
            "exist elsewhere in the system."
        )
    )


class ExtractedItem(BaseModel):
    """One priced (or intentionally unpriced, e.g. included_no_charge/tbd) line item.
    `local_id`/`parent_local_id` are extraction-time-only identifiers (no real
    `offer_items.item_id` exists yet) - a later persist stage remaps them to
    real DB ids. Same for `alternate_group_id`: a string tag shared by every
    item in one mutually-exclusive alternate group, not yet the real int
    `offer_items.alternate_group_id`."""

    local_id: str = Field(
        description=(
            "A short unique identifier you assign to this item for this extraction only "
            "(e.g. 'item_1', 'item_2', ...). Not a real database id."
        )
    )
    parent_local_id: str | None = Field(
        default=None,
        description=(
            "The local_id of this item's parent, if this item is a dependent sub-part or "
            "accessory of another item in this same list (see the system prompt's structure "
            "illustrations for how to decide this). Null if this is a top-level item. Must "
            "reference a local_id that exists elsewhere in items; never itself."
        ),
    )
    item_code: str | None = Field(
        default=None, description="The supplier's own item/part code or row reference, if printed. Null if none."
    )
    item_group_label: str | None = Field(
        default=None,
        description=(
            "The section heading this item belongs to, set only when the source groups sibling "
            "items under labeled headings with no repeated block structure (e.g. 'Outdoor "
            "Units', 'Indoor Units'). Every item in the same section must carry the identical "
            "label - not just some of them. Null when the document has no such section grouping."
        ),
    )
    item_category: ItemCategory = Field(
        description="The controlled category this item belongs to. Pick the closest defined value if nothing matches exactly."
    )
    is_optional: bool = Field(
        default=False,
        description="True if the buyer may add this item on top of everything else (additive). False by default.",
    )
    is_alternate: bool = Field(
        default=False,
        description=(
            "True if this item is one of several competing options for the same position "
            "(substitutive, not additive) - e.g. 'Option A: Mitsubishi engine' vs 'Option B: "
            "Cummins engine'. Every item in the same alternate group shares alternate_group_id."
        ),
    )
    alternate_group_id: str | None = Field(
        default=None,
        description="A tag shared by every item that is a mutually exclusive alternative to this one. Null unless is_alternate is true.",
    )
    is_lump_sum: bool = Field(
        default=False, description="True if this item is priced as a single lump sum rather than quantity x unit price."
    )
    price_basis: PriceBasis = Field(
        default=PriceBasis.FIXED,
        description=(
            "How this item's price is determined: 'fixed' for a stated price, "
            "'percentage_of_parent' when priced as a percentage of another item (also set "
            "percentage_value and parent_local_id to that item), 'included_no_charge' when "
            "stated as included/free of charge, 'tbd' when the price is explicitly not yet "
            "determined."
        ),
    )
    percentage_value: float | None = Field(
        default=None,
        description=(
            "The percentage this item's price represents of its parent item's price, only when "
            "price_basis is percentage_of_parent, and only as explicitly printed - never "
            "calculated by you."
        ),
    )
    discount_amount: float | None = Field(
        default=None, description="A discount amount explicitly stated for this item, if any. Null if none stated."
    )
    description: str = Field(
        description=(
            "This item's description, verbatim from the source. If a shared paragraph precedes "
            "this item's whole section, prepend it (separated by ' - ') per the system prompt's "
            "section-grouping rule."
        )
    )
    model_number: str | None = Field(default=None, description="The equipment model/type designation as printed, if any.")
    equipment_type_original: str | None = Field(
        default=None,
        description=(
            "The specific kind of equipment this item is, verbatim or closely paraphrased from "
            "how the document itself describes it (e.g. 'Standby Diesel Generator', 'Package AC "
            "Unit', 'Chiller', 'Automatic Transfer Switch') - a granular descriptor of what the "
            "item actually is, distinct from item_category's coarse bucket (equipment/accessory/"
            "spare_part/etc.) and from model_number (the specific model/type code). Null when "
            "this item isn't itself a piece of equipment (e.g. a service or payment term line) "
            "or the document gives no descriptive name for what kind of equipment it is."
        ),
    )
    unit: str | None = Field(default=None, description="The unit of measure printed for quantity (e.g. 'pcs', 'm', 'set'), if any.")
    quantity: float = Field(
        description="The quantity as printed for this row. Never inferred or defaulted to 1 without the source stating it."
    )
    unit_price: float | None = Field(
        default=None,
        description=(
            "The unit price as printed for this row. Null if not printed - even when total_price "
            "and quantity are both known, never back-calculated by dividing."
        ),
    )
    total_price: float | None = Field(
        default=None,
        description=(
            "The total price as printed for this row. Null if not printed - never quantity x "
            "unit_price computed by you. If both unit_price and total_price are printed but "
            "don't reconcile, transcribe both exactly as printed anyway."
        ),
    )
    price_currency: CurrencyCode | None = Field(
        default=None, description="The ISO-4217 code this item's price is stated in, mapped from the document's own currency text."
    )
    price_currency_original: str | None = Field(
        default=None, description="The document's own literal currency text for this item's price (e.g. 'US$', 'L.E'), unmapped."
    )
    stated_subtotal_amount: float | None = Field(
        default=None,
        description=(
            "A subtotal the supplier explicitly states for a group this item heads (e.g. a "
            "'Total Price Excluding VAT' line). Only the supplier's own printed figure, never "
            "a sum you compute."
        ),
    )
    stated_subtotal_currency: CurrencyCode | None = Field(
        default=None, description="ISO-4217 code for stated_subtotal_amount's currency."
    )
    tax_treatment_override_original: str | None = Field(
        default=None,
        description="This item's own tax treatment, verbatim, only when it differs from/overrides the offer-wide tax_treatment_original.",
    )
    incoterm_override: str | None = Field(
        default=None,
        description="This item's own incoterm, only when it differs from/overrides the offer-wide incoterm.",
    )
    payment_terms_override_original: str | None = Field(
        default=None,
        description=(
            "This item's own payment terms, verbatim, only when the document states terms for "
            "this specific item/section that differ from the offer-wide payment_terms_original "
            "(e.g. two separately-priced units with different advance/delivery/final splits). "
            "Use payment_schedules with a matching scope_label for the structured milestone "
            "breakdown of these same terms; this field is the prose safety net."
        ),
    )
    delivery_terms_override_original: str | None = Field(
        default=None,
        description=(
            "This item's own delivery point/condition, verbatim, only when the document states "
            "delivery terms for this specific item/section that differ from the offer-wide "
            "delivery_terms_original (e.g. one unit shipped Ex-Works, another CIF to a "
            "different port). Null when this item shares the offer-wide terms."
        ),
    )
    availability_original_text: str | None = Field(
        default=None,
        description=(
            "This row's own printed lead-time/availability text (e.g. '3 - 4 Months', "
            "'Ex-stock'), if the pricing table has a column or inline note for it specific to "
            "this row. Null only when this row genuinely has none of its own."
        ),
    )
    extra_attributes: dict[str, str] | None = Field(
        default=None,
        description=(
            "A flat {label: verbatim value} map for a discrete, standalone fact about this "
            "specific item that has no other home in this schema - not a term, not a spec (use "
            "tech_specs), not an inclusion/exclusion. Null when nothing qualifies."
        ),
    )
    source_page_number: int | None = Field(
        default=None, description="The page number where this item is printed (the starting page if it spans more than one)."
    )


class ExtractedTechSpec(BaseModel):
    entity_type: EntityType = Field(
        description="Whether this spec belongs to one specific item or to the offer as a whole."
    )
    entity_local_id: str | None = Field(
        default=None,
        description="The local_id of the item this spec belongs to, required when entity_type is 'item'. Null when entity_type is 'offer'.",
    )
    spec_group: str = Field(
        description="The sub-section/label this spec was printed under, as printed (e.g. 'Engine', 'Battery', 'Control Panel')."
    )
    spec_name: str = Field(description="The spec's own label, as printed (e.g. 'Voltage', 'Frequency', 'Capacity').")
    spec_value: str = Field(description="The spec's value, as printed, verbatim.")
    spec_unit: str | None = Field(default=None, description="The unit for spec_value, if printed as a separate token (e.g. 'V', 'Hz', 'kW').")


class ExtractedIncludedFeature(BaseModel):
    entity_type: EntityType = Field(
        description="Whether this feature belongs to one specific item or to the offer as a whole."
    )
    entity_local_id: str | None = Field(
        default=None,
        description="The local_id of the item this feature belongs to, required when entity_type is 'item'. Null when entity_type is 'offer'.",
    )
    feature_text: str = Field(
        description=(
            "An informal 'comes with' bullet describing what's bundled into this entity's own "
            "price, verbatim (e.g. 'Complete with base fuel tank, battery, and battery "
            "charger'). Not part of a formal offer-wide Includes/Excludes declaration - those "
            "belong in inclusions_exclusions instead, never split across both."
        )
    )
    feature_category: str | None = Field(default=None, description="A short category label for this feature, if a natural one applies. Null otherwise.")


class ExtractedInclusionExclusion(BaseModel):
    entry_type: EntryType = Field(
        description="'include' for a point under a formal 'Includes' declaration, 'exclude' for a point under a formal 'Excludes' declaration."
    )
    description: str = Field(
        description=(
            "One point's text, verbatim, one entry per bullet - not a concatenated paragraph. "
            "Only for a formal offer-wide Includes/Excludes declaration; an item's own informal "
            "'comes with' bullets belong in included_features instead."
        )
    )


class ExtractedPaymentSchedule(BaseModel):
    scope_label: str | None = Field(
        default=None,
        description="Which system/section this milestone applies to, verbatim as printed (e.g. 'For items 1 : 7'), only if the document ties payment terms to a specific part rather than the whole offer. Null if offer-wide.",
    )
    scope_item_local_ids: list[str] | None = Field(
        default=None,
        description=(
            "The local_id of every item this milestone's scope actually covers, resolved by you from "
            "the document's own reference (a row-number range like 'items 1 : 7', a named section like "
            "'Training Scope', an item list) against the items you already extracted with those exact "
            "local_ids - not left for a reader to work out later by matching text against row numbers "
            "themselves. Include every item the scope covers, not just the first and last of a range. "
            "Null when scope_label is null (offer-wide) or when the document's own reference genuinely "
            "cannot be resolved to specific items you extracted (e.g. it points at rows outside what was "
            "extracted in this chunk) - never guess a plausible-looking set of items."
        ),
    )
    sequence_no: int = Field(description="This milestone's order among all payment milestones for this offer, starting at 1.")
    trigger_event: str = Field(
        description="The short event that triggers this payment (e.g. 'order confirmation', 'delivery', 'commissioning')."
    )
    percentage: float | None = Field(
        default=None, description="The percentage of total value this milestone represents, as printed. Null if not stated as a percentage."
    )
    description_original: str = Field(description="This payment milestone's full text, verbatim, as printed.")


class OfferExtractionPayload(BaseModel):
    offer_ref: str | None = Field(
        default=None,
        description="The offer's own reference/quotation number, verbatim. Null if the document genuinely never states one - never invented.",
    )
    project_name_original: str | None = Field(
        default=None, description="The project's name, verbatim, as the document states it. Null if not stated."
    )
    client_name_original: str | None = Field(
        default=None,
        description=(
            "The client/buyer *organization's* name only, verbatim, as the document states it - "
            "never a person's name, job title, or department, even when the document prints them "
            "together on one line or in one contact block (e.g. 'Omar Morsi | Presales Engineer | "
            "ELSEWEDY DIGITAL' means client_name_original is 'ELSEWEDY DIGITAL' alone; the person and "
            "title are not part of the company's name and must not be prepended or appended to it - a "
            "named individual belongs in general_notes_original as a plain sentence instead, e.g. "
            "'Client contact: Omar Morsi, Presales Engineer', since contacts is for the supplier's own "
            "people, not the buyer's). This field feeds an exact-match identity check when uploading a "
            "new version of an existing offer; a stray name or title mixed into it causes that check to "
            "wrongly reject a real revision from the same client. Null if the document never states a "
            "client/buyer organization."
        ),
    )
    project_location_original: str | None = Field(
        default=None, description="The project's site/location, verbatim, if the document states one. Null otherwise."
    )
    payment_terms_original: str | None = Field(
        default=None,
        description="The offer's payment terms as printed in prose/summary form. See payment_schedules for the structured, one-row-per-milestone breakdown of the same terms.",
    )
    price_currency_original: str | None = Field(
        default=None, description="The document's own literal text for its overall/primary currency (e.g. 'US Dollars'), unmapped."
    )
    currency_primary: CurrencyCode | None = Field(
        default=None, description="The ISO-4217 code for this offer's overall/primary currency, mapped from price_currency_original."
    )
    grand_total: float | None = Field(
        default=None,
        description=(
            "The offer's own single, final, bottom-line total for the whole offer, exactly as "
            "printed - whatever word labels it ('Grand Total', 'Total', 'Total Price', 'Total "
            "Offer Value', 'Amount Due', or 'Sub Total' when it is the document's only/final "
            "total line with nothing further summing it). Never a sum of items you compute "
            "yourself. If the document has several partial subtotals that themselves get summed "
            "into one further final total line, that final line is grand_total - the partial "
            "subtotals belong on their own group's item via stated_subtotal_amount instead. "
            "Leave `null`, rather than guessing or combining, when the document instead presents "
            "two or more independent, mutually exclusive offers with no single combining total of "
            "their own (e.g. a 'Base offer' and an 'Alternative offer' each with their own 'Total "
            "price' line and nothing summing the two together) - each one's own total still "
            "belongs on its own group's item via stated_subtotal_amount, there just isn't a "
            "genuine offer-wide figure to put here."
        ),
    )
    grand_total_currency: CurrencyCode | None = Field(default=None, description="ISO-4217 code for grand_total's currency.")
    tax_treatment_original: str | None = Field(
        default=None, description="The offer-wide tax treatment/basis, verbatim, if stated (e.g. 'prices exclude VAT')."
    )
    incoterm: str | None = Field(
        default=None, description="The offer-wide incoterm (e.g. 'EXW', 'FOB', 'CIF'), mapped from the document's own shipping/delivery wording."
    )
    delivery_terms_original: str | None = Field(
        default=None,
        description="The offer-wide delivery point/condition, verbatim, stated once. Distinct from a row's own availability_original_text (per-item lead time).",
    )
    validity_terms_original: str | None = Field(
        default=None,
        description=(
            "The offer's stated validity period, verbatim (e.g. 'Valid for 30 days from date of "
            "offer', 'This quotation is valid until 31/12/2026'). Null if the document never "
            "states how long the offer/prices remain valid - never invented or assumed."
        ),
    )
    warranty_terms_original: str | None = Field(
        default=None,
        description=(
            "The offer-wide warranty terms, verbatim (e.g. '12 months warranty against "
            "manufacturing defects from date of commissioning'), only when stated for the offer "
            "as a whole rather than one specific item. Null if not stated at the offer level - "
            "an item-specific warranty belongs in that item's own fields/tech_specs instead."
        ),
    )
    manufacturer_original: str | None = Field(
        default=None,
        description=(
            "The equipment manufacturer/brand name for this offer, verbatim, if the document "
            "states one (e.g. 'Caterpillar', 'Mitsubishi Electric'). Null if the document quotes "
            "multiple different manufacturers with no single overall one, or states none at all - "
            "never inferred from a model number or guessed from context."
        ),
    )
    product_name_original: str | None = Field(
        default=None,
        description=(
            "The offer's own product/system name or type, verbatim, if it states one for the "
            "offer as a whole (e.g. 'Standby Diesel Generator Set', 'Package Air Conditioning "
            "Unit'). Null if the offer quotes several unrelated products with no single overall "
            "one, or never names one - see each item's own equipment_type_original for the "
            "per-item equivalent."
        ),
    )
    offer_date_original: str | None = Field(
        default=None,
        description=(
            "The date this offer/quotation was issued, exactly as printed (e.g. '12/08/2026', "
            "'August 12, 2026') - copy the document's own format verbatim, never reformatted or "
            "guessed. This is the offer's own issue date, not its validity period (see "
            "validity_terms_original) or any project delivery date. Null if the document never "
            "prints an issue date for itself."
        ),
    )
    offer_signed_by_original: str | None = Field(
        default=None,
        description=(
            "The name in a closing signature/sign-off line (e.g. 'Regards, [Name]') with no "
            "role, phone, or email of its own. Never also duplicated into contacts unless that "
            "same person is independently named elsewhere with a real role/phone/email."
        ),
    )
    general_notes_original: str | None = Field(
        default=None,
        description=(
            "Free-running prose that doesn't fit a more specific field - most importantly "
            "standalone caveats/disclaimers/conditions the document states about the price or "
            "offer (e.g. a currency-fluctuation clause), and the full contents of any section "
            "the document itself labels 'Notes', 'Remarks', 'General Notes', or similar - every "
            "numbered/bulleted point in such a section, not a summary of just the first one. "
            "Multiple distinct notes are kept as separate sentences here, not merged into one "
            "vague paraphrase."
        ),
    )
    extra_attributes: dict[str, str] | None = Field(
        default=None,
        description="A flat {label: verbatim value} map for a discrete, offer-wide fact with no other home in this schema. Null when nothing qualifies.",
    )

    supplier: ExtractedSupplier = Field(
        default_factory=ExtractedSupplier, description="Identity signal about the supplier issuing this offer."
    )
    contacts: list[ExtractedContact] = Field(
        default_factory=list, description="Every named point of contact - one entry per person given a role and/or phone/email."
    )
    attachments: list[ExtractedAttachment] = Field(
        default_factory=list, description="Every attachment the document's own text references."
    )
    items: list[ExtractedItem] = Field(
        default_factory=list,
        description="Every priced line item, structured into the parent/child hierarchy reflecting the document's own organization.",
    )
    tech_specs: list[ExtractedTechSpec] = Field(
        default_factory=list, description="Structured spec rows extracted from labeled sub-sections or spec tables, one row per label/value pair."
    )
    included_features: list[ExtractedIncludedFeature] = Field(
        default_factory=list, description="Informal 'comes with' bullets scoped to one item's (or the offer's) own bundled contents."
    )
    inclusions_exclusions: list[ExtractedInclusionExclusion] = Field(
        default_factory=list, description="A formal offer-wide Includes/Excludes declaration, one entry per bullet, from both sides symmetrically."
    )
    payment_schedules: list[ExtractedPaymentSchedule] = Field(
        default_factory=list, description="One row per payment milestone the document states, not just a summary."
    )

    @model_validator(mode="after")
    def _validate_item_hierarchy(self) -> "OfferExtractionPayload":
        """Invariant 1 (see NUMERIC_HIERARCHY_AUDIT_PROMPT in extractController.py):
        every parent_local_id/entity_local_id resolves to a real local_id, with
        no self-reference and no cycles anywhere in the chain."""
        item_ids = [item.local_id for item in self.items]
        id_set = set(item_ids)
        if len(id_set) != len(item_ids):
            seen: set[str] = set()
            duplicates = {i for i in item_ids if i in seen or seen.add(i)}
            raise ValueError(f"Duplicate item local_id(s): {sorted(duplicates)}")

        parent_of: dict[str, str | None] = {item.local_id: item.parent_local_id for item in self.items}
        for item in self.items:
            if item.parent_local_id is None:
                continue
            if item.parent_local_id == item.local_id:
                raise ValueError(f"Item '{item.local_id}' cannot be its own parent")
            if item.parent_local_id not in id_set:
                raise ValueError(
                    f"Item '{item.local_id}' has parent_local_id "
                    f"'{item.parent_local_id}' which does not exist in items"
                )

        for start_id in id_set:
            chain_seen = {start_id}
            current = parent_of[start_id]
            while current is not None:
                if current in chain_seen:
                    raise ValueError(f"Cycle detected in item hierarchy involving '{start_id}'")
                chain_seen.add(current)
                current = parent_of.get(current)

        for spec in self.tech_specs:
            if spec.entity_type == EntityType.ITEM and spec.entity_local_id not in id_set:
                raise ValueError(
                    f"tech_specs entry references unknown item local_id '{spec.entity_local_id}'"
                )
        for feature in self.included_features:
            if feature.entity_type == EntityType.ITEM and feature.entity_local_id not in id_set:
                raise ValueError(
                    "included_features entry references unknown item local_id "
                    f"'{feature.entity_local_id}'"
                )
        for schedule in self.payment_schedules:
            for local_id in schedule.scope_item_local_ids or []:
                if local_id not in id_set:
                    raise ValueError(
                        f"payment_schedules entry references unknown item local_id '{local_id}'"
                    )

        return self


class ExtractOfferResponse(BaseModel):
    signal: ResponseSignal
    offer_id: int
    payload: OfferExtractionPayload
