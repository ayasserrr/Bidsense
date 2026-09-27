from enum import Enum


class SanityCheckStatus(str, Enum):
    PASSED = "passed"
    NEEDS_REVIEW = "needs_review"


class SanityCheckSeverity(str, Enum):
    WARNING = "warning"
    CRITICAL = "critical"


class SanityCheckIssueType(str, Enum):
    ARITHMETIC_MISMATCH = "arithmetic_mismatch"
    PERCENTAGE_MISMATCH = "percentage_mismatch"
    SUBTOTAL_MISMATCH = "subtotal_mismatch"
    GRAND_TOTAL_MISMATCH = "grand_total_mismatch"
    PAYMENT_SCHEDULE_MISMATCH = "payment_schedule_mismatch"
