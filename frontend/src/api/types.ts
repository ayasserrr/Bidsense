// Mirrors the real backend's response shapes (routes/*.py, schema/*.py).
//
// The job, completeness and taxonomy shapes live beside their own API modules
// (api/jobApi.ts, api/completenessApi.ts, api/taxonomyApi.ts); this file holds
// the offer itself and the stage payloads it is built from.

export type ItemCategory =
  | "equipment"
  | "accessory"
  | "spare_part"
  | "installation"
  | "service"
  | "warranty"
  | "training"
  | "software"
  | "civil_works"
  | "transportation"
  | "other"

export type PriceBasis = "fixed" | "percentage_of_parent" | "included_no_charge" | "tbd"

export type EntryType = "include" | "exclude"

export type EntityType = "offer" | "item"

export type SanityCheckStatus = "passed" | "needs_review"

export type SanityCheckSeverity = "warning" | "critical"

export type SanityCheckIssueType =
  | "arithmetic_mismatch"
  | "percentage_mismatch"
  | "subtotal_mismatch"
  | "grand_total_mismatch"
  | "payment_schedule_mismatch"

export type VerificationStatus = "skipped" | "resolved" | "needs_human_review"

export type ExtractionVerdict = "confirmed" | "incorrect" | "insufficient_evidence"

export type FindingVerdict = "confirmed" | "explained" | "insufficient_evidence"

export type UploadItemStatus = "success" | "duplicate" | "error"

// ---- Persisted (DB-backed) shapes - GET /api/v1/offers/{id} and the
// response body of POST /api/v1/persist/{offer_id} ----

export interface OfferDB {
  id: number
  root_offer_id: number | null
  parent_offer_id: number | null
  is_active_latest: boolean
  supplier_id: number | null
  project_id: number | null
  offer_ref: string | null
  // Filed by the person who uploaded it, not read out of the document.
  rfq_number: string | null
  project_name_entered: string | null
  project_name_original: string | null
  client_name_original: string | null
  project_location_original: string | null
  payment_terms_original: string | null
  price_currency_original: string | null
  currency_primary: string | null
  grand_total: number | null
  grand_total_currency: string | null
  tax_treatment_original: string | null
  incoterm: string | null
  delivery_terms_original: string | null
  validity_terms_original: string | null
  warranty_terms_original: string | null
  manufacturer_original: string | null
  product_name_original: string | null
  offer_date_original: string | null
  offer_signed_by_original: string | null
  general_notes_original: string | null
  extra_attributes: Record<string, string> | null
  sanity_check_status: SanityCheckStatus | null
  sanity_check_summary: string | null
  verification_status: VerificationStatus | null
  verification_summary: string | null
  created_at: string
  updated_at: string
}

export interface SupplierDB {
  supplier_id: number
  supplier_name: string
  supplier_code: string | null
  supplier_aliases: string[] | null
  is_sole_agent_for: string[] | null
}

export interface ProjectDB {
  project_id: number
  project_name: string
  project_aliases: string[] | null
  client_name: string | null
  client_aliases: string[] | null
  location: string | null
}

export interface SupplierContactDB {
  contact_id: number
  supplier_id: number
  contact_name: string
  role: string | null
  phone: string | null
  email: string | null
  source_document_id: string | null
}

export interface OfferItemDB {
  item_id: number
  offer_id: number
  parent_item_id: number | null
  item_code: string | null
  item_group_label: string | null
  item_category: ItemCategory
  is_optional: boolean
  is_alternate: boolean
  alternate_group_id: number | null
  is_lump_sum: boolean
  price_basis: PriceBasis
  percentage_value: number | null
  discount_amount: number | null
  description: string
  model_number: string | null
  equipment_type_original: string | null
  unit: string | null
  quantity: number
  unit_price: number | null
  total_price: number | null
  price_currency: string | null
  price_currency_original: string | null
  stated_subtotal_amount: number | null
  stated_subtotal_currency: string | null
  tax_treatment_override_original: string | null
  incoterm_override: string | null
  payment_terms_override_original: string | null
  delivery_terms_override_original: string | null
  availability_original_text: string | null
  extra_attributes: Record<string, string> | null
  source_page_number: number | null
  sort_order: number
}

export interface OfferPaymentScheduleDB {
  schedule_id: number
  offer_id: number
  scope_label: string | null
  scope_item_ids: number[] | null
  sequence_no: number
  trigger_event: string
  percentage: number | null
  description_original: string
}

export interface TechSpecDB {
  spec_id: number
  entity_type: EntityType
  entity_id: number
  spec_group: string
  spec_name: string
  spec_value: string
  spec_unit: string | null
  sort_order: number
}

export interface IncludedFeatureDB {
  feature_id: number
  entity_type: EntityType
  entity_id: number
  feature_text: string
  feature_category: string | null
  sort_order: number
}

export interface InclusionExclusionDB {
  entry_id: number
  entity_type: string
  entity_id: number
  entry_type: EntryType
  description: string
  sort_order: number
}

export interface OfferAttachmentDB {
  attachment_id: number
  offer_id: number
  attachment_label: string
  document_id: string | null
}

