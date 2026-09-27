"""Matching an item's own words against the taxonomy.

Three steps, cheapest first: an exact alias hit, then a fuzzy one, and only
what survives both goes to the model. On a real BOQ most rows are resolved
before any LLM call is made at all, which matters - a 36-row bill of
quantities should not cost 36 gateway requests to categorise.
"""

import re
from difflib import SequenceMatcher

_PUNCTUATION = re.compile(r"[^\w\s]+", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")

# Words that carry no categorising information and only dilute a fuzzy score.
_NOISE_WORDS = frozenset(
    {
        "the", "and", "for", "with", "of", "to", "a", "an",
        "supply", "supplying", "install", "installation", "installed",
        "including", "include", "included", "complete", "set", "sets",
        "unit", "units", "system", "systems", "type", "model", "new",
        "as", "per", "above", "each", "no", "nos", "pcs", "piece", "pieces",
    }
)


def normalize_alias(text: str | None) -> str:
    """The form every alias is stored and looked up in.

    Lowercased, punctuation removed, whitespace collapsed - so "VRV-System",
    "vrv system" and "V.R.V. System" are one alias rather than three.
    """
    if not text:
        return ""
    lowered = text.casefold()
    lowered = _PUNCTUATION.sub(" ", lowered)
    return _WHITESPACE.sub(" ", lowered).strip()


def significant_tokens(text: str | None) -> list[str]:
    """Normalised words with the boilerplate dropped.

    "Supply and installation of water cooled chiller complete set" reduces to
    ["water", "cooled", "chiller"], which is what a fuzzy comparison should be
    working with - otherwise every line item looks alike because they all start
    with "supply and installation of".
    """
    return [token for token in normalize_alias(text).split() if token not in _NOISE_WORDS]


# How much of an item's own wording a single alias is allowed to speak for.
#
# Containment is what catches "vrv" inside a real description, and it has to
# keep doing that - but an alias buried in a long multi-clause line is a passing
# mention, not what the item IS. Measured case: "Installation works (OPTION):
# Gen-set fixing, Exhaust system with insulation, Duct canvas (max depth 1 m),
# Fuel system" contains the one-word alias "duct", which scored 0.915 and put a
# generator installation line into HVAC - and from there marked the whole HVAC
# discipline as covered on an offer with no HVAC in it at all.
#
# So an alias must account for a fair share of the words: one alias word per six
# significant words of description. A five-word line can still be decided by one
# word; a twenty-word one cannot.
MAX_TOKENS_PER_ALIAS_TOKEN = 6

# ...or the alias opens the line. A ratio alone is too blunt: a real BOQ row
# names what the item IS in its first few words and then qualifies it at length,
# so "Air handling unit (AHU) 10,000 CFM double skin with EC fans, filters and
# vibration isolators" is thirteen significant words carrying a one-word alias -
# thrown away by the ratio, though "ahu" is its third word. The passing mention
# the ratio exists to reject is late and preceded by other subjects: "duct" is
# the seventh word of the generator line, after works, option, gen, fixing,
# exhaust and insulation.
HEAD_TOKENS = 4


def fuzzy_best_match(
    text: str,
    candidates: dict[str, int],
    *,
    minimum_score: float = 0.82,
) -> tuple[int, float] | None:
    """The best-scoring alias for `text`, or None when nothing is close enough.

    `candidates` maps a normalised alias to its node id. Scoring is the higher
    of a whole-string similarity and a containment check, because the two catch
    different things: "vrv" appearing as one word inside a long description is a
    containment hit, while "chillar" (a real, common misspelling) is only ever
    caught by similarity.

    The threshold is deliberately high. A wrong discipline is worse than an
    unresolved one - an unresolved item is visibly unresolved, while a
    confidently wrong one quietly corrupts the completeness report that reads
    from it.
    """
    needle = normalize_alias(text)
    if not needle:
        return None
    ordered = significant_tokens(text)
    tokens = set(ordered)

    best_node: int | None = None
    best_score = 0.0
    for alias, node_id in candidates.items():
        if not alias:
            continue
        # Containment: the alias appears as a whole word (or word run) inside
        # the description. Scored below 1.0 so a genuine near-exact match still
        # wins, and scaled by how many words the alias has so that the more
        # SPECIFIC containment wins a tie. "Concrete base for the generator"
        # contains both "generator" and "concrete base"; without this the
        # winner was whichever the dictionary happened to yield first.
        alias_tokens = alias.split()
        if alias_tokens and tokens.issuperset(alias_tokens):
            head_position = min(ordered.index(token) for token in alias_tokens)
            speaks_for_the_line = (
                len(tokens) <= MAX_TOKENS_PER_ALIAS_TOKEN * len(alias_tokens)
                or head_position < HEAD_TOKENS
            )
        else:
            speaks_for_the_line = False
        if speaks_for_the_line:
            score = min(0.99, 0.90 + 0.015 * len(alias_tokens))
        else:
            score = SequenceMatcher(None, needle, alias).ratio()
        if score > best_score:
            best_score, best_node = score, node_id

    if best_node is None or best_score < minimum_score:
        return None
    return best_node, best_score
