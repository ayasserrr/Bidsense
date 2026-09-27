import { ApiError, type ApiErrorBody } from "./types"

// Empty by default, which means same-origin: requests go to /api/... on
// whatever host is serving the app, and Vite's `/api` proxy (see
// vite.config.ts) forwards them to the backend. That keeps the session cookie
// first-party and keeps CORS out of the dev loop entirely.
//
// Set VITE_API_BASE_URL only to point at a backend on a different origin -
// which then also requires the backend's CORS_ALLOWED_ORIGINS to list this
// app's origin, and allow_credentials to be on for the cookie to survive.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ""

// Set by the auth provider. Called when any request comes back 401 so the app
// can drop the signed-in user and show the sign-in page.
//
// The login and session-check endpoints are excluded below: a 401 from THEM is
// the expected answer to "are these credentials right?" / "am I signed in?",
// not the loss of an established session, and treating it as one would clear
// state on every mistyped password.
type UnauthorizedHandler = () => void
let unauthorizedHandler: UnauthorizedHandler | null = null

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler
}

const AUTH_ENDPOINTS = ["/api/v1/auth/login", "/api/v1/auth/me", "/api/v1/auth/logout"]

// Fire-and-forget POST that survives the calling component unmounting or
// the tab closing right after the call (a normal fetch would be aborted in
// either case) - for cleanup calls where nothing depends on the response.
export function beaconPost(path: string): void {
  navigator.sendBeacon(`${API_BASE_URL}${path}`, new Blob())
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE"
  json?: unknown
  formData?: FormData
  /** Milliseconds. Real pipeline stages run for minutes - see lib/pipeline.ts's own per-stage timeouts. */
  timeoutMs?: number
  signal?: AbortSignal
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", json, formData, timeoutMs = 30_000, signal } = options

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)
  // If the caller also passes their own signal (e.g. a "cancel upload"
  // button), either one aborting the request works.
  signal?.addEventListener("abort", () => controller.abort())

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      // The session is an HttpOnly cookie, never a token this code can read.
      // "include" covers both deployments: same-origin (the default, via the
      // Vite proxy) and a cross-origin API, where it is required.
      credentials: "include",
      headers: json ? { "Content-Type": "application/json" } : undefined,
      body: formData ?? (json ? JSON.stringify(json) : undefined),
      signal: controller.signal,
    })
  } catch (err) {
    clearTimeout(timeoutId)
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(
        `Request timed out after ${Math.round(timeoutMs / 1000)}s. This step can genuinely take a while on a large document - if you believe the backend is still working, this is just this app's own wait limit, not necessarily a failure.`,
        null,
        {},
      )
    }
    throw new ApiError(
      "Could not reach the backend. Is the API server running and is VITE_API_BASE_URL set correctly?",
      null,
      {},
    )
  }
  clearTimeout(timeoutId)

  let body: unknown = null
  const text = await response.text()
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = { detail: text }
    }
  }

  if (response.status === 401 && !AUTH_ENDPOINTS.includes(path)) {
    unauthorizedHandler?.()
  }

  if (!response.ok) {
    const errBody = (body ?? {}) as ApiErrorBody
    // The upload endpoints report a total failure via `results` (one entry
    // per file) rather than a `detail` string - surface the real per-file
    // reasons instead of a bare "Request failed (422)".
    const failedFiles = errBody.results?.filter((r) => r.status !== "success")
    const message =
      errBody.detail ||
      (failedFiles && failedFiles.length > 0
        ? failedFiles.map((r) => `${r.filename}: ${r.message}`).join("; ")
        : undefined)
    throw new ApiError(message || `Request failed (${response.status})`, response.status, errBody)
  }

  return body as T
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: "POST" }),
  patch: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: "PATCH" }),
  delete: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: "DELETE" }),
}
