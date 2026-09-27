import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  BadgeCheck,
  Briefcase,
  Building2,
  CalendarDays,
  ChevronDown,
  Clock,
  Landmark,
  LogOut,
  Mail,
  MapPin,
  ShieldCheck,
  Users,
  X,
  type LucideIcon,
} from "lucide-react"
import { ConfirmDialog, useConfirmAction } from "../ui/ConfirmDialog"
import { useAuth } from "../../lib/auth"
import { cn } from "../../lib/cn"
import { formatDate } from "../../lib/format"

const focusRing = "outline-none focus-visible:ring-2 focus-visible:ring-accent-40"

const badge = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.68rem] font-semibold"

/** Two-letter avatar from the directory display name ("Mohanad Hassan" -> "MH").
 * Falls back to the username so the avatar is never blank. */
function initials(name: string, fallback: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
  const source = parts[0] || fallback
  return source.slice(0, 2).toUpperCase()
}

/** "Mohanad Hassan" -> "Mohanad H.", short enough for the header. Falls back
 * to the username for an account the directory gave no display name. */
function shortName(name: string, fallback: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return `${parts[0]} ${parts[parts.length - 1][0].toUpperCase()}.`
  return parts[0] || fallback
}

/** Date and time, since the last sign-in is often today. Empty for a missing or
 * unreadable value, which hides the row. */
function formatDateTime(iso: string | null): string {
  if (!iso) return ""
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ""
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

/** One profile attribute. Renders nothing for an empty value: the directory
 * leaves plenty of fields blank, and a row of dashes reads as broken data. */
function Row({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string }) {
  if (!value) return null
  return (
    <div className="flex items-start gap-3 py-2">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0">
        <div className="text-[0.68rem] font-medium uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="truncate text-sm text-foreground" title={value}>
          {value}
        </div>
      </div>
    </div>
  )
}

/** The signed-in account in the header: opens the person's directory profile,
 * with sign-out inside it behind a confirmation - a bare sign-out button in the
 * header ended the session on a single stray click. */
export function ProfileMenu() {
  const { user, refresh, signOut } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  const confirmSignOut = useConfirmAction(async () => {
    setOpen(false)
    await signOut()
    // flushSync commits the route change in the same render as the cleared
    // user. As a plain transition it renders after that update, so <Protected>
    // on the page being left redirects first, with `from` pointing at it - and
    // the next person to sign in on this machine is sent back to that page.
    navigate("/signin", { replace: true, flushSync: true })
  })
  const confirming = confirmSignOut.dialogProps.open

  // The user held here is from when the app loaded; a sign-in elsewhere (which
  // re-reads the directory) or a role change since then only shows after a refetch.
  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

  // Off while the confirmation is up, so Escape there backs out of that
  // dialog alone instead of closing the card underneath it too.
  useEffect(() => {
    if (!open || confirming) return
    closeRef.current?.focus()
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return
      setOpen(false)
      triggerRef.current?.focus()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, confirming])

  function closeCard() {
    setOpen(false)
    // Back to the button that opened the card, rather than dropping focus on <body>.
    triggerRef.current?.focus()
  }

  if (!user) return null

  const name = user.display_name || user.username
  const avatar = initials(user.display_name, user.username)

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Your profile"
        aria-haspopup="dialog"
        aria-expanded={open}
        title={name}
        className={cn(
          "inline-flex h-9 items-center gap-2 rounded-full border border-transparent py-0 pl-1 pr-2 transition-colors hover:bg-muted",
          focusRing,
        )}
      >
        <span className="grid h-7 w-7 flex-none place-items-center rounded-full bg-accent text-[11px] font-bold tracking-[0.02em] text-accent-foreground">
          {avatar}
        </span>
        <span className="hidden whitespace-nowrap text-[13px] font-medium text-foreground sm:inline">
          {shortName(user.display_name, user.username)}
        </span>
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={closeCard}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label="User profile"
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-md overflow-hidden rounded-2xl border border-border bg-card shadow-xl"
          >
            <div className="relative bg-muted-60 px-6 pb-5 pt-6">
              <button
                ref={closeRef}
                type="button"
                onClick={closeCard}
                aria-label="Close"
                className={cn(
                  "absolute right-3 top-3 rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground",
                  focusRing,
                )}
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
              <div className="flex items-center gap-4 pr-6">
                <span className="grid h-14 w-14 flex-none place-items-center rounded-full bg-accent-15 text-lg font-bold text-accent">
                  {avatar}
                </span>
                <div className="min-w-0">
                  <h2 className="truncate text-base font-semibold text-foreground">{name}</h2>
                  {user.job_title && <p className="truncate text-sm text-muted-foreground">{user.job_title}</p>}
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    {user.auth_source === "ldap" ? (
                      <span className={cn(badge, "bg-accent-10 text-accent")}>
                        <ShieldCheck className="h-3 w-3" aria-hidden />
                        Corporate account
                      </span>
                    ) : (
                      <span className={cn(badge, "bg-muted text-foreground-80")}>Local account</span>
                    )}
                    {user.is_admin && (
                      <span className={cn(badge, "bg-muted text-foreground-80")}>
                        <BadgeCheck className="h-3 w-3" aria-hidden />
                        Admin
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>

            <div className="max-h-[55vh] overflow-y-auto px-6 py-4">
              <div className="divide-y divide-border-60">
                <Row icon={Mail} label="Email" value={user.email} />
                <Row icon={Landmark} label="Company" value={user.company} />
                <Row icon={Users} label="Department" value={user.department} />
                <Row icon={Briefcase} label="Job title" value={user.job_title} />
                <Row icon={Building2} label="Office" value={user.office} />
                <Row icon={MapPin} label="City" value={user.city} />
                <Row icon={Clock} label="Last sign-in" value={formatDateTime(user.last_login_at)} />
                <Row icon={CalendarDays} label="Member since" value={formatDate(user.created_at)} />
              </div>
            </div>

            <div className="flex items-center gap-3 border-t border-border bg-muted-40 px-6 py-3">
              <p className="min-w-0 flex-1 text-[0.72rem] text-muted-foreground">
                Your details come from your company directory and update each time you sign in.
              </p>
              <button
                type="button"
                onClick={confirmSignOut.request}
                className={cn(
                  "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-border bg-card px-2.5 text-xs font-medium text-muted-foreground transition hover:border-destructive-30 hover:text-destructive",
                  focusRing,
                )}
              >
                <LogOut className="h-3.5 w-3.5" aria-hidden />
                Sign out
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        {...confirmSignOut.dialogProps}
        title="Sign out?"
        body="You'll need your corporate password to sign back in."
        confirmLabel="Sign out"
        cancelLabel="Cancel"
      />
    </>
  )
}
