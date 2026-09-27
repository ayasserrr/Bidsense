import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "../../lib/cn"

interface PillProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon?: ReactNode
  chevron?: boolean
  active?: boolean
}

/** Qualisense Pill. Icons are passed in at h-3.5 w-3.5. */
export const Pill = forwardRef<HTMLButtonElement, PillProps>(function Pill(
  { icon, chevron = false, active = false, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs transition outline-none",
        "focus-visible:ring-2 focus-visible:ring-accent-40 disabled:cursor-not-allowed disabled:opacity-40",
        active
          ? "border-accent-30 bg-accent-10 text-accent"
          : "border-border bg-background text-foreground hover:bg-muted",
        className,
      )}
      {...rest}
    >
      {icon}
      <span className="truncate">{children}</span>
      {chevron && <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-70" aria-hidden />}
    </button>
  )
})
