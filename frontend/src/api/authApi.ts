import { api } from "./client"

export interface AuthUser {
  id: number
  username: string
  email: string
  display_name: string
  department: string
  company: string
  job_title: string
  office: string
  city: string
  role: string
  is_admin: boolean
  /** "ldap" for a corporate directory account; "local" only for the bootstrap admin. */
  auth_source: string
  last_login_at: string | null
  created_at: string | null
}

/** The session lives in an HttpOnly cookie the browser sets and sends on its
 * own - there is no token for this code to hold, store, or attach. */
export const authApi = {
  // `remember` picks the persistent cookie; false asks for a browser-session
  // cookie, so a shared workstation forgets the session when the browser closes.
  login: (username: string, password: string, remember: boolean) =>
    api.post<AuthUser>("/api/v1/auth/login", {
      json: { username, password, remember },
      timeoutMs: 90_000, // a cold directory can take a while to answer
    }),

  me: () => api.get<AuthUser>("/api/v1/auth/me", { timeoutMs: 15_000 }),

  logout: () => api.post<void>("/api/v1/auth/logout", { timeoutMs: 15_000 }),
}
