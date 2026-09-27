import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Archive, FolderOpen, GitCompare, Plus, Search, Trash2 } from "lucide-react"
import { deleteOffer, getOfferFilterOptions, listOffersPage } from "../api/offerApi"
import type { OfferListStatusFilter, OfferSummary } from "../api/types"
import { MAX_COMPARE_OFFERS } from "../api/compareApi"
import { AppHeader } from "../components/layout/AppHeader"
import { AppShell } from "../components/layout/AppShell"
import { Badge } from "../components/ui/Badge"
import { ConfirmDialog, useConfirmAction } from "../components/ui/ConfirmDialog"
import { EmptyState } from "../components/ui/EmptyState"
import { ErrorBanner } from "../components/ui/ErrorBanner"
import { Pill } from "../components/ui/Pill"
import { PrimaryButton } from "../components/ui/PrimaryButton"
import { Spinner } from "../components/ui/Spinner"
import { Table, Tbody, Td, Th, Thead, Tr } from "../components/ui/Table"
import { formatDate, formatMoney } from "../lib/format"
import { missingTermsLabel } from "../lib/completeness"

const VIEWS: { value: OfferListStatusFilter | "working"; label: string }[] = [
  { value: "working", label: "All offers" },
  { value: "needs_review", label: "Needs review" },
  { value: "unchecked", label: "Unchecked" },
  { value: "archived", label: "Archived" },
]

const PAGE_SIZE = 50

function statusBadge(offer: OfferSummary) {
  if (offer.is_archived) return <Badge tone="neutral">Archived</Badge>
  if (offer.review_status === "needs_review") return <Badge tone="critical">Needs review</Badge>
  if (offer.review_status === "clear") return <Badge tone="success">Clear</Badge>
  return null
}

