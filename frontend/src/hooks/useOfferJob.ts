import { useCallback, useEffect, useState } from "react"
import {
  cancelJob,
  getJob,
  isTerminal,
  rerunOfferJob,
  startOfferJob,
  type Job,
} from "../api/jobApi"
import { ApiError, type UploadedFileResult } from "../api/types"

const POLL_INTERVAL_MS = 1_500

export interface OfferJobState {
  job: Job | null
  /** Files the upload rejected or recognised as duplicates. Reported straight
   * away rather than inside the job - a rejected file is something to see now,
   * not twenty minutes later. */
  skippedFiles: UploadedFileResult[]
  /** A problem with THIS page's own requests (the upload failed, the poll
   * cannot reach the server) - distinct from job.error_message, which is the
   * run itself reporting a failure. */
  error: string | null
  starting: boolean
}

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return "Something unexpected went wrong."
}

/** Starts a background run and watches it.
 *
 * What this hook deliberately does NOT do is drive the pipeline. The stages run
 * on the server; this only asks how it is going. That is the difference that
 * matters: unmounting this component - navigating away, closing the tab, losing
 * the network - no longer touches the run. The old version called
 * `abandonOffer` on unmount, which hard-deleted the offer, its documents and
 * its files, so a reviewer who clicked away at minute nine lost everything.
 */
export function useOfferJob() {
  const [state, setState] = useState<OfferJobState>({
    job: null,
    skippedFiles: [],
    error: null,
    starting: false,
  })
  const [watchedJobId, setWatchedJobId] = useState<string | null>(null)

  // The polling loop lives in an effect keyed on the job id, so switching jobs
  // or unmounting tears down the previous loop for free - no timer refs to
  // keep in step with renders, and no way to leave one running.
  useEffect(() => {
    if (!watchedJobId) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined

    async function tick(jobId: string) {
      if (stopped) return
      try {
        const job = await getJob(jobId)
        if (stopped) return
        setState((prev) => ({ ...prev, job, error: null }))
        if (isTerminal(job.status)) return
      } catch (err) {
        if (stopped) return
        // A failed poll is not a failed run - the server may be restarting, or
        // the laptop may have slept. Keep polling and say so, rather than
        // declaring dead a run that is very likely still going.
        setState((prev) => ({ ...prev, error: messageOf(err) }))
      }
      timer = setTimeout(() => void tick(jobId), POLL_INTERVAL_MS)
    }

    void tick(watchedJobId)
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  }, [watchedJobId])

  const watch = useCallback((jobId: string) => setWatchedJobId(jobId), [])

  const start = useCallback(
    async (
      files: File[],
      targetOfferId?: number,
      projectName?: string,
      rfqNumber?: string,
    ): Promise<string | null> => {
      setState({ job: null, skippedFiles: [], error: null, starting: true })
      try {
        const response = await startOfferJob(files, targetOfferId, projectName, rfqNumber)
        const skipped = response.results.filter((result) => result.status !== "success")
        const accepted = response.results.some((result) => result.status === "success")
        if (!accepted) {
          const reasons = skipped.map((f) => `${f.filename}: ${f.message}`).join("; ")
          setState({
            job: null,
            skippedFiles: skipped,
            error: reasons || "None of the selected files could be uploaded.",
            starting: false,
          })
          return null
        }
        setState({ job: null, skippedFiles: skipped, error: null, starting: false })
        setWatchedJobId(response.job_id)
        return response.job_id
      } catch (err) {
        setState({ job: null, skippedFiles: [], error: messageOf(err), starting: false })
        return null
      }
    },
    [],
  )

  const rerun = useCallback(async (offerId: number): Promise<string | null> => {
    setState((prev) => ({ ...prev, error: null, starting: true }))
    try {
      const job = await rerunOfferJob(offerId)
      setState((prev) => ({ ...prev, job, starting: false }))
      setWatchedJobId(job.job_id)
      return job.job_id
    } catch (err) {
      setState((prev) => ({ ...prev, error: messageOf(err), starting: false }))
      return null
    }
  }, [])

  const stop = useCallback(async () => {
    const jobId = state.job?.job_id ?? watchedJobId
    if (!jobId) return
    try {
      const job = await cancelJob(jobId)
      setState((prev) => ({ ...prev, job }))
    } catch (err) {
      setState((prev) => ({ ...prev, error: messageOf(err) }))
    }
  }, [state.job?.job_id, watchedJobId])

  return { state, start, watch, rerun, stop }
}
