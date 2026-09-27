import { useState, type ReactNode } from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "../../lib/cn"
import { IconButton } from "../ui/IconButton"

/** The card shell every offer-detail section sits in. */
export function DetailSection({
  title,
  description,
  aside,
  bodyClassName,
  children,
  collapsible = false,
  defaultOpen = true,
}: {
  title: string
  description?: string
  aside?: ReactNode
  bodyClassName?: string
  children: ReactNode
  /** When true, a chevron in the header toggles the body open/closed. */
  collapsible?: boolean
  /** Only relevant when collapsible. Defaults to open. */
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  // A section's loading/error/empty short-circuit returns often render this
  // same DetailSection without `collapsible`/`defaultOpen` set, so React
  // reuses this instance's state rather than re-seeding it once real data
  // arrives and those props change. Adjust during render (React's documented
  // pattern for this) rather than in an effect, so there's no stale frame.
  const [prevDefaultOpen, setPrevDefaultOpen] = useState(defaultOpen)
  if (defaultOpen !== prevDefaultOpen) {
    setPrevDefaultOpen(defaultOpen)
    setOpen(defaultOpen)
  }
  const isOpen = !collapsible || open

  return (
    <section className="overflow-hidden rounded-[14px] border border-border bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-border bg-accent-5 px-5 py-3.5">
        <div>
          <h2 className="m-0 flex items-center gap-[9px] text-[15px] font-bold tracking-[-0.01em]">
            <span className="h-[7px] w-[7px] flex-none rounded-[2px] bg-accent" aria-hidden="true" />
            {title}
          </h2>
          {description && <p className="m-0 mt-[4px] pl-[16px] text-[12.5px] text-muted-foreground">{description}</p>}
        </div>
        <div className="flex flex-none items-center gap-2">
          {aside}
          {collapsible && (
            <IconButton
              size="sm"
              aria-label={isOpen ? `Collapse ${title}` : `Expand ${title}`}
              aria-expanded={isOpen}
              onClick={() => setOpen((current) => !current)}
            >
              <ChevronDown
                className={cn("h-4 w-4 transition-transform", !isOpen && "-rotate-90")}
                aria-hidden="true"
              />
            </IconButton>
          )}
        </div>
      </div>
      {isOpen && <div className={bodyClassName}>{children}</div>}
    </section>
  )
}

/** A label/value pair - renders nothing at all when the document didn't
 * state a value, rather than a placeholder like "Not stated". */
export function DetailField({
  label,
  value,
  tabular = false,
  className,
}: {
  label: string
  value: ReactNode
  tabular?: boolean
  className?: string
}) {
  const isEmpty = value === null || value === undefined || value === ""
  if (isEmpty) return null

  return (
    <div className={cn("flex flex-col gap-[3px]", className)}>
      <dt className="text-[11px] font-extrabold uppercase tracking-[0.08em] text-foreground">{label}</dt>
      <dd className={cn("m-0 text-sm font-medium leading-[1.45]", tabular && "tabular")}>{value}</dd>
    </div>
  )
}
