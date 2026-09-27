import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_schema import Document, DocumentPage

from .source_index import SourceIndex, SourceSegment, build_normalized


async def get_offer_documents(db: AsyncSession, offer_id: int) -> list[dict]:
    """Every document uploaded under one offer, in the `documents` shape
    callers expect (document_id + filename only - each document's own pages
    are fetched separately). Ordered by upload time so chunk boundaries (and
    therefore extraction/verification results) are stable across repeated
    runs of the same offer, rather than depending on whatever order Postgres
    happens to return rows in."""
    result = await db.execute(
        select(Document).where(Document.offer_id == offer_id).order_by(Document.uploaded_at)
    )
    documents = result.scalars().all()
    return [
        {"document_id": document.document_id, "filename": document.original_filename}
        for document in documents
    ]


async def get_ordered_pages(db: AsyncSession, document_id: uuid.UUID) -> list[DocumentPage]:
    result = await db.execute(
        select(DocumentPage)
        .where(DocumentPage.file_id == document_id)
        .order_by(DocumentPage.page_number)
    )
    return list(result.scalars().all())


def render_table_as_text(table: dict) -> str:
    num_rows = table.get("num_rows", 0)
    num_cols = table.get("num_cols", 0)
    grid = [["" for _ in range(num_cols)] for _ in range(num_rows)]

    for cell in table.get("cells", []):
        row, col = cell.get("row", 0), cell.get("col", 0)
        if 0 <= row < num_rows and 0 <= col < num_cols:
            grid[row][col] = cell.get("text", "") or ""

    return "\n".join(" | ".join(row_cells) for row_cells in grid)


def build_indexed_page_text(
    pages: list[DocumentPage], file_labels: dict[uuid.UUID, str] | None = None
) -> SourceIndex:
    """The merged text AND the offset map saying which page each part came from.

    `file_labels` (document_id -> filename) marks a file boundary whenever the
    source file changes, so an offer split across several uploaded files (e.g. a
    technical datasheet + a separate commercial sheet) reads as one document
    with clearly labeled sections instead of colliding page numbers ("PAGE 1"
    from two different files back to back).

    The index is produced here, by the same loop that assembles the text,
    because the two have to agree exactly. Anything that needs to attribute a
    quote back to a file and page - the completeness checker - uses this;
    `build_merged_page_text` is the same assembly when only the text is wanted.
    """
    blocks: list[str] = []
    segments: list[SourceSegment] = []
    offset = 0
    current_file_id: uuid.UUID | None = None
    multi_file = bool(file_labels) and len({p.file_id for p in pages}) > 1

    def append(block: str) -> int:
        """Appends a block and returns the offset it starts at."""
        nonlocal offset
        if blocks:
            offset += 2  # the blank line that will join this block to the last
        start_offset = offset
        blocks.append(block)
        offset += len(block)
        return start_offset

    for page in pages:
        if multi_file and page.file_id != current_file_id:
            current_file_id = page.file_id
            append(f"=== FILE: {file_labels.get(page.file_id, page.file_id)} ===")
        page_number = page.page_number if page.page_number is not None else "?"
        # A "page" of a spreadsheet or Word file is a unit Parsing Studio
        # names ("Sheet 'BOQ'"). Page 3 alone tells neither the model nor a
        # reviewer which sheet a price came from.
        unit_name = ((page.unit_location or {}).get("page_label") or "").strip()
        marker = f"--- PAGE {page_number} ({unit_name}) ---" if unit_name else f"--- PAGE {page_number} ---"
        page_parts = [page.raw_text or ""]
        # Pages parsed before Parsing Studio carry structured tables; newer
        # pages have their tables inline as Markdown and none here.
        for table_index, table in enumerate(page.raw_tables or []):
            page_parts.append(f"[TABLE {table_index + 1}]\n{render_table_as_text(table)}")
        block = f"{marker}\n" + "\n\n".join(page_parts)
        block_start = append(block)
        segments.append(
            SourceSegment(
                start=block_start,
                end=offset,
                document_id=page.file_id,
                page_number=page.page_number,
            )
        )

    text = "\n\n".join(blocks)
    normalized, normalized_offsets = build_normalized(text)
    return SourceIndex(
        text=text,
        segments=tuple(segments),
        normalized=normalized,
        normalized_offsets=normalized_offsets,
    )


def build_merged_page_text(
    pages: list[DocumentPage], file_labels: dict[uuid.UUID, str] | None = None
) -> str:
    """The merged source text for a set of pages - delegates to
    `build_indexed_page_text` so the text and its offset index can never
    drift apart."""
    return build_indexed_page_text(pages, file_labels).text


async def get_offer_source_text(db: AsyncSession, offer_id: int) -> str:
    """The full parsed text of every document uploaded under one offer,
    merged into a single blob (no chunking) - used by callers like the
    Verification node that need to compare specific extracted values or
    findings against the complete original source in one pass, rather than
    the page-chunked view extraction itself uses."""
    documents = await get_offer_documents(db, offer_id)
    document_ids = [doc["document_id"] for doc in documents]
    file_labels = {doc["document_id"]: doc["filename"] for doc in documents}

    pages: list[DocumentPage] = []
    for document_id in document_ids:
        pages.extend(await get_ordered_pages(db, document_id))

    return build_merged_page_text(pages, file_labels)
