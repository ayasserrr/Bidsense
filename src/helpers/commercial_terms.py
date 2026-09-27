"""Deterministic readings of the commercial terms the checklist asks about.

Every function here is pure, LLM-free and testable. They exist as a safety net
over the model's own verdicts: when extraction has already captured a term, or
when the rule is mechanical (is this string a real Incoterm? is this currency
actually named?), the answer should not depend on a second model call that
might say something different this time.

The client's own rules are encoded here, not paraphrased:
  - a delivery term is present if it is ANY Incoterms 2020 term, not only the
    four he named;
  - a currency counts only when NAMED - a bare dollar sign does not identify one.
"""

import re

from models.enums import EntryType, ItemCategory, ScopeAnswer

# Incoterms 2020 in full. The four the client called out (CIF, DDP, and EXW via
# "Ex-Works"/"Ex-Factory") are the common ones, not the whole set - he was
# explicit that an offer must not be flagged merely for using a different one.
INCOTERMS_2020: dict[str, str] = {
    "EXW": "Ex Works",
    "FCA": "Free Carrier",
    "CPT": "Carriage Paid To",
    "CIP": "Carriage and Insurance Paid To",
    "DAP": "Delivered at Place",
    "DPU": "Delivered at Place Unloaded",
    "DDP": "Delivered Duty Paid",
    "FAS": "Free Alongside Ship",
    "FOB": "Free on Board",
    "CFR": "Cost and Freight",
    "CIF": "Cost, Insurance and Freight",
}

# Spellings seen in real offers that are not the three-letter code.
# "Ex-Factory" is not an Incoterm at all, but the client named it explicitly
# and it means EXW in practice, so it resolves rather than being reported as
# unrecognised.
#
# Deliberately NOT here: "ex stock" and "delivered to site". Neither is a
# delivery term. "Ex-stock" says the goods are on the shelf - an availability
# statement, which is what the Delivery Lead Time row asks about - and
# "delivered to site" says where the truck stops without saying who carries the
# cost, the risk, the clearance or the insurance. Reading either as an Incoterm
# reports a term as stated when the offer never stated it, which is the exact
# failure this checklist exists to catch.
_INCOTERM_PHRASES: tuple[tuple[str, str], ...] = (
    ("ex works", "EXW"),
    ("ex work", "EXW"),
    ("exworks", "EXW"),
    ("exwork", "EXW"),
    ("ex factory", "EXW"),
    ("exfactory", "EXW"),
    ("ex warehouse", "EXW"),
    ("free carrier", "FCA"),
    ("free alongside ship", "FAS"),
    ("free on board", "FOB"),
    ("cost and freight", "CFR"),
    ("cost insurance and freight", "CIF"),
    ("carriage and insurance paid", "CIP"),
    ("carriage paid to", "CPT"),
    ("delivered duty paid", "DDP"),
    ("delivered at place unloaded", "DPU"),
    ("delivered at place", "DAP"),
)

_CODE_TOKEN = re.compile(r"\b(EXW|FCA|CPT|CIP|DAP|DPU|DDP|FAS|FOB|CFR|CIF|C&F|CNF)\b", re.I)

# The written-out spellings, anchored on word boundaries. A plain substring test
# read "the complex work of cabling" and "Complex Works Building" as EXW - the
# "ex work" is inside "complex work" - and because the delivery-term rule settles
# an `unclear` verdict, that silently reported a mandatory term as stated.
_INCOTERM_PHRASE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(r"\b" + r"\s+".join(re.escape(word) for word in phrase.split()) + r"\b"), code)
    for phrase, code in _INCOTERM_PHRASES
)

# "C.I.F." / "c.i.f. Alexandria" / "F.O.B." - the dotted form is as common on a
# real quotation as the bare code, and read letter by letter it is not a code at
# all.
_DOTTED_CODE = re.compile(r"\b([A-Za-z])\.\s*([A-Za-z])\.\s*([A-Za-z])\.?")
# Every separator an offer writes between "Ex" and "Works": hyphen, en/em dash,
# full stop, slash, underscore. Collapsing them is what makes "Ex-Work",
# "Ex.Works" and "Ex– Works" the same term they obviously are.
_TERM_SEPARATORS = re.compile(r"[‐-―\-./\\_,]+")