export function OffersPage() {
  const navigate = useNavigate()
  const [view, setView] = useState<(typeof VIEWS)[number]["value"]>("working")
  const [q, setQ] = useState("")
  const [supplierId, setSupplierId] = useState<number | undefined>(undefined)
  const [project, setProject] = useState<string | undefined>(undefined)
  const [rfq, setRfq] = useState("")
  const [uploadedBy, setUploadedBy] = useState<number | undefined>(undefined)
  const [selected, setSelected] = useState<Set<number>>(new Set())

  const { data: filterOptions } = useQuery({
    queryKey: ["offers", "filter-options"],
    queryFn: () => getOfferFilterOptions(),
  })

  const { data, isLoading, isError } = useQuery({
    queryKey: ["offers", { view, q, supplierId, project, rfq, uploadedBy }],
    queryFn: () =>
      listOffersPage({
        status: view === "working" ? undefined : view,
        q: q || undefined,
        supplierId,
        project,
        rfq: rfq || undefined,
        uploadedBy,
        limit: PAGE_SIZE,
      }),
  })

  const offers = data?.items ?? []

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else if (next.size < MAX_COMPARE_OFFERS) next.add(id)
      return next
    })
  }

  function clearFilters() {
    setQ("")
    setSupplierId(undefined)
    setProject(undefined)
    setRfq("")
    setUploadedBy(undefined)
  }

  const queryClient = useQueryClient()
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // Deleted one at a time rather than in parallel: the server refuses an offer
  // that still has a newer version or a running read, and a sequential pass
  // means each refusal is reported against the offer it belongs to instead of
  // one failure hiding the rest.
  const deleteMutation = useMutation({
    mutationFn: async (ids: number[]) => {
      const failures: { id: number; message: string }[] = []
      for (const id of ids) {
        try {
          await deleteOffer(id)
        } catch (err) {
          failures.push({ id, message: (err as Error).message })
        }
      }
      return failures
    },
    onSuccess: (failures) => {
      void queryClient.invalidateQueries({ queryKey: ["offers"] })
      // Whatever was refused stays selected, so the reason on screen still
      // lines up with a row the reviewer can see and act on.
      setSelected(new Set(failures.map((f) => f.id)))
      setDeleteError(
        failures.length === 0
          ? null
          : failures.map((f) => `Offer ${f.id}: ${f.message}`).join(" · "),
      )
    },
  })

  const confirmDelete = useConfirmAction(async () => {
    setDeleteError(null)
    await deleteMutation.mutateAsync([...selected])
  })

  const hasFilters = !!(q || supplierId || project || rfq || uploadedBy)

  return (
    <AppShell>
      <AppHeader />
      <main className="mx-auto max-w-[1200px] px-6 pb-20 pt-11">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2 text-accent">
              <FolderOpen className="h-4 w-4" aria-hidden />
              <span className="text-[11px] font-bold uppercase tracking-[0.12em]">Offers</span>
            </div>
            <h1 className="m-0 text-[27px] font-bold leading-[1.15] tracking-[-0.025em]">All offers</h1>
          </div>
          <div className="w-[200px]">
            <PrimaryButton type="button" onClick={() => navigate("/upload")}>
              <Plus className="h-4 w-4" aria-hidden />
              New check
            </PrimaryButton>
          </div>
        </div>

        <div className="mb-4 flex flex-wrap gap-1.5">
          {VIEWS.map((v) => (
            <Pill key={v.value} active={view === v.value} onClick={() => setView(v.value)}>
              {v.label}
            </Pill>
          ))}
        </div>

        <div data-tour="filters" className="mb-5 flex flex-col gap-2.5 rounded-[12px] border border-border bg-card p-3.5">
          <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-2.5">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <input
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Offer ref, project, supplier, RFQ"
                className="h-9 w-full rounded-lg border border-input bg-background pl-8 pr-3 text-[13px] outline-none focus:border-ring"
              />
            </label>
            <select
              value={supplierId ?? ""}
              onChange={(e) => setSupplierId(e.target.value ? Number(e.target.value) : undefined)}
              className="h-9 rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus:border-ring"
            >
              <option value="">All suppliers</option>
              {filterOptions?.suppliers.map((s) => (
                <option key={s.supplier_id} value={s.supplier_id}>
                  {s.supplier_name} ({s.offer_count})
                </option>
              ))}
            </select>
            <select
              value={project ?? ""}
              onChange={(e) => setProject(e.target.value || undefined)}
              className="h-9 rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus:border-ring"
            >
              <option value="">All projects</option>
              {filterOptions?.projects.map((p) => (
                <option key={p.project_label} value={p.project_label}>
                  {p.project_label} ({p.offer_count})
                </option>
              ))}
            </select>
            <input
              type="text"
              value={rfq}
              onChange={(e) => setRfq(e.target.value)}
              placeholder="RFQ-2026-"
              className="h-9 rounded-lg border border-input bg-background px-2.5 text-[13px] outline-none focus:border-ring"
            />
            <select
              value={uploadedBy ?? ""}
              onChange={(e) => setUploadedBy(e.target.value ? Number(e.target.value) : undefined)}
              className="h-9 rounded-lg border border-input bg-background px-2.5 text-[13px] text-foreground outline-none focus:border-ring"
            >
              <option value="">Anyone</option>
              {filterOptions?.uploaders.map((u) => (
                <option key={u.user_id} value={u.user_id}>
                  {u.display_name} ({u.offer_count})
                </option>
              ))}
            </select>
            {hasFilters && (
              <button type="button" onClick={clearFilters} className="text-[12.5px] font-semibold text-accent">
                Clear filters
              </button>
            )}
          </div>
        </div>

        {selected.size > 0 && (
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded-[10px] border border-accent-25 bg-accent-5 px-3.5 py-2.5">
            <span className="text-[12.5px] font-medium">{selected.size} offer(s) selected</span>
            <button
              type="button"
              onClick={() =>
                navigate(`/compare?${[...selected].map((id) => `offer_ids=${id}`).join("&")}`)
              }
              className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-accent"
            >
              <GitCompare className="h-3.5 w-3.5" aria-hidden />
              Compare
            </button>
            <button
              type="button"
              onClick={confirmDelete.request}
              className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-destructive hover:opacity-80"
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
              Delete
            </button>
            <button
              type="button"
              onClick={() => setSelected(new Set())}
              className="ml-auto text-[12.5px] font-medium text-muted-foreground hover:text-foreground"
            >
              Clear
            </button>
          </div>
        )}

        {deleteError && (
          <div className="mb-4">
            <ErrorBanner>{deleteError}</ErrorBanner>
          </div>
        )}

        {isLoading && (
          <div className="flex justify-center py-16">
            <Spinner label="Loading offers..." />
          </div>
        )}

        {isError && <p className="text-sm text-destructive">Could not load offers.</p>}

        {data && offers.length === 0 && (
          <EmptyState
            icon={<FolderOpen className="h-6 w-6" aria-hidden />}
            title="No offers found"
            description={hasFilters ? "No offer matches these filters." : "Upload your first supplier offer to see it here."}
            action={
              hasFilters ? (
                <button type="button" onClick={clearFilters} className="text-sm font-semibold text-accent">
                  Clear filters
                </button>
              ) : (
                <button type="button" onClick={() => navigate("/upload")} className="text-sm font-semibold text-accent">
                  Upload an offer
                </button>
              )
            }
          />
        )}

        {data && offers.length > 0 && (
          <>
            <Table>
              <Thead>
                <Tr>
                  <Th className="w-8" />
                  <Th>Offer</Th>
                  <Th>RFQ</Th>
                  <Th>Project</Th>
                  <Th>Supplier</Th>
                  <Th className="text-right">Value</Th>
                  <Th>Uploaded</Th>
                  <Th>Status</Th>
                </Tr>
              </Thead>
              <Tbody>
                {offers.map((offer) => {
                  const missingTerms = missingTermsLabel(offer.completeness_mandatory_gaps)
                  return (
                    <Tr key={offer.id} className="hover:bg-muted">
                      <Td onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selected.has(offer.id)}
                          onChange={() => toggle(offer.id)}
                          aria-label={`Select ${offer.offer_ref ?? `offer ${offer.id}`}`}
                        />
                      </Td>
                      <Td className="cursor-pointer" onClick={() => navigate(`/offers/${offer.id}`)}>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{offer.offer_ref ?? `Offer #${offer.id}`}</span>
                          {offer.version_count > 1 && <Badge tone="neutral">v{offer.version_count}</Badge>}
                        </div>
                      </Td>
                      <Td className="cursor-pointer" onClick={() => navigate(`/offers/${offer.id}`)}>
                        {offer.rfq_number ?? ""}
                      </Td>
                      <Td className="cursor-pointer" onClick={() => navigate(`/offers/${offer.id}`)}>
                        {offer.project_label ?? offer.project_name_original}
                      </Td>
                      <Td className="cursor-pointer" onClick={() => navigate(`/offers/${offer.id}`)}>
                        {offer.supplier_name}
                      </Td>
                      <Td
                        className="tabular cursor-pointer text-right"
                        onClick={() => navigate(`/offers/${offer.id}`)}
                      >
                        {formatMoney(offer.grand_total, offer.grand_total_currency)}
                      </Td>
                      <Td className="cursor-pointer" onClick={() => navigate(`/offers/${offer.id}`)}>
                        <div className="flex flex-col">
                          <span className="tabular">{formatDate(offer.created_at)}</span>
                          {offer.created_by_display_name && (
                            <span className="text-xs text-muted-foreground">{offer.created_by_display_name}</span>
                          )}
                        </div>
                      </Td>
                      <Td className="cursor-pointer" onClick={() => navigate(`/offers/${offer.id}`)}>
                        <div className="flex flex-wrap items-center gap-1.5">
                          {statusBadge(offer)}
                          {missingTerms && <Badge tone="critical">{missingTerms}</Badge>}
                        </div>
                      </Td>
                    </Tr>
                  )
                })}
              </Tbody>
            </Table>
            <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
              {offers.length} of {data.total} offer(s)
              {data.archived_matching > 0 && view !== "archived" && (
                <>
                  {" "}
                  ·{" "}
                  <button type="button" onClick={() => setView("archived")} className="inline-flex items-center gap-1 font-semibold text-accent">
                    <Archive className="h-3 w-3" aria-hidden />
                    and {data.archived_matching} archived
                  </button>
                </>
              )}
            </p>
          </>
        )}
      </main>

      <ConfirmDialog
        {...confirmDelete.dialogProps}
        title={selected.size === 1 ? "Delete this offer?" : `Delete ${selected.size} offers?`}
        confirmLabel="Delete"
        body={
          selected.size === 1
            ? "This permanently deletes the offer, its documents, and its entire history - findings, activity and pipeline runs included. Its files are removed from disk too. This cannot be undone."
            : `This permanently deletes all ${selected.size} selected offers, their documents, and their entire history - findings, activity and pipeline runs included. Their files are removed from disk too. This cannot be undone.`
        }
      />
    </AppShell>
  )
}
