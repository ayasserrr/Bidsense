import { useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  Check,
  FileUp,
  HelpCircle,
  ListChecks,
  MinusCircle,
  Paperclip,
  RefreshCw,
} from "lucide-react"
import {
  clearOverride,
  evidenceDownloadUrl,
  getCompleteness,
  recheckCompleteness,
  saveOverride,
  uploadEvidence,
  type CompletenessResult,
  type CompletenessVerdict,
} from "../../api/completenessApi"
import { Badge, type BadgeTone } from "../ui/Badge"
import { DetailSection } from "./DetailSection"
import { EmptyState } from "../ui/EmptyState"
import { ErrorBanner } from "../ui/ErrorBanner"
import { Pill } from "../ui/Pill"
import { Spinner } from "../ui/Spinner"
import { StatCard } from "../ui/StatCard"
import { cn } from "../../lib/cn"

const VERDICT_LABEL: Record<CompletenessVerdict, string> = {
  present: "Stated",
  missing: "Not stated",
  unclear: "Unclear",
  not_applicable: "N/A",
}

const VERDICT_TONE: Record<CompletenessVerdict, BadgeTone> = {
  present: "success",
  missing: "critical",
  unclear: "warning",
  not_applicable: "neutral",
}

function VerdictIcon({ verdict }: { verdict: CompletenessVerdict }) {
  const className = "h-3.5 w-3.5"
  if (verdict === "present") return <Check className={className} aria-hidden />
  if (verdict === "missing") return <AlertTriangle className={className} aria-hidden />
  if (verdict === "unclear") return <HelpCircle className={className} aria-hidden />
  return <MinusCircle className={className} aria-hidden />
}

interface OverrideDraft {
  verdict: CompletenessVerdict
  value: string
  note: string
  file: File | null
}

/** What the offer says, and - the point of this whole feature - what it does not.
 *
 * Two things in here are load-bearing rather than decorative:
 *
 *  - A row's source is shown as a real filename and page because the backend
 *    resolved it by finding the quote in the merged source text. When it could
 *    not be located, the row says nothing about where it came from instead of
 *    showing a filename the model guessed at.
 *  - An override is visibly an override, in brand colour with the reviewer's
 *    evidence attached. A corrected verdict must never be mistakable for
 *    something the supplier actually wrote.
 */
