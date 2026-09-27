import { cn } from "../../lib/cn"

interface ProgressBarProps {
  /** 0-100, as the server computed it. */
  percent: number
  /** Stops the shimmer and turns the bar red or grey when a run has ended. */
  tone?: "running" | "done" | "error" | "stopped"
  label?: string
}

const TONE_CLASS: Record<NonNullable<ProgressBarProps["tone"]>, string> = {
  running: "bg-accent",
  done: "bg-success",
  error: "bg-destructive",
  stopped: "bg-muted-foreground",
}

/** The one number a reviewer actually watches.
 *
 * The value is whatever the server says, never re-derived here: stage weights
 * are rough measured durations (extraction is most of the wall clock) and
 * splitting that knowledge across two places is how a bar ends up jumping to
 * 50% and then sitting still for ten minutes.
 */
export function ProgressBar({ percent, tone = "running", label }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(percent)))
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        {label && <span className="text-[13px] text-muted-foreground">{label}</span>}
        <span className="tabular text-[13px] font-semibold text-foreground">{clamped}%</span>
      </div>
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? "Progress"}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-500 ease-out",
            TONE_CLASS[tone],
          )}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  )
}
