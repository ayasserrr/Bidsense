import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, Layers, Pause, Play, Plus, X } from "lucide-react"
import { cancelJob } from "../api/jobApi"
import { getQueue, moveJobInQueue, pauseQueue, resumeQueue, setQueueSlots, type QueueJob, type QueueState } from "../api/queueApi"
import { AppHeader } from "../components/layout/AppHeader"
import { AppShell } from "../components/layout/AppShell"
import { ProgressBar } from "../components/progress/ProgressBar"
import { StepList } from "../components/progress/StepList"
import { Badge } from "../components/ui/Badge"
import { EmptyState } from "../components/ui/EmptyState"
import { Pill } from "../components/ui/Pill"
import { Spinner } from "../components/ui/Spinner"
import { formatDuration } from "../hooks/useElapsedSeconds"

function seconds(n: number | null): string {
  if (n === null) return ""
  if (n <= 0) return "any moment now"
  return `~${formatDuration(n)}`
}

function jobLabel(job: QueueJob): string {
  return job.project_name ?? job.offer_ref ?? `Offer #${job.offer_id ?? "?"}`
}

function jobMeta(job: QueueJob): string {
  const parts: string[] = []
  if (job.rfq_number) parts.push(job.rfq_number)
  parts.push(job.file_count === 1 ? "1 file" : `${job.file_count} file(s)`)
  if (job.page_count > 0) parts.push(`${job.page_count} pages`)
  if (job.created_by_display_name) parts.push(`queued by ${job.created_by_display_name}`)
  return parts.join(" · ")
}

function RunningCard({ job, onCancel, cancelling }: { job: QueueJob; onCancel: () => void; cancelling: boolean }) {
  const activeStage = job.stages.find((s) => s.status === "active")
  return (
    <div className="flex flex-col gap-3 rounded-[14px] border border-accent-25 bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate text-[15px] font-bold">{jobLabel(job)}</span>
          <span className="truncate text-xs text-muted-foreground">{jobMeta(job)}</span>
        </div>
        <div className="flex flex-none items-center gap-2">
          {job.elapsed_seconds !== null && (
            <Badge tone="brand">{formatDuration(job.elapsed_seconds)} elapsed</Badge>
          )}
          <Pill icon={<X className="h-3.5 w-3.5" aria-hidden />} onClick={onCancel} disabled={cancelling}>
            Stop
          </Pill>
        </div>
      </div>
      <ProgressBar percent={job.progress_percent} tone="running" label={activeStage?.label} />
      <div className="-mx-1.5">
        <StepList stages={job.stages} />
      </div>
    </div>
  )
}

function WaitingRow({
  job,
  index,
  total,
  onMove,
  onCancel,
  busy,
}: {
  job: QueueJob
  index: number
  total: number
  onMove: (delta: 1 | -1) => void
  onCancel: () => void
  busy: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-[10px] border border-border bg-card px-3.5 py-2.5">
      <span className="grid h-[26px] w-[26px] flex-none place-items-center rounded-full bg-muted text-[12px] font-bold text-muted-foreground">
        {job.queue_position ?? index + 1}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-[13.5px] font-semibold">{jobLabel(job)}</span>
        <span className="truncate text-xs text-muted-foreground">{jobMeta(job)}</span>
      </div>
      <div className="flex flex-none flex-col items-end gap-0.5">
        <span className="tabular text-[12.5px] font-medium text-foreground">
          {seconds(job.estimated_start_seconds)}
        </span>
        <span className="text-[10.5px] uppercase tracking-wide text-muted-foreground">estimated wait</span>
      </div>
      <div className="flex flex-none items-center gap-1">
        <button
          type="button"
          aria-label="Move up"
          disabled={busy || index === 0}
          onClick={() => onMove(-1)}
          className="grid h-7 w-7 place-items-center rounded-md border border-border text-muted-foreground transition hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30"
        >
          <ArrowUp className="h-3.5 w-3.5" aria-hidden />
        </button>
        <button
          type="button"
          aria-label="Move down"
          disabled={busy || index === total - 1}
          onClick={() => onMove(1)}
          className="grid h-7 w-7 place-items-center rounded-md border border-border text-muted-foreground transition hover:text-foreground disabled:cursor-not-allowed disabled:opacity-30"
        >
          <ArrowDown className="h-3.5 w-3.5" aria-hidden />
        </button>
        <Pill icon={<X className="h-3.5 w-3.5" aria-hidden />} onClick={onCancel} disabled={busy}>
          Cancel
        </Pill>
      </div>
    </div>
  )
}

