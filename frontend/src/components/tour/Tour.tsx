import { useEffect, useState, type CSSProperties } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { useAuth } from "../../lib/auth"
import { TOUR_STEPS, hasSeenTour, markTourSeen } from "../../lib/tour"
import { cn } from "../../lib/cn"

interface AnchorRect {
  top: number
  left: number
  width: number
  height: number
}

const PAD = 8
const TOOLTIP_WIDTH = 300

function tooltipStyle(rect: AnchorRect | null): CSSProperties | undefined {
  if (!rect || typeof window === "undefined") return undefined
  const margin = 12
  const estimatedHeight = 190
  let top = rect.top + rect.height + margin
  if (top + estimatedHeight > window.innerHeight) {
    top = Math.max(margin, rect.top - estimatedHeight - margin)
  }
  let left = rect.left
  if (left + TOOLTIP_WIDTH > window.innerWidth - margin) left = window.innerWidth - TOOLTIP_WIDTH - margin
  if (left < margin) left = margin
  return { top, left }
}

/** A first-run guided tour: five steps, each anchored to a `data-tour="<id>"`
 * element already present on the shell (Rail, AppHeader, the Offers filter
 * bar, the new Summary section).
 *
 * Mounted exactly once, in App.tsx's root layout - inside the router (steps
 * navigate between /dashboard and /offers) and inside AuthProvider (it only
 * ever runs for a signed-in user, since it needs the Rail/Offers it points
 * at to exist). Every hook below runs unconditionally, per the rules of
 * hooks; each effect's BODY is what checks `user` and bails out, rather than
 * the hook call itself being conditional. */
export function Tour() {
  const { user } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [active, setActive] = useState(false)
  const [stepIndex, setStepIndex] = useState(0)
  const [rect, setRect] = useState<AnchorRect | null>(null)

  const step = TOUR_STEPS[stepIndex]
  const onStepRoute = location.pathname === step.route

  // Starts once a signed-in user who hasn't seen it lands anywhere in the app.
  useEffect(() => {
    if (!user || hasSeenTour()) return
    setActive(true)
    setStepIndex(0)
  }, [user])

  // Gets to the current step's page. Most anchors (nav, new, queue) are on
  // every signed-in screen via the Rail/AppHeader, but this still routes to
  // each step's own `route` so the tour reads the same regardless of where
  // it was started from.
  useEffect(() => {
    if (!active || !user || onStepRoute) return
    navigate(step.route)
  }, [active, user, onStepRoute, step.route, navigate])

  // Finds and measures the step's anchor, retrying briefly for a route
  // transition whose anchor hasn't painted yet. An anchor that genuinely
  // isn't on this page (the "summary" step, from the Offers list) settles on
  // `null` instead of retrying forever - a centered tooltip with no
  // spotlight, not a crash or an infinite loop.
  useEffect(() => {
    if (!active || !user) return
    if (!onStepRoute) {
      setRect(null)
      return
    }
    let cancelled = false
    let attempts = 0
    let frame = 0

    function measureNow(): boolean {
      const el = document.querySelector(`[data-tour="${step.id}"]`)
      if (!el) return false
      const r = el.getBoundingClientRect()
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height })
      return true
    }

    function measure() {
      if (cancelled) return
      if (measureNow()) return
      attempts += 1
      if (attempts < 15) {
        frame = requestAnimationFrame(measure)
      } else {
        setRect(null)
      }
    }
    measure()

    // A resize (breakpoint change collapsing the Rail, devtools opening) or a
    // scroll of a non-sticky anchor (the Offers filter bar) moves the anchor
    // without unmounting it - found by review: without this, the spotlight
    // and tooltip stayed at their pre-resize/scroll coordinates, visually
    // detached from the button they're meant to point at. If the anchor is
    // genuinely gone by the time this fires, fall back to null rather than
    // leaving stale coordinates on screen.
    function onViewportChange() {
      if (!measureNow()) setRect(null)
    }
    window.addEventListener("resize", onViewportChange)
    window.addEventListener("scroll", onViewportChange, { passive: true, capture: true })

    return () => {
      cancelled = true
      cancelAnimationFrame(frame)
      window.removeEventListener("resize", onViewportChange)
      window.removeEventListener("scroll", onViewportChange, { capture: true })
    }
  }, [active, user, onStepRoute, step.id, stepIndex])

  // Escape skips the whole tour, same convention as ConfirmDialog/ProfileMenu.
  useEffect(() => {
    if (!active || !user) return
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") finish()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
    // `finish` is intentionally left out of the deps: it only closes over
    // stable setters, and including it (a new function identity every
    // render) would tear down and re-add this listener on every render.
  }, [active, user])

  if (!active || !user) return null

  function finish() {
    markTourSeen()
    setActive(false)
  }

  function next() {
    if (stepIndex >= TOUR_STEPS.length - 1) {
      finish()
      return
    }
    setStepIndex((i) => i + 1)
  }

  function back() {
    setStepIndex((i) => Math.max(0, i - 1))
  }

  const stepNumber = stepIndex + 1
  const total = TOUR_STEPS.length
  const isLast = stepIndex === total - 1
  const buttonClass =
    "h-8 rounded-md px-3 text-xs font-medium transition outline-none focus-visible:ring-2 focus-visible:ring-accent-40"

  return (
    <div className="fixed inset-0 z-[100]" role="dialog" aria-modal="true" aria-label={`Guided tour: ${step.title}`}>
      {rect ? (
        <>
          <div className="fixed bg-black/60" style={{ top: 0, left: 0, right: 0, height: Math.max(0, rect.top - PAD) }} />
          <div
            className="fixed bg-black/60"
            style={{ top: rect.top + rect.height + PAD, left: 0, right: 0, bottom: 0 }}
          />
          <div
            className="fixed bg-black/60"
            style={{
              top: rect.top - PAD,
              left: 0,
              width: Math.max(0, rect.left - PAD),
              height: rect.height + PAD * 2,
            }}
          />
          <div
            className="fixed bg-black/60"
            style={{ top: rect.top - PAD, left: rect.left + rect.width + PAD, right: 0, height: rect.height + PAD * 2 }}
          />
          <div
            aria-hidden
            className="fixed rounded-lg ring-2 ring-accent"
            style={{
              top: rect.top - PAD,
              left: rect.left - PAD,
              width: rect.width + PAD * 2,
              height: rect.height + PAD * 2,
            }}
          />
        </>
      ) : (
        <div className="fixed inset-0 bg-black/60" />
      )}

      <div
        className={cn(
          "fixed z-[101] flex flex-col gap-2.5 rounded-2xl border border-border bg-card p-4 shadow-soft",
          !rect && "left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2",
        )}
        style={{ width: TOOLTIP_WIDTH, ...(rect ? tooltipStyle(rect) : undefined) }}
      >
        <h2 className="m-0 text-[15px] font-bold leading-snug">{step.title}</h2>
        <p className="m-0 text-[13px] leading-snug text-muted-foreground">{step.body}</p>
        <div className="mt-1 flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground">
            {stepNumber} of {total}
          </span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={finish}
              className={cn(buttonClass, "text-muted-foreground hover:text-foreground")}
            >
              Skip the tour
            </button>
            {stepIndex > 0 && (
              <button
                type="button"
                onClick={back}
                className={cn(buttonClass, "border border-border bg-card text-foreground hover:bg-muted")}
              >
                Back
              </button>
            )}
            <button type="button" onClick={next} className={cn(buttonClass, "bg-accent text-accent-foreground hover:opacity-90")}>
              {isLast ? "Got it" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
