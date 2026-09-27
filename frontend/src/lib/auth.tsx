import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react"
import { authApi, type AuthUser } from "../api/authApi"
import { setUnauthorizedHandler } from "../api/client"
import { ApiError } from "../api/types"

interface AuthContextValue {
  user: AuthUser | null
  /** True until the initial "am I signed in?" check settles. Route guards must
   * wait for this, or a refresh bounces a signed-in user to the sign-in page. */
  loading: boolean
  signIn: (username: string, password: string, remember: boolean) => Promise<AuthUser>
  signOut: () => Promise<void>
  /** Re-reads the session from the server, for a view that should show the
   * account as it is now rather than as it was when the app loaded. */
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

/** Holds the signed-in user.
 *
 * There is no token in here: the session is an HttpOnly cookie the browser
 * attaches by itself, so this context only ever mirrors server state. It is
 * mounted above the router, which means it cannot call useNavigate - clearing
 * `user` is the signal, and <Protected> does the redirecting.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    authApi
      .me()
      .then((u) => {
        if (!cancelled) setUser(u)
      })
      .catch(() => {
        // A 401 here is the normal "not signed in yet" case, not an error
        // worth showing. Any other failure also leaves the user signed out,
        // which <Protected> turns into the sign-in page.
        if (!cancelled) setUser(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    // A 401 from any later call means the session died server-side (expired,
    // or the account was deactivated). Drop the user so the guard redirects.
    //
    // Deliberately does NOT navigate: a running pipeline unmounts its page on
    // navigation, and that unmount abandons - and permanently deletes - the
    // offer being processed. Clearing state lets <Protected> handle it in one
    // place instead of yanking the route out from under an in-flight run.
    setUnauthorizedHandler(() => setUser(null))
    return () => setUnauthorizedHandler(null)
  }, [])

  const signIn = useCallback(async (username: string, password: string, remember: boolean) => {
    const u = await authApi.login(username, password, remember)
    setUser(u)
    return u
  }, [])

  const signOut = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      // Even if the server never heard us, forget the user locally - the
      // cookie is already unusable from this app's point of view.
    }
    setUser(null)
  }, [])

  const refresh = useCallback(async () => {
    try {
      const u = await authApi.me()
      // Only ever updates someone still signed in: a sign-out that lands while
      // this request is in flight must not be undone by its answer.
      setUser((current) => (current ? u : null))
    } catch (err) {
      // /auth/me is exempt from the client's unauthorized handler (a 401 there
      // usually just means "not signed in yet"), so a dead session is dropped
      // here. Any other failure keeps the details already on screen.
      if (isUnauthorized(err)) setUser(null)
    }
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut, refresh }}>{children}</AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error("useAuth must be used within an AuthProvider")
  return context
}

/** True when an error is a 401 - used to tell "wrong password" apart from
 * "the directory is unreachable" (503), which need different wording. */
export function isUnauthorized(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401
}
