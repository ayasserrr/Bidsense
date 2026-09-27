import type { OfferVerifiedFindingDB } from "../../api/types"
import {
  EXTRACTION_VERDICT_LABELS,
  FINDING_VERDICT_LABELS,
  SANITY_CHECK_ISSUE_TYPE_LABELS,
} from "../../lib/findingLabels"
import { Badge } from "../ui/Badge"
import { DetailSection } from "./DetailSection"

/** Only shows findings verification independently confirmed as a genuine,
 * unexplained issue against the source document (finding_verdict ===
 * "confirmed") - the raw deterministic sanity-check list and any finding
 * verification explained away or couldn't confirm are deliberately not
 * shown here, since only a verification-confirmed finding is reliable
 * enough to surface as a real issue. */
export function FindingsSection({
  verifiedFindings,
}: {
  verifiedFindings: OfferVerifiedFindingDB[]
}) {
  const realIssues = verifiedFindings.filter((finding) => finding.finding_verdict === "confirmed")
  if (realIssues.length === 0) return null

  return (
    <DetailSection
      title="Findings"
      description="Pricing/consistency issues confirmed as genuine after independently re-checking against the source document."
      collapsible
    >
      <div className="flex flex-col gap-2.5 px-5 py-4">
        {realIssues.map((finding) => (
          <div
            key={finding.verified_finding_id}
            className="flex flex-col gap-1.5 rounded-[10px] border border-border p-3"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold">{SANITY_CHECK_ISSUE_TYPE_LABELS[finding.issue_type]}</span>
              <span className="text-xs text-muted-foreground">{finding.field_path}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={EXTRACTION_VERDICT_LABELS[finding.extraction_verdict].tone}>
                {EXTRACTION_VERDICT_LABELS[finding.extraction_verdict].label}
              </Badge>
              <Badge tone={FINDING_VERDICT_LABELS[finding.finding_verdict].tone}>
                {FINDING_VERDICT_LABELS[finding.finding_verdict].label}
              </Badge>
            </div>
            {finding.extraction_correction && (
              <p className="m-0 text-sm">
                <strong>Correction:</strong> {finding.extraction_correction}
              </p>
            )}
            <p className="m-0 text-sm text-muted-foreground">{finding.reasoning}</p>
            <blockquote className="m-0 border-l-2 border-border pl-2.5 text-xs italic text-muted-foreground">
              &ldquo;{finding.evidence_quote}&rdquo;
            </blockquote>
          </div>
        ))}
      </div>
    </DetailSection>
  )
}
