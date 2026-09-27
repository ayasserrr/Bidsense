import { type ButtonHTMLAttributes, forwardRef } from "react"
import { Loader2 } from "lucide-react"
import { cn } from "../../lib/cn"

type Variant = "primary" | "secondary" | "ghost" | "danger"
type Size = "sm" | "md" | "lg"

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
}

const variantClasses: Record<Variant, string> = {
  primary:
    "bg-brand text-white hover:bg-brand-hover active:bg-brand-active shadow-sm disabled:bg-ink-faint",
  secondary:
    "bg-surface text-ink border border-border-strong hover:bg-surface-sunken disabled:text-ink-faint disabled:border-border",
  ghost: "text-ink-muted hover:bg-surface-sunken hover:text-ink disabled:text-ink-faint",
  danger: "bg-white text-brand border border-brand-border hover:bg-brand-subtle disabled:text-ink-faint disabled:border-border",
}

const sizeClasses: Record<Size, string> = {
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-6 text-base gap-2",
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", loading = false, disabled, className, children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(
          "inline-flex items-center justify-center rounded-lg font-medium transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 focus-visible:ring-offset-2",
          "disabled:cursor-not-allowed disabled:shadow-none",
          variantClasses[variant],
          sizeClasses[size],
          className,
        )}
        {...props}
      >
        {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
        {children}
      </button>
    )
  },
)
Button.displayName = "Button"
