import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cancelJob, type Job } from "../api/jobApi"
import { getQueue, moveJobInQueue, type QueueJob, type QueueState } from "../api/queueApi"
import { QueuePage } from "./QueuePage"

vi.mock("../api/queueApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/queueApi")>()
  return { ...actual, getQueue: vi.fn(), moveJobInQueue: vi.fn(), pauseQueue: vi.fn(), resumeQueue: vi.fn(), setQueueSlots: vi.fn() }
})
vi.mock("../api/jobApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/jobApi")>()
  return { ...actual, cancelJob: vi.fn() }
})
// The header pulls in auth/theme/notifications and the rail pulls in its own
// queue-badge poll - none of it is what this file is testing.
vi.mock("../components/layout/AppHeader", () => ({ AppHeader: () => null }))
vi.mock("../components/layout/Rail", () => ({ Rail: () => null }))

function waitingJob(overrides: Partial<QueueJob> = {}): QueueJob {
  return {
    job_id: "job-a",
    kind: "offer_pipeline",
    status: "queued",
    offer_id: 1,
    offer_ref: "Q-1",
    rfq_number: null,
    project_name: "Offer A",
    file_count: 1,
    page_count: 2,
    stages: [],
    current_stage: null,
    progress_percent: 0,
    error_stage: null,
    error_message: null,
    cancel_requested: false,
    queue_position: 1,
    created_at: "2026-09-18T09:00:00Z",
    enqueued_at: "2026-09-18T09:00:00Z",
    started_at: null,
    updated_at: "2026-09-18T09:00:00Z",
    finished_at: null,
    created_by_user_id: null,
    created_by_display_name: "",
    offer_persisted: false,
    estimated_start_seconds: 300,
    estimated_start_at: null,
    elapsed_seconds: null,
    estimated_remaining_seconds: null,
    ...overrides,
  }
}

function queueState(waiting: QueueJob[]): QueueState {
  return {
    is_paused: false,
    paused_at: null,
    paused_by: "",
    parallel_slots: 1,
    slots: 1,
    slot_ceiling: 3,
    running: [],
    waiting,
    running_count: 0,
    waiting_count: waiting.length,
    hidden_running_count: 0,
    hidden_waiting_count: 0,
    next_position: waiting.length + 1,
    next_start_seconds: null,
    next_start_at: null,
    finishes_at: null,
    estimates_available: true,
    estimate_note: "",
    estimate_runs: {},
    summary: `${waiting.length} waiting`,
  }
}

function renderQueue() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/queue"]}>
        <QueuePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function rowFor(label: string): HTMLElement {
  return screen.getByText(label).closest("div.flex.flex-wrap") as HTMLElement
}

beforeEach(() => {
  vi.mocked(getQueue).mockReset()
  vi.mocked(moveJobInQueue).mockReset()
  vi.mocked(cancelJob).mockReset()
})

describe("QueuePage - concurrent per-row actions", () => {
  it("does not let one job's in-flight action clear another job's busy state", async () => {
    const jobA = waitingJob({ job_id: "job-a", project_name: "Offer A", queue_position: 1 })
    const jobB = waitingJob({ job_id: "job-b", project_name: "Offer B", queue_position: 2 })
    vi.mocked(getQueue).mockResolvedValue(queueState([jobA, jobB]))

    // Both requests are left unresolved deliberately, to inspect the UI while
    // they are still "in flight" - exactly the window the race lived in.
    let resolveMove: (state: QueueState) => void = () => {}
    vi.mocked(moveJobInQueue).mockReturnValue(new Promise((resolve) => (resolveMove = resolve)))
    let resolveCancel: (job: Job) => void = () => {}
    vi.mocked(cancelJob).mockReturnValue(new Promise<Job>((resolve) => (resolveCancel = resolve)))

    renderQueue()
    await screen.findByText("Offer A")

    // Job A is first of two, so its own "Move up" is always disabled by
    // position regardless of busy state - "Move down" is the one purely
    // busy-gated button on this row, and is what the assertions below use.

    // Start moving job A down...
    await userEvent.click(within(rowFor("Offer A")).getByRole("button", { name: "Move down" }))
    await waitFor(() => {
      expect(within(rowFor("Offer A")).getByRole("button", { name: "Move down" })).toBeDisabled()
    })

    // ...then, before that resolves, cancel job B.
    await userEvent.click(within(rowFor("Offer B")).getByRole("button", { name: "Cancel" }))

    // Job A's own buttons must still read busy - job B's action must not have
    // cleared them (the pre-fix bug: a single shared `pendingJobId` meant
    // starting B's action overwrote the only record that A was still busy).
    expect(within(rowFor("Offer A")).getByRole("button", { name: "Move down" })).toBeDisabled()
    expect(within(rowFor("Offer B")).getByRole("button", { name: "Move up" })).toBeDisabled()

    // Settling A's action must not clear B's still-outstanding one, either.
    resolveMove(queueState([jobA, jobB]))
    await waitFor(() => {
      expect(within(rowFor("Offer A")).getByRole("button", { name: "Move down" })).not.toBeDisabled()
    })
    expect(within(rowFor("Offer B")).getByRole("button", { name: "Move up" })).toBeDisabled()

    resolveCancel({} as Job)
  })
})
