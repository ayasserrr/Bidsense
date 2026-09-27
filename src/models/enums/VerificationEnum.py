from enum import Enum


class VerificationStatus(str, Enum):

    SKIPPED = "skipped"
    RESOLVED = "resolved"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class ExtractionVerdict(str, Enum):

    CONFIRMED = "confirmed"
    INCORRECT = "incorrect"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class FindingVerdict(str, Enum):

    CONFIRMED = "confirmed"
    EXPLAINED = "explained"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
