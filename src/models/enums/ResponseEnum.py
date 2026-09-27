from enum import Enum

class ResponseSignal(str, Enum):

    FILE_TYPE_NOT_SUPPORTED = "file_type_not_supported"
    FILE_SIZE_EXCEEDED = "file_size_exceeded"
    FILE_EMPTY = "file_empty"
    FILE_VALIDATED_SUCCESS = "file_validated_success"
    FILE_UPLOADED_FAILED = "file_uploaded_failed"
    FILE_UPLOADED_SUCCESS = "file_uploaded_success"
    FILE_ALREADY_EXISTS = "file_already_exists"

    PARSE_SUCCESS = "parse_success"
    PARSE_FAILED = "parse_failed"

    EXTRACTION_SUCCESS = "extraction_success"
    EXTRACTION_FAILED = "extraction_failed"

    SANITY_CHECK_COMPLETED = "sanity_check_completed"

    VERIFICATION_COMPLETED = "verification_completed"

    PERSIST_SUCCESS = "persist_success"

    COMPLETENESS_COMPLETED = "completeness_completed"

    TAXONOMY_RESOLVED = "taxonomy_resolved"