import { Link, useLocation } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Folder, Gauge, GitCompare, Layers, Plus } from "lucide-react"
import { getQueue } from "../../api/queueApi"
import { Wordmark } from "./Wordmark"
import { cn } from "../../lib/cn"

/** The left-hand navigation rail: the app's five places, always in the same
 * order, with a live count on Queue so a busy queue is visible from anywhere.
 *
 * Session-level controls (theme, notifications, sign-out, the profile card)
 * do NOT live here - they stay in `AppHeader`, visible at every width. The
 * design puts a user block and the theme toggle in the rail's own foot and
 * hides that whole foot below 980px (`[data-rail-foot] { display:none }`),
 * which would take sign-out down with it. That is a drawing decision, not an
 * app one - see `ui-revamp-decisions`: the app's behaviour wins where the two
 * disagree, so those controls stay put in the header instead of moving here.
 */

interface NavItem {
  to: string
  label: string
  icon: React.ReactNode
  /** Which paths count as "on this item", beyond an exact match. */
  match: (pathname: string) => boolean
  /** Anchor for the first-run tour (lib/tour.ts), when this item is one of its steps. */
  tour?: string
}

const NAV: NavItem[] = [
  {
    to: "/dashboard",
    label: "Dashboard",
    icon: <Gauge className="h-4 w-4" aria-hidden />,
    match: (p) => p === "/dashboard",
  },
  {
    to: "/upload",
    label: "New check",
    icon: <Plus className="h-4 w-4" aria-hidden />,
    match: (p) => p === "/upload" || p === "/upload/existing" || p === "/processing",
    tour: "new",
  },
  {
    to: "/queue",
    label: "Queue",
    icon: <Layers className="h-4 w-4" aria-hidden />,
    match: (p) => p === "/queue",
  },
  {
    to: "/offers",
    label: "Offers",
    icon: <Folder className="h-4 w-4" aria-hidden />,
    // The detail screen has no rail entry of its own - it is reached FROM
    // Offers, so Offers stays the active item while reading one.
    match: (p) => p.startsWith("/offers"),
  },
  {
    to: "/compare",
    label: "Compare",
    icon: <GitCompare className="h-4 w-4" aria-hidden />,
    match: (p) => p === "/compare",
  },
]

export function Rail() {
  const { pathname } = useLocation()
  // Shared with the header's queue pill and the queue screen itself under the
  // same query key, so all three ever show one number rather than three that
  // can drift apart by a poll interval.
  const { data: queue } = useQuery({
    queryKey: ["queue"],
    queryFn: ({ signal }) => getQueue(signal),
    refetchInterval: 15_000,
  })

  return (
    <nav
      aria-label="Main"
      data-tour="nav"
      className={cn(
        "sticky top-0 flex h-screen w-[244px] flex-none flex-col gap-[18px] overflow-y-auto",
        "border-r border-border bg-card px-3.5 py-4",
        // Narrow widths: a horizontal strip rather than a column, so the rail
        // never eats the vertical space a phone doesn't have. Nothing here is
        // a session control, so nothing is lost by scrolling it sideways.
        "max-[980px]:h-auto max-[980px]:w-full max-[980px]:flex-row max-[980px]:items-center",
        "max-[980px]:gap-3 max-[980px]:overflow-x-auto max-[980px]:border-b max-[980px]:border-r-0",
        "max-[980px]:px-3 max-[980px]:py-2.5",
      )}
    >
      <Link
        to="/dashboard"
        className="flex flex-none items-center gap-2.5 border-b border-border pb-3.5 max-[980px]:border-b-0 max-[980px]:pb-0"
      >
        <img src="/brand/wedy-mark.png" alt="" className="block h-[19px] w-[34px] object-contain" />
        <Wordmark />
      </Link>

      <ul className="flex flex-col gap-0.5 max-[980px]:flex-row">
        {NAV.map((item) => {
          const active = item.match(pathname)
          const badge = item.to === "/queue" ? queue?.waiting_count : undefined
          return (
            <li key={item.to}>
              <Link
                to={item.to}
                aria-current={active ? "page" : undefined}
                data-tour={item.tour}
                className={cn(
                  "flex h-[38px] items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] font-medium transition-colors",
                  "max-[980px]:h-9 max-[980px]:whitespace-nowrap max-[980px]:px-3",
                  active
                    ? "bg-muted font-semibold text-foreground [&>svg]:text-accent"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {item.icon}
                {item.label}
                {!!badge && (
                  <span className="ml-auto flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-accent-12 px-1 text-[10.5px] font-bold text-accent">
                    {badge}
                  </span>
                )}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
