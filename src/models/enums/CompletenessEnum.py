from enum import Enum


class RequirementGroup(str, Enum):
    """The two halves of the client's checklist.

    `technical` is the ten engineering disciplines - the same ten that form the
    roots of the item taxonomy, so a discipline being covered by the offer and a
    discipline existing as a category are one fact, not two.
    `commercial` is the ten offer terms (A-J on the client's own list).
    """

    TECHNICAL = "technical"
    COMMERCIAL = "commercial"


class CompletenessVerdict(str, Enum):
    """What the checker concluded about one requirement.

    The distinction between `missing` and `unclear` is the point of having four
    values rather than a boolean: `missing` is a statement the reviewer can act
    on ("ask the supplier for this"), while `unclear` says the offer touches the
    subject without pinning it down. Collapsing them would turn every ambiguity
    into a false accusation against the supplier.

    `not_applicable` exists because the checklist is fixed and offers are not:
    a UPS quotation has nothing to say about Plumbing, and reporting that as a
    gap trains reviewers to ignore the whole report.
    """

    PRESENT = "present"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    UNCLEAR = "unclear"


class ScopeAnswer(str, Enum):
    """Whether a scope question (installation, spare parts, maintenance,
    training) is answered by the offer, and how."""

    INCLUDED = "included"
    EXCLUDED = "excluded"
    UNSPECIFIED = "unspecified"


class EvidenceKind(str, Enum):
    """Where an override's supporting document came from.

    The client was explicit that a reviewer filling a gap must attach something
    - an email, a signed letter, an amended quotation. A phone call is not
    evidence, so there is deliberately no value here for one.
    """

    EMAIL = "email"
    LETTER = "letter"
    REVISED_OFFER = "revised_offer"
    OTHER = "other"