def _canonical_term_text(text: str) -> str:
    """The text with the cosmetic spellings of a delivery term flattened out."""
    collapsed = _DOTTED_CODE.sub(r"\1\2\3", text)
    collapsed = _TERM_SEPARATORS.sub(" ", collapsed)
    return " ".join(collapsed.lower().split())


def normalize_incoterm(text: str | None) -> str | None:
    """The Incoterms 2020 code a piece of text states, or None.

    Checks the three-letter codes first and the written-out phrases second, so
    "CIF Alexandria" and "Cost, Insurance and Freight to Alexandria" give the
    same answer. C&F and CNF are long-standing trade shorthand for CFR.

    Punctuation is flattened before either check, because the dotted and
    hyphenated spellings ("C.I.F.", "Ex-Work", "Ex.Works") are how offers
    actually print these terms - and failing to recognise one meant the offer
    fell back to the model's verdict on a term it had plainly stated.
    """
    if not text:
        return None
    canonical = _canonical_term_text(text)
    match = _CODE_TOKEN.search(canonical)
    if match:
        token = match.group(1).upper()
        return "CFR" if token in {"C&F", "CNF"} else token

    for pattern, code in _INCOTERM_PHRASE_PATTERNS:
        if pattern.search(canonical):
            return code
    return None


# What a Delivery Lead Time actually has to say: how long, or by when. The
# checklist's own words - "a number of days or weeks, a delivery date, or a
# period counted from a stated trigger".
_LEAD_TIME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b\d+\s*(?:[-‐-―]\s*\d+\s*)?"
        r"(?:working\s+|calendar\s+|business\s+)?"
        r"(?:day|days|week|weeks|month|months|year|years)\b",
        re.I,
    ),
    re.compile(r"\b(?:immediate|immediately|prompt|promptly)\b", re.I),
    re.compile(
        r"\b(?:within|after|from|upon)\b[^.\n]{0,40}"
        r"\b(?:order|po|purchase\s+order|contract|advance|down\s+payment|"
        r"l\s?/?\s?c|letter\s+of\s+credit|confirmation|approval)\b",
        re.I,
    ),
    re.compile(r"\b\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{2,4}\b"),
    re.compile(
        r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{2,4}\b",
        re.I,
    ),
)


def states_lead_time(text: str | None) -> bool:
    """Whether a piece of text says WHEN delivery happens.

    A per-item "Availability" column is often the only place a lead time
    appears, but it is just as often filled with a stock condition - "Ex-stock",
    "Based on the available stock", "Subject to prior sale". Those say where the
    goods are, not when they arrive, and treating them as a lead time reports a
    term as stated that the supplier never committed to.
    """
    if not text:
        return False
    return any(pattern.search(text) for pattern in _LEAD_TIME_PATTERNS)


# VAT wording, most specific first: "exclusive of VAT" must not be read as
# "inclusive" merely because the two words share a suffix.
_VAT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "exempt",
        re.compile(r"\b(vat|tax)\s*(is\s*)?(exempt|free)\b|\bexempt(ed)?\s+from\s+(vat|tax)\b", re.I),
    ),
    (
        "zero_rated",
        re.compile(r"\bzero[\s-]?rated\b|\b(vat|tax)\s*(rate\s*)?(of\s*)?0\s*%", re.I),
    ),
    (
        "exclusive",
        re.compile(
            r"\bexclu(?:d(?:e|es|ed|ing)|sive)\b[^.\n]{0,24}\b(?:vat|tax|taxes)\b"
            r"|\bexcl\.?\s[^.\n]{0,24}\b(?:vat|tax|taxes)\b"
            r"|\b(?:without|before|net\s+of|plus)\b[^.\n]{0,24}\b(?:vat|tax|taxes)\b"
            r"|\b(?:vat|tax|taxes)\b[^.\n]{0,24}\b(?:not\s+included|excluded|extra|additional|on\s+top)\b",
            re.I,
        ),
    ),
    (
        "inclusive",
        re.compile(
            r"\binclu(?:d(?:e|es|ed|ing)|sive)\b[^.\n]{0,24}\b(?:vat|tax|taxes)\b"
            r"|\binc(?:l)?\.?\s[^.\n]{0,24}\b(?:vat|tax|taxes)\b"
            r"|\b(?:vat|tax|taxes)\b[^.\n]{0,24}\b(?:included|inclusive)\b",
            re.I,
        ),
    ),
)


