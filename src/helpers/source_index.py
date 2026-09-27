"""Resolving a quoted snippet back to the file and page it came from.

The completeness checker has to say *where* it found something - "stated on
page 3 of TECHNICAL_OFFER.pdf" - and that attribution has to be true. Asking
the model to name the file is not an option: the same model was measured
returning nulls for fields that were plainly present, and a confidently wrong
filename destroys exactly the traceability the client asked for.

So the model is only ever asked for a verbatim quote, and the quote is located
in the merged text mechanically. If it cannot be located, the result says so
rather than inventing a source.
"""

import bisect
import re
import uuid
from dataclasses import dataclass

_WHITESPACE_RUN = re.compile(r"\s+")


@dataclass(frozen=True)
class SourceSegment:
    """One page's slice of the merged text."""

    start: int
    end: int
    document_id: uuid.UUID
    page_number: int | None


@dataclass(frozen=True)
class SourceIndex:
    """The merged text plus the map from offsets back to pages.

    Built by the same function that builds the text, never separately: an index
    computed against a differently-assembled string would silently attribute
    quotes to the wrong file.
    """

    text: str
    segments: tuple[SourceSegment, ...]

    # Whitespace-collapsed, casefolded copy of `text`, and the offset each of
    # its characters came from. Quotes come back from the model with the
    # spacing subtly changed far too often to rely on an exact match.
    normalized: str
    normalized_offsets: tuple[int, ...]

    def segment_at(self, offset: int) -> SourceSegment | None:
        if not self.segments:
            return None
        starts = [segment.start for segment in self.segments]
        position = bisect.bisect_right(starts, offset) - 1
        if position < 0:
            return None
        segment = self.segments[position]
        return segment if offset < segment.end else segment

    def locate(self, quote: str) -> SourceSegment | None:
        """The page a quote came from, or None if it is not in the source.

        None is a real answer, not a failure to try: a quote that is nowhere in
        the document means the model paraphrased or invented it, and the caller
        downgrades the finding rather than attaching a source it cannot stand
        behind.
        """
        normalized_quote = normalize_for_match(quote or "")
        if len(normalized_quote) < 4:
            # Too short to be evidence of anything. "5%" or "of" would match in
            # a dozen places and the first one would win by accident - checked
            # before the exact match, not only after it, because an exact hit on
            # two characters is just as meaningless.
            return None

        offset = self.text.find(quote)
        if offset != -1:
            return self.segment_at(offset)

        position = self.normalized.find(normalized_quote)
        if position == -1:
            return None
        return self.segment_at(self.normalized_offsets[position])


def normalize_for_match(text: str) -> str:
    return _WHITESPACE_RUN.sub(" ", text).strip().casefold()


def build_normalized(text: str) -> tuple[str, tuple[int, ...]]:
    """Whitespace-collapsed casefolded text, plus each character's origin offset.

    Built character by character rather than with a regex substitution because
    the offsets are the whole point: a regex would give the collapsed string
    but lose the mapping back into the original.
    """
    out: list[str] = []
    offsets: list[int] = []
    in_whitespace = False
    for index, char in enumerate(text):
        if char.isspace():
            if not in_whitespace:
                out.append(" ")
                offsets.append(index)
                in_whitespace = True
            continue
        in_whitespace = False
        lowered = char.casefold()
        # casefold() can expand one character into several (German ß -> ss).
        # Every expanded character points back at the same source offset, so
        # offsets stays exactly as long as the normalized string.
        for expanded in lowered:
            out.append(expanded)
            offsets.append(index)
    # Leading space, if any, is not stripped here: stripping would shift every
    # offset. Matching uses .find() on a stripped needle, which is unaffected.
    return "".join(out), tuple(offsets)
