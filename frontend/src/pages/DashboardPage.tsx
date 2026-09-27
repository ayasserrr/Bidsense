import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, CheckCircle2, Clock, Folder, GitCompare, Layers } from "lucide-react"
import { getDashboard, type AttentionOffer, type CompareReadyRfq } from "../api/dashboardApi"
import { getQueue } from "../api/queueApi"
import { AppHeader } from "../components/layout/AppHeader"
import { AppShell } from "../components/layout/AppShell"
import { Badge } from "../components/ui/Badge"
import { Spinner } from "../components/ui/Spinner"
import { formatDecimalString } from "../lib/format"
import { formatDuration } from "../hooks/useElapsedSeconds"
import { missingTermsLabel } from "../lib/completeness"

function Kpi({
  icon,
  value,
  label,
  sub,
  tone = "plain",
}: {
  icon: React.ReactNode
  value: string
  label: string
  sub: string
  tone?: "plain" | "warn"
}) {
  return (
    <div
      className={
        tone === "warn"
          ? "flex flex-col gap-2 rounded-[14px] border border-destructive-30 bg-destructive-5 p-4"
          : "flex flex-col gap-2 rounded-[14px] border border-border bg-card p-4"
      }
    >
      <span
        className={
          tone === "warn"
            ? "grid h-8 w-8 place-items-center rounded-lg bg-destructive-10 text-destructive"
            : "grid h-8 w-8 place-items-center rounded-lg bg-muted text-muted-foreground"
        }
      >
        {icon}
      </span>
      <span className="tabular text-[26px] font-extrabold leading-none">{value}</span>
      <div className="flex flex-col gap-0.5">
        <span className="text-[12.5px] font-medium text-foreground">{label}</span>
        <span className="text-[11px] text-muted-foreground">{sub}</span>
      </div>
    </div>
  )
}

function attentionChip(offer: AttentionOffer) {
  if (offer.confirmed_findings > 0) {
    return (
      <Badge tone="critical">
        {offer.confirmed_findings} {offer.confirmed_findings === 1 ? "finding" : "findings"}
      </Badge>
    )
  }
  const label = missingTermsLabel(offer.mandatory_gaps)
  if (label) return <Badge tone="critical">{label}</Badge>
  return <Badge tone="neutral">Ready</Badge>
}

