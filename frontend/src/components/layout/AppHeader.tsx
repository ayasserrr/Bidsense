import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Bell, Layers, Moon, Sun } from "lucide-react"
import { IconButton } from "../ui/IconButton"
import { ProfileMenu } from "./ProfileMenu"
import { getQueue } from "../../api/queueApi"
import { useTheme } from "../../lib/theme"
import { cn } from "../../lib/cn"

export { Wordmark } from "./Wordmark"

/** The sticky product chrome shown on every signed-in screen, now that
 * primary navigation lives in `Rail` instead of here.
 *
 * Everything left in this bar is a SESSION control - the queue's own state,
 * theme, notifications, sign-out - deliberately kept out of the rail, which
 * collapses to a horizontal strip below 980px. A control that decides who is
 * signed in, or that the whole company's read queue is paused, must stay
 * reachable at every width; see `Rail`'s own comment on why the design's
 * rail-foot placement for these was not carried over.
 *
 * The landing and sign-in screens carry their own headers and don't render
 * this one. */
export function AppHeader() {
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()
  // Same query key as `Rail` and the queue screen - one number, not three
  // that can each be mid-poll when a reviewer compares them.
  const { data: queue } = useQuery({
    queryKey: ["queue"],
    queryFn: ({ signal }) => getQueue(signal),
    refetchInterval: 15_000,
  })

  return (
    <header className="sticky top-0 z-40 flex h-[58px] items-center justify-end gap-2 border-b border-border bg-card px-5">
      <button
        type="button"
        onClick={() => navigate("/queue")}
        data-tour="queue"
        className={cn(
          "mr-auto inline-flex h-8 items-center gap-[7px] rounded-full border px-3 text-[12.5px] font-medium transition-colors",
          queue && !queue.is_paused && queue.running_count > 0
            ? "border-accent-30 bg-accent-10 text-accent"
            : "border-border bg-background text-muted-foreground hover:text-foreground",
        )}
      >
        <Layers className="h-3.5 w-3.5" aria-hidden />
        {queue?.summary ?? "Queue"}
      </button>

      <IconButton aria-label="Toggle theme" onClick={toggleTheme}>
        {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
      </IconButton>
      <IconButton aria-label="Notifications">
        <Bell className="h-4 w-4" aria-hidden />
      </IconButton>
      <div className="mx-0.5 h-[22px] w-px bg-border" />
      <ProfileMenu />
    </header>
  )
}
