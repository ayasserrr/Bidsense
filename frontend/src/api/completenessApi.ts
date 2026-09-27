import { api } from "./client"
import type { Job } from "./jobApi"

export type CompletenessVerdict = "present" | "missing" | "not_applicable" | "unclear"
export type RequirementGroup = "technical" | "commercial"
export type EvidenceKind = "email" | "letter" | "revised_offer" | "other"

export interface CompletenessResult {
  result_id: number
  requirement_code: string
  requirement_label: string
  requirement_group: RequirementGroup
  was_mandatory: boolean
  sort_order: number

  verdict: CompletenessVerdict
  extracted_value: string | null
  normalized_value: string | null
  evidence_quote: string | null
  /** Resolved by locating the quote in the source text, never from a filename
   * the model claimed. Null means the quote could not be placed. */
  source_document_id: string | null
  source_filename: string | null
  source_page_number: number | null
  reasoning: string | null

  is_overridden: boolean
  override_verdict: CompletenessVerdict | null
  override_value: string | null
  override_note: string | null
  override_evidence_id: string | null
  override_evidence_filename: string | null
  overridden_by: string | null
  overridden_at: string | null

  /** The override where one exists, otherwise the checker's verdict. Computed
   * server-side so this rule has exactly one implementation. */
  effective_verdict: CompletenessVerdict
  effective_value: string | null
  checked_at: string
}

export interface CompletenessSummary {
  total: number
  present: number
  missing: number
  unclear: number
  not_applicable: number
  /** Required AND either absent or too vague to act on - the number that means
   * "go back to the supplier". */
  mandatory_gaps: number
  overridden: number
}

export interface CompletenessEvidence {
  evidence_id: string
  requirement_code: string
  evidence_kind: EvidenceKind
  original_filename: string
  file_size: number
  uploaded_at: string
}

export interface OfferCompleteness {
  signal: string
  offer_id: number
  checked_at: string | null
  summary: CompletenessSummary
  results: CompletenessResult[]
  evidence: CompletenessEvidence[]
}

export interface Requirement {
  requirement_id: number
  code: string
  requirement_group: RequirementGroup
  label: string
  description: string
  is_mandatory: boolean
  is_active: boolean
  sort_order: number
}

export function getCompleteness(offerId: number | string) {
  return api.get<OfferCompleteness>(`/api/v1/offers/${offerId}/completeness`, {
    timeoutMs: 20_000,
  })
}

/** Runs the check again - after a late file arrives, or an override is
 * recorded. Overrides and their evidence survive every re-run. */
export function recheckCompleteness(offerId: number | string) {
  return api.post<Job>(`/api/v1/offers/${offerId}/completeness/recheck`, { timeoutMs: 30_000 })
}

/** Uploads the document behind an override. Must happen BEFORE saving the
 * override - the server (and the database) refuse one without evidence. */
export function uploadEvidence(
  offerId: number | string,
  requirementCode: string,
  evidenceKind: EvidenceKind,
  file: File,
) {
  const formData = new FormData()
  formData.append("requirement_code", requirementCode)
  formData.append("evidence_kind", evidenceKind)
  formData.append("file", file)
  return api.post<CompletenessEvidence>(`/api/v1/offers/${offerId}/completeness/evidence`, {
    formData,
    timeoutMs: 60_000,
  })
}

export function saveOverride(
  offerId: number | string,
  requirementCode: string,
  body: { verdict: CompletenessVerdict; value?: string; note?: string; evidence_id: string },
) {
  return api.post<CompletenessResult>(
    `/api/v1/offers/${offerId}/completeness/${requirementCode}/override`,
    { json: body, timeoutMs: 20_000 },
  )
}

export function clearOverride(offerId: number | string, requirementCode: string) {
  return api.post<CompletenessResult>(
    `/api/v1/offers/${offerId}/completeness/${requirementCode}/override/clear`,
    { timeoutMs: 20_000 },
  )
}

export function evidenceDownloadUrl(offerId: number | string, evidenceId: string): string {
  return `/api/v1/offers/${offerId}/completeness/evidence/${evidenceId}`
}

export function listRequirements() {
  return api.get<Requirement[]>("/api/v1/completeness/requirements", { timeoutMs: 20_000 })
}
