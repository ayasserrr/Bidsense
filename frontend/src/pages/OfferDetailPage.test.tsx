import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { deleteOffer, getOffer, getOfferVersions } from "../api/offerApi"
import { ApiError, type OfferDB, type OfferFullDB } from "../api/types"
import { OfferDetailPage } from "./OfferDetailPage"

vi.mock("../api/offerApi", () => ({ getOffer: vi.fn(), getOfferVersions: vi.fn(), deleteOffer: vi.fn() }))
// Everything below the header fetches on its own account; this test is about
// what the header says.
vi.mock("../components/layout/AppHeader", () => ({ AppHeader: () => null }))
vi.mock("../components/offerDetail/CompletenessSection", () => ({
  CompletenessSection: () => null,
}))
vi.mock("../components/offerDetail/TaxonomySection", () => ({ TaxonomySection: () => null }))
vi.mock("../components/offerDetail/ReviewSummarySection", () => ({
  ReviewSummarySection: () => null,
}))

const OFFER: OfferDB = {
  id: 42,
  root_offer_id: null,
  parent_offer_id: null,
  is_active_latest: true,
  supplier_id: null,
  project_id: null,
  offer_ref: "Q-2001",
  rfq_number: null,
  project_name_entered: null,
  project_name_original: "New plant",
  client_name_original: "A client",
  project_location_original: null,
  payment_terms_original: null,
  price_currency_original: null,
  currency_primary: "USD",
  grand_total: 1000,
  grand_total_currency: "USD",
  tax_treatment_original: null,
  incoterm: null,
  delivery_terms_original: null,
  validity_terms_original: null,
  warranty_terms_original: null,
  manufacturer_original: null,
  product_name_original: null,
  offer_date_original: null,
  offer_signed_by_original: null,
  general_notes_original: null,
  extra_attributes: null,
  sanity_check_status: "passed",
  sanity_check_summary: null,
  verification_status: null,
  verification_summary: null,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:00:00Z",
}

function fullOffer(gaps: number | null): OfferFullDB {
  return {
    offer: OFFER,
    supplier: null,
    project: null,
    contacts: [],
    items: [],
    payment_schedules: [],
    tech_specs: [],
    included_features: [],
    inclusions_exclusions: [],
    attachments: [],
    sanity_findings: [],
    verified_findings: [],
    completeness_mandatory_gaps: gaps,
    created_by_display_name: null,
    project_label: OFFER.project_name_original,
  }
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/offers/42"]}>
        <Routes>
          <Route path="/offers/:offerId" element={<OfferDetailPage />} />
          {/* Where a delete should land - nothing left to show for the
              offer it deleted. */}
          <Route path="/offers" element={<p>Offers list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(getOffer).mockReset()
  vi.mocked(getOfferVersions).mockReset()
  vi.mocked(getOfferVersions).mockResolvedValue([])
  vi.mocked(deleteOffer).mockReset()
})

describe("OfferDetailPage header", () => {
  it("flags unstated required terms next to the offer reference", async () => {
    vi.mocked(getOffer).mockResolvedValue(fullOffer(3))
    renderDetail()

    expect(await screen.findByText("3 terms missing")).toBeInTheDocument()
  })

  it("says one term in the singular", async () => {
    vi.mocked(getOffer).mockResolvedValue(fullOffer(1))
    renderDetail()

    expect(await screen.findByText("1 term missing")).toBeInTheDocument()
  })

  it("shows no badge when the offer stated everything", async () => {
    vi.mocked(getOffer).mockResolvedValue(fullOffer(0))
    renderDetail()

    expect(await screen.findByText("Q-2001")).toBeInTheDocument()
    expect(screen.queryByText(/term(s)? missing/)).not.toBeInTheDocument()
  })

  it("shows no badge when the check has never run", async () => {
    vi.mocked(getOffer).mockResolvedValue(fullOffer(null))
    renderDetail()

    expect(await screen.findByText("Q-2001")).toBeInTheDocument()
    expect(screen.queryByText(/term(s)? missing/)).not.toBeInTheDocument()
  })
})

describe("OfferDetailPage delete", () => {
  it("opens the confirmation dialog and does not call the API before it is confirmed", async () => {
    vi.mocked(getOffer).mockResolvedValue(fullOffer(0))
    renderDetail()
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "Delete" }))

    expect(await screen.findByRole("alertdialog", { name: "Delete this offer?" })).toBeInTheDocument()
    expect(deleteOffer).not.toHaveBeenCalled()
  })

  it("calls deleteOffer with the offer id and navigates to /offers once confirmed", async () => {
    vi.mocked(getOffer).mockResolvedValue(fullOffer(0))
    vi.mocked(deleteOffer).mockResolvedValue(undefined)
    renderDetail()
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "Delete" }))
    const dialog = screen.getByRole("alertdialog", { name: "Delete this offer?" })
    await user.click(within(dialog).getByRole("button", { name: "Delete" }))

    expect(deleteOffer).toHaveBeenCalledWith("42")
    expect(await screen.findByText("Offers list")).toBeInTheDocument()
  })

  it("disables the Delete trigger with an explanatory title when this isn't the latest version", async () => {
    vi.mocked(getOffer).mockResolvedValue({ ...fullOffer(0), offer: { ...OFFER, is_active_latest: false } })
    renderDetail()

    const button = await screen.findByRole("button", { name: "Delete" })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute("title", "A newer version of this offer exists. Delete that version first.")
  })

  it("shows the server's own 409 message via ErrorBanner, not a generic one", async () => {
    vi.mocked(getOffer).mockResolvedValue(fullOffer(0))
    vi.mocked(deleteOffer).mockRejectedValue(
      new ApiError("This offer has a read in progress and can't be deleted yet.", 409, {
        detail: "This offer has a read in progress and can't be deleted yet.",
      }),
    )
    renderDetail()
    const user = userEvent.setup()

    await user.click(await screen.findByRole("button", { name: "Delete" }))
    const dialog = screen.getByRole("alertdialog", { name: "Delete this offer?" })
    await user.click(within(dialog).getByRole("button", { name: "Delete" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This offer has a read in progress and can't be deleted yet.",
    )
    expect(screen.queryByText("Offers list")).not.toBeInTheDocument()
  })
})
