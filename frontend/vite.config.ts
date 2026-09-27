import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'

// Where the FastAPI backend listens. Overridable so a mismatched launch is
// fixable without editing this file - nothing in the backend enforces 8004
// (it is a uvicorn CLI argument, see README).
const API_TARGET = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8004'

// The `/api` proxy is what makes the browser and the API same-origin. That is
// not a convenience: it is what lets the session cookie be sent at all, and
// what lets `navigator.sendBeacon` (used to abandon orphaned offers) reach the
// backend - a beacon cannot set an Authorization header, and a cross-site
// SameSite=Lax cookie would not ride along either.
//
// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // `::` is dual-stack. `0.0.0.0` is IPv4-only, and on Windows browsers often
    // resolve `localhost` to ::1, so http://localhost:8002 can refuse while
    // 127.0.0.1 works.
    host: '::',
    port: 8002,
    // Fail loudly instead of silently moving to 8003: the backend CORS
    // allowlist and the cookie origin are both pinned to 8002.
    strictPort: true,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
  // `vite preview` serves the built dist/. It inherits host, strictPort and
  // proxy from `server`, but NOT `port` (it would default to 4173), so the
  // port has to be restated here.
  preview: {
    port: 8002,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
  },
})
