import { describe, expect, it } from "vitest"
import {
  FINDING_TYPE_LABELS,
  findingTypeInfo,
  SEVERITY_INFO,
  severityInfo,
  type FindingType,
  type FindingSeverity,
} from "./findingLabels"

// Deliberately an INDEPENDENT, hand-maintained list - not derived from
// FINDING_TYPE_LABELS itself (that would make this test tautological: any
// mapping, complete or not, would trivially "cover" its own keys). This
// list must be kept in sync with the backend's own finding_type Literal in
// models/schemas/sanity_check.py - if the backend adds a 7th type, this
// test must be updated too, and until it is, this test is what catches a
// forgotten frontend label (rather than the finding silently rendering
// with no icon/text).
const BACKEND_FINDING_TYPES: FindingType[] = [
  "FINANCIAL_MISMATCH",
  "TECHNICAL_DISCREPANCY",
  "GRAND_TOTAL_MISMATCH",
  "CURRENCY_MISMATCH",
  "COMMERCIAL_CONTRADICTION",
  "TERMS_DISAGREEMENT",
]

const BACKEND_SEVERITIES: FindingSeverity[] = ["LOW", "MEDIUM", "HIGH"]

describe("finding type label coverage", () => {
  it.each(BACKEND_FINDING_TYPES)("%s has a real, non-generic label and icon", (type) => {
    const info = FINDING_TYPE_LABELS[type]
    expect(info).toBeDefined()
    expect(info.label).not.toBe(type) // never just echoes the raw enum value
    expect(info.label.length).toBeGreaterThan(0)
    expect(info.icon).toBeDefined()
  })

  it("findingTypeInfo() never falls back to the raw type string for a known type", () => {
    for (const type of BACKEND_FINDING_TYPES) {
      expect(findingTypeInfo(type).label).not.toBe(type)
    }
  })

  it("falls back gracefully (not throw) for a genuinely unrecognized type", () => {
    // Simulates the backend shipping a 7th finding_type before the
    // frontend catches up - must render something readable, never crash.
    const info = findingTypeInfo("SOME_FUTURE_FINDING_TYPE" as FindingType)
    expect(info.label).toBe("SOME_FUTURE_FINDING_TYPE")
    expect(info.icon).toBeDefined()
  })
})

describe("severity label coverage", () => {
  it.each(BACKEND_SEVERITIES)("%s has a real label and a defined tone/rank", (severity) => {
    const info = SEVERITY_INFO[severity]
    expect(info).toBeDefined()
    expect(info.label.length).toBeGreaterThan(0)
    expect(info.rank).toBeGreaterThanOrEqual(0)
  })

  it("HIGH ranks above MEDIUM which ranks above LOW", () => {
    expect(severityInfo("HIGH").rank).toBeGreaterThan(severityInfo("MEDIUM").rank)
    expect(severityInfo("MEDIUM").rank).toBeGreaterThan(severityInfo("LOW").rank)
  })
})
