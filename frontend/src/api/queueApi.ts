import { api } from "./client"
import type { Job } from "./jobApi"

// The one shared queue - not a job, not addressed by a job id. See
// routes/jobs.py's own note on why it gets its own router (/api/v1/queue).

export interface QueueJob extends Job {
  /** Seconds from now until this job is expected to START, and the same
   * thing as a timestamp. Null when this installation has not finished
   * enough runs to say, or the queue is paused - `estimate_note` says which. */
  estimated_start_seconds: number | null
  estimated_start_at: string | null
  /** Running jobs only. */
  elapsed_seconds: number | null
  estimated_remaining_seconds: number | null
}

export interface QueueState {
  is_paused: boolean
  paused_at: string | null
  paused_by: string
  parallel_slots: number
  slots: number
  slot_ceiling: number
  running: QueueJob[]
  waiting: QueueJob[]
  running_count: number
  waiting_count: number
  hidden_running_count: number
  hidden_waiting_count: number
  next_position: number
  next_start_seconds: number | null
  next_start_at: string | null
  finishes_at: string | null
  estimates_available: boolean
  estimate_note: string
  estimate_runs: Record<string, number>
  summary: string
}

export function getQueue(signal?: AbortSignal) {
  return api.get<QueueState>("/api/v1/queue", { timeoutMs: 15_000, signal })
}

export function pauseQueue() {
  return api.post<QueueState>("/api/v1/queue/pause", { timeoutMs: 15_000 })
}

export function resumeQueue() {
  return api.post<QueueState>("/api/v1/queue/resume", { timeoutMs: 15_000 })
}

/** How many offers may read at the same time (1-3). The deployment's own
 * ceiling still applies on top - `slots` in the response is the smaller of
 * the two, and `slot_ceiling` says what limited it when they differ. */
export function setQueueSlots(parallelSlots: number) {
  return api.patch<QueueState>("/api/v1/queue/slots", {
    json: { parallel_slots: parallelSlots },
    timeoutMs: 15_000,
  })
}

/** Moves a waiting job to a position in the whole queue - 1 starts next.
 * Returns the whole queue, because every position after the move changes. */
export function moveJobInQueue(jobId: string, position: number) {
  return api.patch<QueueState>(`/api/v1/jobs/${jobId}/position`, {
    json: { position },
    timeoutMs: 15_000,
  })
}
