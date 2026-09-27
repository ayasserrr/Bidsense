import { api } from "./client"
import type { Job } from "./jobApi"

export interface TaxonomyNode {
  node_id: number
  parent_node_id: number | null
  code: string
  label: string
  level: number
  sort_order: number
  is_active: boolean
  item_count: number
  children: TaxonomyNode[]
}

export interface ItemTaxonomy {
  item_id: number
  description: string
  equipment_type_original: string | null
  node_id: number | null
  node_code: string | null
  node_label: string | null
  discipline_code: string | null
  discipline_label: string | null
}

export interface OfferTaxonomy {
  signal: string
  offer_id: number
  resolved_count: number
  unresolved_count: number
  /** Discipline code -> how many of this offer's items sit in it. */
  disciplines: Record<string, number>
  items: ItemTaxonomy[]
}

export function getTaxonomy() {
  return api.get<TaxonomyNode[]>("/api/v1/taxonomy", { timeoutMs: 20_000 })
}

export function getOfferTaxonomy(offerId: number | string) {
  return api.get<OfferTaxonomy>(`/api/v1/offers/${offerId}/taxonomy`, { timeoutMs: 20_000 })
}

export function recheckTaxonomy(offerId: number | string) {
  return api.post<Job>(`/api/v1/offers/${offerId}/taxonomy/recheck`, { timeoutMs: 30_000 })
}

/** Moves one item to the right category. `learn_alias` remembers the wording
 * for future offers - but the new alias needs an admin's approval before it
 * starts resolving anyone else's items. */
export function setItemCategory(
  offerId: number | string,
  itemId: number,
  nodeId: number,
  learnAlias = false,
) {
  return api.post<ItemTaxonomy>(`/api/v1/offers/${offerId}/items/${itemId}/category`, {
    json: { node_id: nodeId, learn_alias: learnAlias },
    timeoutMs: 20_000,
  })
}
