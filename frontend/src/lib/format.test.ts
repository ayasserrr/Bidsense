import { describe, expect, it } from "vitest"
import { formatSpecValue } from "./format"

// Real bug found live via manual QA against the Tradex VRV offer: a spec's
// value sometimes already embeds its own unit (e.g. "19mm" with
// unit_original also "mm"), and naively appending produced "19mm mm".
describe("formatSpecValue", () => {
  it("appends the unit when the value doesn't already contain it", () => {
    expect(formatSpecValue("1500", "RPM")).toBe("1500 RPM")
  })

  it("does not duplicate the unit when the value already ends with it", () => {
    expect(formatSpecValue("19mm", "mm")).toBe("19mm")
  })

  it("is case-insensitive when checking for a duplicate unit", () => {
    expect(formatSpecValue("400V", "V")).toBe("400V")
  })

  it("returns the bare value when there is no unit", () => {
    expect(formatSpecValue("Cast Resin", null)).toBe("Cast Resin")
  })
})
