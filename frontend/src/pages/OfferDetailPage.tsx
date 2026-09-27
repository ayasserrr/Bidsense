import { Fragment, useState } from "react"
import { useLocation, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Banknote, ChevronDown, ChevronRight, FileWarning, Package, Trash2 } from "lucide-react"
import { deleteOffer, getOffer, getOfferVersions } from "../api/offerApi"
import type {
  IncludedFeatureDB,
  OfferFullDB,
  OfferItemDB,
  TechSpecDB,
  UploadedFileResult,
} from "../api/types"
import { AppHeader } from "../components/layout/AppHeader"
import { AppShell } from "../components/layout/AppShell"
import { Badge } from "../components/ui/Badge"
import { DetailField, DetailSection } from "../components/offerDetail/DetailSection"
import { CompletenessSection } from "../components/offerDetail/CompletenessSection"
import { ConfirmDialog, useConfirmAction } from "../components/ui/ConfirmDialog"
import { FindingsSection } from "../components/offerDetail/FindingsSection"
import { ReviewSummarySection } from "../components/offerDetail/ReviewSummarySection"
import { FormattedText } from "../components/offerDetail/FormattedText"
import { TaxonomySection } from "../components/offerDetail/TaxonomySection"
import { EmptyState } from "../components/ui/EmptyState"
import { ErrorBanner } from "../components/ui/ErrorBanner"
import { Spinner } from "../components/ui/Spinner"
import { StatCard } from "../components/ui/StatCard"
import { Table, Tbody, Td, Th, Thead, Tr } from "../components/ui/Table"
import { formatAmount, formatMoney, formatSpecValue } from "../lib/format"
import { missingTermsLabel } from "../lib/completeness"
import { cn } from "../lib/cn"

interface LocationState {
  offer?: OfferFullDB
  skippedFiles?: UploadedFileResult[]
}

interface ItemNode extends OfferItemDB {
  children: ItemNode[]
}

function buildItemTree(items: OfferItemDB[]): ItemNode[] {
  const nodes = new Map<number, ItemNode>(items.map((item) => [item.item_id, { ...item, children: [] }]))
  const roots: ItemNode[] = []
  for (const item of items) {
    const node = nodes.get(item.item_id)!
    if (item.parent_item_id !== null && nodes.has(item.parent_item_id)) {
      nodes.get(item.parent_item_id)!.children.push(node)
    } else {
      roots.push(node)
    }
  }
  return roots
}

// Marks where a section header should render above the first item of each
// new item_group_label run among top-level items.
function withGroupHeaders(
  rows: { node: ItemNode; depth: number }[],
): { node: ItemNode; depth: number; groupHeader: string | null }[] {
  let previousTopLevelLabel: string | null = null
  return rows.map(({ node, depth }) => {
    if (depth !== 0 || !node.item_group_label) {
      if (depth === 0) previousTopLevelLabel = null
      return { node, depth, groupHeader: null }
    }
    const isNewGroup = node.item_group_label !== previousTopLevelLabel
    previousTopLevelLabel = node.item_group_label
    return { node, depth, groupHeader: isNewGroup ? node.item_group_label : null }
  })
}

function flattenTree(nodes: ItemNode[], depth = 0): { node: ItemNode; depth: number }[] {
  return nodes.flatMap((node) => [{ node, depth }, ...flattenTree(node.children, depth + 1)])
}

// Tax treatment text is verbatim from the source and can be a short phrase
// ("Excluding VAT") or a full disclaimer paragraph - a pill-shaped Badge
// (rounded-full) only looks right for the former and stretches into an odd
// blob for the latter, so this always uses a wrapping note box instead:
// w-fit keeps short text chip-sized while max-w-full lets long text wrap
// cleanly within the card.
function TaxTreatmentNote({ text }: { text: string }) {
  return (
    <p className="m-0 w-fit max-w-full rounded-md border border-yellow-300 bg-yellow-50 px-2 py-1 text-[11px] leading-snug text-yellow-800 dark:border-yellow-500/30 dark:bg-yellow-500/10 dark:text-yellow-400">
      {text}
    </p>
  )
}

function pricingBadge(item: OfferItemDB) {
  if (item.is_alternate) return <Badge tone="warning">Alternate</Badge>
  if (item.is_optional) return <Badge tone="info">Optional</Badge>
  return null
}

