import { createBrowserRouter, Outlet, RouterProvider } from "react-router-dom"
import { LandingPage } from "./pages/LandingPage"
import { SignInPage } from "./pages/SignInPage"
import { DashboardPage } from "./pages/DashboardPage"
import { UploadPage } from "./pages/UploadPage"
import { UpdateOfferPage } from "./pages/UpdateOfferPage"
import { ProgressPage } from "./pages/ProgressPage"
import { QueuePage } from "./pages/QueuePage"
import { OffersPage } from "./pages/OffersPage"
import { OfferDetailPage } from "./pages/OfferDetailPage"
import { ComparePage } from "./pages/ComparePage"
import { Protected } from "./components/layout/Protected"
import { Tour } from "./components/tour/Tour"

// A thin root layout rather than a bare list of routes, purely so <Tour />
// mounts exactly once, inside the router (its steps navigate between
// /dashboard and /offers with useNavigate) and inside <AuthProvider> (mounted
// above <App /> in main.tsx, so it is reachable here) - it gates itself on a
// signed-in user internally, so it renders nothing on "/" or "/signin".
function RootLayout() {
  return (
    <>
      <Outlet />
      <Tour />
    </>
  )
}

// A data router (rather than plain <BrowserRouter>) is required for
// ProgressPage's useBlocker call, which intercepts in-app navigation away
// from a still-running pipeline with a confirmation prompt - useBlocker
// only works inside a data router's context.
const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: "/", element: <LandingPage /> },
      { path: "/signin", element: <SignInPage /> },
      { path: "/dashboard", element: <Protected><DashboardPage /></Protected> },
      { path: "/upload", element: <Protected><UploadPage /></Protected> },
      { path: "/upload/existing", element: <Protected><UpdateOfferPage /></Protected> },
      { path: "/processing", element: <Protected><ProgressPage /></Protected> },
      { path: "/queue", element: <Protected><QueuePage /></Protected> },
      { path: "/offers", element: <Protected><OffersPage /></Protected> },
      { path: "/offers/:offerId", element: <Protected><OfferDetailPage /></Protected> },
      { path: "/compare", element: <Protected><ComparePage /></Protected> },
    ],
  },
])

export default function App() {
  return <RouterProvider router={router} />
}
