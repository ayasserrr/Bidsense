import { useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, CheckCircle2, HelpCircle, Mail, RefreshCw } from "lucide-react"
import {
  getReviewSummary,
  recheckReviewSummary,
  type ChaseItem,
  type ChaseItemKind,
} from "../../api/reviewSummaryApi"
import { DetailSection } from "./DetailSection"
import { EmailDraftModal } from "./EmailDraftModal"
import { ErrorBanner } from "../ui/ErrorBanner"
import { Pill } from "../ui/Pill"
import { Spinner } from "../ui/Spinner"
import { formatDate } from "../../lib/format"

// Two sources, shown differently so a reader can tell them apart at a
// glance - NOT two severities. Both kinds are equally "things to chase";
// there is no critical/minor split in this data and none is invented here.
const KIND_ICON: Record<ChaseItemKind, typeof AlertCircle> = {
  confirmed_finding: AlertCircle,
  mandatory_gap: HelpCircle,
}

const KIND_LABEL: Record<ChaseItemKind, string> = {
  confirmed_finding: "Finding",
  mandatory_gap: "Gap",
}

function chaseItemSource(item: ChaseItem): string | null {
  if (!item.source_filename) return null
  return item.source_page_number !== null
    ? `${item.source_filename}, page ${item.source_page_number}`
    : item.source_filename
}

function ChaseItemRow({ item }: { item: ChaseItem }) {
  const Icon = KIND_ICON[item.kind]
  const source = chaseItemSource(item)
  return (
    <li className="flex gap-3 border-b border-border px-5 py-3.5 last:border-b-0">
      <span className="mt-0.5 grid h-7 w-7 flex-none place-items-center rounded-full bg-muted text-muted-foreground">
        <Icon className="h-3.5 w-3.5" aria-hidden />
      </span>
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold">{item.title}</span>
          <span className="text-[10.5px] font-bold uppercase tracking-[0.06em] text-muted-foreground">
            {KIND_LABEL[item.kind]}
          </span>
        </div>
        <p className="m-0 text-[13.5px] leading-snug text-foreground">{item.detail}</p>
        {source && <span className="text-[12px] text-muted-foreground">{source}</span>}
      </div>
    </li>
  )
}

/** The detail screen's "read this first" panel: what this offer's own
 * pipeline has already confirmed is worth chasing, plus a ready clarification
 * email. Composed server-side from already-verified findings and
 * completeness gaps - never a fresh LLM paragraph, never a "money at risk"
 * figure or a ranking. See the backend's `schema/review_summary.py` module
 * docstring for why both are deliberately left out. */
export function ReviewSummarySection({ offerId }: { offerId: number }) {
  const queryClient = useQueryClient()
  const [emailOpen, setEmailOpen] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const emailButtonRef = useRef<HTMLButtonElement>(null)
  const queryKey = ["review-summary", offerId]

  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () => getReviewSummary(offerId),
  })

  const recheck = useMutation({
    mutationFn: () => recheckReviewSummary(offerId),
    // Same pattern as CompletenessSection's recheck: this is a fast,
    // single-stage background job, not something worth a real poll for - give
    // it a moment, then refetch.
    onSuccess: () => {
      setActionError(null)
      setTimeout(() => void queryClient.invalidateQueries({ queryKey }), 4_000)
    },
    onError: (err: Error) => setActionError(err.message),
  })

  function closeEmail() {
    setEmailOpen(false)
    emailButtonRef.current?.focus()
  }

  const aside = (
    <Pill
      icon={<RefreshCw className="h-3.5 w-3.5" />}
      onClick={() => recheck.mutate()}
      disabled={recheck.isPending}
    >
      {recheck.isPending ? "Starting..." : "Regenerate"}
    </Pill>
  )

  if (isLoading) {
    return (
      <DetailSection title="Summary" aside={aside}>
        <div data-tour="summary" className="grid place-items-center py-10">
          <Spinner />
        </div>
      </DetailSection>
    )
  }

  if (error || !data) {
    return (
      <DetailSection title="Summary" aside={aside}>
        <div data-tour="summary" className="px-5 py-4">
          <ErrorBanner>{(error as Error)?.message ?? "Could not load the summary."}</ErrorBanner>
        </div>
      </DetailSection>
    )
  }

  const hasChaseItems = data.chase_items.length > 0
  // Not generated yet and "generated, verified clear" both have zero chase
  // items - without generated_at they render identically apart from a
  // subtitle that's easy to miss, so a reviewer could mistake "never
  // checked" for "checked and clear". generated_at is what actually tells
  // them apart.
  const neverGenerated = data.generated_at === null

  return (
    <DetailSection
      title="Summary"
      description={data.generated_at ? `Generated ${formatDate(data.generated_at)}` : undefined}
      collapsible
      aside={aside}
    >
      <div data-tour="summary">
        {actionError && (
          <div className="px-5 pt-4">
            <ErrorBanner>{actionError}</ErrorBanner>
          </div>
        )}
        <div className="flex items-start gap-2.5 px-5 py-4">
          {/* No icon at all when there is something to chase - the row below
              already carries its own icon per item; a checkmark is only
              meaningful for a genuinely checked-and-clear offer, and a plain
              HelpCircle marks one that was never checked - see neverGenerated
              above. */}
          {!hasChaseItems && !neverGenerated && (
            <CheckCircle2 className="mt-0.5 h-4 w-4 flex-none text-success" aria-hidden />
          )}
          {!hasChaseItems && neverGenerated && (
            <HelpCircle className="mt-0.5 h-4 w-4 flex-none text-muted-foreground" aria-hidden />
          )}
          {/* The backend's own headline already says "Nothing to chase..."
              or "not generated yet" - that IS the empty state, not a copy
              this component invents on top of it. */}
          <p className="m-0 text-[15px] font-semibold leading-snug">{data.headline}</p>
        </div>

        {hasChaseItems && (
          <ul className="m-0 list-none border-t border-border p-0">
            {data.chase_items.map((item, index) => (
              <ChaseItemRow key={`${item.kind}-${item.title}-${index}`} item={item} />
            ))}
          </ul>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-5 py-3.5">
          <span className="text-[12px] text-muted-foreground">
            {hasChaseItems
              ? `${data.chase_items.length} ${data.chase_items.length === 1 ? "thing" : "things"} to resolve`
              : null}
          </span>
          <Pill
            ref={emailButtonRef}
            icon={<Mail className="h-3.5 w-3.5" />}
            onClick={() => setEmailOpen(true)}
            disabled={!hasChaseItems}
            title={!hasChaseItems ? "There is nothing to draft a clarification email about yet" : undefined}
          >
            Draft the clarification email
          </Pill>
        </div>
      </div>

      <EmailDraftModal
        open={emailOpen}
        emailTo={data.email_to}
        emailSubject={data.email_subject}
        emailBody={data.email_body}
        onClose={closeEmail}
      />
    </DetailSection>
  )
}