export function CompletenessSection({ offerId }: { offerId: number }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState<OverrideDraft | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const queryKey = ["completeness", offerId]
  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () => getCompleteness(offerId),
  })

  const recheck = useMutation({
    mutationFn: () => recheckCompleteness(offerId),
    onSuccess: () => {
      setActionError(null)
      // The re-check is a background job; give it a moment, then refetch. The
      // offer is already saved either way, so there is nothing at risk here.
      setTimeout(() => void queryClient.invalidateQueries({ queryKey }), 4_000)
    },
    onError: (err: Error) => setActionError(err.message),
  })

  const submitOverride = useMutation({
    mutationFn: async ({ code, override }: { code: string; override: OverrideDraft }) => {
      if (!override.file) throw new Error("Attach the email or document this comes from first.")
      // Evidence first, then the override that points at it. The server and the
      // database both refuse an override without one, so there is no path that
      // records a correction with nothing behind it.
      const evidence = await uploadEvidence(offerId, code, "email", override.file)
      return saveOverride(offerId, code, {
        verdict: override.verdict,
        value: override.value || undefined,
        note: override.note || undefined,
        evidence_id: evidence.evidence_id,
      })
    },
    onSuccess: () => {
      setEditing(null)
      setDraft(null)
      setActionError(null)
      void queryClient.invalidateQueries({ queryKey })
    },
    onError: (err: Error) => setActionError(err.message),
  })

  const removeOverride = useMutation({
    mutationFn: (code: string) => clearOverride(offerId, code),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey }),
    onError: (err: Error) => setActionError(err.message),
  })

  if (isLoading) {
    return (
      <DetailSection title="Completeness check">
        <div className="grid place-items-center py-10">
          <Spinner />
        </div>
      </DetailSection>
    )
  }

  if (error || !data) {
    return (
      <DetailSection title="Completeness check">
        <div className="px-5 py-4">
          <ErrorBanner>{(error as Error)?.message ?? "Could not load the completeness check."}</ErrorBanner>
        </div>
      </DetailSection>
    )
  }

  if (data.results.length === 0) {
    return (
      <DetailSection
        title="Completeness check"
        aside={
          <Pill icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => recheck.mutate()}>
            Run the check
          </Pill>
        }
      >
        <EmptyState
          icon={<ListChecks className="h-5 w-5" aria-hidden />}
          title="Not checked yet"
          description="Running the check reads every uploaded file and reports anything the supplier did not state."
        />
      </DetailSection>
    )
  }

  const { summary, results } = data
  const commercial = results.filter((r) => r.requirement_group === "commercial")
  const technical = results.filter((r) => r.requirement_group === "technical")

  const startEditing = (result: CompletenessResult) => {
    setEditing(result.requirement_code)
    setActionError(null)
    setDraft({
      verdict: result.is_overridden ? (result.override_verdict ?? "present") : "present",
      value: result.override_value ?? result.extracted_value ?? "",
      note: result.override_note ?? "",
      file: null,
    })
  }

  const renderRow = (result: CompletenessResult) => {
    const verdict = result.effective_verdict
    const isEditing = editing === result.requirement_code
    const gap =
      result.was_mandatory && (verdict === "missing" || verdict === "unclear")

    return (
      <li
        key={result.requirement_code}
        className={cn(
          "flex flex-col gap-2 border-b border-border px-5 py-3.5 last:border-b-0",
          gap && "bg-destructive-10/40",
        )}
      >
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold">{result.requirement_label}</span>
              <Badge tone={VERDICT_TONE[verdict]}>
                <VerdictIcon verdict={verdict} />
                {VERDICT_LABEL[verdict]}
              </Badge>
              {/* "brand", not "info": info and neutral render identically grey
                  in this theme, and a reviewer's correction has to be visually
                  distinct from what the supplier stated. */}
              {result.is_overridden && <Badge tone="brand">Corrected by a reviewer</Badge>}
            </div>

            {result.effective_value && (
              <span className="text-[13.5px] leading-snug text-foreground">{result.effective_value}</span>
            )}

            {result.evidence_quote && (
              <blockquote className="m-0 border-l-2 border-border pl-2.5 text-[12.5px] italic leading-snug text-muted-foreground">
                &ldquo;{result.evidence_quote}&rdquo;
              </blockquote>
            )}

            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
              {result.source_filename ? (
                <span>
                  Found in <span className="font-medium text-foreground">{result.source_filename}</span>
                  {result.source_page_number !== null && `, page ${result.source_page_number}`}
                </span>
              ) : (
                result.evidence_quote && <span>Source file could not be pinpointed</span>
              )}
              {result.override_evidence_id && result.override_evidence_filename && (
                <a
                  className="inline-flex items-center gap-1 text-accent underline-offset-2 hover:underline"
                  href={evidenceDownloadUrl(offerId, result.override_evidence_id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Paperclip className="h-3 w-3" aria-hidden />
                  {result.override_evidence_filename}
                </a>
              )}
              {result.reasoning && <span className="italic">{result.reasoning}</span>}
            </div>
          </div>

          <div className="flex flex-none gap-1.5">
            <Pill onClick={() => (isEditing ? setEditing(null) : startEditing(result))}>
              {isEditing ? "Cancel" : result.is_overridden ? "Change" : "Correct this"}
            </Pill>
            {result.is_overridden && (
              <Pill onClick={() => removeOverride.mutate(result.requirement_code)}>Undo</Pill>
            )}
          </div>
        </div>

        {isEditing && draft && (
          <div className="flex flex-col gap-2.5 rounded-[10px] border border-border bg-muted-60 px-3.5 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] font-extrabold uppercase tracking-[0.08em]">Verdict</span>
              {(["present", "missing", "unclear", "not_applicable"] as CompletenessVerdict[]).map(
                (option) => (
                  <Pill
                    key={option}
                    active={draft.verdict === option}
                    onClick={() => setDraft({ ...draft, verdict: option })}
                  >
                    {VERDICT_LABEL[option]}
                  </Pill>
                ),
              )}
            </div>

            <input
              className="h-9 rounded-[8px] border border-border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent-40"
              placeholder="What the supplier actually confirmed (e.g. '24 months from commissioning')"
              value={draft.value}
              onChange={(event) => setDraft({ ...draft, value: event.target.value })}
            />
            <input
              className="h-9 rounded-[8px] border border-border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent-40"
              placeholder="Note for whoever reads this later (optional)"
              value={draft.note}
              onChange={(event) => setDraft({ ...draft, note: event.target.value })}
            />

            <div className="flex flex-wrap items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                accept=".eml,.msg,.pdf,.png,.jpg,.jpeg,.txt,.doc,.docx"
                onChange={(event) =>
                  setDraft({ ...draft, file: event.target.files?.[0] ?? null })
                }
              />
              <Pill
                icon={<FileUp className="h-3.5 w-3.5" />}
                onClick={() => fileInputRef.current?.click()}
              >
                {draft.file ? draft.file.name : "Attach the email or document"}
              </Pill>
              <span className="text-[12px] text-muted-foreground">
                Required - a correction has to point at something written down.
              </span>
            </div>

            <div className="flex gap-2">
              <Pill
                active
                disabled={!draft.file || submitOverride.isPending}
                onClick={() =>
                  submitOverride.mutate({ code: result.requirement_code, override: draft })
                }
              >
                {submitOverride.isPending ? "Saving..." : "Save correction"}
              </Pill>
            </div>
          </div>
        )}
      </li>
    )
  }

  return (
    <DetailSection
      title="Completeness check"
      description={
        data.checked_at
          ? `Checked against ${summary.total} requirements across every uploaded file`
          : undefined
      }
      collapsible
      defaultOpen={false}
      aside={
        <Pill
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          onClick={() => recheck.mutate()}
          disabled={recheck.isPending}
        >
          {recheck.isPending ? "Starting..." : "Check again"}
        </Pill>
      }
    >
      <div className="grid grid-cols-2 gap-3 px-5 py-[18px] sm:grid-cols-4">
        <StatCard
          icon={<AlertTriangle className="h-4 w-4" aria-hidden />}
          label="Missing or unclear"
          value={String(summary.mandatory_gaps)}
          tone={summary.mandatory_gaps > 0 ? "danger" : "default"}
          sub="Required terms to chase"
        />
        <StatCard
          icon={<Check className="h-4 w-4" aria-hidden />}
          label="Stated"
          value={String(summary.present)}
        />
        <StatCard
          icon={<MinusCircle className="h-4 w-4" aria-hidden />}
          label="Not applicable"
          value={String(summary.not_applicable)}
        />
        <StatCard
          icon={<Paperclip className="h-4 w-4" aria-hidden />}
          label="Corrected"
          value={String(summary.overridden)}
          sub={summary.overridden > 0 ? "With attached evidence" : undefined}
        />
      </div>

      {actionError && (
        <div className="px-5 pb-3">
          <ErrorBanner>{actionError}</ErrorBanner>
        </div>
      )}

      <div className="border-t border-border px-5 py-2.5 text-[11px] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">
        Commercial terms
      </div>
      <ul className="m-0 list-none p-0">{commercial.map(renderRow)}</ul>

      <div className="border-t border-border px-5 py-2.5 text-[11px] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">
        Technical disciplines
      </div>
      <ul className="m-0 list-none p-0">{technical.map(renderRow)}</ul>
    </DetailSection>
  )
}
