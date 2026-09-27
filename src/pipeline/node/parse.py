import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from controllers import ParseController
from helpers import get_settings
from helpers.offer_events import record_documents_parsed
from models.db_schema import Document
from pipeline.progress import JobProgress
from pipeline.state import PipelineState

STAGE_ID = "parse"


def make_parse_node(
    session_factory: Callable[[], AsyncSession],
    progress: JobProgress,
) -> Callable[[PipelineState], Awaitable[PipelineState]]:
    """Builds the node that sends every file uploaded for one offer to Parsing
    Studio and stores the text it returns, page by page.

    Files go up concurrently, bounded by PARSING_STUDIO_MAX_CONCURRENT_FILES.
    That bound is about the SERVICE, not this machine: Parsing Studio runs a
    fixed number of parses at once for everyone who uses it and queues the
    rest, so sending more than that from here makes nothing faster - it only
    puts this offer's extra files in the queue ahead of a colleague's.

    While a file is being read, the progress detail names the stage the service
    reports for it ("BOQ.xlsx: extract"), so a slow OCR run on a scanned page
    reads as work in progress rather than a hang. A cancel is checked on every
    poll, not only between files, for the same reason.

    Each file gets its own session: `parse_document` commits, and sharing one
    session across concurrent writers is not safe.
    """

    async def parse_node(state: PipelineState) -> PipelineState:
        await progress.raise_if_cancelled()
        settings = get_settings()
        document_ids = list(state["document_ids"])
        total = len(document_ids)
        await progress.start_stage(STAGE_ID, f"0 of {total} file(s) read")

        gate = asyncio.Semaphore(max(1, settings.PARSING_STUDIO_MAX_CONCURRENT_FILES))
        completed = 0
        # filename -> the stage Parsing Studio last reported for it
        in_flight: dict[str, str] = {}
        lock = asyncio.Lock()

        async def report() -> None:
            detail = f"{completed} of {total} file(s) read"
            if in_flight:
                detail += " · " + ", ".join(f"{name}: {stage}" for name, stage in in_flight.items())
            await progress.update_detail(
                STAGE_ID, detail, fraction=completed / total if total else 1.0
            )

        async def parse_one(document_id) -> int:
            nonlocal completed
            async with gate:
                async with session_factory() as db:
                    document = await db.get(Document, document_id)
                    filename = document.original_filename if document else str(document_id)

                    async def on_stage(stage: str) -> None:
                        async with lock:
                            in_flight[filename] = stage
                            await report()

                    try:
                        document, _parsed = await ParseController(db).parse_document(
                            document_id=document_id,
                            commit=True,
                            on_stage=on_stage,
                            check_cancelled=progress.raise_if_cancelled,
                        )
                    finally:
                        in_flight.pop(filename, None)
                    page_count = document.page_count or 0
            async with lock:
                completed += 1
                await report()
            return page_count

        tasks = [asyncio.create_task(parse_one(document_id)) for document_id in document_ids]
        try:
            page_counts = await asyncio.gather(*tasks)
        except BaseException:
            # A failure here aborts the run, but the other files must not keep
            # polling (and holding a slot at the service) for a job nobody is
            # watching any more.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        pages = sum(page_counts)
        await progress.finish_stage(
            STAGE_ID, f"{total} file(s), {pages} page(s)"
        )
        # "Bidsense parsed 42 pages across 3 files". Written here, while the
        # counts are in hand: re-running this offer replaces its pages, and by
        # tomorrow nothing could reconstruct what this run actually read.
        await record_documents_parsed(
            offer_id=state["offer_id"], file_count=total, page_count=pages
        )
        return {}

    return parse_node
