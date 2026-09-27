import { useEffect, useRef } from "react"
import { useNavigate, useLocation, useSearchParams } from "react-router-dom"
import { Clock } from "lucide-react"
import { isTerminal } from "../api/jobApi"
import { queueWait } from "../lib/queueWait"
import { abandonOffer } from "../api/offerApi"
import { useOfferJob } from "../hooks/useOfferJob"
import { useElapsedSeconds, formatDuration } from "../hooks/useElapsedSeconds"
import { ProgressBar } from "../components/progress/ProgressBar"
import { StepList } from "../components/progress/StepList"
import { AppHeader } from "../components/layout/AppHeader"
import { AppShell } from "../components/layout/AppShell"
import { ErrorBanner } from "../components/ui/ErrorBanner"
import { Pill } from "../components/ui/Pill"
import { Spinner } from "../components/ui/Spinner"
import { StatusChip } from "../components/ui/StatusChip"

interface LocationState {
  files?: File[]
  targetOfferId?: number
  targetOfferLabel?: string
  projectName?: string
  rfqNumber?: string
}

/** Watches a background run.
 *
 * The run is on the server, so this page is a window onto it rather than the
 * thing driving it. Two consequences worth knowing about:
 *
 *  - The job id goes into the URL. A refresh, a restored tab, or a link sent to
 *    a colleague reattaches to the same run instead of starting a new one.
 *  - Leaving does not cancel. The previous version of this page blocked
 *    navigation and abandoned the offer on unmount, which deleted a run's work
 *    if the reviewer clicked away at minute nine. Stopping is now an explicit
 *    button, and nothing else stops anything.
 */