def normalize_vat_status(text: str | None) -> str | None:
    """One of inclusive / exclusive / exempt / zero_rated, or None when the
    text says nothing definite about tax."""
    if not text:
        return None
    for status, pattern in _VAT_PATTERNS:
        if pattern.search(text):
            return status
    return None


def currency_is_named(original_text: str | None, resolved_code: str | None) -> bool:
    """The client's rule: a currency counts as stated only when it is NAMED.

    A bare glyph is not a name. A lone dollar sign does not distinguish US,
    Canadian, Australian or Singapore dollars, and an offer that only ever
    prints one has genuinely left the currency open - exactly the kind of gap
    this feature exists to surface. A resolved ISO code is not enough on its
    own either: extraction may have inferred it from context rather than read
    it, and `resolved_code` alone would let that inference pass as a statement.
    """
    if not original_text:
        return False
    letters = sum(1 for char in original_text if char.isalpha())
    if letters >= 3:
        return True
    # Two letters only count when extraction also resolved a code - that covers
    # the genuinely unambiguous local short forms ("L.E." for Egyptian pounds)
    # without letting a lone glyph through on the strength of a guess.
    return letters >= 2 and bool(resolved_code)


# What counts as evidence for each scope question, in the offer's own words.
# Matched as whole words against normalised text, never as loose substrings:
# "install" inside "installation manual" and "service" inside "serviceable" are
# not offers of installation or maintenance.
_SCOPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "installation": (
        "install", "installs", "installed", "installing", "installation",
        "installations", "erect", "erected", "erection", "commission",
        "commissioned", "commissioning", "supervision", "supervise",
        "site works", "site work",
        # The words a bill of quantities actually uses for the same work.
        # "Supply and fixing" is the standard BOQ wording for installation
        # included in this market, and an offer that says it has answered the
        # Installation row as plainly as one that says "installation".
        "fixing", "fixings", "mounting", "start up", "startup",
    ),
    "spare_parts": (
        "spare part", "spare parts", "spares", "recommended spares",
        "commissioning spares", "consumable", "consumables",
    ),
    "maintenance": (
        "maintenance", "service contract", "after sales", "aftersales",
        "preventive", "preventative", "servicing", "overhaul",
    ),
    "training": ("training", "train the", "operator course"),
}

# Phrases that contain a keyword while meaning something else entirely. Each one
# is a measured false positive: a "maintenance bypass switch" is a part of a UPS,
# not an offer to maintain it, and "maintenance-free batteries" is the opposite
# of a maintenance offering. They are removed from the text BEFORE the keywords
# are looked for, so the rest of the sentence is still read normally.
_SCOPE_NON_MATCHES: dict[str, tuple[str, ...]] = {
    "installation": (
        "soft start", "self commissioning", "mounting bracket", "mounting kit",
        "mounting frame", "mounting accessories", "wall mounted",
        "wall mounting", "floor mounting", "ceiling mounting",
        "surface mounting", "rack mounting", "fixing bracket", "fixing kit",
        "fixing accessories", "fixing bolts", "fixing screws",
        "start up current", "startup current", "start up time",
        "installation manual", "installation instructions", "installed base",
    ),
    "spare_parts": ("spares kit not included", "consumable cost", "consumables cost"),
    "maintenance": (
        "maintenance free", "maintenance bypass", "low maintenance",
        "maintenance switch", "maintenance interval", "maintenance manual",
        "easy maintenance",
    ),
    "training": ("training manual",),
}

# A non-match that is only a non-match in one sense of the words. "Maintenance
# free" is the adjective in "maintenance-free batteries" and the OFFER in
# "Maintenance free of charge for the first year" - and a table cell reading
# "Maintenance | Free of charge for 12 months" normalises to exactly the second.
# Deleting that sentence before looking for the keyword removed the supplier's
# answer from the text it was being looked for in, and flagged a mandatory row
# the offer had answered. The tail says when the phrase is NOT the false
# positive, so the guard fires on the adjective only.
_NON_MATCH_TAILS: dict[str, str] = {
    "maintenance free": r"(?!\s+(?:of\s+charge|for\s+\d|for\s+the\s+first))",
}


