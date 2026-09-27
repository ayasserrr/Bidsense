import { api } from "./client"
import type { UploadedFileResult } from "./types"

// The pipeline runs on the SERVER now, not here. This module starts a job and
// then watches it; it does not drive the stages. That is what lets a reviewer
// close the tab during a twenty-minute extraction and come back to a finished
// offer instead of a deleted one.

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled"
export type JobStageStatus = "pending" | "active" | "done" | "error" | "skipped"
export type JobKind = "offer_pipeline" | "completeness" | "taxonomy"

export interface JobStage {
  id: string
  /** Comes from the server so a job of any kind describes its own steps. */
  label: string
  weight: number
  status: JobStageStatus
  detail: string | null
}

export interface Job {
  job_id: string
  kind: JobKind
  status: JobStatus
  offer_id: number | null
  // Enough of the offer to draw a row without a second request. A job whose
  // offer is a few seconds old has none of these yet.
  offer_ref: string | null
  rfq_number: string | null
  project_name: string | null
  file_count: number
  page_count: number
  stages: JobStage[]
  current_stage: string | null
  progress_percent: number
  error_stage: string | null
  error_message: string | null
  cancel_requested: boolean
  // Where this job sits in the waiting list, 1 for the one that starts next.
  // Null unless the job is waiting. It counts the whole installation's queue,
  // including offers this user's department cannot see.
  queue_position: number | null
  created_at: string
  // When it joined the waiting list and when it left it. A job that waited has
  // a `started_at` well after `created_at`.
  enqueued_at: string | null
  started_at: string | null
  updated_at: string
  finished_at: string | null
  created_by_user_id: number | null
  /** "queued by Yara Kamal". Empty for a job from before sign-in existed. */
  created_by_display_name: string
  /** True once the offer is safely written - a failure after this point costs
   * a re-check, not the offer. */
  offer_persisted: boolean
}

export interface StartOfferJobResponse {
  job_id: string
  offer_id: number
  results: UploadedFileResult[]
  parent_offer_id: number | null
  root_offer_id: number | null
}

export function isTerminal(status: JobStatus): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled"
}

/** Uploads the files and starts the run. Returns in a second or two - the
 * reading itself continues on the server.
 *
 * `projectName`/`rfqNumber` are what was typed on the upload form - only
 * meaningful for a brand NEW offer. Sending them alongside a `targetOfferId`
 * would be ignored server-side anyway (a version inherits its chain's RFQ and
 * typed name, see `UploadController.create_offer_version`), so they are only
 * ever sent when there is no target. */
export function startOfferJob(
  files: File[],
  targetOfferId?: number,
  projectName?: string,
  rfqNumber?: string,
) {
  const formData = new FormData()
  for (const file of files) formData.append("files", file)
  if (targetOfferId === undefined) {
    if (projectName) formData.append("project_name_entered", projectName)
    if (rfqNumber) formData.append("rfq_number", rfqNumber)
  }
  const query = targetOfferId !== undefined ? `?target_offer_id=${targetOfferId}` : ""
  return api.post<StartOfferJobResponse>(`/api/v1/jobs/offer${query}`, {
    formData,
    // Only covers the upload itself. The pipeline's own duration is irrelevant
    // here - that is what the job is for.
    timeoutMs: 120_000,
  })
}

/** Runs the pipeline again over files that are already uploaded - what a
 * failed run leads to, so a retry costs a re-read and not a re-upload. */
export function rerunOfferJob(offerId: number) {
  return api.post<Job>(`/api/v1/jobs/offer/${offerId}/rerun`, { timeoutMs: 30_000 })
}

export function getJob(jobId: string, signal?: AbortSignal) {
  return api.get<Job>(`/api/v1/jobs/${jobId}`, { timeoutMs: 20_000, signal })
}

export function listJobs(limit = 25) {
  return api.get<Job[]>(`/api/v1/jobs?limit=${limit}`, { timeoutMs: 20_000 })
}

/** Asks a job to stop. It stops at its next stage boundary; the offer and its
 * files are kept. */
export function cancelJob(jobId: string) {
  return api.post<Job>(`/api/v1/jobs/${jobId}/cancel`, { timeoutMs: 20_000 })
}
