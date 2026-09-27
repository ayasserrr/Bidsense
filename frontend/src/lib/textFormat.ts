/**
 * Splits a long verbatim clause-dump (e.g. payment terms listing several
 * percentages/conditions in one field) into individual readable clauses -
 * display formatting only, never touches the underlying stored text.
 *
 * Splits on:
 * - existing line breaks (the source document's own line structure, when
 *   the extractor preserved it - e.g. "Terms of Supply: ..." and
 *   "Terms of Installation: ..." printed as separate lines);
 * - semicolons (the documents' own delimiter for listing several terms
 *   in one field);
 * - a sentence boundary that starts a new clause ("...before dispatch.
 *   For items 8 : 10: ..."). Requires a 4+ letter word before the period
 *   so short titles like "Eng." or "Dr." don't get split from the name
 *   that follows, and a capital letter after so decimals like "3.5" are
 *   never touched;
 * - a numbered/lettered list marker ("1.", "2-", "3)") starting a new
 *   item within a line, since a source line can bundle several numbered
 *   items in one run ("1. 50% Down Payment 2. 50% Before Delivery").
 */
export function splitClauses(text: string): string[] {
  const normalized = text.trim()
  if (!normalized) return []

  return normalized
    .split(/\r?\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .flatMap((line) =>
      line
        .split(/;\s*|(?<=[a-zA-Z]{4,}|\))\.\s+(?=[A-Z])|\s+(?=\d{1,2}[.\-)]\s)/g)
        .map((clause) => clause.trim())
        .filter(Boolean)
    )
}