export function QueuePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  // A Set, not a single id - found by review: a scalar shared between move
  // AND cancel meant starting a second job's action while the first's request
  // was still in flight overwrote the only record of it, so the first row's
  // buttons re-enabled while its request was still outstanding (and a second
  // action on it could still fire, computed from the same stale position).
  const [pendingJobIds, setPendingJobIds] = useState<Set<string>>(new Set())

  function markPending(jobId: string) {
    setPendingJobIds((prev) => new Set(prev).add(jobId))
  }

  function clearPending(jobId: string) {
    setPendingJobIds((prev) => {
      if (!prev.has(jobId)) return prev
      const next = new Set(prev)
      next.delete(jobId)
      return next
    })
  }

  const { data: queue, isLoading, isError } = useQuery({
    queryKey: ["queue"],
    queryFn: ({ signal }) => getQueue(signal),
    // Faster than the header/rail's own poll while this screen is the one
    // being watched - both intervals share the same cache entry, so opening
    // this page also sharpens up the header pill and the rail badge.
    refetchInterval: 4_000,
  })

  function apply(next: QueueState) {
    queryClient.setQueryData(["queue"], next)
  }

  const pauseMutation = useMutation({ mutationFn: pauseQueue, onSuccess: apply })
  const resumeMutation = useMutation({ mutationFn: resumeQueue, onSuccess: apply })
  const slotsMutation = useMutation({ mutationFn: setQueueSlots, onSuccess: apply })

  const moveMutation = useMutation({
    mutationFn: ({ jobId, position }: { jobId: string; position: number }) => moveJobInQueue(jobId, position),
    onMutate: ({ jobId }) => markPending(jobId),
    onSuccess: apply,
    onSettled: (_data, _error, { jobId }) => clearPending(jobId),
  })

  const cancelMutation = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onMutate: (jobId) => markPending(jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue"] }),
    onSettled: (_data, _error, jobId) => clearPending(jobId),
  })

  function move(job: QueueJob, delta: 1 | -1) {
    const current = job.queue_position ?? 1
    const target = current + delta
    if (target < 1) return
    moveMutation.mutate({ jobId: job.job_id, position: target })
  }

  return (
    <AppShell>
      <AppHeader />
      <main className="mx-auto max-w-[1060px] px-6 pb-20 pt-11">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2 text-accent">
              <Layers className="h-4 w-4" aria-hidden />
              <span className="text-[11px] font-bold uppercase tracking-[0.12em]">Queue</span>
            </div>
            <h1 className="m-0 text-[27px] font-bold leading-[1.15] tracking-[-0.025em]">
              One offer reads at a time
            </h1>
            <p className="m-0 text-[13.5px] text-muted-foreground">
              The rest wait in order - move a row or cancel it whenever you like.
            </p>
          </div>
          <div className="w-[180px]">
            <button
              type="button"
              onClick={() => navigate("/upload")}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-[10px] bg-accent text-sm font-semibold text-accent-foreground shadow-glow transition hover:opacity-90"
            >
              <Plus className="h-4 w-4" aria-hidden />
              New check
            </button>
          </div>
        </div>

        {isLoading && (
          <div className="flex justify-center py-16">
            <Spinner label="Loading the queue..." />
          </div>
        )}
        {isError && <p className="text-sm text-destructive">Could not load the queue.</p>}

        {queue && (
          <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-[12px] border border-border bg-card px-4 py-3">
              <div className="flex flex-wrap items-center gap-3">
                <Pill
                  icon={
                    queue.is_paused ? (
                      <Play className="h-3.5 w-3.5" aria-hidden />
                    ) : (
                      <Pause className="h-3.5 w-3.5" aria-hidden />
                    )
                  }
                  active={queue.is_paused}
                  disabled={pauseMutation.isPending || resumeMutation.isPending}
                  onClick={() => (queue.is_paused ? resumeMutation.mutate() : pauseMutation.mutate())}
                >
                  {queue.is_paused ? "Resume the queue" : "Pause the queue"}
                </Pill>
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span>Reading at once:</span>
                  {[1, 2, 3].map((n) => (
                    <button
                      key={n}
                      type="button"
                      disabled={slotsMutation.isPending}
                      onClick={() => slotsMutation.mutate(n)}
                      className={`grid h-6 w-6 place-items-center rounded-md border text-[11px] font-semibold transition ${
                        queue.parallel_slots === n
                          ? "border-accent-30 bg-accent-10 text-accent"
                          : "border-border text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {n}
                    </button>
                  ))}
                  {queue.slots < queue.parallel_slots && (
                    <span title={`This deployment's own ceiling is ${queue.slot_ceiling}.`}>
                      (capped at {queue.slots})
                    </span>
                  )}
                </div>
              </div>
              <span className="text-[12.5px] text-muted-foreground">
                {queue.summary}
                {queue.finishes_at && !queue.is_paused && (
                  <> · finishes around {new Date(queue.finishes_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</>
                )}
              </span>
            </div>

            {queue.is_paused && (
              <div role="alert" className="rounded-[10px] border border-destructive-30 bg-destructive-10 px-4 py-3 text-[13px] text-destructive">
                Queue paused{queue.paused_by ? ` by ${queue.paused_by}` : ""}. The run in progress finishes;
                nothing new starts until you resume.
              </div>
            )}

            {queue.running.length > 0 && (
              <section className="flex flex-col gap-3">
                <h2 className="m-0 text-[13px] font-bold uppercase tracking-wide text-muted-foreground">
                  Running now
                </h2>
                {queue.running.map((job) => (
                  <RunningCard
                    key={job.job_id}
                    job={job}
                    cancelling={pendingJobIds.has(job.job_id)}
                    onCancel={() => cancelMutation.mutate(job.job_id)}
                  />
                ))}
              </section>
            )}

            <section className="flex flex-col gap-3">
              <div className="flex items-baseline justify-between">
                <h2 className="m-0 text-[13px] font-bold uppercase tracking-wide text-muted-foreground">
                  Waiting ({queue.waiting_count})
                </h2>
                {queue.hidden_waiting_count > 0 && (
                  <span className="text-xs text-muted-foreground">
                    {queue.hidden_waiting_count} more ahead from other departments
                  </span>
                )}
              </div>
              {!queue.estimates_available && (
                <p className="m-0 text-xs text-muted-foreground">{queue.estimate_note}</p>
              )}
              {queue.waiting.length === 0 ? (
                <EmptyState
                  title="Nothing waiting"
                  description="Queue the next offer now and it starts the moment the current read finishes."
                  action={
                    <button type="button" onClick={() => navigate("/upload")} className="text-sm font-semibold text-accent">
                      Queue an offer
                    </button>
                  }
                />
              ) : (
                <div className="flex flex-col gap-2">
                  {queue.waiting.map((job, index) => (
                    <WaitingRow
                      key={job.job_id}
                      job={job}
                      index={index}
                      total={queue.waiting.length}
                      busy={pendingJobIds.has(job.job_id)}
                      onMove={(delta) => move(job, delta)}
                      onCancel={() => cancelMutation.mutate(job.job_id)}
                    />
                  ))}
                </div>
              )}
            </section>

            {queue.running.length === 0 && queue.waiting.length === 0 && (
              <EmptyState
                icon={<Layers className="h-6 w-6" aria-hidden />}
                title="The queue is empty"
                description="Nothing is reading and nothing is waiting."
              />
            )}
          </div>
        )}
      </main>
    </AppShell>
  )
}
