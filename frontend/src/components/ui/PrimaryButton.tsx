import { forwardRef, type ButtonHTMLAttributes } from "react"
import { Loader2 } from "lucide-react"
import { cn } from "../../lib/cn"

interface PrimaryButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  loading?: boolean
}

/** Qualisense PrimaryButton - the single red call to action. Full-width by
 * design; the caller sizes it by constraining its container. */
export const PrimaryButton = forwardRef<HTMLButtonElement, PrimaryButtonProps>(function PrimaryButton(
  { type = "submit", loading = false, disabled, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={cn(
        "inline-flex h-11 w-full items-center justify-center gap-2 rounded-[10px] bg-accent text-sm font-semibold",
        "text-accent-foreground shadow-glow transition hover:opacity-90 hover:shadow-glow-lg",
        "disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none",
        className,
      )}
      {...rest}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
})
