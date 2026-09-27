import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from "react-router-dom"
import type { AuthUser } from "../../api/authApi"
import { ProfileMenu } from "./ProfileMenu"

// What the corporate directory returned for a real account at login, as
// /auth/me then serves it: the directory's literal "[]" office and city are
// already cleaned to "", its `title` is stored as job_title, and the email is
// lowercased.
const DIRECTORY_USER: AuthUser = {
  id: 1,
  username: "mohanad.hassan",
  email: "mohanad.hassan@elsewedy.com",
  display_name: "Mohanad Hassan",
  department: "AI & Data Science",
  company: "Elsewedy Electric",
  job_title: "Data Science Senior Engineer",
  office: "",
  city: "",
  role: "user",
  is_admin: false,
  auth_source: "ldap",
  last_login_at: "2026-09-15T08:30:00Z",
  created_at: "2026-03-02T09:00:00Z",
}

// The auth context is faked rather than the real provider rendered: these
// tests are about what the menu does with the session, not how it is fetched.
const auth = vi.hoisted(() => ({
  user: null as AuthUser | null,
  refresh: vi.fn(),
  signOut: vi.fn(),
}))

vi.mock("../../lib/auth", () => ({
  useAuth: () => ({
    user: auth.user,
    loading: false,
    signIn: vi.fn(),
    refresh: auth.refresh,
    signOut: auth.signOut,
  }),
}))

function LocationProbe() {
  const location = useLocation()
  const navigationType = useNavigationType()
  return (
    <p data-testid="location" data-navigation={navigationType}>
      {location.pathname}
    </p>
  )
}

function renderMenu() {
  render(
    <MemoryRouter initialEntries={["/upload"]}>
      <ProfileMenu />
      <Routes>
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

function trigger() {
  return screen.getByRole("button", { name: "Your profile" })
}

async function openProfile() {
  await userEvent.click(trigger())
  return screen.getByRole("dialog", { name: "User profile" })
}

async function requestSignOut(card: HTMLElement) {
  await userEvent.click(within(card).getByRole("button", { name: "Sign out" }))
  return screen.getByRole("alertdialog", { name: "Sign out?" })
}

beforeEach(() => {
  auth.user = DIRECTORY_USER
  auth.refresh.mockReset().mockResolvedValue(undefined)
  auth.signOut.mockReset().mockResolvedValue(undefined)
})

describe("ProfileMenu", () => {
  it("shows the directory account's initials and short name on the trigger", () => {
    renderMenu()

    expect(trigger()).toHaveAttribute("aria-haspopup", "dialog")
    expect(within(trigger()).getByText("MH")).toBeInTheDocument()
    expect(within(trigger()).getByText("Mohanad H.")).toBeInTheDocument()
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(auth.refresh).not.toHaveBeenCalled()
  })

  it("opens a card with the directory details and leaves out what the directory left empty", async () => {
    renderMenu()
    const card = await openProfile()

    expect(within(card).getByRole("heading", { name: "Mohanad Hassan" })).toBeInTheDocument()
    expect(within(card).getByText("mohanad.hassan@elsewedy.com")).toBeInTheDocument()
    expect(within(card).getByText("Elsewedy Electric")).toBeInTheDocument()
    expect(within(card).getByText("AI & Data Science")).toBeInTheDocument()
    expect(within(card).getByText("Job title")).toBeInTheDocument()
    // Once under the name and once as its own row.
    expect(within(card).getAllByText("Data Science Senior Engineer")).toHaveLength(2)
    expect(within(card).getByText("Corporate account")).toBeInTheDocument()
    expect(within(card).getByText("Last sign-in")).toBeInTheDocument()
    expect(within(card).getByText("Member since")).toBeInTheDocument()

    expect(within(card).queryByText("Office")).not.toBeInTheDocument()
    expect(within(card).queryByText("City")).not.toBeInTheDocument()
    expect(within(card).queryByText("Admin")).not.toBeInTheDocument()
  })

  it("labels a local administrator account", async () => {
    auth.user = { ...DIRECTORY_USER, auth_source: "local", is_admin: true }
    renderMenu()
    const card = await openProfile()

    expect(within(card).getByText("Local account")).toBeInTheDocument()
    expect(within(card).getByText("Admin")).toBeInTheDocument()
    expect(within(card).queryByText("Corporate account")).not.toBeInTheDocument()
  })

  it("re-fetches the details each time the card opens", async () => {
    renderMenu()

    await openProfile()
    expect(auth.refresh).toHaveBeenCalledTimes(1)

    await userEvent.click(screen.getByRole("button", { name: "Close" }))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()

    await openProfile()
    expect(auth.refresh).toHaveBeenCalledTimes(2)
  })

  it("closes the card on Escape and on a backdrop click", async () => {
    renderMenu()

    await openProfile()
    await userEvent.keyboard("{Escape}")
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(trigger()).toHaveFocus()

    const card = await openProfile()
    const backdrop = card.parentElement
    if (!backdrop) throw new Error("The card rendered without a backdrop")
    await userEvent.click(backdrop)
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("asks before signing out, and Cancel goes back to the card still signed in", async () => {
    renderMenu()
    const card = await openProfile()

    const confirm = await requestSignOut(card)
    expect(confirm).toHaveAccessibleDescription("You'll need your corporate password to sign back in.")
    expect(auth.signOut).not.toHaveBeenCalled()

    await userEvent.click(within(confirm).getByRole("button", { name: "Cancel" }))

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    expect(screen.getByRole("dialog", { name: "User profile" })).toBeInTheDocument()
    expect(auth.signOut).not.toHaveBeenCalled()
    expect(screen.getByTestId("location")).toHaveTextContent("/upload")
  })

  it("dismisses only the confirmation when Escape is pressed on it", async () => {
    renderMenu()
    const card = await openProfile()
    await requestSignOut(card)

    await userEvent.keyboard("{Escape}")

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
    expect(screen.getByRole("dialog", { name: "User profile" })).toBeInTheDocument()
    expect(auth.signOut).not.toHaveBeenCalled()
  })

  it("signs out once, and only then replaces the page with the sign-in screen", async () => {
    // Held open to see the in-flight moment: leaving before the server has
    // ended the session would show the sign-in screen over a live session.
    let finishSignOut = () => {}
    auth.signOut.mockReturnValue(new Promise<void>((resolve) => (finishSignOut = resolve)))
    renderMenu()
    const card = await openProfile()
    const confirm = await requestSignOut(card)

    await userEvent.click(within(confirm).getByRole("button", { name: "Sign out" }))

    expect(auth.signOut).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(within(confirm).getByRole("button", { name: "Working…" })).toBeDisabled()
    expect(screen.getByTestId("location")).toHaveTextContent("/upload")

    finishSignOut()

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/signin"))
    // Replaced rather than pushed, so Back doesn't return to a signed-in page.
    expect(screen.getByTestId("location")).toHaveAttribute("data-navigation", "REPLACE")
    expect(auth.signOut).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument())
  })

  it("renders nothing without a signed-in user", () => {
    auth.user = null
    renderMenu()

    expect(screen.queryByRole("button", { name: "Your profile" })).not.toBeInTheDocument()
  })
})
