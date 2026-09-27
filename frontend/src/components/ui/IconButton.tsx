import { forwardRef, type ButtonHTMLAttributes } from "react"
import { cn } from "../../lib/cn"

const BASE =
  "grid place-items-center rounded-lg border transition outline-none focus-visible:ring-2 focus-visible:ring-accent-40 disabled:opacity-40 disabled:cursor-not-allowed"

const SIZES = {
  sm: "h-8 w-8",
  md: "h-9 w-9",
} as const

function tone(active: boolean): string {
  return active
    ? "border-accent-30 bg-accent-10 text-accent"
    : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground"
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  active?: boolean
  size?: keyof typeof SIZES
}

/** Qualisense IconButton. Icons are passed in at h-4 w-4. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { active = false, size = "md", className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      className={cn(BASE, SIZES[size], tone(active), className)}
      {...rest}
    />
  )
})