// One row per automated arithmetic/consistency flag the deterministic
// sanity-check pass raised and the LLM review kept as a genuine issue.
export interface OfferSanityFindingDB {
  finding_id: number
  offer_id: number
  issue_type: SanityCheckIssueType
  severity: SanityCheckSeverity
  field_path: string
  description: string
  sort_order: number
}

// One row per sanity-check finding independently re-checked against the
// original source document by the verification stage.
export interface OfferVerifiedFindingDB {
  verified_finding_id: number
  offer_id: number
  issue_type: SanityCheckIssueType
  field_path: string
  extraction_verdict: ExtractionVerdict
  extraction_correction: string | null
  finding_verdict: FindingVerdict
  explanation: string | null
  evidence_quote: string
  reasoning: string
  sort_order: number
}

export interface OfferFullDB {
  offer: OfferDB
  supplier: SupplierDB | null
  project: ProjectDB | null
  contacts: SupplierContactDB[]
  items: OfferItemDB[]
  payment_schedules: OfferPaymentScheduleDB[]
  tech_specs: TechSpecDB[]
  included_features: IncludedFeatureDB[]
  inclusions_exclusions: InclusionExclusionDB[]
  attachments: OfferAttachmentDB[]
  sanity_findings: OfferSanityFindingDB[]
  verified_findings: OfferVerifiedFindingDB[]
  /** Required terms this offer does not state, or states too vaguely to act on.
   * null means the completeness check has never run - which is not the same as
   * "nothing missing", so the header shows no badge rather than a clean one. */
  completeness_mandatory_gaps: number | null
  /** Filled in by the read route, not by persist - both null on a persist
   * response, which has no reader to join for yet. */
  created_by_display_name: string | null
  /** The typed project name where there is one, else the extracted one - the
   * same rule the offers list applies, so the header and the row it was
   * opened from cannot print different names. */
  project_label: string | null
}

export type OfferReviewStatus = "needs_review" | "clear" | "unchecked"

// Lightweight row for the offers list / version picker - GET /api/v1/offers
// and GET /api/v1/offers/{id}/versions.
export interface OfferSummary {
  id: number
  offer_ref: string | null
  /** The RFQ this offer answers, as typed at upload. null for anything filed
   * before there was a field to type it into. */
  rfq_number: string | null
  project_name_original: string | null
  /** What a person typed when filing it - null unless one did. */
  project_name_entered: string | null
  /** The typed name where there is one, else the extracted one - what the
   * list and every filter dropdown actually group and display by. */
  project_label: string | null
  client_name_original: string | null
  supplier_name: string | null
  grand_total: number | null
  grand_total_currency: string | null
  is_active_latest: boolean
  root_offer_id: number | null
  parent_offer_id: number | null
  sanity_check_status: SanityCheckStatus | null
  verification_status: VerificationStatus | null
  /** The one word the Status column shows, derived server-side from the two
   * raw statuses above so the list and the filter can never disagree. */
  review_status: OfferReviewStatus
  /** Required terms the supplier did not state, or stated too vaguely to act
   * on - the same number the completeness section headlines. null means never
   * checked, which must not be shown as a clean result. */
  completeness_mandatory_gaps: number | null
  version_count: number
  created_by_user_id: number | null
  created_by_display_name: string | null
  created_at: string
  /** Retired by a reviewer - still readable and re-runnable, just off the
   * working list. null means not archived. */
  archived_at: string | null
  is_archived: boolean
}

export type OfferSortKey = "uploaded_at" | "value" | "supplier" | "project"
export type SortDirection = "asc" | "desc"
export type OfferListStatusFilter = "needs_review" | "clear" | "unchecked" | "archived" | "all"

export interface OfferListPage {
  items: OfferSummary[]
  total: number
  limit: number
  offset: number
  /** How many ARCHIVED offers the same filters match, ignoring the status
   * filter itself - so the footer can say "and 4 archived" instead of
   * dropping them in silence. */
  archived_matching: number
}

export interface SupplierFilterOption {
  supplier_id: number
  supplier_name: string
  offer_count: number
}

export interface ProjectFilterOption {
  project_label: string
  offer_count: number
}

export interface UploaderFilterOption {
  user_id: number
  display_name: string
  offer_count: number
}

export interface RfqFilterOption {
  rfq_number: string
  offer_count: number
}

export interface OfferFilterOptions {
  suppliers: SupplierFilterOption[]
  projects: ProjectFilterOption[]
  uploaders: UploaderFilterOption[]
  rfq_numbers: RfqFilterOption[]
}

// ---- In-flight (not-yet-persisted) shapes - mirror schema/offer.py,
// schema/sanity_check.py and schema/verification.py exactly.
//
// Nothing in the app threads these between calls any more: the pipeline runs
// on the server and the browser only watches a job (see api/jobApi.ts). They
// stay because the per-stage endpoints still exist for scripted and diagnostic
// use, and because the persisted shapes below are built out of them. ----

export interface ExtractedSupplier {
  supplier_name_original: string | null
  supplier_aliases_seen: string[]
  sole_agent_for_original: string | null
}

