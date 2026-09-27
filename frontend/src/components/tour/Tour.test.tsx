import { describe, expect, it, vi } from "vitest"
import { act, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import type { AuthUser } from "../../api/authApi"
import { Tour } from "./Tour"

const USER = { id: 1, display_name: "Yara Kamal" } as AuthUser

vi.mock("../../lib/auth", () => ({
  useAuth: () => ({ user: USER, loading: false, signIn: vi.fn(), refresh: vi.fn(), signOut: vi.fn() }),
}))

vi.mock("../../lib/tour", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/tour")>()
  return { ...actual, hasSeenTour: () => false, markTourSeen: vi.fn() }
})

function renderTour(rect: DOMRect) {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(() => rect)
  render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <button data-tour="nav">Dashboard</button>
      <Tour />
    </MemoryRouter>,
  )
}

function rect(top: number, left: number): DOMRect {
  return { top, left, width: 40, height: 24, bottom: top + 24, right: left + 40, x: left, y: top, toJSON: () => ({}) }
}

describe("Tour", () => {
  it("re-measures its anchor on resize instead of keeping stale coordinates", async () => {
    renderTour(rect(100, 50))
    await screen.findByText("Five places, nothing hidden")

    const ringBefore = document.querySelector(".ring-2.ring-accent") as HTMLElement
    expect(ringBefore.style.top).toBe("92px") // rect.top(100) - PAD(8)

    // The anchor moved (e.g. a breakpoint change collapsed the rail) without
    // unmounting - only a resize listener would notice.
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(() => rect(300, 50))
    act(() => {
      window.dispatchEvent(new Event("resize"))
    })

    await waitFor(() => {
      const ring = document.querySelector(".ring-2.ring-accent") as HTMLElement
      expect(ring.style.top).toBe("292px")
    })
  })

  it("falls back to a centered tooltip, not stale coordinates, if the anchor disappears on resize", async () => {
    renderTour(rect(100, 50))
    await screen.findByText("Five places, nothing hidden")

    // The anchor unmounted (or no longer matches) by the time resize fires -
    // simulated by detaching the attribute the selector looks for, rather
    // than removing the node itself.
    document.querySelector('[data-tour="nav"]')?.removeAttribute("data-tour")
    act(() => {
      window.dispatchEvent(new Event("resize"))
    })

    await waitFor(() => {
      expect(document.querySelector(".ring-2.ring-accent")).not.toBeInTheDocument()
    })
    expect(screen.getByText("Five places, nothing hidden")).toBeInTheDocument()
  })
})
