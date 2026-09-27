import type { ReactNode } from "react"
import { cn } from "../../lib/cn"

export type StatTone = "default" | "accent" | "danger"

interface StatCardProps {
  icon: ReactNode
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: StatTone
  className?: string
}

const cardTones: Record<StatTone, string> = {
  default: "border-border bg-card",
  accent: "border-accent-25 bg-accent-5",
  danger: "border-destructive-30 bg-destructive-5",
}

const iconTones: Record<StatTone, string> = {
  default: "bg-muted text-muted-foreground",
  accent: "bg-accent-15 text-accent",
  danger: "bg-destructive-10 text-destructive",
}

/** Qualisense StatCard. Icons are passed in at h-4 w-4. */
export function StatCard({ icon, label, value, sub, tone = "default", className }: StatCardProps) {
  return (
    <div className={cn("rounded-xl border p-4", cardTones[tone], className)}>
      <div className="flex items-start justify-between gap-2">
        <span className={cn("grid h-8 w-8 place-items-center rounded-lg", iconTones[tone])}>{icon}</span>
      </div>
      <div className="tabular mt-3 text-2xl font-extrabold tracking-tight">{value}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{label}</div>
      {sub && <div className="mt-1 text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  )
}
