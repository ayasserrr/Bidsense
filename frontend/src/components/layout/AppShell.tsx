import type { ReactNode } from "react"
import { Rail } from "./Rail"

/** Every signed-in screen's outer frame: the nav rail on the left, the page's
 * own header + main content on the right. Replaces each page's bare
 * `<div className="min-h-screen">` wrapper - the page itself is unchanged,
 * still rendering its own `<AppHeader />` and `<main>` as a child here. */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen max-[980px]:flex-col">
      <Rail />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}
