import type { ReactNode } from "react"
import { cn } from "../../lib/cn"

/** Qualisense ErrorBanner. There is no second error hue in this system -
 * errors and destructive actions both use `destructive`. */
export function ErrorBanner({ children, className }: { children?: ReactNode; className?: string }) {
  if (!children) return null
  return (
    <div
      role="alert"
      className={cn(
        "rounded-md border border-destructive-30 bg-destructive-10 px-3 py-2 text-sm text-destructive",
        className,
      )}
    >
      {children}
    </div>
  )
}
