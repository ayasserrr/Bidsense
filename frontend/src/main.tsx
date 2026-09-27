import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'
import { ThemeProvider } from './lib/theme'
import { AuthProvider } from './lib/auth'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

// Deliberately NOT wrapped in <StrictMode>: the progress screen kicks off a
// real, expensive, side-effecting pipeline run (creates a real offer,
// uploads real files, runs a multi-minute backend pipeline) the moment it
// mounts. StrictMode's dev-only mount -> unmount -> remount simulation
// would trigger that run twice on every page load in development, which is
// actively harmful here (not just noisy) - the usual StrictMode benefit
// (surfacing an unsafe effect) isn't worth that cost for this one page.
createRoot(document.getElementById('root')!).render(
  <ThemeProvider>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </QueryClientProvider>
  </ThemeProvider>,
)
