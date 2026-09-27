import uuid
from typing import TypedDict

from schema.offer import OfferExtractionPayload
from schema.sanity_check import SanityCheckResult
from schema.verification import VerificationResult


class PipelineState(TypedDict, total=False):
    """Shared state threaded through the offer pipeline graph.

    Upload is NOT a node. The files arrive as part of an HTTP request and have
    to be consumed while that request is alive, so the offer and its documents
    are created there - which also means the reviewer gets the per-file
    duplicate/rejected results immediately instead of waiting behind a
    twenty-minute extraction. The graph picks up from already-saved documents.
    """

    offer_id: int
    document_ids: list[uuid.UUID]

    extraction_payload: OfferExtractionPayload
    sanity_check_result: SanityCheckResult
    verification_result: VerificationResult

    # Post-persist stages. These run against an offer that is already saved, so
    # their results are reported but their failure never fails the run.
    completeness_gaps: int
    completeness_failed: bool
    taxonomy_resolved: int
    taxonomy_unresolved: int
