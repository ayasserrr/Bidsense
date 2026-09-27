import { Link } from "react-router-dom"
import { Clock, Info, OctagonAlert, ScrollText, Shield, Sun, TriangleAlert } from "lucide-react"
import { Wordmark } from "../components/layout/Wordmark"
import { SEVERITY_PRESENTATION } from "../lib/findingLabels"
import { useTheme } from "../lib/theme"
import { cn } from "../lib/cn"

/** The design's own paths for the glyphs lucide has since redrawn - its file,
 * file-plus and layers gained rounded corners, its calculator turned portrait,
 * its git-compare grew node circles. Lucide is used wherever it still matches. */
const GLYPH = {
  file: "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7zM14 2v4a2 2 0 0 0 2 2h4",
  layers: "M12 2 2 7l10 5 10-5-10-5ZM2 17l10 5 10-5M2 12l10 5 10-5",
  calc: "M4 2h16a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zM8 6h8M16 14v4M16 10h.01M12 10h.01M8 10h.01M12 14h.01M8 14h.01M12 18h.01M8 18h.01",
  compare: "M13 6h3a2 2 0 0 1 2 2v7M11 18H8a2 2 0 0 1-2-2V9",
  draft: "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7zM14 2v4a2 2 0 0 0 2 2h4M9 15h6M12 18v-6",
  moon: "M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z",
}

function Glyph({ d, className }: { d: string; className: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d={d} />
    </svg>
  )
}

const GUTTER = "px-[clamp(16px,3vw,40px)]"

// The header is sticky and 66px tall; without this an in-page jump parks the
// section's top edge underneath it.
const ANCHOR = "scroll-mt-[66px]"

// Below 860px the header only has room for the brand and the two controls.
const WIDE_ONLY = "[@media(max-width:860px)]:hidden"

const NAV_LINKS = [
  { href: "#what", label: "What it does" },
  { href: "#findings", label: "A real report" },
  { href: "#phases", label: "Roadmap" },
]

// Unmeasured figures are stated as what the product does rather than as a
// number: a page count or an average read time would be a claim, not a fact.
const PROOF_POINTS = [
  {
    icon: <Glyph d={GLYPH.file} className="h-4 w-4" />,
    value: "All",
    label: "Pages read per offer",
    sub: "Every page of every file, scans included",
  },
  {
    icon: <Shield className="h-4 w-4" aria-hidden />,
    value: "20",
    label: "Required terms checked",
    sub: "And what the supplier failed to state",
  },
  {
    icon: <Clock className="h-4 w-4" aria-hidden />,
    value: "Minutes",
    label: "Runs on the server",
    sub: "Close the tab if you like — the check keeps going",
  },
  {
    icon: <Glyph d={GLYPH.layers} className="h-4 w-4" />,
    value: "10",
    label: "Engineering disciplines",
    sub: "Every line item sorted, correctable by hand",
  },
]

const SEVERITY_CARDS = [
  {
    severity: SEVERITY_PRESENTATION.critical,
    value: "2",
    icon: <OctagonAlert className="h-4 w-4" aria-hidden />,
    card: "border-destructive-30 bg-destructive-5",
    tile: "bg-destructive-10 text-destructive",
  },
  {
    severity: SEVERITY_PRESENTATION.review,
    value: "2",
    icon: <TriangleAlert className="h-4 w-4" aria-hidden />,
    card: "border-accent-25 bg-accent-5",
    tile: "bg-accent-15 text-accent",
  },
  {
    severity: SEVERITY_PRESENTATION.minor,
    value: "1",
    icon: <Info className="h-4 w-4" aria-hidden />,
    card: "border-border bg-card",
    tile: "bg-muted text-muted-foreground",
  },
]

const HERO_FINDINGS = [
  {
    icon: <Glyph d={GLYPH.calc} className="h-[18px] w-[18px]" />,
    severity: SEVERITY_PRESENTATION.critical,
    title: "Grand total doesn't add up",
    body: "The line items in the priced BOQ add up to 4,163,940 EGP, but the offer's cover page states a grand total of 4,287,500 EGP — a difference of 123,560 EGP the documents do not explain.",
  },
  {
    icon: <ScrollText className="h-[18px] w-[18px]" aria-hidden />,
    severity: SEVERITY_PRESENTATION.review,
    title: "Documents disagree",
    body: "The cover letter promises delivery in 12–14 weeks. The attached terms and conditions, Clause 7.2, state 16 weeks from order confirmation.",
  },
]

