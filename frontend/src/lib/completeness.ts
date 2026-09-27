/** How a completeness gap is worded outside the completeness section.
 *
 * One function so the offers list and the offer header cannot drift into
 * saying the same number two different ways, and so the "never checked" case
 * is decided once. An offer nobody has checked shows NO badge: a reviewer
 * reading a clean row has to be able to trust that somebody looked.
 */
export function missingTermsLabel(gaps: number | null | undefined): string | null {
  if (typeof gaps !== "number" || gaps <= 0) return null
  return gaps === 1 ? "1 term missing" : `${gaps} terms missing`
}
