import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import { cn } from "../../lib/cn"

const BUTTON =
  "h-9 rounded-md px-3 text-sm font-medium transition outline-none focus-visible:ring-2 focus-visible:ring-accent-40 disabled:cursor-not-allowed disabled:opacity-50"

const TONES = {
  destructive: "bg-destructive text-destructive-foreground hover:opacity-90",
  accent: "bg-accent text-accent-foreground hover:opacity-90",
} as const

interface ConfirmDialogProps {
  open: boolean
  title: string
  body?: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  tone?: keyof typeof TONES
  /** The confirmed action is running: both buttons disable and nothing
   * dismisses the dialog, since it is the only sign the action is underway. */
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Qualisense ConfirmDialog - a blocking "are you sure" before an action the
 * user can't take back. Focus opens on Cancel, so an Enter pressed out of
 * habit backs out instead of confirming. */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "destructive",
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const bodyId = useId()

  // Keyed on `open` alone: callers usually pass a new onCancel every render,
  // and re-running this with it would pull focus back to Cancel each time.
  useEffect(() => {
    if (open) cancelRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, busy, onCancel])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[60] grid place-items-center bg-black/50 p-4"
      onClick={() => {
        if (!busy) onCancel()
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={body ? bodyId : undefined}
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-sm overflow-hidden rounded-2xl border border-border bg-card shadow-soft"
      >
        <div className="px-6 pb-4 pt-6">
          <h2 id={titleId} className="text-base font-semibold text-foreground">
            {title}
          </h2>
          {body && (
            <div id={bodyId} className="mt-2 text-sm text-muted-foreground">
              {body}
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-border bg-muted-40 px-6 py-3">
          <button
            ref={cancelRef}
            type="button"
            disabled={busy}
            onClick={onCancel}
            className={cn(BUTTON, "border border-border bg-card text-foreground hover:bg-muted")}
          >
            {cancelLabel}
          </button>
          <button type="button" disabled={busy} onClick={onConfirm} className={cn(BUTTON, TONES[tone])}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

/** Puts an action behind a ConfirmDialog: `request()` opens the dialog, and
 * confirming runs the action with the dialog held busy until it settles.
 * Spread `dialogProps` onto the dialog alongside its title and labels.
 *
 * Kept beside the dialog it drives, at the cost of a full reload instead of a
 * hot swap when this file is edited in dev. */
// oxlint-disable-next-line react/only-export-components
export function useConfirmAction(action: () => void | Promise<void>) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  async function onConfirm() {
    setBusy(true)
    try {
      await action()
    } finally {
      setBusy(false)
      setOpen(false)
    }
  }

  return {
    request: () => setOpen(true),
    dialogProps: { open, busy, onConfirm, onCancel: () => setOpen(false) },
  }
}