function groupBySpecGroup(specs: TechSpecDB[]): Map<string, TechSpecDB[]> {
  const groups = new Map<string, TechSpecDB[]>()
  for (const spec of specs) {
    const list = groups.get(spec.spec_group) ?? []
    list.push(spec)
    groups.set(spec.spec_group, list)
  }
  return groups
}

// Renders the extraction's {label: value} catch-all for facts with no dedicated field.
function ExtraAttributesList({ attributes }: { attributes: Record<string, string> }) {
  const entries = Object.entries(attributes)
  if (entries.length === 0) return null
  return (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
      {entries.map(([label, value]) => (
        <div key={label} className="flex gap-1.5 text-[12.5px]">
          <dt className="font-medium text-foreground">{label}:</dt>
          <dd className="m-0 text-muted-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function ItemDetailPanel({
  techSpecs,
  features,
  extraAttributes,
  depth,
}: {
  techSpecs: TechSpecDB[]
  features: IncludedFeatureDB[]
  extraAttributes: Record<string, string> | null
  depth: number
}) {
  const groups = groupBySpecGroup(techSpecs)
  const hasExtra = !!extraAttributes && Object.keys(extraAttributes).length > 0
  if (groups.size === 0 && features.length === 0 && !hasExtra) return null

  return (
    <div
      className="flex flex-col gap-3 border-t border-border bg-muted-60 px-4 py-3"
      style={{ paddingLeft: `${16 + depth * 20}px` }}
    >
      {[...groups.entries()].map(([groupName, specs]) => (
        <div key={groupName} className="flex flex-col gap-1">
          <span className="text-[10.5px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
            {groupName}
          </span>
          <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
            {specs.map((spec) => (
              <div key={spec.spec_id} className="flex gap-1.5 text-[12.5px]">
                <dt className="font-medium text-foreground">{spec.spec_name}:</dt>
                <dd className="m-0 text-muted-foreground">{formatSpecValue(spec.spec_value, spec.spec_unit)}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
      {features.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {features.map((f) => (
            <li key={f.feature_id} className="text-[12.5px] text-muted-foreground">
              • {f.feature_text}
            </li>
          ))}
        </ul>
      )}
      {hasExtra && (
        <div className="flex flex-col gap-1">
          <span className="text-[10.5px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
            Additional info
          </span>
          <ExtraAttributesList attributes={extraAttributes!} />
        </div>
      )}
    </div>
  )
}

export function OfferDetailPage() {
  const { offerId } = useParams<{ offerId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const navigatedOffer = (location.state as LocationState | null)?.offer
  const skippedFiles = (location.state as LocationState | null)?.skippedFiles
  const [expandedItemIds, setExpandedItemIds] = useState<Set<number>>(new Set())
  const [expandedScheduleIds, setExpandedScheduleIds] = useState<Set<number>>(new Set())

  function toggleItem(itemId: number) {
    setExpandedItemIds((prev) => {
      const next = new Set(prev)
      if (next.has(itemId)) next.delete(itemId)
      else next.add(itemId)
      return next
    })
  }

  function toggleSchedule(scheduleId: number) {
    setExpandedScheduleIds((prev) => {
      const next = new Set(prev)
      if (next.has(scheduleId)) next.delete(scheduleId)
      else next.add(scheduleId)
      return next
    })
  }

  // navigatedOffer avoids a refetch flash right after a pipeline run;
  // a direct visit/refresh has no router state and falls back to a real fetch.
  const { data: fetchedOffer, isLoading, isError } = useQuery({
    queryKey: ["offer", offerId],
    queryFn: () => getOffer(offerId!),
    enabled: !!offerId && !navigatedOffer,
  })
  const offer = navigatedOffer ?? fetchedOffer

  const { data: versions, isError: isVersionsError } = useQuery({
    queryKey: ["offer-versions", offerId],
    queryFn: () => getOfferVersions(offerId!),
    enabled: !!offerId,
  })

  const queryClient = useQueryClient()
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const deleteMutation = useMutation({
    mutationFn: () => deleteOffer(offerId!),
    onSuccess: () => {
      setDeleteError(null)
      // The offer no longer exists - drop its cached data entirely rather
      // than invalidating it, which would just refetch a 404. The list is
      // still real, just stale, so that one is invalidated instead.
      queryClient.removeQueries({ queryKey: ["offer", offerId] })
      queryClient.removeQueries({ queryKey: ["offer-versions", offerId] })
      void queryClient.invalidateQueries({ queryKey: ["offers"] })
      navigate("/offers", { replace: true })
    },
    onError: (err: Error) => setDeleteError(err.message),
  })
  const confirmDelete = useConfirmAction(async () => {
    try {
      await deleteMutation.mutateAsync()
    } catch {
      // Already captured above as `deleteError`, shown via ErrorBanner - the
      // dialog itself just needs to close without also rejecting up into an
      // unhandled promise.
    }
  })

  if (isLoading) {
    return (
      <AppShell>
        <AppHeader />
        <div className="flex min-h-[60vh] items-center justify-center">
          <Spinner label="Loading offer..." />
        </div>
      </AppShell>
    )
  }

  if (!offer || isError) {
    return (
      <AppShell>
        <AppHeader />
        <main className="px-6 pb-20 pt-14">
          <div className="mx-auto max-w-[660px]">
            <EmptyState
              icon={<FileWarning className="h-6 w-6" aria-hidden />}
              title="This offer couldn't be loaded"
              description="It may not exist, or something went wrong reaching the backend."
              action={
                <button
                  type="button"
                  onClick={() => navigate("/offers")}
                  className="text-sm font-semibold text-accent"
                >
                  Back to all offers
                </button>
              }
            />
          </div>
        </main>
      </AppShell>
    )
  }

  const {
    offer: o,
    supplier,
    project,
    contacts,
    items,
    payment_schedules,
    tech_specs,
    included_features,
    inclusions_exclusions,
    attachments,
    verified_findings,
    completeness_mandatory_gaps,
  } = offer

  // Single derived review badge: verification (source-grounded, the more
  // authoritative check) wins when it's run; otherwise fall back to the
  // sanity check's own status.
  const needsReview =
    o.verification_status === "needs_human_review" ||
    (o.verification_status === null && o.sanity_check_status === "needs_review")

  // The completeness gaps, said in the header rather than only in the section
  // further down the page. Nothing is shown when the check has never run.
  const missingTerms = missingTermsLabel(completeness_mandatory_gaps)

  const itemRows = withGroupHeaders(flattenTree(buildItemTree(items)))
  const showAvailabilityCol = items.some((i) => i.availability_original_text)
  const showStatusCol = items.some((i) => i.is_optional || i.is_alternate)
  // chevron, Description, Qty, Unit price, Total, Currency are always shown.
  const itemColumnCount = 6 + (showAvailabilityCol ? 1 : 0) + (showStatusCol ? 1 : 0)
  const offerTechSpecs = tech_specs.filter((spec) => spec.entity_type === "offer")
  const offerFeatures = included_features.filter((f) => f.entity_type === "offer")
  const inclusions = inclusions_exclusions.filter((e) => e.entry_type === "include")
  const exclusions = inclusions_exclusions.filter((e) => e.entry_type === "exclude")
  const itemTechSpecs = tech_specs.filter((spec) => spec.entity_type === "item")
  const itemFeatures = included_features.filter((f) => f.entity_type === "item")

  // A document with no single offer-wide grand_total (e.g. a "Base offer"
  // and an "Alternative offer" each independently totaled, with nothing
  // summing the two together) still has a real total per group, on that
  // group's own top-level item - show those instead of one blank card.
  const groupTotals = items.filter((i) => i.parent_item_id === null && i.stated_subtotal_amount !== null)
  const showGroupTotals = o.grand_total === null && groupTotals.length > 0

  return (
    <AppShell>
      <AppHeader />

      <div className="border-b border-border bg-card">
        <div className="mx-auto max-w-[1060px] px-6 pt-[22px] pb-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex min-w-0 flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2.5">
                <h1 className="m-0 text-[27px] font-bold leading-[1.15] tracking-[-0.025em]">
                  {o.offer_ref ?? `Offer #${o.id}`}
                </h1>
                {needsReview && <Badge tone="critical">Needs review</Badge>}
                {missingTerms && <Badge tone="critical">{missingTerms}</Badge>}
                {o.rfq_number && <Badge tone="neutral">{o.rfq_number}</Badge>}
              </div>
              <p className="m-0 text-[14.5px] text-muted-foreground">
                {[offer.project_label ?? o.project_name_original, supplier?.supplier_name]
                  .filter(Boolean)
                  .join(" · ") || `Offer id ${offerId}`}
                {offer.created_by_display_name && ` · uploaded by ${offer.created_by_display_name}`}
              </p>
            </div>

            <button
              type="button"
              onClick={confirmDelete.request}
              disabled={!o.is_active_latest}
              title={
                o.is_active_latest
                  ? undefined
                  : "A newer version of this offer exists. Delete that version first."
              }
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-border bg-card px-2.5 text-xs font-medium text-muted-foreground transition hover:border-destructive-30 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
              Delete
            </button>
          </div>

          {isVersionsError && (
            <p className="mt-4 text-xs text-muted-foreground">Version history couldn't be loaded.</p>
          )}

          {versions && versions.length > 1 && (
            <div className="mt-4 flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-muted-foreground">Versions:</span>
              {versions.map((v, index) => (
                <button
                  key={v.id}
                  type="button"
                  onClick={() => navigate(`/offers/${v.id}`)}
                  className={cn(
                    "h-6 rounded-full border px-2.5 text-[11.5px] font-medium transition-colors",
                    v.id === o.id
                      ? "border-accent bg-accent text-accent-foreground"
                      : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  v{index + 1}
                  {v.is_active_latest && v.id !== o.id ? " · latest" : ""}
                </button>
              ))}
            </div>
          )}

          <div className="mt-5 flex flex-wrap gap-3">
            {showGroupTotals ? (
              groupTotals.map((group) => (
                <StatCard
                  key={group.item_id}
                  className="min-w-[220px] flex-1 basis-[220px]"
                  icon={<Banknote className="h-4 w-4" aria-hidden />}
                  label="Grand total"
                  value={formatMoney(group.stated_subtotal_amount, group.stated_subtotal_currency)}
                  sub={
                    <div className="flex flex-col gap-1.5">
                      <span className="font-medium text-foreground">{group.item_group_label ?? group.description}</span>
                      {(group.tax_treatment_override_original ?? o.tax_treatment_original) && (
                        <TaxTreatmentNote text={group.tax_treatment_override_original ?? o.tax_treatment_original!} />
                      )}
                    </div>
                  }
                />
              ))
            ) : (
              <StatCard
                className="min-w-[200px] flex-1 basis-[200px]"
                icon={<Banknote className="h-4 w-4" aria-hidden />}
                label="Grand total"
                value={formatMoney(o.grand_total, o.grand_total_currency)}
                sub={o.tax_treatment_original && <TaxTreatmentNote text={o.tax_treatment_original} />}
              />
            )}
            <StatCard
              className="min-w-[200px] flex-1 basis-[200px]"
              icon={<Package className="h-4 w-4" aria-hidden />}
              label="Line items"
              value={String(items.length)}
              sub={`${items.filter((i) => i.is_optional).length} optional`}
            />
            <StatCard
              className="min-w-[200px] flex-1 basis-[200px]"
              icon={<FileWarning className="h-4 w-4" aria-hidden />}
              label="Attachments referenced"
              value={String(attachments.length)}
              sub={`${payment_schedules.length} payment milestones`}
            />
          </div>
        </div>
      </div>

      <main className="mx-auto flex max-w-[1060px] flex-col gap-5 px-6 pb-20 pt-[26px]">
        {deleteError && <ErrorBanner>{deleteError}</ErrorBanner>}

        {skippedFiles && skippedFiles.length > 0 && (
          <ErrorBanner>
            {skippedFiles.length === 1 ? "1 file" : `${skippedFiles.length} files`} from this upload{" "}
            {skippedFiles.length === 1 ? "wasn't" : "weren't"} included:{" "}
            {skippedFiles.map((f) => `${f.filename} (${f.message})`).join("; ")}
          </ErrorBanner>
        )}

        {/* First thing in <main> - the whole point of this panel is "read
            this first", before the raw findings/completeness lists below. */}
        <ReviewSummarySection offerId={o.id} />

        <FindingsSection verifiedFindings={verified_findings} />

        {/* Directly under the findings, because this is the question the
            client actually asked the product to answer: what did the
            supplier fail to state? */}
        <CompletenessSection offerId={o.id} />

        <DetailSection
          title="Commercial offer"
          collapsible
          bodyClassName="grid grid-cols-1 gap-4 px-5 py-[18px] sm:grid-cols-3"
        >
          <DetailField label="Project" value={o.project_name_original} />
          <DetailField label="Client" value={o.client_name_original} />
          <DetailField label="Incoterm" value={o.incoterm} />
          <DetailField label="Currency" value={o.currency_primary} />
          <DetailField label="Signed by" value={o.offer_signed_by_original} />
          <DetailField label="Offer date" value={o.offer_date_original} />
          <DetailField label="Manufacturer" value={o.manufacturer_original} />
          <DetailField label="Product" value={o.product_name_original} />
          <DetailField
            label="Validity terms"
            className="sm:col-span-3"
            value={o.validity_terms_original ? <FormattedText text={o.validity_terms_original} /> : null}
          />
          <DetailField
            label="Payment terms"
            className="sm:col-span-3"
            value={o.payment_terms_original ? <FormattedText text={o.payment_terms_original} /> : null}
          />
          <DetailField
            label="Delivery terms"
            className="sm:col-span-3"
            value={o.delivery_terms_original ? <FormattedText text={o.delivery_terms_original} /> : null}
          />
          <DetailField
            label="Warranty terms"
            className="sm:col-span-3"
            value={o.warranty_terms_original ? <FormattedText text={o.warranty_terms_original} /> : null}
          />
          <DetailField
            label="Notes"
            className="sm:col-span-3"
            value={o.general_notes_original ? <FormattedText text={o.general_notes_original} /> : null}
          />
        </DetailSection>

        {o.extra_attributes && Object.keys(o.extra_attributes).length > 0 && (
          <DetailSection
            title="Additional info"
            description="Real facts the document stated that don't fit a specific field above"
            bodyClassName="px-5 py-[18px]"
            collapsible
            defaultOpen={false}
          >
            <ExtraAttributesList attributes={o.extra_attributes} />
          </DetailSection>
        )}

        {project && (
          <DetailSection
            title="Project"
            collapsible
            defaultOpen={false}
            bodyClassName="grid grid-cols-1 gap-4 px-5 py-[18px] sm:grid-cols-3"
          >
            <DetailField label="Project name" value={project.project_name} />
            <DetailField label="Client" value={project.client_name} />
            <DetailField label="Location" value={project.location} />
          </DetailSection>
        )}

        <DetailSection title="Items" description={`${items.length} line item(s)`} collapsible>
          {items.length === 0 ? (
            <div className="px-5 py-8">
              <EmptyState title="No items extracted" />
            </div>
          ) : (
            <Table>
              <Thead>
                <Tr>
                  <Th></Th>
                  <Th>Description</Th>
                  {showAvailabilityCol && <Th>Availability</Th>}
                  <Th>Qty</Th>
                  <Th>Unit price</Th>
                  <Th>Total</Th>
                  <Th>Currency</Th>
                  {showStatusCol && <Th>Status</Th>}
                </Tr>
              </Thead>
              <Tbody>
                {itemRows.map(({ node, depth, groupHeader }) => {
                  const specsForItem = itemTechSpecs.filter((spec) => spec.entity_id === node.item_id)
                  const featuresForItem = itemFeatures.filter((f) => f.entity_id === node.item_id)
                  const hasExtraAttrs = !!node.extra_attributes && Object.keys(node.extra_attributes).length > 0
                  const hasLongDescription = node.description.length > 220
                  const hasDetail = specsForItem.length > 0 || featuresForItem.length > 0 || hasExtraAttrs || hasLongDescription
                  const isExpanded = expandedItemIds.has(node.item_id)
                  return (
                    <Fragment key={node.item_id}>
                      {groupHeader && (
                        <Tr className="bg-muted-60">
                          <Td colSpan={itemColumnCount} className="py-2 text-[11.5px] font-bold uppercase tracking-[0.06em] text-muted-foreground">
                            {groupHeader}
                          </Td>
                        </Tr>
                      )}
                      <Tr
                        className={cn(hasDetail && "cursor-pointer hover:bg-muted", depth > 0 && "bg-muted-30")}
                        onClick={hasDetail ? () => toggleItem(node.item_id) : undefined}
                      >
                        <Td className="w-8 pr-0">
                          {hasDetail &&
                            (isExpanded ? (
                              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                            ) : (
                              <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                            ))}
                        </Td>
                        <Td className="relative max-w-[420px]" style={{ paddingLeft: `${16 + depth * 20}px` }}>
                          {depth > 0 && (
                            <span
                              className="absolute top-0 h-full border-l-2 border-border"
                              style={{ left: `${16 + (depth - 1) * 20 + 7}px` }}
                              aria-hidden="true"
                            />
                          )}
                          <div
                            className={cn(
                              "leading-[1.55]",
                              depth === 0 ? "font-semibold" : "font-medium",
                              !isExpanded && hasLongDescription && "line-clamp-3",
                            )}
                          >
                            {isExpanded && hasLongDescription ? (
                              <FormattedText text={node.description} />
                            ) : (
                              node.description
                            )}
                          </div>
                          {hasLongDescription && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                toggleItem(node.item_id)
                              }}
                              className="mt-0.5 text-xs font-medium text-accent hover:underline"
                            >
                              {isExpanded ? "Show less" : "Show more"}
                            </button>
                          )}
                          {(node.equipment_type_original || node.model_number) && (
                            <div className="mt-0.5 text-xs text-muted-foreground">
                              {[node.equipment_type_original, node.model_number && `Model ${node.model_number}`]
                                .filter(Boolean)
                                .join(" · ")}
                            </div>
                          )}
                        </Td>
                        {showAvailabilityCol && <Td>{node.availability_original_text}</Td>}
                        <Td className="tabular">
                          {node.quantity} {node.unit ?? ""}
                        </Td>
                        <Td className="tabular">{formatAmount(node.unit_price)}</Td>
                        <Td className="tabular">{formatAmount(node.total_price)}</Td>
                        <Td className="tabular">{node.price_currency}</Td>
                        {showStatusCol && <Td>{pricingBadge(node)}</Td>}
                      </Tr>
                      {isExpanded && (
                        <Tr>
                          <Td colSpan={itemColumnCount} className="p-0">
                            <ItemDetailPanel
                              techSpecs={specsForItem}
                              features={featuresForItem}
                              extraAttributes={node.extra_attributes}
                              depth={depth}
                            />
                          </Td>
                        </Tr>
                      )}
                    </Fragment>
                  )
                })}
              </Tbody>
            </Table>
          )}
        </DetailSection>

        <TaxonomySection offerId={o.id} />

        <DetailSection
          title="Technical specifications"
          description="Offer-level specs and features"
          collapsible
          defaultOpen={false}
        >
          <div className="flex flex-col gap-4 px-5 py-[18px]">
            {offerTechSpecs.length === 0 && offerFeatures.length === 0 ? (
              <EmptyState title="No offer-level tech specs" />
            ) : (
              <>
                {offerTechSpecs.length > 0 && (
                  <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    {offerTechSpecs.map((spec) => (
                      <DetailField
                        key={spec.spec_id}
                        label={`${spec.spec_group} · ${spec.spec_name}`}
                        value={formatSpecValue(spec.spec_value, spec.spec_unit)}
                      />
                    ))}
                  </dl>
                )}
                {offerFeatures.length > 0 && (
                  <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                    {offerFeatures.map((f) => (
                      <li key={f.feature_id} className="text-sm">
                        • {f.feature_text}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        </DetailSection>

        <DetailSection title="Inclusions & exclusions" collapsible defaultOpen={false}>
          <div className="grid grid-cols-1 gap-5 px-5 py-[18px] sm:grid-cols-2">
            <div>
              <h3 className="m-0 mb-2 text-xs font-bold uppercase tracking-wide text-success">Included</h3>
              {inclusions.length === 0 ? (
                <p className="text-sm text-muted-foreground">None stated</p>
              ) : (
                <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-sm">
                  {inclusions.map((e) => (
                    <li key={e.entry_id}>• {e.description}</li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h3 className="m-0 mb-2 text-xs font-bold uppercase tracking-wide text-destructive">Excluded</h3>
              {exclusions.length === 0 ? (
                <p className="text-sm text-muted-foreground">None stated</p>
              ) : (
                <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-sm">
                  {exclusions.map((e) => (
                    <li key={e.entry_id}>• {e.description}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </DetailSection>

        <DetailSection title="Payment schedule" collapsible defaultOpen={false}>
          {payment_schedules.length === 0 ? (
            <div className="px-5 py-8">
              <EmptyState title="No payment schedule extracted" />
            </div>
          ) : (
            <Table>
              <Thead>
                <Tr>
                  <Th>#</Th>
                  <Th>Trigger</Th>
                  <Th>Scope</Th>
                  <Th>Percentage</Th>
                  <Th>Description</Th>
                </Tr>
              </Thead>
              <Tbody>
                {payment_schedules
                  .slice()
                  .sort((a, b) => a.sequence_no - b.sequence_no)
                  .map((p) => {
                    const coveredItems = (p.scope_item_ids ?? [])
                      .map((itemId) => items.find((i) => i.item_id === itemId))
                      .filter((i): i is OfferItemDB => !!i)
                    // A schedule "scoped" to every item in the offer isn't
                    // really scoped to anything specific - only show the
                    // item breakdown when it's a genuine subset.
                    const hasSpecificScope = coveredItems.length > 0 && coveredItems.length < items.length
                    const isExpanded = expandedScheduleIds.has(p.schedule_id)
                    return (
                      <Fragment key={p.schedule_id}>
                        <Tr>
                          <Td>{p.sequence_no}</Td>
                          <Td>{p.trigger_event}</Td>
                          <Td>
                            {p.scope_label}
                            {hasSpecificScope && (
                              <button
                                type="button"
                                onClick={() => toggleSchedule(p.schedule_id)}
                                className="mt-0.5 flex items-center gap-1 text-xs font-medium text-accent hover:underline"
                              >
                                {isExpanded ? (
                                  <ChevronDown className="h-3 w-3" aria-hidden />
                                ) : (
                                  <ChevronRight className="h-3 w-3" aria-hidden />
                                )}
                                {coveredItems.length === 1 ? "1 item" : `${coveredItems.length} items`}
                              </button>
                            )}
                          </Td>
                          <Td className="tabular">{p.percentage !== null ? `${p.percentage}%` : ""}</Td>
                          <Td>{p.description_original}</Td>
                        </Tr>
                        {isExpanded && hasSpecificScope && (
                          <Tr>
                            <Td colSpan={5} className="bg-muted-60 py-2.5">
                              <ul className="m-0 flex list-none flex-col gap-1 p-0 pl-1 text-sm">
                                {coveredItems.map((item) => (
                                  <li key={item.item_id}>• {item.description}</li>
                                ))}
                              </ul>
                            </Td>
                          </Tr>
                        )}
                      </Fragment>
                    )
                  })}
              </Tbody>
            </Table>
          )}
        </DetailSection>

        <DetailSection title="Supplier & contacts" collapsible defaultOpen={false}>
          <div className="flex flex-col gap-4 px-5 py-[18px]">
            {supplier ? (
              <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <DetailField label="Supplier" value={supplier.supplier_name} />
                <DetailField label="Aliases" value={supplier.supplier_aliases?.join(", ") ?? null} />
                <DetailField label="Sole agent for" value={supplier.is_sole_agent_for?.join(", ") ?? null} />
              </dl>
            ) : (
              <EmptyState title="No supplier resolved" />
            )}
            {contacts.length > 0 && (
              <Table>
                <Thead>
                  <Tr>
                    <Th>Name</Th>
                    <Th>Role</Th>
                    <Th>Phone</Th>
                    <Th>Email</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {contacts.map((c) => (
                    <Tr key={c.contact_id}>
                      <Td>{c.contact_name}</Td>
                      <Td>{c.role}</Td>
                      <Td>{c.phone}</Td>
                      <Td>{c.email}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            )}
          </div>
        </DetailSection>

        {attachments.length > 0 && (
          <DetailSection title="Attachments referenced in the document" collapsible defaultOpen={false}>
            <ul className="m-0 flex list-none flex-col gap-1.5 p-5 pt-[18px] text-sm">
              {attachments.map((a) => (
                <li key={a.attachment_id}>• {a.attachment_label}</li>
              ))}
            </ul>
          </DetailSection>
        )}
      </main>

      <ConfirmDialog
        {...confirmDelete.dialogProps}
        title="Delete this offer?"
        body="This permanently deletes the offer, its documents, and its entire history - findings, activity and pipeline runs included. Its files are removed from disk too. This cannot be undone."
        confirmLabel="Delete"
        cancelLabel="Cancel"
      />
    </AppShell>
  )
}
