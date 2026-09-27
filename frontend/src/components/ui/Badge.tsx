import type { HTMLAttributes } from "react"
import { cn } from "../../lib/cn"

export type BadgeTone = "neutral" | "brand" | "success" | "warning" | "critical" | "info"

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone
}

// Every class here must resolve against the real tokens declared in
// index.css's @theme block (background/foreground/card/muted/accent/success/
// destructive/border + their tint variants) - there is no separate "ink"/
// "surface"/"brand"/"info" token set in this app's theme, and no dedicated
// info hue at all, so `info` reuses a neutral-ish look rather than inventing
// a new color.
const toneClasses: Record<BadgeTone, string> = {
  neutral: "bg-muted text-muted-foreground border-border",
  brand: "border-accent-35 bg-accent-12 text-accent",
  success: "bg-success-10 text-success border-success-30",
  warning: "bg-yellow-50 text-yellow-800 border-yellow-300 dark:bg-yellow-500/10 dark:text-yellow-400 dark:border-yellow-500/30",
  critical: "bg-destructive-10 text-destructive border-destructive-30",
  info: "bg-muted-60 text-foreground border-border",
}

export function Badge({ tone = "neutral", className, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        toneClasses[tone],
        className,
      )}
      {...props}
    />
  )
}
