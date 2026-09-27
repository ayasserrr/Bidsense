import { api } from "./client"
import type { Job } from "./jobApi"

export type ChaseItemKind = "confirmed_finding" | "mandatory_gap"

/** One thing to chase before this offer can go to sign-off - composed
 * server-side from this offer's own already-verified findings and
 * completeness gaps, never a fresh LLM paragraph. See the backend's
 * `schema/review_summary.py` module docstring for why. */
export interface ChaseItem {
  kind: ChaseItemKind
  title: string
  detail: string
  /** Present for a mandatory_gap item when the checker names one; a
   * confirmed_finding's source is the verification quote itself, already in
   * `detail`. */
  source_filename: string | null
  source_page_number: number | null
}

export interface ReviewSummary {
  headline: string
  chase_items: ChaseItem[]
  /** The recipient's own words - null means extraction couldn't place a
   * contact email, not that one was invented and withheld. */
  email_to: string | null
  email_subject: string
  email_body: string
  generated_at: string | null
}

/** Never 404s for an offer with no summary yet - the server reads back an
 * empty/placeholder shape instead, since the summary is a bonus, not a
 * precondition of viewing the offer. */
export function getReviewSummary(offerId: number | string) {
  return api.get<ReviewSummary>(`/api/v1/offers/${offerId}/summary`, { timeoutMs: 20_000 })
}

/** Composes the chase list and email draft again - worth doing after a
 * completeness override or late evidence changes what is left to chase.
 * Mirrors completenessApi's recheckCompleteness exactly: a background Job
 * comes back (202 Accepted), not the summary itself. */
export function recheckReviewSummary(offerId: number | string) {
  return api.post<Job>(`/api/v1/offers/${offerId}/summary/recheck`, { timeoutMs: 30_000 })
}