export interface ExtractedContact {
  contact_name: string
  role: string | null
  phone: string | null
  email: string | null
}

export interface ExtractedAttachment {
  attachment_label: string
}

export interface ExtractedItem {
  local_id: string
  parent_local_id: string | null
  item_code: string | null
  item_group_label: string | null
  item_category: ItemCategory
  is_optional: boolean
  is_alternate: boolean
  alternate_group_id: string | null
  is_lump_sum: boolean
  price_basis: PriceBasis
  percentage_value: number | null
  discount_amount: number | null
  description: string
  model_number: string | null
  equipment_type_original: string | null
  unit: string | null
  quantity: number
  unit_price: number | null
  total_price: number | null
  price_currency: string | null
  price_currency_original: string | null
  stated_subtotal_amount: number | null
  stated_subtotal_currency: string | null
  tax_treatment_override_original: string | null
  incoterm_override: string | null
  payment_terms_override_original: string | null
  delivery_terms_override_original: string | null
  availability_original_text: string | null
  extra_attributes: Record<string, string> | null
  source_page_number: number | null
}

export interface ExtractedTechSpec {
  entity_type: EntityType
  entity_local_id: string | null
  spec_group: string
  spec_name: string
  spec_value: string
  spec_unit: string | null
}

export interface ExtractedIncludedFeature {
  entity_type: EntityType
  entity_local_id: string | null
  feature_text: string
  feature_category: string | null
}

export interface ExtractedInclusionExclusion {
  entry_type: EntryType
  description: string
}

export interface ExtractedPaymentSchedule {
  scope_label: string | null
  scope_item_local_ids: string[] | null
  sequence_no: number
  trigger_event: string
  percentage: number | null
  description_original: string
}

export interface OfferExtractionPayload {
  offer_ref: string | null
  project_name_original: string | null
  client_name_original: string | null
  project_location_original: string | null
  payment_terms_original: string | null
  price_currency_original: string | null
  currency_primary: string | null
  grand_total: number | null
  grand_total_currency: string | null
  tax_treatment_original: string | null
  incoterm: string | null
  delivery_terms_original: string | null
  validity_terms_original: string | null
  warranty_terms_original: string | null
  manufacturer_original: string | null
  product_name_original: string | null
  offer_date_original: string | null
  offer_signed_by_original: string | null
  general_notes_original: string | null
  extra_attributes: Record<string, string> | null
  supplier: ExtractedSupplier
  contacts: ExtractedContact[]
  attachments: ExtractedAttachment[]
  items: ExtractedItem[]
  tech_specs: ExtractedTechSpec[]
  included_features: ExtractedIncludedFeature[]
  inclusions_exclusions: ExtractedInclusionExclusion[]
  payment_schedules: ExtractedPaymentSchedule[]
}

export interface ExtractOfferResponse {
  signal: string
  offer_id: number
  payload: OfferExtractionPayload
}

export interface SanityCheckFinding {
  issue_type: SanityCheckIssueType
  severity: SanityCheckSeverity
  field_path: string
  description: string
}

export interface SanityCheckResult {
  status: SanityCheckStatus
  findings: SanityCheckFinding[]
  summary: string
}

export interface SanityCheckOfferResponse {
  signal: string
  offer_id: number
  result: SanityCheckResult
}

export interface VerifiedFinding {
  issue_type: SanityCheckIssueType
  field_path: string
  extraction_verdict: ExtractionVerdict
  extraction_correction: string | null
  finding_verdict: FindingVerdict
  explanation: string | null
  evidence_quote: string
  reasoning: string
}

export interface VerificationResult {
  status: VerificationStatus
  verified_findings: VerifiedFinding[]
  summary: string
}

export interface VerificationOfferResponse {
  signal: string
  offer_id: number
  result: VerificationResult
}

export interface UploadedFileResult {
  filename: string
  status: UploadItemStatus
  message: string
  document_id: string | null
  checksum: string | null
}

export interface UploadOfferResponse {
  signal: string
  offer_id: number
  results: UploadedFileResult[]
}

export interface NewOfferVersionResponse {
  signal: string
  offer_id: number
  parent_offer_id: number
  root_offer_id: number
  results: UploadedFileResult[]
}

export interface PersistOfferResponse {
  signal: string
  offer_id: number
  offer: OfferFullDB
}

// ---- Errors ----

// Most real backend routes raise `HTTPException(detail="plain string")` -
// there is no structured error object (no signal/stage/conflicts payload
// like a different backend generation might have had). The one exception:
// `/api/v1/upload` and `/api/v1/upload/{id}/new-version` report a total
// failure (HTTP 422) with a normal `UploadOfferResponse`-shaped body
// (`results`, one entry per file) instead of a `detail` string, since the
// useful information is which file failed and why, not one summary message.
export interface ApiErrorBody {
  detail?: string
  results?: UploadedFileResult[]
}

export class ApiError extends Error {
  status: number | null
  body: ApiErrorBody

  constructor(message: string, status: number | null, body: ApiErrorBody) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}
