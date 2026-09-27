import {
  Calculator, Coins, MessagesSquare, FileWarning, Wrench, ScrollText, type LucideIcon,
} from "lucide-react"
import type { BadgeTone } from "../components/ui/Badge"
import type {
  ExtractionVerdict,
  FindingVerdict,
  SanityCheckIssueType,
  SanityCheckSeverity,
} from "../api/types"

// ---- real backend enums (sanity-check / verification findings) ------------

export const SANITY_CHECK_ISSUE_TYPE_LABELS: Record<SanityCheckIssueType, string> = {
  arithmetic_mismatch: "Arithmetic mismatch",
  percentage_mismatch: "Percentage mismatch",
  subtotal_mismatch: "Subtotal mismatch",
  grand_total_mismatch: "Grand total mismatch",
  payment_schedule_mismatch: "Payment schedule mismatch",
}

export const SANITY_CHECK_SEVERITY_TONE: Record<SanityCheckSeverity, BadgeTone> = {
  critical: "critical",
  warning: "warning",
}

export const EXTRACTION_VERDICT_LABELS: Record<ExtractionVerdict, { label: string; tone: BadgeTone }> = {
  confirmed: { label: "Extraction confirmed", tone: "success" },
  incorrect: { label: "Extraction incorrect", tone: "critical" },
  insufficient_evidence: { label: "Insufficient evidence", tone: "neutral" },
}

export const FINDING_VERDICT_LABELS: Record<FindingVerdict, { label: string; tone: BadgeTone }> = {
  confirmed: { label: "Genuine issue", tone: "critical" },
  explained: { label: "Explained by document", tone: "success" },
  insufficient_evidence: { label: "Insufficient evidence", tone: "neutral" },
}

// Not backed by a real endpoint - standalone presentation types for the landing page's illustrative preview.
export type FindingType =
  | "GRAND_TOTAL_MISMATCH"
  | "CURRENCY_MISMATCH"
  | "COMMERCIAL_CONTRADICTION"
  | "TERMS_DISAGREEMENT"
  | "TECHNICAL_DISCREPANCY"
  | "FINANCIAL_MISMATCH"

export type FindingSeverity = "HIGH" | "MEDIUM" | "LOW"

export interface FindingTypeInfo {
  label: string
  icon: LucideIcon
}

// Deliberately exhaustive and tested (findingLabels.test.ts).
export const FINDING_TYPE_LABELS: Record<FindingType, FindingTypeInfo> = {
  GRAND_TOTAL_MISMATCH: { label: "Grand total doesn't add up", icon: Calculator },
  CURRENCY_MISMATCH: { label: "Currency mismatch", icon: Coins },
  COMMERCIAL_CONTRADICTION: { label: "Conflicting commercial terms", icon: MessagesSquare },
  TERMS_DISAGREEMENT: { label: "Documents disagree", icon: ScrollText },
  TECHNICAL_DISCREPANCY: { label: "Technical specs don't match", icon: Wrench },
  FINANCIAL_MISMATCH: { label: "Numbers don't match", icon: FileWarning },
}

export function findingTypeInfo(type: FindingType): FindingTypeInfo {
  return FINDING_TYPE_LABELS[type] ?? { label: type, icon: FileWarning }
}

export interface SeverityInfo {
  label: string
  tone: BadgeTone
  /** Sort weight - higher shows first. */
  rank: number
}

export const SEVERITY_INFO: Record<FindingSeverity, SeverityInfo> = {
  HIGH: { label: "Critical", tone: "critical", rank: 2 },
  MEDIUM: { label: "Needs review", tone: "warning", rank: 1 },
  LOW: { label: "Minor", tone: "neutral", rank: 0 },
}

export function severityInfo(severity: FindingSeverity): SeverityInfo {
  return SEVERITY_INFO[severity] ?? { label: severity, tone: "neutral", rank: -1 }
}

// ---- presentation (the revamped issues view) --------------------------------

export type SeverityKind = "critical" | "review" | "minor"

export interface SeverityPresentation {
  kind: SeverityKind
  label: string
  /** The inline chip beside a finding's title. */
  chip: string
  /** The 38px rounded tile the finding's icon sits in. */
  tile: string
  /** The uppercase group heading above a severity's findings. */
  heading: string
  /** Wording for the group heading itself. */
  groupLabel: string
  /** Sub-label under the count on the summary stat cards. */
  statSub: string
}

// Only `critical` gets a solid fill, reserved for findings that block sign-off.
export const SEVERITY_PRESENTATION: Record<SeverityKind, SeverityPresentation> = {
  critical: {
    kind: "critical",
    label: "Critical",
    chip: "border-destructive bg-destructive text-destructive-foreground",
    tile: "bg-destructive-12 text-destructive",
    heading: "text-destructive",
    groupLabel: "Critical · blocking sign-off",
    statSub: "Blocking sign-off",
  },
  review: {
    kind: "review",
    label: "Needs review",
    chip: "border-accent-35 bg-accent-12 text-accent",
    tile: "bg-accent-10 text-accent",
    heading: "text-accent",
    groupLabel: "Needs review",
    statSub: "Check against source",
  },
  minor: {
    kind: "minor",
    label: "Minor",
    chip: "border-border bg-muted text-muted-foreground",
    tile: "bg-muted text-muted-foreground",
    heading: "text-muted-foreground",
    groupLabel: "Minor",
    statSub: "Note and proceed",
  },
}

const SEVERITY_KIND: Record<FindingSeverity, SeverityKind> = {
  HIGH: "critical",
  MEDIUM: "review",
  LOW: "minor",
}

export function severityPresentation(severity: FindingSeverity): SeverityPresentation {
  return SEVERITY_PRESENTATION[SEVERITY_KIND[severity] ?? "minor"]
}