def _non_match_pattern(phrase: str) -> re.Pattern[str]:
    body = r"\s+".join(re.escape(word) for word in phrase.split())
    return re.compile(r"\b" + body + r"\b" + _NON_MATCH_TAILS.get(phrase, ""))


_SCOPE_NON_MATCH_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    subject: tuple(_non_match_pattern(phrase) for phrase in phrases)
    for subject, phrases in _SCOPE_NON_MATCHES.items()
}

# A category that answers the scope question by itself: an item extraction
# called an installation IS installation, a spare part IS a spare part.
_SCOPE_CATEGORIES: dict[str, tuple[ItemCategory, ...]] = {
    "installation": (ItemCategory.INSTALLATION,),
    "spare_parts": (ItemCategory.SPARE_PART,),
    "maintenance": (ItemCategory.SERVICE,),
    "training": (ItemCategory.TRAINING,),
}

# ...and the ones that do not. `service` is a generic bucket covering labour,
# commissioning, transport and anything else that is not a thing in a box, so a
# service line only answers the Maintenance question when the line itself says
# something about maintenance. Without this, an "Installation works" line priced
# as a service was read as proof of an after-sales maintenance offering - and a
# term the supplier never mentioned was reported as included.
_GENERIC_CATEGORIES: frozenset[str] = frozenset({ItemCategory.SERVICE.value})

SCOPE_SUBJECTS: tuple[str, ...] = ("installation", "spare_parts", "maintenance", "training")

_NON_WORD = re.compile(r"[^0-9a-z]+")


def _normalized_scope_text(*parts: str | None) -> str:
    """Lowercased, punctuation-flattened, space-padded - so a keyword can be
    looked for as a whole word with a plain substring test."""
    joined = " ".join(part for part in parts if part)
    return " " + _NON_WORD.sub(" ", joined.casefold()).strip() + " "


def mentions_scope_subject(subject: str, *parts: str | None) -> bool:
    """Whether this text is actually ABOUT `subject`."""
    text = _normalized_scope_text(*parts)
    for pattern in _SCOPE_NON_MATCH_PATTERNS[subject]:
        text = pattern.sub(" ", text)
    return any(f" {keyword} " in text for keyword in _SCOPE_KEYWORDS[subject])


def derive_scope_answer(payload, subject: str) -> ScopeAnswer:
    """Whether the offer puts `subject` in scope, out of scope, or says nothing.

    Reads the three places an offer actually answers this: a priced line item of
    the matching category, an explicit inclusion/exclusion entry, and the
    included-features list. A priced line item is the strongest signal there is -
    an offer that charges for installation has unambiguously included it - so it
    wins over an exclusion sentence, which more often than not is excluding
    something adjacent ("excluding civil works for the installation").

    A line item in a GENERIC category has to earn it: the item's own words must
    be about the subject too. "The supplier quoted installation labour" is not
    "the supplier offers maintenance", and a rule that cannot tell those apart
    silences a real gap on a mandatory term.
    """
    categories = {category.value for category in _SCOPE_CATEGORIES[subject]}

    for item in getattr(payload, "items", None) or []:
        category = getattr(item, "item_category", None)
        category_value = getattr(category, "value", category)
        if category_value not in categories:
            continue
        if category_value in _GENERIC_CATEGORIES and not mentions_scope_subject(
            subject,
            getattr(item, "description", None),
            getattr(item, "equipment_type_original", None),
        ):
            continue
        return ScopeAnswer.INCLUDED

    for feature in getattr(payload, "included_features", None) or []:
        if mentions_scope_subject(subject, getattr(feature, "feature_text", None)):
            return ScopeAnswer.INCLUDED

    excluded = False
    for entry in getattr(payload, "inclusions_exclusions", None) or []:
        if not mentions_scope_subject(subject, getattr(entry, "description", None)):
            continue
        entry_type = getattr(entry, "entry_type", None)
        entry_value = getattr(entry_type, "value", entry_type)
        if entry_value == EntryType.INCLUDE.value:
            return ScopeAnswer.INCLUDED
        excluded = True

    return ScopeAnswer.EXCLUDED if excluded else ScopeAnswer.UNSPECIFIED
