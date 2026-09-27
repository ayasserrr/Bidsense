import type { Job } from "../api/jobApi"

/**
 * What the progress page says while a job is WAITING rather than running.
 *
 * Before the queue existed every upload started reading immediately, so
 * `queued` lasted a moment and nobody had to be told about it. Now only
 * `parallel_slots` offers read at once and the rest wait - potentially for the
 * ten minutes an offer ahead takes. A progress bar sitting at "Starting" for
 * that long reads as a hung app, which is the one thing this screen must never
 * look like. So a waiting job says it is waiting, and where it stands.
 *
 * `queue_position` is the whole installation's queue, not this department's
 * (see `JobOut.queue_position`), so the wording never implies the person can
 * go and look at the offers ahead of theirs.
 */
export interface QueueWait {
  headline: string
  body: string
  barLabel: string
}

export function queueWait(job: Job | null | undefined): QueueWait | null {
  if (!job || job.status !== "queued") return null

  const position = job.queue_position
  const body =
    position === null || position === undefined
      ? "Your files are safely uploaded. The check starts as soon as the reader is free."
      : position <= 1
        ? "Your files are safely uploaded. Yours is next - it starts as soon as the reader is free."
        : `Your files are safely uploaded. Yours is number ${position} in the queue and starts once the ones ahead of it finish.`

  return {
    headline: "Waiting to start",
    body,
    barLabel: "Waiting in the queue",
  }
}
