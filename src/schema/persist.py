import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from models.enums import (
    CurrencyCode,
    EntityType,
    EntryType,
    ExtractionVerdict,
    FindingVerdict,
    ItemCategory,
    PriceBasis,
    ResponseSignal,
    SanityCheckIssueType,
    SanityCheckSeverity,
    SanityCheckStatus,
    VerificationStatus,
)
from schema.offer import OfferExtractionPayload
from schema.sanity_check import SanityCheckResult
from schema.verification import VerificationResult


class SupplierDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    supplier_id: int
    supplier_name: str
    supplier_code: str | None
    supplier_aliases: list[str] | None
    is_sole_agent_for: list[str] | None


class ProjectDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    project_name: str
    project_aliases: list[str] | None
    client_name: str | None
    client_aliases: list[str] | None
    location: str | None


class SupplierContactDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    contact_id: int
    supplier_id: int
    contact_name: str
    role: str | None
    phone: str | None
    email: str | None
    source_document_id: uuid.UUID | None


class OfferItemDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: int
    offer_id: int
    parent_item_id: int | None
    item_code: str | None
    item_group_label: str | None
    item_category: ItemCategory
    is_optional: bool
    is_alternate: bool
    alternate_group_id: int | None
    is_lump_sum: bool
    price_basis: PriceBasis
    percentage_value: float | None
    discount_amount: float | None
    description: str
    model_number: str | None
    equipment_type_original: str | None
    unit: str | None
    quantity: float
    unit_price: float | None
    total_price: float | None
    price_currency: CurrencyCode | None
    price_currency_original: str | None
    stated_subtotal_amount: float | None
    stated_subtotal_currency: CurrencyCode | None
    tax_treatment_override_original: str | None
    incoterm_override: str | None
    payment_terms_override_original: str | None
    delivery_terms_override_original: str | None
    availability_original_text: str | None
    extra_attributes: dict[str, str] | None
    source_page_number: int | None
    sort_order: int


class OfferPaymentScheduleDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    schedule_id: int
    offer_id: int
    scope_label: str | None
    scope_item_ids: list[int] | None
    sequence_no: int
    trigger_event: str
    percentage: float | None
    description_original: str


class TechSpecDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    spec_id: int
    entity_type: EntityType
    entity_id: int
    spec_group: str
    spec_name: str
    spec_value: str
    spec_unit: str | None
    sort_order: int


class IncludedFeatureDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feature_id: int
    entity_type: EntityType
    entity_id: int
    feature_text: str
    feature_category: str | None
    sort_order: int


class InclusionExclusionDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entry_id: int
    entity_type: str
    entity_id: int
    entry_type: EntryType
    description: str
    sort_order: int


class OfferAttachmentDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attachment_id: int
    offer_id: int
    attachment_label: str
    document_id: uuid.UUID | None


class OfferSanityFindingDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    finding_id: int
    offer_id: int
    issue_type: SanityCheckIssueType
    severity: SanityCheckSeverity
    field_path: str
    description: str
    sort_order: int


class OfferVerifiedFindingDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    verified_finding_id: int
    offer_id: int
    issue_type: SanityCheckIssueType
    field_path: str
    extraction_verdict: ExtractionVerdict
    extraction_correction: str | None
    finding_verdict: FindingVerdict
    explanation: str | None
    evidence_quote: str
    reasoning: str
    sort_order: int


class OfferDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    root_offer_id: int | None
    parent_offer_id: int | None
    is_active_latest: bool
    supplier_id: int | None
    project_id: int | None
    offer_ref: str | None
    # Filed by the person who uploaded it, not read out of the document. The
    # typed project name sits next to the extracted one rather than replacing
    # it: the extracted one is what `helpers.offer_versioning
    # .check_same_offer_identity` compares when a new version arrives.
    rfq_number: str | None = None
    project_name_entered: str | None = None
    project_name_original: str | None
    client_name_original: str | None
    project_location_original: str | None
    payment_terms_original: str | None
    price_currency_original: str | None
    currency_primary: CurrencyCode | None
    grand_total: float | None
    grand_total_currency: CurrencyCode | None
    tax_treatment_original: str | None
    incoterm: str | None
    delivery_terms_original: str | None
    validity_terms_original: str | None
    warranty_terms_original: str | None
    manufacturer_original: str | None
    product_name_original: str | None
    offer_date_original: str | None
    offer_signed_by_original: str | None
    general_notes_original: str | None
    extra_attributes: dict[str, str] | None
    sanity_check_status: SanityCheckStatus | None
    sanity_check_summary: str | None
    verification_status: VerificationStatus | None
    verification_summary: str | None
    # Who uploaded it. Null for an offer created before sign-in existed, and for
    # one whose uploader's account has since been deleted (ON DELETE SET NULL) -
    # `OfferFullDB.created_by_display_name` carries the name where there is one.
    created_by_user_id: int | None = None
    # Set the first time this offer completed the persist stage; null while a
    # run is still in flight or has failed.
    persisted_at: datetime | None = None
    # Retired by a reviewer: still readable, still comparable, just out of the
    # working list. Null means not archived. Nothing to do with
    # `is_active_latest`, which means "newest version of its chain".
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OfferFullDB(BaseModel):
    """Reads back everything persisted for one offer, structured by table -
    the counterpart to `PersistController.persist_offer`'s writes."""

    offer: OfferDB
    supplier: SupplierDB | None
    project: ProjectDB | None
    contacts: list[SupplierContactDB]
    items: list[OfferItemDB]
    payment_schedules: list[OfferPaymentScheduleDB]
    tech_specs: list[TechSpecDB]
    included_features: list[IncludedFeatureDB]
    inclusions_exclusions: list[InclusionExclusionDB]
    attachments: list[OfferAttachmentDB]
    sanity_findings: list[OfferSanityFindingDB]
    verified_findings: list[OfferVerifiedFindingDB]
    # Filled in by the read route, not by `persist_offer`: at persist time the
    # completeness check has not run yet. None means never checked - the offer
    # header shows no badge at all rather than a reassuring zero.
    completeness_mandatory_gaps: int | None = None
    # Also filled in by the read route. The name is a join - there is no
    # relationship() in this schema - and the label is the rule the offers list
    # applies to the two project names, borrowed rather than re-derived so the
    # header and the row it was opened from cannot print different names. Both
    # stay None on the persist response, which has no reader to join for.
    created_by_display_name: str | None = None
    project_label: str | None = None


class PersistRequest(BaseModel):
    payload: OfferExtractionPayload
    sanity_check_result: SanityCheckResult | None = None
    verification_result: VerificationResult | None = None


class PersistOfferResponse(BaseModel):
    signal: ResponseSignal
    offer_id: int
    offer: OfferFullDB
