import type { ReactNode } from "react"
import { Navigate, useLocation } from "react-router-dom"
import { Spinner } from "../ui/Spinner"
import { useAuth } from "../../lib/auth"

/** Gate for every screen that needs a signed-in user.
 *
 * Waiting on `loading` is the load-bearing part: the session check is a round
 * trip, and redirecting before it settles would bounce an already-signed-in
 * user to the sign-in page on every refresh.
 */
export function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner />
      </div>
    )
  }

  if (!user) {
    // `from` lets the sign-in page send the user back where they were headed
    // instead of dropping everyone on the upload screen.
    return <Navigate to="/signin" replace state={{ from: location.pathname + location.search }} />
  }

  return <>{children}</>
}