export function DashboardPage() {
  const navigate = useNavigate()

  const { data, isLoading, isError } = useQuery({
    queryKey: ["dashboard"],
    queryFn: ({ signal }) => getDashboard(signal),
  })
  // Same cache entry the header/rail/queue screen share - opening the
  // dashboard costs nothing extra here.
  const { data: queue } = useQuery({ queryKey: ["queue"], queryFn: ({ signal }) => getQueue(signal) })

  return (
    <AppShell>
      <AppHeader />
      <main className="mx-auto max-w-[1200px] px-6 pb-20 pt-11">
        <div className="mb-6 flex flex-col gap-1.5">
          <h1 className="m-0 text-[27px] font-bold leading-[1.15] tracking-[-0.025em]">Dashboard</h1>
          <p className="m-0 text-[13.5px] text-muted-foreground">Where every offer stands this week</p>
        </div>

        {isLoading && (
          <div className="flex justify-center py-16">
            <Spinner label="Loading the dashboard..." />
          </div>
        )}
        {isError && <p className="text-sm text-destructive">Could not load the dashboard.</p>}

        {data && (
          <div className="flex flex-col gap-6">
            <div className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-3">
              <Kpi
                icon={<Folder className="h-4 w-4" aria-hidden />}
                value={String(data.offers_in_review.count)}
                label="Offers in review"
                sub={
                  data.offers_in_review.waiting_longer_than_stale_days > 0
                    ? `${data.offers_in_review.waiting_longer_than_stale_days} over ${data.offers_in_review.stale_days} days old`
                    : `${data.offers_in_review.added_last_7_days} added this week`
                }
              />
              <Kpi
                icon={<AlertTriangle className="h-4 w-4" aria-hidden />}
                value={String(data.terms_to_chase.mandatory_gaps)}
                label="Terms to chase"
                sub={`Across ${data.terms_to_chase.offers_with_gaps} live offer(s)`}
                tone={data.terms_to_chase.mandatory_gaps > 0 ? "warn" : "plain"}
              />
              <Kpi
                icon={<Clock className="h-4 w-4" aria-hidden />}
                value={data.average_read_time.seconds !== null ? formatDuration(Math.round(data.average_read_time.seconds)) : "—"}
                label="Average read time"
                sub={
                  data.average_read_time.sample_size > 0
                    ? `Last ${data.average_read_time.sample_size} read(s)`
                    : "No finished reads yet"
                }
              />
              <Kpi
                icon={<CheckCircle2 className="h-4 w-4" aria-hidden />}
                value={
                  data.money.live_offers.converted_total !== null
                    ? `${formatDecimalString(data.money.live_offers.converted_total)} ${data.base_currency}`
                    : "—"
                }
                label="Value of live offers"
                sub={
                  data.money.live_offers.is_complete
                    ? "Every currency converted"
                    : `${data.money.live_offers.unconvertible_currencies.join(", ")} has no rate on file`
                }
              />
            </div>

            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,420px),1fr))] items-start gap-3">
              <div className="rounded-[14px] border border-border bg-card">
                <div className="flex items-center justify-between gap-2 rounded-t-[14px] bg-accent-5 px-4 py-2.5">
                  <span className="flex items-center gap-2 text-[13px] font-semibold">
                    <span className="h-[7px] w-[7px] rounded-sm bg-accent" />
                    Processing now
                  </span>
                  <button type="button" onClick={() => navigate("/queue")} className="text-xs font-semibold text-accent">
                    Open the queue
                  </button>
                </div>
                <div className="flex flex-col gap-2 p-4">
                  {queue && queue.running.length === 0 && queue.waiting.length === 0 ? (
                    <p className="m-0 text-sm text-muted-foreground">Nothing is reading right now.</p>
                  ) : (
                    <>
                      <p className="m-0 text-[13px] text-muted-foreground">
                        {data.reading_now.running} reading, {data.reading_now.waiting} waiting
                      </p>
                      {queue?.waiting.slice(0, 3).map((job) => (
                        <div key={job.job_id} className="flex items-center gap-2.5 text-[12.5px]">
                          <span className="grid h-[22px] w-[22px] flex-none place-items-center rounded-full bg-muted text-[11px] font-bold text-muted-foreground">
                            {job.queue_position}
                          </span>
                          <span className="min-w-0 flex-1 truncate">
                            {job.project_name ?? job.offer_ref ?? `Offer #${job.offer_id}`}
                          </span>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              </div>

              <div className="rounded-[14px] border border-border bg-card">
                <div className="flex items-center justify-between gap-2 px-4 py-2.5">
                  <span className="text-[13px] font-semibold">Needs your attention</span>
                  <span className="text-xs text-muted-foreground">{data.needs_attention.offers_total} offer(s)</span>
                </div>
                <div className="flex flex-col divide-y divide-border">
                  {data.needs_attention.offers.length === 0 && data.needs_attention.compare_ready.length === 0 && (
                    <p className="m-0 px-4 pb-4 text-sm text-muted-foreground">Nothing needs a second look right now.</p>
                  )}
                  {data.needs_attention.compare_ready.map((rfq: CompareReadyRfq) => (
                    <button
                      key={rfq.rfq_number}
                      type="button"
                      onClick={() => navigate(`/compare?${rfq.offer_ids.map((id) => `offer_ids=${id}`).join("&")}`)}
                      className="flex items-center gap-3 px-4 py-2.5 text-left transition hover:bg-muted"
                    >
                      <span className="grid h-[34px] w-[34px] flex-none place-items-center rounded-lg bg-accent-10 text-accent">
                        <GitCompare className="h-4 w-4" aria-hidden />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-semibold">
                          {rfq.rfq_number} · {rfq.offer_count} offers ready
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {rfq.supplier_names.join(", ")} — nothing compared yet
                        </span>
                      </span>
                      <Badge tone="brand">Compare</Badge>
                    </button>
                  ))}
                  {data.needs_attention.offers.map((offer) => (
                    <button
                      key={offer.offer_id}
                      type="button"
                      onClick={() => navigate(`/offers/${offer.offer_id}`)}
                      className="flex items-center gap-3 px-4 py-2.5 text-left transition hover:bg-muted"
                    >
                      <span className="grid h-[34px] w-[34px] flex-none place-items-center rounded-lg bg-destructive-10 text-destructive">
                        <AlertTriangle className="h-4 w-4" aria-hidden />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-semibold">
                          {offer.offer_ref ?? `Offer #${offer.offer_id}`} · {offer.supplier_name ?? "Unknown supplier"}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {offer.project_name ?? "No project name yet"}
                        </span>
                      </span>
                      {attentionChip(offer)}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="rounded-[14px] border border-border bg-card p-4">
              <h2 className="m-0 mb-3 text-[13px] font-bold uppercase tracking-wide text-muted-foreground">
                Activity
              </h2>
              {data.activity.length === 0 ? (
                <p className="m-0 text-sm text-muted-foreground">Nothing has happened yet.</p>
              ) : (
                <div className="relative flex flex-col gap-4 pl-1">
                  {data.activity.map((event, index) => (
                    <div key={event.event_id} className="relative flex items-start gap-3 pl-7">
                      {index < data.activity.length - 1 && (
                        <span className="absolute left-[11px] top-[22px] bottom-[-16px] w-px bg-border" />
                      )}
                      <span className="absolute left-0 top-0 grid h-6 w-6 place-items-center rounded-full border-2 border-border bg-card">
                        <Layers className="h-3 w-3 text-muted-foreground" aria-hidden />
                      </span>
                      <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-1.5 text-[13px]">
                        <span className="font-semibold">{event.actor_display_name || "Bidsense"}</span>
                        <span className="text-muted-foreground">{event.detail}</span>
                        <span className="ml-auto whitespace-nowrap text-xs text-muted-foreground">
                          {new Date(event.created_at).toLocaleString([], {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </AppShell>
  )
}
