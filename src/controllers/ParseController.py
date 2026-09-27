import re
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from langdetect import DetectorFactory, LangDetectException, detect
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from helpers.parsing_studio import ParsingStudioClient, StudioParse, parse_server_urls
from models.db_schema import Document, DocumentPage, Offer
from models.enums import ExtractionMethod, ParseWarningType

from .BaseController import BaseController

# langdetect's classifier samples characters probabilistically; without a
# fixed seed, the same text can get different results across runs.
DetectorFactory.seed = 0

_WHITESPACE_RE = re.compile(r"[ \t\x0b\f\r]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

# Parsing Studio's words for a page whose text should not be trusted as a
# complete reading of it. "fallback" is the one that matters most: the vision
# model was asked and returned nothing, so the page is its own text layer alone
# - usually empty on a scan. Left unflagged, a term printed on that page would
# surface later as a confident "missing" in the completeness report.
_LOW_QUALITY = frozenset({"bad", "fallback", "flagged", "fused_divergent"})


def normalize_extracted_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    normalized = _BLANK_LINES_RE.sub("\n\n", normalized)
    return normalized.strip()


def detect_language(text: str, min_chars: int) -> str | None:
    if not text or len(text.strip()) < min_chars:
        return None
    try:
        return detect(text)
    except LangDetectException:
        return None


@dataclass(frozen=True)
class ParsedPage:
    page_number: int | None
    raw_text: str | None
    raw_tables: list[dict] | None
    unit_location: dict
    extraction_method: ExtractionMethod


@dataclass(frozen=True)
class ParsedDocument:
    pages: list[ParsedPage]
    page_count: int
    language: str | None
    warnings: list[dict] = field(default_factory=list)


def build_parsed_document(studio: StudioParse, min_chars_for_language_detection: int) -> ParsedDocument:
    """Parsing Studio's pages, in the shape `document_pages` stores.

    Tables arrive inside the page text as Markdown, so `raw_tables` stays
    empty - the model reads them where they sit in the page, rather than as a
    separately reconstructed grid appended after it. `unit_location` records
    what produced each page, which is what answers "why is page 7 empty?"
    without re-running anything.
    """
    pages: list[ParsedPage] = []
    warnings: list[dict] = []

    for studio_page in studio.pages:
        text = normalize_extracted_text(studio_page.text)
        failed = bool(studio_page.error) and not text

        unit_location: dict = {"blocks": [], "source": "parsing_studio", "run_id": studio.run_id}
        unit_location.update(
            {
                key: value
                for key, value in (
                    ("parser", studio_page.parser),
                    ("quality", studio_page.quality),
                    ("page_label", studio_page.page_label),
                )
                if value
            }
        )
        if failed:
            unit_location["status"] = "failed"

        if studio_page.error:
            warnings.append(
                {
                    "type": ParseWarningType.PAGE_EXTRACTION_FAILED,
                    "page_number": studio_page.page,
                    "errors": [studio_page.error],
                }
            )
        elif studio_page.quality in _LOW_QUALITY:
            warnings.append(
                {
                    "type": ParseWarningType.PAGE_LOW_QUALITY,
                    "page_number": studio_page.page,
                    "quality": studio_page.quality,
                    "parser": studio_page.parser,
                }
            )

        pages.append(
            ParsedPage(
                page_number=studio_page.page,
                raw_text=text or None,
                raw_tables=None,
                unit_location=unit_location,
                extraction_method=ExtractionMethod.FAILED if failed else ExtractionMethod.PARSING_STUDIO,
            )
        )

    if not pages:
        warnings.append(
            {
                "type": ParseWarningType.DOCUMENT_EXTRACTION_FAILED,
                "status": "no_pages",
                "errors": ["Parsing Studio finished but returned no pages for this file"],
            }
        )

    full_text = "\n".join(page.raw_text for page in pages if page.raw_text)
    return ParsedDocument(
        pages=pages,
        page_count=len(pages),
        language=detect_language(full_text, min_chars_for_language_detection),
        warnings=warnings,
    )


class DocumentNotFoundError(Exception):
    def __init__(self, document_id: uuid.UUID):
        self.document_id = document_id
        super().__init__(f"Document {document_id} not found")


class ParseController(BaseController):
    def __init__(self, db: AsyncSession):
        super().__init__()
        self.db = db

    async def get_document(self, document_id: uuid.UUID) -> Document:
        document = await self.db.get(Document, document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        return document

    async def get_document_pages(self, document_id: uuid.UUID) -> list[DocumentPage]:
        result = await self.db.execute(
            select(DocumentPage)
            .where(DocumentPage.file_id == document_id)
            .order_by(DocumentPage.page_number)
        )
        return list(result.scalars().all())

    def _parsing_client(self) -> ParsingStudioClient:
        return ParsingStudioClient(
            urls=parse_server_urls(self.app_settings.PARSING_STUDIO_URLS),
            recipe=self.app_settings.PARSING_STUDIO_RECIPE,
            timeout_seconds=self.app_settings.PARSING_STUDIO_TIMEOUT_SECONDS,
        )

    async def parse_document(
        self,
        document_id: uuid.UUID,
        commit: bool = True,
        on_stage: Callable[[str], Awaitable[None]] | None = None,
        check_cancelled: Callable[[], Awaitable[None]] | None = None,
    ) -> tuple[Document, ParsedDocument]:
        document = await self.get_document(document_id)
        absolute_path = Path(self.base_dir) / document.storage_path

        if commit:
            # Close the read transaction before the remote parse. A scanned
            # offer can take minutes, and a connection left idle in a
            # transaction for that long holds a pool slot and a snapshot for
            # nothing. Nothing is pending, so this commits no data.
            await self.db.commit()

        studio = await self._parsing_client().parse_file(
            absolute_path,
            document.original_filename,
            on_stage=on_stage,
            check_cancelled=check_cancelled,
        )
        parsed = build_parsed_document(studio, self.app_settings.LANGUAGE_DETECTION_SAMPLE_CHARS)

        await self.db.execute(delete(DocumentPage).where(DocumentPage.file_id == document_id))

        self.db.add_all(
            DocumentPage(
                file_id=document_id,
                page_number=page.page_number,
                unit_location=page.unit_location,
                raw_text=page.raw_text,
                raw_tables=page.raw_tables,
                extraction_method=page.extraction_method,
            )
            for page in parsed.pages
        )

        document.page_count = parsed.page_count
        document.language = parsed.language
        document.debug_extraction_trace = {"warnings": parsed.warnings} if parsed.warnings else None

        if document.offer_id is not None:
            # A (re)parse invalidates any pre-persist stage output cached for
            # this offer's resume - it was computed from this document's
            # PREVIOUS text. Without this, re-parsing one document (e.g. to
            # fix an OCR problem) independently of a pipeline run leaves a
            # stale `pipeline_checkpoint` in place; the next rerun would see
            # "all documents parsed" + "checkpoint present" and skip straight
            # to persist with extraction/verification results computed
            # against text that no longer exists. See `pipeline/resume.py`,
            # whose own docstring says the checkpoint is invalidated as a
            # whole the moment any document isn't fully parsed - this is the
            # same rule applied to a parse that happens outside a job.
            offer = await self.db.get(Offer, document.offer_id)
            if offer is not None and offer.pipeline_checkpoint is not None:
                offer.pipeline_checkpoint = None
                offer.pipeline_checkpoint_updated_at = None

        try:
            if commit:
                await self.db.commit()
            else:
                await self.db.flush()
        except Exception:
            await self.db.rollback()
            raise

        await self.db.refresh(document)
        return document, parsed
