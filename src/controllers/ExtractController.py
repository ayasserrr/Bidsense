import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from helpers.extraction_merge import chunk_pages, drop_signature_only_contact_duplicate, merge_chunk_payloads
from helpers.llm_runnable import LlmCallError, LlmValidationError
from helpers.source_text import (
    build_merged_page_text,
    get_offer_documents,
    get_ordered_pages,
    render_table_as_text,
)
from models.db_schema import Document, DocumentPage
from schema.offer import OfferExtractionPayload
from tools import extract_offer_draft, extract_offer_verify
from tools._common import unpack_result

from .BaseController import BaseController

logger = logging.getLogger(__name__)

# (chunks_completed, chunks_total) - lets a long extraction report real
# progress while it runs instead of looking frozen for ten minutes.
ChunkProgressCallback = Callable[[int, int], Awaitable[None]]


class DocumentHasNoParsedPagesError(Exception):
    def __init__(self, document_ids: list[uuid.UUID]):
        self.document_ids = document_ids
        ids = ", ".join(str(d) for d in document_ids)
        super().__init__(f"No parsed pages found for document(s): {ids}")


class ExtractController(BaseController):
    def __init__(self, db: AsyncSession):
        super().__init__()
        self.db = db

    async def get_document(self, document_id: uuid.UUID) -> Document | None:
        return await self.db.get(Document, document_id)

    async def get_offer_documents(self, offer_id: int) -> list[dict]:
        return await get_offer_documents(self.db, offer_id)

    async def get_ordered_pages(self, document_id: uuid.UUID) -> list[DocumentPage]:
        return await get_ordered_pages(self.db, document_id)

    @staticmethod
    def render_table_as_text(table: dict) -> str:
        return render_table_as_text(table)

    @staticmethod
    def build_merged_page_text(
        pages: list[DocumentPage], file_labels: dict[uuid.UUID, str] | None = None
    ) -> str:
        return build_merged_page_text(pages, file_labels)

    async def _extract_chunk(
        self,
        *,
        log_id: str,
        merged_text: str,
        chunk_index: int,
        total_chunks: int,
    ) -> tuple[OfferExtractionPayload, dict]:
        """Runs the draft -> verify two-pass extraction (via the
        `extract_offer_draft`/`extract_offer_verify` tools) on one chunk's
        worth of pages. When split into multiple chunks, the model is told
        this is a partial excerpt so it doesn't null out offer-level fields
        in confusion. Returns (payload, telemetry_dict)."""
        if total_chunks > 1:
            chunk_note = (
                f"\n\nNOTE: this is part {chunk_index + 1} of {total_chunks} of a single longer document, "
                "split purely because of its length - it is NOT a separate, complete offer on its own. "
                "Extract only what this excerpt itself states. If an offer-level field (supplier name, "
                "payment terms, grand total, etc.) is not stated anywhere in this excerpt, leave it null "
                "rather than guessing - it may be stated in another part of the document and will be "
                "merged in separately. Items you see in this excerpt are still real items - give each one "
                "its own local_id as usual."
            )
            user_content = merged_text + chunk_note
            label_suffix = f"_chunk{chunk_index + 1}of{total_chunks}"
        else:
            user_content = merged_text
            label_suffix = ""

        draft_raw = await extract_offer_draft.ainvoke(
            {"user_content": user_content, "log_id": log_id, "pass_label": f"draft{label_suffix}"}
        )
        draft_payload, draft_telemetry = unpack_result(draft_raw, OfferExtractionPayload)
        draft_repairs = draft_telemetry.get("repair_attempts", 0)

        verify_user_content = (
            "SOURCE DOCUMENT TEXT:\n"
            + user_content
            + "\n\n---\n\nFIRST-PASS EXTRACTED JSON:\n"
            + draft_payload.model_dump_json()
        )

        try:
            verify_raw = await extract_offer_verify.ainvoke(
                {
                    "user_content": verify_user_content,
                    "log_id": log_id,
                    "pass_label": f"verify{label_suffix}",
                }
            )
            verify_payload, verify_telemetry = unpack_result(verify_raw, OfferExtractionPayload)
            telemetry = {
                "draft_repairs": draft_repairs,
                "verify_repairs": verify_telemetry.get("repair_attempts", 0),
                "verify_passed": True,
            }
            return verify_payload, telemetry
        except (LlmCallError, LlmValidationError) as exc:
            # Log diff-style summary if possible
            try:
                if isinstance(exc, LlmValidationError):
                    try:
                        invalid_data = json.loads(exc.raw_response)
                        draft_data = draft_payload.model_dump(mode="json")
                        diff_summary = {
                            "draft_items": len(draft_data.get("items", [])),
                            "verify_items": len(invalid_data.get("items", [])),
                            "draft_fields": sum(len(v) if isinstance(v, dict) else 0 for v in draft_data.values()),
                            "verify_fields": sum(len(v) if isinstance(v, dict) else 0 for v in invalid_data.values()),
                        }
                        logger.error(
                            "verification pass failed for log_id=%s chunk=%s/%s - diff summary: %s; falling back to first-pass extraction",
                            log_id, chunk_index + 1, total_chunks, diff_summary,
                        )
                    except json.JSONDecodeError:
                        logger.error(
                            "verification pass failed for log_id=%s chunk=%s/%s (response not parseable as JSON); falling back to first-pass extraction",
                            log_id, chunk_index + 1, total_chunks,
                        )
                else:
                    logger.error(
                        "verification pass failed for log_id=%s chunk=%s/%s (%s); falling back to first-pass extraction",
                        log_id, chunk_index + 1, total_chunks, exc,
                    )
            except Exception as log_exc:
                logger.error(
                    "verification pass failed for log_id=%s chunk=%s/%s (logging error: %s); falling back to first-pass extraction",
                    log_id, chunk_index + 1, total_chunks, log_exc,
                )

            telemetry = {
                "draft_repairs": draft_repairs,
                "verify_repairs": 0,
                "verify_passed": False,
            }
            return draft_payload, telemetry

    async def extract_offer(
        self,
        documents: list[dict],
        on_chunk_progress: ChunkProgressCallback | None = None,
    ) -> OfferExtractionPayload:
        """Two-pass (draft -> verify) extraction, chunked across pages for long
        documents. `documents` is every file uploaded together for this offer
        - their pages are combined into one list *before* chunking, so a
        technical sheet and a separate commercial sheet are read as one logical
        document (the model can match a spec in one to a price in the other and
        write one item with both) rather than extracted file-by-file and
        reconciled afterward."""
        document_ids = [doc["document_id"] for doc in documents]
        file_labels = {doc["document_id"]: doc["filename"] for doc in documents}

        pages: list[DocumentPage] = []
        for document_id in document_ids:
            pages.extend(await self.get_ordered_pages(document_id))
        if not pages:
            raise DocumentHasNoParsedPagesError(document_ids)

        log_id = ",".join(str(d) for d in document_ids)
        page_chunks = chunk_pages(
            pages,
            max_pages=self.app_settings.EXTRACTION_MAX_PAGES_PER_CHUNK,
            overlap=self.app_settings.EXTRACTION_CHUNK_PAGE_OVERLAP,
        )

        total_chunks = len(page_chunks)
        chunks_completed = 0
        # Guards the counter, not the work: without it two chunks finishing in
        # the same tick could both report the same number and the progress bar
        # would stall a step short of the truth.
        progress_lock = asyncio.Lock()

        async def run_chunk(chunk_index: int, chunk: list[DocumentPage]) -> tuple[OfferExtractionPayload, dict]:
            nonlocal chunks_completed
            result = await self._extract_chunk(
                log_id=log_id,
                merged_text=self.build_merged_page_text(chunk, file_labels),
                chunk_index=chunk_index,
                total_chunks=total_chunks,
            )
            if on_chunk_progress is not None:
                async with progress_lock:
                    chunks_completed += 1
                    await on_chunk_progress(chunks_completed, total_chunks)
            return result

        # Chunks are independent by construction - each is told it is an
        # excerpt and extracts only what it can see - so they run concurrently
        # rather than one after another. A four-chunk offer now costs about as
        # long as its slowest chunk instead of the sum of all four. The real
        # ceiling is LLM_MAX_CONCURRENT_REQUESTS inside the transport, which
        # every stage and every concurrent run shares, so this cannot flood the
        # gateway however many chunks a document happens to produce.
        #
        # gather() preserves argument order in its results, which merge_chunk_
        # payloads relies on: a later chunk's value must lose to an earlier
        # one's for offer-level fields, exactly as in the sequential version.
        tasks = [
            asyncio.create_task(run_chunk(chunk_index, chunk))
            for chunk_index, chunk in enumerate(page_chunks)
        ]
        try:
            chunk_results = await asyncio.gather(*tasks)
        except BaseException:
            # One chunk failing (or the whole extraction timing out) must not
            # leave its siblings running: they would keep holding gateway slots
            # and writing to a request that has already returned. Cancel them,
            # wait for them to actually finish unwinding, then re-raise the
            # ORIGINAL error - routes/extract.py maps LlmCallError and friends
            # onto real HTTP statuses and would show a bare 500 for anything else.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        chunk_payloads = [result[0] for result in chunk_results]
        telemetry_list = [result[1] for result in chunk_results]

        payload = (
            chunk_payloads[0]
            if len(chunk_payloads) == 1
            else merge_chunk_payloads(chunk_payloads)
        )
        if len(chunk_payloads) > 1:
            logger.info(
                "extraction log_id=%s merged %s chunks into one payload", log_id, len(chunk_payloads)
            )

        # Aggregate telemetry for logging
        total_draft_repairs = sum(t.get("draft_repairs", 0) for t in telemetry_list)
        total_verify_repairs = sum(t.get("verify_repairs", 0) for t in telemetry_list)
        all_verify_passed = all(t.get("verify_passed", False) for t in telemetry_list)

        logger.info(
            "extraction log_id=%s item_count=%s tech_spec_count=%s contact_count=%s "
            "attachment_count=%s payment_schedule_count=%s total_draft_repairs=%s "
            "total_verify_repairs=%s verify_passed=%s",
            log_id,
            len(payload.items),
            len(payload.tech_specs),
            len(payload.contacts),
            len(payload.attachments),
            len(payload.payment_schedules),
            total_draft_repairs,
            total_verify_repairs,
            all_verify_passed,
        )

        # Populate debug_extraction_trace with telemetry (lightweight, not full
        # payloads) on every source document, for debugging purposes.
        debug_trace = {
            "chunk_count": len(page_chunks),
            "source_document_count": len(documents),
            "total_draft_repairs": total_draft_repairs,
            "total_verify_repairs": total_verify_repairs,
            "verify_passed": all_verify_passed,
            "item_count": len(payload.items),
            "tech_spec_count": len(payload.tech_specs),
            "contact_count": len(payload.contacts),
            "attachment_count": len(payload.attachments),
            "payment_schedule_count": len(payload.payment_schedules),
        }

        for document_id in document_ids:
            document = await self.get_document(document_id)
            if document:
                document.debug_extraction_trace = debug_trace  # type: ignore
        await self.db.commit()

        return drop_signature_only_contact_duplicate(payload)
