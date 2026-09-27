import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { LandingPage } from "./LandingPage"

// The real ThemeProvider reads localStorage at mount, and under Node 25 the
// runtime's own non-functional `localStorage` global shadows jsdom's - so the
// hook is faked rather than the provider rendered.
const theme = vi.hoisted(() => ({ current: "light" as "light" | "dark", toggleTheme: vi.fn() }))

vi.mock("../lib/theme", () => ({
  useTheme: () => ({ theme: theme.current, toggleTheme: theme.toggleTheme }),
}))

function renderLanding() {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/signin" element={<p>Sign-in screen</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

function section(id: string): HTMLElement {
  const element = document.getElementById(id)
  if (!element) throw new Error(`No #${id} section rendered`)
  return element
}

function themeToggle() {
  return screen.getByRole("button", { name: "Toggle theme" })
}

beforeEach(() => {
  theme.current = "light"
  theme.toggleTheme.mockReset()
})

describe("LandingPage", () => {
  it("renders the headline and both hero calls to action", () => {
    renderLanding()

    expect(
      screen.getByRole("heading", { level: 1, name: "Read every supplier offer before you sign it." }),
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Sign in with your network account" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "See what a report looks like" })).toHaveAttribute("href", "#findings")
  })

  it("points every sign-in control at /signin", async () => {
    renderLanding()

    const controls = screen.getAllByRole("link", { name: /sign in/i })
    expect(controls).toHaveLength(2)
    for (const control of controls) expect(control).toHaveAttribute("href", "/signin")
    expect(screen.queryByRole("button", { name: /sign in/i })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole("link", { name: "Sign in" }))
    expect(screen.getByText("Sign-in screen")).toBeInTheDocument()
  })

  it.each([
    ["All", "Pages read per offer", "Every page of every file, scans included"],
    ["20", "Required terms checked", "And what the supplier failed to state"],
    ["Minutes", "Runs on the server", "Close the tab if you like — the check keeps going"],
    ["10", "Engineering disciplines", "Every line item sorted, correctable by hand"],
  ])("shows the %s proof point", (value, label, sub) => {
    renderLanding()

    const proof = within(section("what"))
    expect(proof.getByText(value)).toBeInTheDocument()
    expect(proof.getByText(label)).toBeInTheDocument()
    expect(proof.getByText(sub)).toBeInTheDocument()
  })

  it("makes no unmeasured page-count or read-time claims", () => {
    renderLanding()

    const text = document.body.textContent ?? ""
    expect(text).not.toContain("42")
    expect(text).not.toContain("6m 40s")
    expect(text).not.toContain("Average read time")
  })

  it.each([
    ["What it does", "#what"],
    ["A real report", "#findings"],
    ["Roadmap", "#phases"],
  ])("anchors the %s nav link to its section", (name, href) => {
    renderLanding()

    const nav = within(screen.getByRole("navigation"))
    expect(nav.getByRole("link", { name })).toHaveAttribute("href", href)
    expect(section(href.slice(1))).toBeInTheDocument()
  })

  it("toggles the theme from the header", async () => {
    renderLanding()

    await userEvent.click(themeToggle())
    expect(theme.toggleTheme).toHaveBeenCalledOnce()
  })

  it("shows the moon in light theme", () => {
    renderLanding()
    expect(themeToggle().querySelector('path[d^="M12 3a6 6"]')).not.toBeNull()
    expect(themeToggle().querySelector(".lucide-sun")).toBeNull()
  })

  it("shows the sun in dark theme", () => {
    theme.current = "dark"
    renderLanding()
    expect(themeToggle().querySelector(".lucide-sun")).not.toBeNull()
  })
})
