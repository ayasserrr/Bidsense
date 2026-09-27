import { useEffect, useState, type FormEvent } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { ArrowLeft, ShieldCheck } from "lucide-react"
import { useAuth } from "../lib/auth"
import { ApiError } from "../api/types"

// The icons are the design's own paths. lucide's current File, Calculator and
// Quote are drawn differently (a rounded fold, a portrait calculator), so the
// nearest lucide icon would not match the brand panel.
const TRUST_POINTS = [
  {
    title: "Every page, before anything is called missing",
    body: "A term stated only in a separate datasheet is found, not reported as a gap.",
    icon: "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7zM14 2v4a2 2 0 0 0 2 2h4",
  },
  {
    title: "The numbers are re-added, not trusted",
    body: "Quantity × price, subtotals and the grand total are checked arithmetically.",
    icon: "M4 2h16a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zM8 6h8M16 14v4M16 10h.01M12 10h.01M8 10h.01M12 14h.01M8 14h.01M12 18h.01M8 18h.01",
  },
  {
    title: "Findings are quoted from the source",
    body: "Each one carries the verbatim wording, the file and the page it came from.",
    icon: "M16 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h1a1 1 0 0 1 1 1v1a2 2 0 0 1-2 2h-1a1 1 0 0 0-1 1v1a1 1 0 0 0 1 1h1a6 6 0 0 0 6-6V5a2 2 0 0 0-2-2zM5 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h1a1 1 0 0 1 1 1v1a2 2 0 0 1-2 2H4a1 1 0 0 0-1 1v1a1 1 0 0 0 1 1h1a6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z",
  },
]

const INPUT_CLASS =
  "h-11 w-full rounded-[10px] border border-input bg-background px-3 text-[14px] text-foreground outline-none focus:border-ring"

/** Signs in against the corporate directory.
 *
 * Either the bare corporate username or the full address works - the backend
 * completes a bare name to a UPN before asking the directory, which rejects
 * anything without an "@". That is also why the email field is type="text":
 * the browser's own email validation would refuse a bare username.
 */
