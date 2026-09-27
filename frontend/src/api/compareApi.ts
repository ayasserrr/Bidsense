import { api } from "./client"
import type { CompletenessVerdict } from "./completenessApi"
import type { ConvertedMoney } from "./dashboardApi"
import type { SanityCheckStatus, VerificationStatus } from "./types"

// GET /api/v1/compare - several offers side by side, facts only. See
// schema/compare.py's own note: there is no "Recommended" column and no
// score. The inputs would be four free-text fields parsed out of PDFs, and a
// screen that ranks suppliers on that is a screen that gets somebody's
// contract award wrong - so this returns what each offer states, normalised
// where there is a mechanical rule for it, and leaves the rest to the reader.

export const MAX_COMPARE_OFFERS = 6

export interface CompareTerm {
  stated: string | null
  normalized: string | null
  normalized_from: string | null
  verdict: CompletenessVerdict | null
  is_overridden: boolean
}

export interface CompareTerms {
  incoterm: CompareTerm
  delivery_terms: CompareTerm
  delivery_lead_time: CompareTerm
  payment_terms: CompareTerm
  warranty: CompareTerm
  validity: CompareTerm
}

export interface ComparePaymentMilestone {
  sequence_no: number
  trigger_event: string
  percentage: string | null
  description: string
}

// Populated only when `grand_total` has no `original_amount` - a "Base offer"
// and an "Alternative offer" each independently totaled, with nothing summing
// the two together, still has a real total per group. Mirrors
// OfferDetailPage.tsx's identical fallback.
export interface CompareGroupTotal {
  label: string
  total: ConvertedMoney
}

export interface CompareOffer {
  offer_id: number
  offer_ref: string | null
  supplier_name: string | null
  rfq_number: string | null
  project_name_entered: string | null
  project_name_original: string | null
  is_active_latest: boolean
  archived: boolean
  created_at: string
  persisted_at: string | null
  grand_total: ConvertedMoney
  group_totals: CompareGroupTotal[]
  confirmed_findings: number
  sanity_check_status: SanityCheckStatus | null
  verification_status: VerificationStatus | null
  mandatory_gaps: number | null
  mandatory_terms_total: number
  completeness_checked: boolean
  item_count: number
  terms: CompareTerms
  payment_schedule: ComparePaymentMilestone[]
}

export interface CompareResponse {
  generated_at: string
  base_currency: string
  offers: CompareOffer[]
  rfq_numbers: string[]
  same_rfq: boolean
  currencies: string[]
  rate_dependent: boolean
  unconvertible_currencies: { currency_code: string; reason: string }[]
  notes: string[]
}

export function compareOffers(offerIds: number[], signal?: AbortSignal) {
  const params = new URLSearchParams()
  for (const id of offerIds) params.append("offer_ids", String(id))
  return api.get<CompareResponse>(`/api/v1/compare?${params.toString()}`, {
    timeoutMs: 20_000,
    signal,
  })
}
