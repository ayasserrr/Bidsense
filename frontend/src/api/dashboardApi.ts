import { api } from "./client"
import type { SanityCheckStatus, VerificationStatus } from "./types"

// GET /api/v1/dashboard - see schema/dashboard.py's own note: there is
// deliberately no "money at risk" figure. Nothing in this database records a
// monetary amount per finding, so that number could only ever be a guess
// dressed as a measurement. What IS here is real: offers waiting on a
// decision, terms not yet stated, how long a read usually takes.

/** One amount, in the currency the supplier wrote and in the base currency.
 * Both are Decimal-as-string (see lib/format.ts's own note on why). */
export interface ConvertedMoney {
  original_amount: string | null
  original_currency: string | null
  base_currency: string
  converted_amount: string | null
  rate: {
    currency_code: string
    rate_to_base: string
    source: "api" | "manual" | null
    set_at: string | null
    rate_as_of: string | null
    age_seconds: number | null
  } | null
  unconvertible_reason: string | null
}

export interface CurrencyTotal {
  currency_code: string | null
  amount: string
  offer_count: number
  converted_amount: string | null
}

export interface MoneyTotal {
  base_currency: string
  converted_total: string | null
  is_complete: boolean
  by_currency: CurrencyTotal[]
  unconvertible_currencies: string[]
}

export interface OffersInReview {
  count: number
  waiting_longer_than_stale_days: number
  stale_days: number
  added_last_7_days: number
  live_offers: number
}

export interface TermsToChase {
  mandatory_gaps: number
  offers_with_gaps: number
  mandatory_terms_per_offer: number
  offers_checked: number
  offers_never_checked: number
}

export interface AverageReadTime {
  seconds: number | null
  sample_size: number
  sample_requested: number
}

export interface ReadingNow {
  running: number
  waiting: number
}

export interface DashboardMoney {
  live_offers: MoneyTotal
  awaiting_review: MoneyTotal
  offers_without_a_total: number
}

export interface AttentionOffer {
  offer_id: number
  offer_ref: string | null
  supplier_name: string | null
  rfq_number: string | null
  project_name: string | null
  confirmed_findings: number
  mandatory_gaps: number | null
  mandatory_terms_total: number
  sanity_check_status: SanityCheckStatus | null
  verification_status: VerificationStatus | null
  grand_total: ConvertedMoney
  waiting_days: number | null
  created_at: string
  persisted_at: string | null
}

export interface CompareReadyRfq {
  rfq_number: string
  offer_count: number
  offer_ids: number[]
  supplier_names: string[]
  latest_created_at: string
}

export interface NeedsAttention {
  offers: AttentionOffer[]
  compare_ready: CompareReadyRfq[]
  offers_total: number
}

export interface ActivityEvent {
  event_id: number
  offer_id: number
  offer_ref: string | null
  kind: string
  detail: string
  actor_user_id: number | null
  actor_display_name: string
  is_system: boolean
  created_at: string
}

export interface DashboardResponse {
  generated_at: string
  base_currency: string
  offers_in_review: OffersInReview
  terms_to_chase: TermsToChase
  average_read_time: AverageReadTime
  reading_now: ReadingNow
  money: DashboardMoney
  needs_attention: NeedsAttention
  activity: ActivityEvent[]
}

export function getDashboard(signal?: AbortSignal) {
  return api.get<DashboardResponse>("/api/v1/dashboard", { timeoutMs: 20_000, signal })
}
