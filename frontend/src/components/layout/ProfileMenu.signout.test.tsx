import { describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { createMemoryRouter, RouterProvider } from "react-router-dom"
import { authApi, type AuthUser } from "../../api/authApi"
import { AuthProvider } from "../../lib/auth"
import { SignInPage } from "../../pages/SignInPage"
import { Protected } from "./Protected"
import { ProfileMenu } from "./ProfileMenu"

// Unlike ProfileMenu.test.tsx, the real AuthProvider, <Protected> and sign-in
// page run here on a data router, wired as App.tsx wires them: what this guards
// is how the cleared session and the route change interleave, which a faked
// session hides. Only the network layer underneath is faked.
vi.mock("../../api/authApi", () => ({
  authApi: { login: vi.fn(), me: vi.fn(), logout: vi.fn() },
}))

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

function renderApp(initialPath: string) {
  const router = createMemoryRouter(
    [
      { path: "/signin", element: <SignInPage /> },
      { path: "/dashboard", element: <Protected><p>Dashboard page</p></Protected> },
      { path: "/upload", element: <Protected><p>Upload page</p></Protected> },
      { path: "/offers/:offerId", element: <Protected><ProfileMenu /></Protected> },
    ],
    { initialEntries: [initialPath] },
  )
  render(
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>,
  )
  return router
}

describe("signing out from the profile menu", () => {
  it("doesn't send whoever signs in next back to the page that was signed out of", async () => {
    vi.mocked(authApi.me).mockResolvedValue(DIRECTORY_USER)
    vi.mocked(authApi.logout).mockResolvedValue(undefined)
    vi.mocked(authApi.login).mockResolvedValue(DIRECTORY_USER)
    const router = renderApp("/offers/42")

    await userEvent.click(await screen.findByRole("button", { name: "Your profile" }))
    const card = screen.getByRole("dialog", { name: "User profile" })
    await userEvent.click(within(card).getByRole("button", { name: "Sign out" }))
    const confirm = screen.getByRole("alertdialog", { name: "Sign out?" })
    await userEvent.click(within(confirm).getByRole("button", { name: "Sign out" }))

    expect(await screen.findByRole("heading", { name: "Sign in to Bidsense" })).toBeInTheDocument()
    expect(authApi.logout).toHaveBeenCalledTimes(1)
    // <Protected>'s redirect for a vanished session would carry
    // { from: "/offers/42" }; a deliberate sign-out arrives with nothing.
    expect(router.state.location.state).toBeNull()

    await userEvent.type(screen.getByLabelText(/company email/i), "mohanad.hassan")
    await userEvent.type(screen.getByLabelText(/^password$/i), "hunter2")
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }))

    // No `from` state survives a deliberate sign-out (checked above), so the
    // next sign-in lands on the dashboard - not back on the page that was
    // signed out of, and not on /upload either.
    expect(await screen.findByText("Dashboard page")).toBeInTheDocument()
    expect(router.state.location.pathname).toBe("/dashboard")
  })
})