const PHASES = [
  {
    icon: <Shield className="h-[18px] w-[18px]" aria-hidden />,
    tile: "bg-accent-12 text-accent",
    chip: "border-accent-30 bg-accent-10 text-accent",
    status: "Live",
    title: "Check",
    body: "One offer, read end to end. Totals, currencies, terms and specs are cross-checked against every document in the pack, and anything that disagrees is held for review.",
  },
  {
    icon: <Glyph d={GLYPH.compare} className="h-[18px] w-[18px]" />,
    tile: "bg-muted text-muted-foreground",
    chip: "border-border bg-muted text-muted-foreground",
    status: "Phase 2",
    title: "Compare",
    body: "Several offers for the same package, lined up line by line. The model picks the strongest one and shows the comparison it based that on.",
  },
  {
    icon: <Glyph d={GLYPH.draft} className="h-[18px] w-[18px]" />,
    tile: "bg-muted text-muted-foreground",
    chip: "border-border bg-muted text-muted-foreground",
    status: "Phase 3",
    title: "Draft",
    body: "A new offer written from what your historical offers already agreed to — pricing structure, payment schedule and terms carried forward.",
  },
]

export function LandingPage() {
  const { theme, toggleTheme } = useTheme()

  return (
    <div className="min-h-screen bg-background">
      <header
        className={cn(
          "sticky top-0 z-30 flex h-[66px] items-center justify-between gap-4 border-b border-border bg-card",
          GUTTER,
        )}
      >
        <a href="#" className="flex flex-none items-center gap-[11px]">
          <img src="/brand/wedy-lockup.png" alt="WEDY.AI" className="block h-8 w-11 object-contain" />
          <span className="h-[22px] w-px bg-border" />
          <Wordmark className="text-foreground" />
        </a>
        <nav className={cn("flex items-center gap-[22px]", WIDE_ONLY)}>
          {NAV_LINKS.map((link) => (
            <a key={link.href} href={link.href} className="text-[13px] font-medium text-muted-foreground">
              {link.label}
            </a>
          ))}
        </nav>
        <div className="flex flex-none items-center gap-2.5">
          <span className={cn("text-[13px] text-muted-foreground", WIDE_ONLY)}>Procurement suite</span>
          <button
            type="button"
            aria-label="Toggle theme"
            onClick={toggleTheme}
            className="grid h-9 w-9 cursor-pointer place-items-center rounded-lg border border-border bg-card text-muted-foreground"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden /> : <Glyph d={GLYPH.moon} className="h-4 w-4" />}
          </button>
          <Link
            to="/signin"
            className="inline-flex h-10 flex-none items-center justify-center whitespace-nowrap rounded-[10px] bg-accent px-5 text-[13.5px] font-semibold text-accent-foreground shadow-glow"
          >
            Sign in
          </Link>
        </div>
      </header>

      <section
        className={cn(
          "mx-auto flex max-w-[1180px] flex-col items-center gap-[22px] pb-[clamp(32px,4vw,56px)] pt-[clamp(48px,7vw,92px)] text-center",
          GUTTER,
        )}
      >
        <div className="flex h-7 items-center gap-[9px] rounded-full bg-muted px-[13px] text-[11.5px] font-semibold tracking-[0.04em] text-muted-foreground">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          <span>
            Bid<span className="font-bold text-accent">sense</span> · phase 1 live
          </span>
        </div>
        <h1 className="m-0 max-w-[880px] text-[clamp(34px,5.2vw,58px)] font-bold leading-[1.03] tracking-[-0.035em] text-balance">
          Read every supplier offer before you sign it.
        </h1>
        <p className="m-0 max-w-[620px] text-[clamp(14.5px,1.4vw,17px)] leading-[1.6] text-pretty text-muted-foreground">
          Upload a supplier's offer with its BOQ and datasheets. Bidsense reads all of it, cross-checks the numbers
          against each other, and holds anything that doesn't add up before it reaches sign-off.
        </p>
        <div className="flex flex-wrap justify-center gap-2.5">
          <Link
            to="/signin"
            className="inline-flex h-11 items-center justify-center whitespace-nowrap rounded-[10px] bg-accent px-6 text-[14px] font-semibold text-accent-foreground shadow-glow"
          >
            Sign in with your network account
          </Link>
          <a
            href="#findings"
            className="inline-flex h-11 items-center justify-center whitespace-nowrap rounded-[10px] border border-border bg-card px-6 text-[14px] font-semibold text-foreground"
          >
            See what a report looks like
          </a>
        </div>
        <p className="m-0 text-[12.5px] text-muted-foreground">
          Sign in with your company email. Access is granted through your corporate directory — no separate password.
        </p>
      </section>

      <section
        id="what"
        className={cn("mx-auto max-w-[1180px] pb-[clamp(32px,4vw,56px)]", GUTTER, ANCHOR)}
      >
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,230px),1fr))] gap-3">
          {PROOF_POINTS.map((point) => (
            <div key={point.label} className="rounded-[14px] border border-border bg-card p-[18px]">
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-muted text-muted-foreground">
                {point.icon}
              </span>
              <p className="tabular mt-3 text-[24px] font-extrabold leading-[1.1] tracking-[-0.025em]">
                {point.value}
              </p>
              <p className="mt-[3px] text-[12.5px] font-semibold">{point.label}</p>
              <p className="mt-[3px] text-[11.5px] leading-[1.5] text-muted-foreground">{point.sub}</p>
            </div>
          ))}
        </div>
      </section>

      <section
        id="findings"
        className={cn("mx-auto max-w-[1180px] pb-[clamp(32px,4vw,48px)]", GUTTER, ANCHOR)}
      >
        <div className="overflow-hidden rounded-[16px] border border-border bg-card shadow-hero">
          <div className="flex items-center gap-2.5 border-b border-border px-5 py-3.5">
            <span className="flex flex-none gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-muted" />
              <span className="h-2.5 w-2.5 rounded-full bg-muted" />
              <span className="h-2.5 w-2.5 rounded-full bg-muted" />
            </span>
            <span className="tabular flex-1 truncate text-center text-[12px] text-muted-foreground">
              QT-4471-R2 · Nile Delta 220 kV Substation — Cable Supply Package
            </span>
          </div>
          <div className="flex flex-col gap-[18px] p-[clamp(18px,2.5vw,28px)] text-left">
            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,190px),1fr))] gap-3">
              {SEVERITY_CARDS.map((card) => (
                <div key={card.severity.kind} className={cn("rounded-[12px] border p-4", card.card)}>
                  <span className={cn("grid h-8 w-8 place-items-center rounded-lg", card.tile)}>{card.icon}</span>
                  <div className="tabular mt-3 text-[24px] font-extrabold tracking-[-0.02em]">{card.value}</div>
                  <div className="mt-0.5 text-[12px] text-muted-foreground">{card.severity.label}</div>
                  <div className="mt-1 text-[11px] text-muted-foreground">{card.severity.statSub}</div>
                </div>
              ))}
            </div>
            {HERO_FINDINGS.map((finding) => (
              <article
                key={finding.title}
                className="flex flex-wrap gap-3.5 rounded-[13px] border border-border px-[18px] py-4"
              >
                <span
                  className={cn(
                    "grid h-[38px] w-[38px] flex-none place-items-center rounded-[11px]",
                    finding.severity.tile,
                  )}
                >
                  {finding.icon}
                </span>
                <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
                  <div className="flex flex-wrap items-center gap-[9px]">
                    <h3 className="m-0 text-[14.5px] font-semibold tracking-[-0.01em]">{finding.title}</h3>
                    <span
                      className={cn(
                        "inline-flex h-5 flex-none items-center whitespace-nowrap rounded-full border px-[9px] text-[11px] font-semibold",
                        finding.severity.chip,
                      )}
                    >
                      {finding.severity.label}
                    </span>
                  </div>
                  <p className="m-0 text-[13.5px] leading-[1.65] text-pretty text-muted-foreground">{finding.body}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section
        id="phases"
        className={cn(
          "mx-auto max-w-[1180px] pb-[clamp(56px,7vw,96px)] pt-[clamp(24px,3vw,48px)]",
          GUTTER,
          ANCHOR,
        )}
      >
        <div className="mb-[26px] flex items-center gap-3">
          <h2 className="m-0 whitespace-nowrap text-[11px] font-bold uppercase tracking-[0.13em] text-muted-foreground">
            Three phases
          </h2>
          <span className="h-px flex-1 bg-border" />
        </div>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,260px),1fr))] gap-4">
          {PHASES.map((phase) => (
            <article
              key={phase.title}
              className="flex flex-col gap-3 rounded-[14px] border border-border bg-card p-[22px]"
            >
              <div className="flex items-center justify-between gap-2.5">
                <span className={cn("grid h-[38px] w-[38px] place-items-center rounded-[11px]", phase.tile)}>
                  {phase.icon}
                </span>
                <span
                  className={cn(
                    "whitespace-nowrap rounded-full border px-[9px] py-0.5 text-[11px] font-semibold",
                    phase.chip,
                  )}
                >
                  {phase.status}
                </span>
              </div>
              <h3 className="m-0 text-[17px] font-bold tracking-[-0.02em]">{phase.title}</h3>
              <p className="m-0 text-[13.5px] leading-[1.6] text-pretty text-muted-foreground">{phase.body}</p>
            </article>
          ))}
        </div>
      </section>

      <footer className="border-t border-border bg-card">
        <div
          className={cn(
            "mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-3 py-[22px]",
            GUTTER,
          )}
        >
          <div className="flex items-center gap-[9px]">
            <img src="/brand/wedy-mark.png" alt="" className="block h-[15px] w-[27px] object-contain" />
            <span className="text-[12.5px] text-muted-foreground">
              Bidsense — part of the Wedy.AI procurement suite
            </span>
          </div>
          <span className="text-[12.5px] text-muted-foreground">Internal use only</span>
        </div>
      </footer>
    </div>
  )
}
