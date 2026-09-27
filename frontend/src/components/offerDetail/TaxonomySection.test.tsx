import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { getOfferTaxonomy, getTaxonomy, type OfferTaxonomy } from "../../api/taxonomyApi"
import { TaxonomySection } from "./TaxonomySection"

vi.mock("../../api/taxonomyApi", async () => {
  const actual = await vi.importActual<typeof import("../../api/taxonomyApi")>("../../api/taxonomyApi")
  return {
    ...actual,
    getOfferTaxonomy: vi.fn(),
    getTaxonomy: vi.fn(),
    recheckTaxonomy: vi.fn(),
    setItemCategory: vi.fn(),
  }
})

function offerTaxonomy(overrides: Partial<OfferTaxonomy> = {}): OfferTaxonomy {
  return {
    signal: "ok",
    offer_id: 42,
    resolved_count: 1,
    unresolved_count: 0,
    disciplines: { electrical: 1 },
    items: [
      {
        item_id: 1,
        description: "Cable tray, 300mm",
        equipment_type_original: null,
        node_id: 10,
        node_code: "electrical",
        node_label: "Electrical",
        discipline_code: "electrical",
        discipline_label: "Electrical",
      },
    ],
    ...overrides,
  }
}

function renderSection(offerId = 42) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <TaxonomySection offerId={offerId} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(getOfferTaxonomy).mockReset()
  vi.mocked(getTaxonomy).mockReset()
  vi.mocked(getTaxonomy).mockResolvedValue([])
})

describe("TaxonomySection", () => {
  it("starts collapsed, hiding the item list until expanded", async () => {
    vi.mocked(getOfferTaxonomy).mockResolvedValue(offerTaxonomy())
    renderSection()

    const toggle = await screen.findByRole("button", { name: "Expand Items by discipline" })
    expect(screen.queryByText("Cable tray, 300mm")).not.toBeInTheDocument()

    await userEvent.click(toggle)

    expect(await screen.findByText("Cable tray, 300mm")).toBeInTheDocument()
  })
})
