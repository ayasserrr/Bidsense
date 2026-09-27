import { useNavigate, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { GitCompare, Info } from "lucide-react"
import { compareOffers, type CompareOffer, type CompareTerm } from "../api/compareApi"
import { AppHeader } from "../components/layout/AppHeader"
import { AppShell } from "../components/layout/AppShell"
import { EmptyState } from "../components/ui/EmptyState"
import { Spinner } from "../components/ui/Spinner"
import { formatConvertedMoney } from "../lib/format"

function offerHeading(offer: CompareOffer): string {
  return offer.offer_ref ?? `Offer #${offer.offer_id}`
}

function TermCell({ term }: { term: CompareTerm | undefined }) {
  if (!term || (!term.stated && !term.normalized)) {
    return <span className="text-muted-foreground">Not stated</span>
  }
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-foreground">{term.stated ?? term.normalized}</span>
      {term.normalized && term.stated && term.normalized !== term.stated && (
        <span className="text-xs text-muted-foreground">Read as: {term.normalized}</span>
      )}
      {term.is_overridden && <span className="text-xs text-accent">Corrected by a reviewer</span>}
    </div>
  )
}

const ROWS: { label: string; render: (offer: CompareOffer) => React.ReactNode }[] = [
  {
    label: "Grand total",
    render: (offer) => {
      // No single offer-wide total (e.g. a "Base offer" and an "Alternative
      // offer" each independently totaled) - show each group's own total
      // instead of one blank cell. Mirrors OfferDetailPage's identical
      // fallback.
      if (offer.grand_total.original_amount === null && offer.group_totals.length > 0) {
        return (
          <div className="flex flex-col gap-2">
            {offer.group_totals.map((group, index) => {
              const money = formatConvertedMoney(group.total)
              return (
                <div key={index} className="flex flex-col gap-0.5">
                  <span className="text-xs text-muted-foreground">{group.label}</span>
                  <span className="font-semibold text-foreground">{money.original || "Not stated"}</span>
                  {money.converted && <span className="text-xs text-muted-foreground">{money.converted}</span>}
                  {money.note && <span className="text-xs text-muted-foreground">{money.note}</span>}
                </div>
              )
            })}
          </div>
        )
      }
      const money = formatConvertedMoney(offer.grand_total)
      return (
        <div className="flex flex-col gap-0.5">
          <span className="font-semibold text-foreground">{money.original || "Not stated"}</span>
          {money.converted && <span className="text-xs text-muted-foreground">{money.converted}</span>}
          {money.note && <span className="text-xs text-muted-foreground">{money.note}</span>}
        </div>
      )
    },
  },
  {
    label: "Confirmed findings",
    render: (offer) => (
      <span className={offer.confirmed_findings > 0 ? "font-semibold text-destructive" : "text-success"}>
        {offer.confirmed_findings === 0 ? "Nothing flagged" : offer.confirmed_findings}
      </span>
    ),
  },
  {
    label: "Missing mandatory terms",
    render: (offer) =>
      offer.completeness_checked ? (
        <span className={offer.mandatory_gaps ? "font-semibold text-destructive" : "text-success"}>
          {offer.mandatory_gaps ?? 0} of {offer.mandatory_terms_total}
        </span>
      ) : (
        <span className="text-muted-foreground">Never checked</span>
      ),
  },
  { label: "Incoterm", render: (offer) => <TermCell term={offer.terms.incoterm} /> },
  { label: "Delivery terms", render: (offer) => <TermCell term={offer.terms.delivery_terms} /> },
  { label: "Delivery lead time", render: (offer) => <TermCell term={offer.terms.delivery_lead_time} /> },
  { label: "Warranty", render: (offer) => <TermCell term={offer.terms.warranty} /> },
  { label: "Payment terms", render: (offer) => <TermCell term={offer.terms.payment_terms} /> },
  { label: "Price validity", render: (offer) => <TermCell term={offer.terms.validity} /> },
  { label: "Line items", render: (offer) => <span>{offer.item_count}</span> },
]

export function ComparePage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const offerIds = searchParams.getAll("offer_ids").map(Number).filter((n) => Number.isFinite(n))

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["compare", offerIds],
    queryFn: ({ signal }) => compareOffers(offerIds, signal),
    enabled: offerIds.length > 0,
  })

  return (
    <AppShell>
      <AppHeader />
      <main className="mx-auto max-w-[1200px] px-6 pb-20 pt-11">
        <div className="mb-6 flex flex-col gap-1.5">
          <div className="flex items-center gap-2 text-accent">
            <GitCompare className="h-4 w-4" aria-hidden />
            <span className="text-[11px] font-bold uppercase tracking-[0.12em]">Compare</span>
          </div>
          <h1 className="m-0 text-[27px] font-bold leading-[1.15] tracking-[-0.025em]">Compare offers</h1>
          {data && (
            <p className="m-0 text-[13.5px] text-muted-foreground">
              {data.same_rfq && data.rfq_numbers[0]
                ? `${data.rfq_numbers[0]} · ${data.offers.length} offer(s)`
                : `${data.offers.length} offer(s)`}
            </p>
          )}
        </div>

        {offerIds.length === 0 && (
          <EmptyState
            icon={<GitCompare className="h-6 w-6" aria-hidden />}
            title="Pick offers to compare"
            description="Select two or more offers from the offers list, or open a compare link from the dashboard."
            action={
              <button type="button" onClick={() => navigate("/offers")} className="text-sm font-semibold text-accent">
                Go to offers
              </button>
            }
          />
        )}

        {isLoading && offerIds.length > 0 && (
          <div className="flex justify-center py-16">
            <Spinner label="Comparing offers..." />
          </div>
        )}

        {isError && (
          <p className="text-sm text-destructive">
            {error instanceof Error ? error.message : "Could not compare these offers."}
          </p>
        )}

        {data && (
          <div className="flex flex-col gap-4">
            {data.notes.map((note, index) => (
              <div
                key={index}
                className="flex items-start gap-2 rounded-[10px] border border-border bg-muted px-3.5 py-2.5 text-[12.5px] text-muted-foreground"
              >
                <Info className="mt-0.5 h-3.5 w-3.5 flex-none" aria-hidden />
                <span>{note}</span>
              </div>
            ))}

            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[720px] border-collapse text-[13px]">
                <thead>
                  <tr className="bg-accent-5">
                    <th className="w-[180px] px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Comparing
                    </th>
                    {data.offers.map((offer) => (
                      <th key={offer.offer_id} className="min-w-[200px] px-4 py-2.5 text-left">
                        <button
                          type="button"
                          onClick={() => navigate(`/offers/${offer.offer_id}`)}
                          className="text-[13.5px] font-bold text-foreground hover:text-accent"
                        >
                          {offerHeading(offer)}
                        </button>
                        <div className="text-xs font-normal text-muted-foreground">
                          {offer.supplier_name ?? "Unknown supplier"}
                          {!offer.is_active_latest && " · superseded"}
                          {offer.archived && " · archived"}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {ROWS.map((row) => (
                    <tr key={row.label}>
                      <td className="px-4 py-3 align-top text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {row.label}
                      </td>
                      {data.offers.map((offer) => (
                        <td key={offer.offer_id} className="px-4 py-3 align-top">
                          {row.render(offer)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </AppShell>
  )
}
