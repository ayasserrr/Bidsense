import { describe, expect, it } from "vitest"
import { missingTermsLabel } from "./completeness"

describe("missingTermsLabel", () => {
  it("says nothing for an offer that has never been checked", () => {
    // The whole point of the null: "not checked" is not "nothing missing", and
    // a badge-free row has to mean somebody actually looked.
    expect(missingTermsLabel(null)).toBeNull()
    expect(missingTermsLabel(undefined)).toBeNull()
  })

  it("says nothing for an offer that was checked and stated everything", () => {
    expect(missingTermsLabel(0)).toBeNull()
  })

  it("counts gaps, singular and plural", () => {
    expect(missingTermsLabel(1)).toBe("1 term missing")
    expect(missingTermsLabel(4)).toBe("4 terms missing")
  })
})
