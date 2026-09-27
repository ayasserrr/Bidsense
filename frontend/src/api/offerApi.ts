import { api, beaconPost } from "./client"
import type {
  OfferFilterOptions,
  OfferFullDB,
  OfferListPage,
  OfferListStatusFilter,
  OfferSortKey,
  OfferSummary,
  SortDirection,
} from "./types"

// Read-only queries over saved offers, plus the one destructive action a
// reviewer can take on a run that did not finish.
//
// The per-stage endpoints (parse, extract, sanity-check, verification,
// persist) are no longer called from here. The pipeline is orchestrated on the
// server - see api/jobApi.ts - which is what lets a run outlive the browser
// tab that started it. The endpoints still exist on the backend for scripted
// and diagnostic use.

/** Deletes an offer that never finished, along with its documents and files.
 *
 * A deliberate, explicit action now. It used to fire automatically when the
 * progress page unmounted, which meant navigating away at minute nine of a
 * ten-minute run silently destroyed the work. A beacon rather than a fetch so
 * it still lands if the page is closing as it is called.
 */
export function abandonOffer(offerId: number) {
  beaconPost(`/api/v1/upload/${offerId}/abandon`)
}

export interface OfferListQuery {
  q?: string
  supplierId?: number
  project?: string
  rfq?: string
  uploadedBy?: number
  uploadedFrom?: string
  uploadedTo?: string
  status?: OfferListStatusFilter
  includeSuperseded?: boolean
  sort?: OfferSortKey
  direction?: SortDirection
  limit?: number
  offset?: number
}

/** One page of finished offers, newest first - only the caller's department
 * unless they are an admin, and only the working list (not archived) unless
 * `status` asks for archived offers or "all". */
export function listOffersPage(query: OfferListQuery = {}) {
  const params = new URLSearchParams()
  if (query.q) params.set("q", query.q)
  if (query.supplierId !== undefined) params.set("supplier_id", String(query.supplierId))
  if (query.project) params.set("project", query.project)
  if (query.rfq) params.set("rfq", query.rfq)
  if (query.uploadedBy !== undefined) params.set("uploaded_by", String(query.uploadedBy))
  if (query.uploadedFrom) params.set("uploaded_from", query.uploadedFrom)
  if (query.uploadedTo) params.set("uploaded_to", query.uploadedTo)
  if (query.status) params.set("status", query.status)
  if (query.includeSuperseded) params.set("include_superseded", "true")
  if (query.sort) params.set("sort", query.sort)
  if (query.direction) params.set("direction", query.direction)
  params.set("limit", String(query.limit ?? 50))
  params.set("offset", String(query.offset ?? 0))
  return api.get<OfferListPage>(`/api/v1/offers?${params.toString()}`, { timeoutMs: 15_000 })
}

/** The filter bar's dropdowns, built only from offers the caller may see. */
export function getOfferFilterOptions() {
  return api.get<OfferFilterOptions>("/api/v1/offers/filter-options", { timeoutMs: 15_000 })
}

/** Takes an offer out of the working list. Still readable, comparable and
 * re-runnable - not a delete. */
export function archiveOffer(offerId: number) {
  return api.post<OfferSummary>(`/api/v1/offers/${offerId}/archive`, { timeoutMs: 15_000 })
}

export function unarchiveOffer(offerId: number) {
  return api.post<OfferSummary>(`/api/v1/offers/${offerId}/unarchive`, { timeoutMs: 15_000 })
}

/** Permanently deletes a finished offer: its documents, items, findings,
 * activity history and pipeline jobs, and its files on disk. Unlike
 * archive/unarchive, there is no undo. The backend refuses with 409 when this
 * isn't the offer's latest version (a newer version exists and must be
 * deleted first) or when a read is currently queued or in progress for it. */
export function deleteOffer(offerId: number | string) {
  return api.delete<void>(`/api/v1/offers/${offerId}`, { timeoutMs: 15_000 })
}

export function getOffer(offerId: number | string) {
  return api.get<OfferFullDB>(`/api/v1/offers/${offerId}`, { timeoutMs: 15_000 })
}

export function getOfferVersions(offerId: number | string) {
  return api.get<OfferSummary[]>(`/api/v1/offers/${offerId}/versions`, { timeoutMs: 15_000 })
}
