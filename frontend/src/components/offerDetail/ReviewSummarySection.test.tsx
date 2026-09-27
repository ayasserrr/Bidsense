import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { Job } from "../../api/jobApi"
import { getReviewSummary, recheckReviewSummary, type ReviewSummary } from "../../api/reviewSummaryApi"
import { ReviewSummarySection } from "./ReviewSummarySection"

vi.mock("../../api/reviewSummaryApi", () => ({
  getReviewSummary: vi.fn(),
  recheckReviewSummary: vi.fn(),
}))

function fakeJob(overrides: Partial<Job> = {}): Job {
  return {
    job_id: "11111111-1111-1111-1111-111111111111",
    kind: "offer_pipeline",
    status: "queued",
    offer_id: 42,
    offer_ref: null,
    rfq_number: null,
    project_name: null,
    file_count: 0,
    page_count: 0,
    stages: [],
    current_stage: null,
    progress_percent: 0,
    error_stage: null,
    error_message: null,
    cancel_requested: false,
    queue_position: null,
    created_at: "2026-09-18T09:00:00Z",
    enqueued_at: null,
    started_at: null,
    updated_at: "2026-09-18T09:00:00Z",
    finished_at: null,
    created_by_user_id: null,
    created_by_display_name: "",
    offer_persisted: false,
    ...overrides,
  }
}

function summary(overrides: Partial<ReviewSummary> = {}): ReviewSummary {
  return {
    headline: "3 things to chase before this can go to sign-off",
    chase_items: [
      {
        kind: "mandatory_gap",
        title: "Warranty period",
        detail: "The offer never states a warranty period.",
        source_filename: null,
        source_page_number: null,
      },
      {
        kind: "confirmed_finding",
        title: "Grand total does not add up",
        detail: "The stated grand total does not match the sum of line items.",
        source_filename: "BOQ.xlsx",
        source_page_number: 4,
      },
    ],
    email_to: "sales@supplier.example",
    email_subject: "Clarification needed",
    email_body: "Hello,\n\nCould you confirm...",
    generated_at: "2026-09-17T10:00:00Z",
    ...overrides,
  }
}

function renderSection(offerId = 42) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ReviewSummarySection offerId={offerId} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(getReviewSummary).mockReset()
  vi.mocked(recheckReviewSummary).mockReset()
})

describe("ReviewSummarySection", () => {
  it("renders the headline and each chase item, with source when present", async () => {
    vi.mocked(getReviewSummary).mockResolvedValue(summary())
    renderSection()

    expect(await screen.findByText("3 things to chase before this can go to sign-off")).toBeInTheDocument()
    expect(screen.getByText("Warranty period")).toBeInTheDocument()
    expect(screen.getByText("The offer never states a warranty period.")).toBeInTheDocument()
    expect(screen.getByText("Grand total does not add up")).toBeInTheDocument()
    expect(screen.getByText("BOQ.xlsx, page 4")).toBeInTheDocument()
  })

  it("shows the backend's own empty-chase-list headline, with no list and a disabled email button", async () => {
    vi.mocked(getReviewSummary).mockResolvedValue(
      summary({ headline: "Nothing to chase - this offer is clear.", chase_items: [] }),
    )
    renderSection()

    expect(await screen.findByText("Nothing to chase - this offer is clear.")).toBeInTheDocument()
    expect(screen.queryByText("Warranty period")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Draft the clarification email" })).toBeDisabled()
  })

  it("fires the regenerate mutation when clicked", async () => {
    vi.mocked(getReviewSummary).mockResolvedValue(summary())
    vi.mocked(recheckReviewSummary).mockResolvedValue(fakeJob())
    renderSection()
    await screen.findByText("3 things to chase before this can go to sign-off")

    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }))

    await waitFor(() => expect(recheckReviewSummary).toHaveBeenCalledWith(42))
  })

  it("surfaces a failed regenerate instead of silently going back to normal", async () => {
    vi.mocked(getReviewSummary).mockResolvedValue(summary())
    vi.mocked(recheckReviewSummary).mockRejectedValue(new Error("This offer has not finished processing yet."))
    renderSection()
    await screen.findByText("3 things to chase before this can go to sign-off")

    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }))

    expect(await screen.findByText("This offer has not finished processing yet.")).toBeInTheDocument()
  })

  it("tells apart never-generated from genuinely verified-clear", async () => {
    vi.mocked(getReviewSummary).mockResolvedValue(
      summary({
        headline: "The summary has not been generated yet.",
        chase_items: [],
        generated_at: null,
      }),
    )
    renderSection()

    await screen.findByText("The summary has not been generated yet.")
    // No "Generated <date>" subtitle, and no success checkmark - both would
    // wrongly imply this offer was checked and found clear.
    expect(screen.queryByText(/^Generated /)).not.toBeInTheDocument()
  })

  it("is expanded by default but can be collapsed and reopened", async () => {
    vi.mocked(getReviewSummary).mockResolvedValue(summary())
    renderSection()
    await screen.findByText("3 things to chase before this can go to sign-off")

    await userEvent.click(screen.getByRole("button", { name: "Collapse Summary" }))
    expect(screen.queryByText("3 things to chase before this can go to sign-off")).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole("button", { name: "Expand Summary" }))
    expect(screen.getByText("3 things to chase before this can go to sign-off")).toBeInTheDocument()
  })

  it("opens the email draft modal with the offer's draft", async () => {
    vi.mocked(getReviewSummary).mockResolvedValue(summary())
    renderSection()
    await screen.findByText("3 things to chase before this can go to sign-off")

    await userEvent.click(screen.getByRole("button", { name: "Draft the clarification email" }))

    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(screen.getByText("sales@supplier.example")).toBeInTheDocument()
  })
})
