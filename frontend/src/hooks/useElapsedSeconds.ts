import { useEffect, useState } from "react"

/** Ticks once a second while `since` is set - a real elapsed-time readout,
 * never a fabricated progress percentage. */
export function useElapsedSeconds(since: number | null): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (since === null) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [since])

  if (since === null) return 0
  return Math.max(0, Math.floor((now - since) / 1000))
}

export function formatDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes === 0) return `${seconds}s`
  return `${minutes}m ${seconds.toString().padStart(2, "0")}s`
}
