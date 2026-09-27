from enum import Enum


class ExtractionMethod(str, Enum):
    PARSING_STUDIO = "parsing_studio"
    FAILED = "failed"
    # How pages were read before parsing moved to Parsing Studio. Nothing
    # writes these any more; they stay so rows parsed back then still load.
    PDFPLUMBER = "pdfplumber"
    PLAIN_TEXT = "plain_text"


class ParseWarningType(str, Enum):
    PAGE_EXTRACTION_FAILED = "page_extraction_failed"
    # The page was read, but Parsing Studio itself doubts the reading (an OCR
    # page below its confidence margin, a scan whose vision rescue returned
    # nothing). Its absence of a term is weak evidence the term is absent.
    PAGE_LOW_QUALITY = "page_low_quality"
    DOCUMENT_EXTRACTION_FAILED = "document_extraction_failed"
