import { useEffect, useRef, useState } from "react"
import { Check, Copy } from "lucide-react"
import { cn } from "../../lib/cn"

const focusRing = "outline-none focus-visible:ring-2 focus-visible:ring-accent-40"

interface EmailDraftModalProps {
  open: boolean
  emailTo: string | null
  emailSubject: string
  emailBody: string
  onClose: () => void
}

/** The clarification-email draft, in a modal of its own rather than
 * ConfirmDialog: this holds editable-looking text to read and copy, not a
 * yes/no prompt, but follows the same conventions - focus opens on the safe
 * action (Close), Escape closes, the backdrop closes, and focus is the
 * caller's to return (see ReviewSummarySection, which refocuses its own
 * trigger button on close, same as ProfileMenu does for its card). */
export function EmailDraftModal({ open, emailTo, emailSubject, emailBody, onClose }: EmailDraftModalProps) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const [copied, setCopied] = useState(false)

  // Keyed on `open` alone, same reasoning as ConfirmDialog: a caller that
  // passes a new onClose every render must not pull focus back each time.
  useEffect(() => {
    if (open) closeRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  // A per-viewer UI nicety that never needs to survive anything - closing the
  // modal before the timeout fires is fine, there is nothing left to update.
  useEffect(() => {
    if (!copied) return
    const id = setTimeout(() => setCopied(false), 1_500)
    return () => clearTimeout(id)
  }, [copied])

  if (!open) return null

  async function copyText() {
    const text = `To: ${emailTo ?? "(no recipient on file)"}\nSubject: ${emailSubject}\n\n${emailBody}`
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      // Clipboard access can be denied (permissions, insecure context) - the
      // draft is still fully visible and selectable on screen either way.
    }
  }

  return (
    <div className="fixed inset-0 z-[70] grid place-items-center bg-black/50 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="email-draft-title"
        onClick={(event) => event.stopPropagation()}
        className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-soft"
      >
        <div className="border-b border-border px-5 py-3.5">
          <h2 id="email-draft-title" className="m-0 text-[15px] font-bold">
            Clarification email
          </h2>
        </div>

        <div className="flex flex-col gap-3.5 overflow-y-auto px-5 py-4">
          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">To</span>
            {emailTo ? (
              <span className="text-sm">{emailTo}</span>
            ) : (
              <span className="text-sm italic text-muted-foreground">
                No recipient email on file - fill one in before sending.
              </span>
            )}
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">
              Subject
            </span>
            <span className="text-sm font-medium">{emailSubject}</span>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">Body</span>
            {/* Plain text with real newlines, rendered as-is - never parsed as
                markdown/HTML, which the draft was never written to be. */}
            <p className="m-0 whitespace-pre-wrap text-sm leading-[1.55] text-foreground">{emailBody}</p>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border bg-muted-40 px-5 py-3">
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className={cn(
              "h-9 rounded-md border border-border bg-card px-3 text-sm font-medium text-foreground hover:bg-muted",
              focusRing,
            )}
          >
            Close
          </button>
          <button
            type="button"
            onClick={() => void copyText()}
            className={cn(
              "inline-flex h-9 items-center gap-1.5 rounded-md bg-accent px-3 text-sm font-medium text-accent-foreground hover:opacity-90",
              focusRing,
            )}
          >
            {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
            {copied ? "Copied" : "Copy text"}
          </button>
        </div>
      </div>
    </div>
  )
}
