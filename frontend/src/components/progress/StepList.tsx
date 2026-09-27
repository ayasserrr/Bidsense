import { Check, LoaderCircle, Minus, X } from "lucide-react"
import type { JobStage, JobStageStatus } from "../../api/jobApi"
import { cn } from "../../lib/cn"

interface StepListProps {
  /** Comes from the job itself, labels included - a full pipeline run and a
   * single re-check have different steps and this list draws either. */
  stages: JobStage[]
}

interface RowStyle {
  row: string
  spine: string
  dot: string
  label: string
  note: string
  noteClass: string
  glyph: React.ReactNode
}

function rowStyle(status: JobStageStatus, isLast: boolean): RowStyle {
  const base: RowStyle = {
    row: "bg-transparent",
    spine: isLast ? "bg-transparent" : "bg-border",
    dot: "bg-card border-2 border-border text-muted-foreground",
    label: "font-medium text-muted-foreground",
    note: "",
    noteClass: "text-muted-foreground",
    glyph: null,
  }
  switch (status) {
    case "done":
      return {
        ...base,
        spine: isLast ? "bg-transparent" : "bg-success",
        dot: "bg-success border-0 text-success-foreground",
        label: "font-medium text-foreground",
        glyph: <Check className="h-[13px] w-[13px]" strokeWidth={3.2} aria-hidden />,
      }
    case "active":
      return {
        ...base,
        row: "bg-muted",
        dot: "bg-accent border-0 text-accent-foreground",
        label: "font-bold text-foreground",
        note: "In progress",
        noteClass: "text-accent",
        glyph: <LoaderCircle className="h-[13px] w-[13px] animate-spin" aria-hidden />,
      }
    case "error":
      return {
        ...base,
        dot: "bg-destructive border-0 text-destructive-foreground",
        label: "font-bold text-destructive",
        note: "Stopped",
        noteClass: "text-destructive",
        glyph: <X className="h-[13px] w-[13px]" strokeWidth={3.2} aria-hidden />,
      }
    case "skipped":
      return {
        ...base,
        dot: "bg-card border border-border text-muted-foreground",
        label: "font-medium text-muted-foreground line-through",
        note: "Not run",
        glyph: <Minus className="h-3 w-3" aria-hidden />,
      }
    default:
      return base
  }
}

export function StepList({ stages }: StepListProps) {
  return (
    <ol className="m-0 list-none p-0">
      {stages.map((stage, index) => {
        const style = rowStyle(stage.status, index === stages.length - 1)
        return (
          <li
            key={stage.id}
            className={cn("relative flex items-center gap-[13px] rounded-[10px] px-2.5 py-[9px]", style.row)}
          >
            {/* Centred on the dot (10px row padding + half of the 26px dot). */}
            <span className={cn("absolute bottom-0 left-[22px] top-0 w-0.5", style.spine)} aria-hidden />
            <span
              className={cn(
                "relative z-[1] grid h-[26px] w-[26px] flex-none place-items-center rounded-full shadow-[0_0_0_4px_var(--card)]",
                style.dot,
              )}
            >
              {style.glyph}
            </span>
            <span className="flex flex-1 flex-col gap-0.5">
              <span className={cn("text-sm", style.label)}>{stage.label}</span>
              {/* The detail line is where a long stage shows it is alive:
                  "3 of 5 sections extracted" rather than a spinner that could
                  equally mean a hang. */}
              {stage.detail && (
                <span className="text-[12px] leading-snug text-muted-foreground">{stage.detail}</span>
              )}
            </span>
            {style.note && (
              <span
                className={cn(
                  "flex-none text-[11.5px] font-semibold uppercase tracking-[0.04em]",
                  style.noteClass,
                )}
              >
                {style.note}
              </span>
            )}
          </li>
        )
      })}
    </ol>
  )
}