export function SignInPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, signIn } = useAuth()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  // On by default: most sign-ins are from a person's own workstation, and
  // unticking it is the shared-machine case.
  const [remember, setRemember] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Where <Protected> was trying to send them before the redirect here, or
  // the dashboard - "where every offer stands this week" - for a plain visit
  // to /signin with nowhere particular to return to.
  const from = (location.state as { from?: string } | null)?.from ?? "/dashboard"

  useEffect(() => {
    // Covers both arriving here already signed in and the moment sign-in
    // succeeds, so there is one redirect path rather than two.
    if (user) navigate(from, { replace: true })
  }, [user, from, navigate])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!username.trim() || !password) {
      setError("Enter your company email and password to continue.")
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      await signIn(username.trim(), password, remember)
      // The effect above navigates once `user` lands.
    } catch (err) {
      // A rejected password and an unreachable directory need different
      // wording: telling someone their password is wrong when the directory
      // was simply down sends them off to reset a password that was fine.
      if (err instanceof ApiError && err.status === 503) {
        setError("The corporate sign-in service can't be reached right now. Please try again in a few minutes.")
      } else if (err instanceof ApiError && err.status === 429) {
        setError(err.message)
      } else if (err instanceof ApiError && err.message) {
        setError(err.message)
      } else {
        setError("Sign-in failed. Please try again.")
      }
      setPassword("")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    // Below md the brand panel is hidden and the form becomes one centred
    // column - the design system's AuthShell breakpoint.
    <div className="block min-h-screen grid-cols-[minmax(0,46fr)_minmax(0,54fr)] bg-background md:grid">
      <aside className="relative hidden flex-col overflow-hidden bg-[#131313] p-10 text-white md:flex">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -left-24 -top-24 h-80 w-80 rounded-full bg-[rgba(219,1,10,0.25)] blur-3xl"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-32 -right-16 h-96 w-96 rounded-full bg-[rgba(219,1,10,0.15)] blur-3xl"
        />
        <Link to="/" className="relative z-10 inline-flex items-center gap-[11px]">
          <img src="/brand/wedy-lockup-dark.svg" alt="WEDY.AI" className="block h-9 w-auto object-contain" />
        </Link>
        <div className="relative z-10 mt-auto max-w-[460px]">
          <h2 className="m-0 text-[clamp(28px,3.2vw,38px)] font-bold leading-[1.1] tracking-[-0.02em]">
            Read every supplier offer.
            <br />
            <span className="text-[#ff6b7d]">Trust every number.</span>
          </h2>
          <div className="mt-9 flex flex-col gap-5">
            {TRUST_POINTS.map((point) => (
              <div key={point.title} className="flex items-start gap-3.5">
                <span className="grid h-9 w-9 flex-none place-items-center rounded-lg bg-[rgba(255,255,255,0.1)] text-white">
                  <svg
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    aria-hidden="true"
                  >
                    <path d={point.icon} />
                  </svg>
                </span>
                <div>
                  <div className="text-[14px] font-semibold">{point.title}</div>
                  <div className="mt-0.5 text-[13px] font-light leading-[1.5] text-[rgba(255,255,255,0.6)]">
                    {point.body}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
        <p className="relative z-10 mt-auto pt-10 text-[11px] text-[rgba(255,255,255,0.4)]">Elsewedy Electric · Wedy.AI</p>
      </aside>

      <main className="flex min-h-screen flex-col justify-center px-[clamp(24px,4vw,48px)] py-12">
        <div className="mx-auto w-full max-w-[384px]">
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-muted-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            Back to Bidsense
          </Link>
          <div className="mt-7">
            <h1 className="m-0 text-[27px] font-extrabold leading-[1.2] tracking-[-0.02em]">Sign in to Bidsense</h1>
            <p className="mt-2 text-[14px] leading-[1.55] text-muted-foreground">
              Use your company email and the password you sign in to your workstation with. There is no separate
              Bidsense password.
            </p>
          </div>

          <form className="mt-7 flex flex-col gap-4" onSubmit={onSubmit}>
            {error && (
              <div
                role="alert"
                className="rounded-lg border border-destructive-30 bg-destructive-10 px-3 py-[9px] text-[13px] text-destructive"
              >
                {error}
              </div>
            )}

            <label className="block">
              <span className="mb-1.5 flex items-center justify-between gap-2">
                <span className="text-[12px] font-medium text-foreground">Company email</span>
              </span>
              <input
                type="text"
                inputMode="email"
                autoComplete="username"
                // type="text" loses the capitalisation and spell-check
                // suppression type="email" would have given for free.
                autoCapitalize="none"
                spellCheck={false}
                value={username}
                onChange={(e) => {
                  setUsername(e.target.value)
                  setError(null)
                }}
                placeholder="firstname.lastname@elsewedy.com"
                className={INPUT_CLASS}
              />
              <span className="mt-1 block text-[12px] text-muted-foreground">
                Your work address — the same one you use for Outlook.
              </span>
            </label>

            <label className="block">
              <span className="mb-1.5 flex items-center justify-between gap-2">
                <span className="text-[12px] font-medium text-foreground">Password</span>
              </span>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value)
                  setError(null)
                }}
                placeholder="••••••••"
                className={INPUT_CLASS}
              />
            </label>

            <label className="flex cursor-pointer items-center gap-2 text-[12.5px] text-muted-foreground">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="h-3.5 w-3.5 accent-accent"
              />
              Keep me signed in on this workstation
            </label>

            <button
              type="submit"
              disabled={submitting}
              className="inline-flex h-11 w-full cursor-pointer items-center justify-center gap-2 rounded-[10px] border-0 bg-accent text-[14px] font-semibold text-accent-foreground shadow-glow disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none"
            >
              <ShieldCheck className="h-4 w-4" aria-hidden />
              {submitting ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="mt-6 text-[13px] leading-[1.55] text-muted-foreground">
            Anyone with an Elsewedy directory account can sign in. You see the offers from your own department;
            administrators see every department.
          </p>
        </div>
      </main>
    </div>
  )
}
