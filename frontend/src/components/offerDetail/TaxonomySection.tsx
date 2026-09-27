import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Layers, RefreshCw } from "lucide-react"
import {
  getOfferTaxonomy,
  getTaxonomy,
  recheckTaxonomy,
  setItemCategory,
  type TaxonomyNode,
} from "../../api/taxonomyApi"
import { Badge } from "../ui/Badge"
import { DetailSection } from "./DetailSection"
import { EmptyState } from "../ui/EmptyState"
import { ErrorBanner } from "../ui/ErrorBanner"
import { Pill } from "../ui/Pill"
import { Spinner } from "../ui/Spinner"

/** Flattens the tree into the option list a select needs, keeping disciplines
 * and their equipment types visually distinct. */
function flatten(nodes: TaxonomyNode[], depth = 0): { node: TaxonomyNode; depth: number }[] {
  return nodes.flatMap((node) => [{ node, depth }, ...flatten(node.children, depth + 1)])
}

/** Which discipline each line item belongs to, and a way to fix it when the
 * automatic sort got it wrong.
 *
 * Correcting an item optionally teaches the system the wording. That
 * correction is stored as an alias keyed on the item's own text rather than on
 * the item row, because re-persisting an offer wipes and rewrites its items -
 * a fix written onto the row would be lost the next time the offer is re-run.
 * New aliases wait for an admin before they start sorting anyone else's items.
 */
export function TaxonomySection({ offerId }: { offerId: number }) {
  const queryClient = useQueryClient()
  const [learn, setLearn] = useState(true)
  const [actionError, setActionError] = useState<string | null>(null)

  const queryKey = ["offer-taxonomy", offerId]
  const { data, isLoading } = useQuery({ queryKey, queryFn: () => getOfferTaxonomy(offerId) })
  const { data: tree } = useQuery({ queryKey: ["taxonomy"], queryFn: getTaxonomy })

  const recheck = useMutation({
    mutationFn: () => recheckTaxonomy(offerId),
    onSuccess: () => setTimeout(() => void queryClient.invalidateQueries({ queryKey }), 4_000),
    onError: (err: Error) => setActionError(err.message),
  })

  const reassign = useMutation({
    mutationFn: ({ itemId, nodeId }: { itemId: number; nodeId: number }) =>
      setItemCategory(offerId, itemId, nodeId, learn),
    onSuccess: () => {
      setActionError(null)
      void queryClient.invalidateQueries({ queryKey })
    },
    onError: (err: Error) => setActionError(err.message),
  })

  if (isLoading) {
    return (
      <DetailSection title="Items by discipline">
        <div className="grid place-items-center py-10">
          <Spinner />
        </div>
      </DetailSection>
    )
  }

  if (!data || data.items.length === 0) {
    return (
      <DetailSection title="Items by discipline">
        <EmptyState
          icon={<Layers className="h-5 w-5" aria-hidden />}
          title="No line items to sort"
        />
      </DetailSection>
    )
  }

  const options = tree ? flatten(tree) : []

  return (
    <DetailSection
      title="Items by discipline"
      description={`${data.resolved_count} of ${data.items.length} sorted${
        data.unresolved_count > 0 ? `, ${data.unresolved_count} still uncategorised` : ""
      }`}
      collapsible
      defaultOpen={false}
      aside={
        <Pill
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          onClick={() => recheck.mutate()}
          disabled={recheck.isPending}
        >
          {recheck.isPending ? "Starting..." : "Sort again"}
        </Pill>
      }
    >
      {Object.keys(data.disciplines).length > 0 && (
        <div className="flex flex-wrap gap-2 border-b border-border px-5 py-3">
          {Object.entries(data.disciplines).map(([code, count]) => (
            <Badge key={code} tone="brand">
              {data.items.find((item) => item.discipline_code === code)?.discipline_label ?? code}
              {" · "}
              {count}
            </Badge>
          ))}
        </div>
      )}

      {actionError && (
        <div className="px-5 pt-3">
          <ErrorBanner>{actionError}</ErrorBanner>
        </div>
      )}

      <label className="flex items-center gap-2 border-b border-border px-5 py-2.5 text-[12.5px] text-muted-foreground">
        <input
          type="checkbox"
          checked={learn}
          onChange={(event) => setLearn(event.target.checked)}
          className="h-3.5 w-3.5 accent-[var(--accent)]"
        />
        Remember this wording for future offers (an admin approves it before it applies elsewhere)
      </label>

      <ul className="m-0 list-none p-0">
        {data.items.map((item) => (
          <li
            key={item.item_id}
            className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-2.5 last:border-b-0"
          >
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-[13.5px]" title={item.description}>
                {item.description}
              </span>
              {item.equipment_type_original && (
                <span className="text-[12px] text-muted-foreground">
                  {item.equipment_type_original}
                </span>
              )}
            </div>
            <div className="flex flex-none items-center gap-2">
              {item.discipline_label ? (
                <Badge tone="neutral">
                  {item.discipline_label}
                  {item.node_label && item.node_label !== item.discipline_label
                    ? ` › ${item.node_label}`
                    : ""}
                </Badge>
              ) : (
                <Badge tone="warning">Uncategorised</Badge>
              )}
              <select
                className="h-8 rounded-full border border-border bg-background px-2.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-accent-40"
                value={item.node_id ?? ""}
                onChange={(event) => {
                  const nodeId = Number(event.target.value)
                  if (nodeId) reassign.mutate({ itemId: item.item_id, nodeId })
                }}
              >
                <option value="">Move to...</option>
                {options.map(({ node, depth }) => (
                  <option key={node.node_id} value={node.node_id}>
                    {depth > 0 ? `   ${node.label}` : node.label}
                  </option>
                ))}
              </select>
            </div>
          </li>
        ))}
      </ul>
    </DetailSection>
  )
}