export function ProgressPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { state, start, watch, stop } = useOfferJob()
  const startedRef = useRef(false)

  const locationState = location.state as LocationState | null
  const files = locationState?.files
  const targetOfferLabel = locationState?.targetOfferLabel
  const isNewVersion = locationState?.targetOfferId !== undefined
  const jobIdParam = searchParams.get("job")

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true

    if (jobIdParam) {
      watch(jobIdParam)
      return
    }
    if (!files || files.length === 0) {
      navigate("/upload", { replace: true })
      return
    }
    void start(
      files,
      locationState?.targetOfferId,
      locationState?.projectName,
      locationState?.rfqNumber,
    ).then((jobId) => {
      // Into the URL the moment it exists, so a refresh one second later
      // reattaches to the run instead of stranding it.
      if (jobId) setSearchParams({ job: jobId }, { replace: true })
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const job = state.job

  // No job ever started - every file was rejected (e.g. "this offer has
  // already been uploaded"). There is nothing running and nothing to watch,
  // so this page has no business showing a spinner or a "stop this run"
  // button; send the reviewer back to where they came from with the reason.
  // Gated on `!jobIdParam`: a page reattaching to a real job via the URL can
  // have a transient poll failure with `job` still null on its first tick,
  // and that is not a start failure - it keeps polling and shows the error
  // inline instead, same as before.
  const startFailed = !!state.error && !job && !jobIdParam

  useEffect(() => {
    if (job?.status === "succeeded" && job.offer_id) {
      navigate(`/offers/${job.offer_id}`, {
        replace: true,
        state: { skippedFiles: state.skippedFiles },
      })
    }
  }, [job?.status, job?.offer_id, navigate, state.skippedFiles])

  useEffect(() => {
    if (!startFailed) return
    navigate(isNewVersion ? "/upload/existing" : "/upload", {
      replace: true,
      state: { uploadError: state.error },
    })
  }, [startFailed, isNewVersion, navigate, state.error])

  const elapsedSeconds = useElapsedSeconds(job ? new Date(job.created_at).getTime() : null)

  if (!jobIdParam && (!files || files.length === 0)) return null
  if (startFailed) return null

  const failed = job?.status === "failed"
  const cancelled = job?.status === "cancelled"
  const finished = job ? isTerminal(job.status) : false
  const tone = failed ? "error" : cancelled ? "stopped" : job?.status === "succeeded" ? "done" : "running"
  // Null while the job is actually reading; a sentence to show while it waits
  // its turn in the queue.
  const waiting = queueWait(job)

  return (
    <AppShell>
      <AppHeader />
      <main className="px-6 pb-20 pt-14">
        <div className="mx-auto flex max-w-[660px] flex-col gap-6">
          <div className="flex flex-col items-center gap-2.5 text-center">
            <h1 className="m-0 text-[25px] font-bold leading-[1.2] tracking-[-0.02em]">
              {failed
                ? "We ran into a problem"
                : cancelled
                  ? "Stopped"
                  : waiting
                    ? waiting.headline
                    : isNewVersion
                      ? "Checking your new version"
                      : "Reading your offer"}
            </h1>
            <p className="m-0 max-w-[480px] text-[14.5px] leading-[1.6] text-pretty text-muted-foreground">
              {failed
                ? job?.offer_persisted
                  ? "The offer itself was saved - only the last check did not finish. You can run it again from the offer page."
                  : "Your files are still here. Nothing was saved, but you can start the check again without uploading them again."
                : cancelled
                  ? "Your files are still here. Start the check again whenever you like."
                  : waiting
                    ? waiting.body
                    : isNewVersion
                      ? `Reading this file and confirming it really is a new version of ${targetOfferLabel ?? "the selected offer"} before saving it. This runs on the server - you can close this page and come back.`
                      : "This runs on the server, so you can close this page and come back to it. A typical offer takes a few minutes; a large multi-document one takes longer."}
            </p>
            {!finished && (
              <span className="inline-flex h-7 items-center gap-[7px] rounded-full bg-muted px-3 text-[12.5px] font-semibold text-muted-foreground">
                <Clock className="h-[13px] w-[13px]" aria-hidden />
                <span className="tabular">{formatDuration(elapsedSeconds)}</span>
              </span>
            )}
          </div>

          {job ? (
            <div className="flex flex-col gap-4 rounded-[14px] border border-border bg-card px-4 py-4">
              <ProgressBar
                percent={job.progress_percent}
                tone={tone}
                label={
                  finished
                    ? undefined
                    : (waiting?.barLabel ??
                      job.stages.find((stage) => stage.status === "active")?.label ??
                      "Starting")
                }
              />
              <div className="-mx-1.5">
                <StepList stages={job.stages} />
              </div>
            </div>
          ) : (
            <div className="grid place-items-center rounded-[14px] border border-border bg-card py-12">
              <Spinner />
            </div>
          )}

          {!finished && files && files.length > 0 && (
            <div className="flex flex-wrap items-center justify-center gap-2">
              <span className="text-xs text-muted-foreground">Reading</span>
              {files.map((file, index) => (
                <StatusChip key={`${file.name}-${index}`} tone="neutral" title={file.name}>
                  {file.name}
                </StatusChip>
              ))}
            </div>
          )}

          {state.skippedFiles.length > 0 && (
            <div className="flex flex-wrap items-center justify-center gap-2">
              <span className="text-xs text-muted-foreground">Not included</span>
              {state.skippedFiles.map((file) => (
                <StatusChip key={file.filename} tone="muted" title={file.message}>
                  {file.filename}
                </StatusChip>
              ))}
            </div>
          )}

          {state.error && <ErrorBanner>{state.error}</ErrorBanner>}
          {job?.error_message && <ErrorBanner>{job.error_message}</ErrorBanner>}

          <div className="flex flex-wrap justify-center gap-2 pt-0.5">
            {!finished && (
              <>
                {/* Leaving is safe and says so - the single most important
                    behaviour change on this page. */}
                <Pill onClick={() => navigate("/offers")}>Leave it running</Pill>
                <Pill onClick={() => void stop()} disabled={job?.cancel_requested}>
                  {job?.cancel_requested ? "Stopping..." : "Stop this run"}
                </Pill>
              </>
            )}
            {finished && job?.offer_persisted && job.offer_id && (
              <Pill onClick={() => navigate(`/offers/${job.offer_id}`)}>Open the offer</Pill>
            )}
            {finished && <Pill onClick={() => navigate("/upload", { replace: true })}>Back to upload</Pill>}
            {/* Only offered when the offer never reached persist. Once it is
                saved it is a real offer, and this would be a destructive
                action wearing the same label. */}
            {finished && !job?.offer_persisted && job?.offer_id && (
              <Pill
                onClick={() => {
                  abandonOffer(job.offer_id as number)
                  navigate("/upload", { replace: true })
                }}
              >
                Discard these files
              </Pill>
            )}
          </div>
        </div>
      </main>
    </AppShell>
  )
}
