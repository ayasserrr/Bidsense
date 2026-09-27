import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"
import { authApi, type AuthUser } from "../api/authApi"
import { ApiError } from "../api/types"
import { AuthProvider } from "../lib/auth"
import { SignInPage } from "./SignInPage"

// The real AuthProvider runs, so these tests also cover signIn handing
// `remember` through to the API; only the network layer underneath is faked.
vi.mock("../api/authApi", () => ({
  authApi: { login: vi.fn(), me: vi.fn(), logout: vi.fn() },
}))

const SIGNED_IN: AuthUser = {
  id: 1,
  username: "firstname.lastname",
  email: "firstname.lastname@elsewedy.com",
  display_name: "Firstname Lastname",
  department: "Presales",
  company: "Elsewedy Electric",
  job_title: "Presales Engineer",
  office: "HQ",
  city: "Cairo",
  role: "user",
  is_admin: false,
  auth_source: "ldap",
  last_login_at: null,
  created_at: null,
}

function LocationProbe() {
  const location = useLocation()
  return <p data-testid="location">{location.pathname}</p>
}

function renderSignIn(from?: string) {
  render(
    <AuthProvider>
      <MemoryRouter initialEntries={[{ pathname: "/signin", state: from ? { from } : null }]}>
        <Routes>
          <Route path="/signin" element={<SignInPage />} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  )
}

async function fillCredentials() {
  await userEvent.type(screen.getByLabelText(/company email/i), "firstname.lastname@elsewedy.com")
  await userEvent.type(screen.getByLabelText(/^password$/i), "hunter2")
}

function submitButton() {
  return screen.getByRole("button", { name: "Sign in" })
}

beforeEach(() => {
  vi.mocked(authApi.login).mockReset()
  // A session check that never settles leaves the page as a signed-out
  // visitor sees it, without a stray state update landing mid-test.
  vi.mocked(authApi.me).mockReturnValue(new Promise(() => {}))
})

describe("SignInPage", () => {
  it("blocks an empty submit with the validation alert and never calls the directory", async () => {
    renderSignIn()

    await userEvent.click(submitButton())
    expect(screen.getByRole("alert")).toHaveTextContent("Enter your company email and password to continue.")

    await userEvent.type(screen.getByLabelText(/company email/i), "firstname.lastname@elsewedy.com")
    await userEvent.click(submitButton())
    expect(screen.getByRole("alert")).toHaveTextContent("Enter your company email and password to continue.")

    expect(authApi.login).not.toHaveBeenCalled()
  })

  it("keeps the session by default and sends remember=false once unchecked", async () => {
    vi.mocked(authApi.login).mockResolvedValue(SIGNED_IN)
    renderSignIn()

    const remember = screen.getByRole("checkbox", { name: /keep me signed in on this workstation/i })
    expect(remember).toBeChecked()
    await userEvent.click(remember)
    expect(remember).not.toBeChecked()

    await fillCredentials()
    await userEvent.click(submitButton())

    expect(authApi.login).toHaveBeenCalledWith("firstname.lastname@elsewedy.com", "hunter2", false)
  })

  it("sends the user on to where they were headed once signed in", async () => {
    vi.mocked(authApi.login).mockResolvedValue(SIGNED_IN)
    renderSignIn("/offers/42")

    await fillCredentials()
    await userEvent.click(submitButton())

    expect(await screen.findByTestId("location")).toHaveTextContent("/offers/42")
    expect(authApi.login).toHaveBeenCalledWith("firstname.lastname@elsewedy.com", "hunter2", true)
  })

  it("accepts a bare username, trimmed, instead of demanding an email address", async () => {
    vi.mocked(authApi.login).mockResolvedValue(SIGNED_IN)
    renderSignIn()

    const email = screen.getByLabelText(/company email/i)
    expect(email).toHaveAttribute("type", "text")
    await userEvent.type(email, "  firstname.lastname ")
    await userEvent.type(screen.getByLabelText(/^password$/i), "hunter2")
    await userEvent.click(submitButton())

    expect(authApi.login).toHaveBeenCalledWith("firstname.lastname", "hunter2", true)
    expect(await screen.findByTestId("location")).toHaveTextContent("/dashboard")
  })

  it("disables the button while the directory is being asked", async () => {
    vi.mocked(authApi.login).mockReturnValue(new Promise(() => {}))
    renderSignIn()

    await fillCredentials()
    await userEvent.click(submitButton())

    expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled()
  })

  it("shows the server's reason and clears only the password when sign-in fails", async () => {
    vi.mocked(authApi.login).mockRejectedValue(
      new ApiError("Invalid username or password.", 401, { detail: "Invalid username or password." }),
    )
    renderSignIn()

    await fillCredentials()
    await userEvent.click(submitButton())

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password.")
    expect(screen.getByLabelText(/^password$/i)).toHaveValue("")
    expect(screen.getByLabelText(/company email/i)).toHaveValue("firstname.lastname@elsewedy.com")
    expect(submitButton()).toBeEnabled()
  })

  it("tells an unreachable directory apart from a wrong password", async () => {
    vi.mocked(authApi.login).mockRejectedValue(new ApiError("Service Unavailable", 503, {}))
    renderSignIn()

    await fillCredentials()
    await userEvent.click(submitButton())

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The corporate sign-in service can't be reached right now. Please try again in a few minutes.",
    )
  })

  it("offers no reset or access-request links, and says who can sign in", () => {
    renderSignIn()

    expect(screen.queryByText(/forgot it/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/request access/i)).not.toBeInTheDocument()
    expect(screen.getByText(/own department/i)).toHaveTextContent(/administrators see every department/i)
    expect(screen.getByRole("link", { name: /back to bidsense/i })).toHaveAttribute("href", "/")
  })
})
