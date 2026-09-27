import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { deleteOffer, getOfferFilterOptions, listOffersPage } from "../api/offerApi"
import type { OfferListPage, OfferSummary } from "../api/types"
import { OffersPage } from "./OffersPage"

vi.mock("../api/offerApi", () => ({
  listOffersPage: vi.fn(),
  getOfferFilterOptions: vi.fn(),
  deleteOffer: vi.fn(),
}))
// The header pulls in auth, theme and the queue poll - none of it is what
// this file is testing.
vi.mock("../components/layout/AppHeader", () => ({ AppHeader: () => null }))

function offer(overrides: Partial<OfferSummary> = {}): OfferSummary {
  return {
    id: 1,
    offer_ref: "Q-1001",
    rfq_number: null,
    project_name_original: "New plant",
    project_name_entered: null,
    project_label: "New plant",
    client_name_original: "A client",
    supplier_name: "A supplier",
    grand_total: 1000,
    grand_total_currency: "USD",
    is_active_latest: true,
    root_offer_id: null,
    parent_offer_id: null,
    sanity_check_status: "passed",
    verification_status: null,
    review_status: "clear",
    completeness_mandatory_gaps: null,
    version_count: 1,
    created_by_user_id: null,
    created_by_display_name: null,
    created_at: "2026-09-01T10:00:00Z",
    archived_at: null,
    is_archived: false,
    ...overrides,
  }
}

function page(items: OfferSummary[]): OfferListPage {
  return { items, total: items.length, limit: 50, offset: 0, archived_matching: 0 }
}

function renderOffers() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/offers"]}>
        <OffersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function rowFor(reference: string): Promise<HTMLElement> {
  const cell = await screen.findByText(reference)
  return cell.closest("tr") as HTMLElement
}

beforeEach(() => {
  vi.mocked(listOffersPage).mockReset()
  vi.mocked(deleteOffer).mockReset()
  vi.mocked(getOfferFilterOptions).mockReset()
  vi.mocked(getOfferFilterOptions).mockResolvedValue({
    suppliers: [],
    projects: [],
    uploaders: [],
    rfq_numbers: [],
  })
})

describe("OffersPage completeness badge", () => {
  it("flags an offer whose supplier left required terms unstated", async () => {
    // The gap used to be invisible here: an offer missing all ten commercial
    // terms looked exactly as clean as one that stated every single one.
    vi.mocked(listOffersPage).mockResolvedValue(page([offer({ completeness_mandatory_gaps: 4 })]))
    renderOffers()

    expect(within(await rowFor("Q-1001")).getByText("4 terms missing")).toBeInTheDocument()
  })

  it("says one term in the singular", async () => {
    vi.mocked(listOffersPage).mockResolvedValue(page([offer({ completeness_mandatory_gaps: 1 })]))
    renderOffers()

    expect(within(await rowFor("Q-1001")).getByText("1 term missing")).toBeInTheDocument()
  })

  it("shows no badge for an offer that stated everything", async () => {
    vi.mocked(listOffersPage).mockResolvedValue(page([offer({ completeness_mandatory_gaps: 0 })]))
    renderOffers()

    const row = within(await rowFor("Q-1001"))
    expect(row.queryByText(/term(s)? missing/)).not.toBeInTheDocument()
  })

  it("shows no badge for an offer that has never been checked", async () => {
    vi.mocked(listOffersPage).mockResolvedValue(page([offer({ completeness_mandatory_gaps: null })]))
    renderOffers()

    const row = within(await rowFor("Q-1001"))
    expect(row.queryByText(/term(s)? missing/)).not.toBeInTheDocument()
  })

  it("shows the gap badge alongside the pricing one, not instead of it", async () => {
    vi.mocked(listOffersPage).mockResolvedValue(
      page([offer({ review_status: "needs_review", completeness_mandatory_gaps: 2 })]),
    )
    renderOffers()

    const row = within(await rowFor("Q-1001"))
    expect(row.getByText("Needs review")).toBeInTheDocument()
    expect(row.getByText("2 terms missing")).toBeInTheDocument()
  })
})

describe("OffersPage real fields", () => {
  it("shows the RFQ, the typed project label and the uploader", async () => {
    vi.mocked(listOffersPage).mockResolvedValue(
      page([
        offer({
          rfq_number: "RFQ-2026-0188",
          project_label: "Nile Delta Substation",
          created_by_display_name: "Yara Kamal",
        }),
      ]),
    )
    renderOffers()

    const row = within(await rowFor("Q-1001"))
    expect(row.getByText("RFQ-2026-0188")).toBeInTheDocument()
    expect(row.getByText("Nile Delta Substation")).toBeInTheDocument()
    expect(row.getByText("Yara Kamal")).toBeInTheDocument()
  })

  it("shows an archived offer as archived rather than a false Clear", async () => {
    // An offer nobody has re-checked since being retired must not read as a
    // clean result - it is off the working list on purpose, not vetted.
    vi.mocked(listOffersPage).mockResolvedValue(
      page([offer({ is_archived: true, archived_at: "2026-09-10T00:00:00Z", review_status: "clear" })]),
    )
    renderOffers()

    const row = within(await rowFor("Q-1001"))
    expect(row.getByText("Archived")).toBeInTheDocument()
    expect(row.queryByText("Clear")).not.toBeInTheDocument()
  })
})

describe("OffersPage delete", () => {
  async function selectRow(reference: string) {
    const row = within(await rowFor(reference))
    await userEvent.click(row.getByRole("checkbox"))
  }

  it("offers Delete beside Compare once rows are selected, and asks before deleting", async () => {
    vi.mocked(listOffersPage).mockResolvedValue(page([offer()]))
    renderOffers()
    await selectRow("Q-1001")

    await userEvent.click(screen.getByRole("button", { name: "Delete" }))

    // Asked, not done - nothing may be deleted on the strength of one click.
    expect(deleteOffer).not.toHaveBeenCalled()
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Delete this offer?")
  })

  it("deletes every selected offer once confirmed", async () => {
    vi.mocked(listOffersPage).mockResolvedValue(page([offer(), offer({ id: 2, offer_ref: "Q-1002" })]))
    vi.mocked(deleteOffer).mockResolvedValue(undefined)
    renderOffers()
    await selectRow("Q-1001")
    await selectRow("Q-1002")

    await userEvent.click(screen.getByRole("button", { name: "Delete" }))
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Delete 2 offers?")
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }))

    await waitFor(() => expect(deleteOffer).toHaveBeenCalledTimes(2))
    expect(vi.mocked(deleteOffer).mock.calls.map((c) => c[0])).toEqual([1, 2])
  })

  it("shows the server's own reason for a refusal instead of failing silently", async () => {
    vi.mocked(listOffersPage).mockResolvedValue(page([offer()]))
    vi.mocked(deleteOffer).mockRejectedValue(
      new Error("Offer 1 has a newer version (offer 5). Delete the newer version first."),
    )
    renderOffers()
    await selectRow("Q-1001")

    await userEvent.click(screen.getByRole("button", { name: "Delete" }))
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }))

    expect(await screen.findByText(/has a newer version \(offer 5\)/)).toBeInTheDocument()
  })
})
