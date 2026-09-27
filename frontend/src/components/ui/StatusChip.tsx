import type { ReactNode } from "react"
import { cn } from "../../lib/cn"

export type ChipTone = "neutral" | "success" | "accent" | "muted"

interface StatusChipProps {
  icon?: ReactNode
  tone?: ChipTone
  title?: string
  className?: string
  children: ReactNode
}

const tones: Record<ChipTone, string> = {
  neutral: "border-border bg-muted-60 text-foreground-80",
  success: "border-success-30 bg-success-10 text-success",
  accent: "border-accent-30 bg-accent-10 text-accent",
  muted: "border-border bg-transparent text-muted-foreground",
}

/** Qualisense StatusChip. Icons are passed in at h-3 w-3. */
export function StatusChip({ icon, tone = "neutral", title, className, children }: StatusChipProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        tones[tone],
        className,
      )}
    >
      {icon}
      <span className="truncate">{children}</span>
    </span>
  )
}
