export interface TourStep {
  /** Matches a `data-tour="<id>"` anchor somewhere on `route`. */
  id: string
  route: string
  title: string
  body: string
}

const TOUR_KEY = "bidsense.tour.seen.v1"

// Five steps, adapted to this app's ACTUAL shell rather than the original
// design's header - this app's primary navigation lives in the rail, and its
// header holds only session controls (see Rail.tsx's own comment on why).
//
// Step 5 ("summary") is the one genuine compromise: the panel it points at
// only exists on an offer detail page, and the tour has no offer to open on
// someone's behalf without picking one for them. Anchoring it to the Offers
// list instead - where the anchor genuinely is not present - degrades to a
// centered tooltip with no spotlight (see Tour.tsx), which is an accepted,
// documented tradeoff rather than a bug.
export const TOUR_STEPS: TourStep[] = [
  {
    id: "nav",
    route: "/dashboard",
    title: "Five places, nothing hidden",
    body: "Dashboard, New check, Queue, Offers and Compare - the whole app lives in this rail, in the same order everywhere.",
  },
  {
    id: "new",
    route: "/dashboard",
    title: "Start a check from anywhere",
    body: "Upload one or more supplier documents here to start a new completeness check, from any screen in the app.",
  },
  {
    id: "queue",
    route: "/dashboard",
    title: "See what's running",
    body: "Every check in progress across the whole team shows here - pause it, reorder it, or just watch it move.",
  },
  {
    id: "filters",
    route: "/offers",
    title: "Find an offer fast",
    body: "Search and filter by supplier, project, RFQ or uploader - this bar narrows the list below it as you type.",
  },
  {
    id: "summary",
    route: "/offers",
    title: "Read this first",
    body: "Open any offer and its Summary panel lists exactly what to chase with the supplier, plus a ready clarification email - built from that offer's own verified findings, not a guess.",
  },
]

function readLocalStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeLocalStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // A browser with site data blocked just sees the tour again next time -
    // same tradeoff lib/theme.tsx accepts for the theme choice not persisting.
  }
}

/** True once the tour has been shown or skipped. A store that can't be read
 * at all (blocked, private mode) reads back the same as "never seen" - the
 * tour still runs correctly for that session, exactly like lib/theme.tsx's
 * theme choice; only whether it stays dismissed across reloads is lost. */
export function hasSeenTour(): boolean {
  return readLocalStorage(TOUR_KEY) === "1"
}

export function markTourSeen(): void {
  writeLocalStorage(TOUR_KEY, "1")
}
