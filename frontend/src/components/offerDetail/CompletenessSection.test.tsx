import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { getCompleteness, type CompletenessResult, type OfferCompleteness } from "../../api/completenessApi"
import { CompletenessSection } from "./CompletenessSection"

vi.mock("../../api/completenessApi", async () => {
  const actual = await vi.importActual<typeof import("../../api/completenessApi")>("../../api/completenessApi")
  return {
    ...actual,
    getCompleteness: vi.fn(),
    recheckCompleteness: vi.fn(),
    clearOverride: vi.fn(),
    saveOverride: vi.fn(),
  }
})

function result(overrides: Partial<CompletenessResult> = {}): CompletenessResult {
  return {
    result_id: 1,
    requirement_code: "warranty",
    requirement_label: "Warranty period",
    requirement_group: "commercial",
    was_mandatory: true,
    sort_order: 1,
    verdict: "missing",
    extracted_value: null,
    normalized_value: null,
    evidence_quote: null,
    source_document_id: null,
    source_filename: null,
    source_page_number: null,
    reasoning: null,
    is_overridden: false,
    override_verdict: null,
    override_value: null,
    override_note: null,
    override_evidence_id: null,
    override_evidence_filename: null,
    overridden_by: null,
    overridden_at: null,
    effective_verdict: "missing",
    effective_value: null,
    checked_at: "2026-09-18T09:00:00Z",
    ...overrides,
  }
}

function offerCompleteness(overrides: Partial<OfferCompleteness> = {}): OfferCompleteness {
  return {
    signal: "ok",
    offer_id: 42,
    checked_at: "2026-09-18T09:00:00Z",
    summary: { total: 1, present: 0, missing: 1, unclear: 0, not_applicable: 0, mandatory_gaps: 1, overridden: 0 },
    results: [result()],
    evidence: [],
    ...overrides,
  }
}

function renderSection(offerId = 42) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <CompletenessSection offerId={offerId} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(getCompleteness).mockReset()
})

describe("CompletenessSection", () => {
  it("starts collapsed, hiding the requirement rows until expanded", async () => {
    vi.mocked(getCompleteness).mockResolvedValue(offerCompleteness())
    renderSection()

    const toggle = await screen.findByRole("button", { name: "Expand Completeness check" })
    expect(screen.queryByText("Warranty period")).not.toBeInTheDocument()

    await userEvent.click(toggle)

    expect(await screen.findByText("Warranty period")).toBeInTheDocument()
  })
})
