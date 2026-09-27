"""The corporate Parsing Studio service - every offer file is read through it.

Bidsense does not parse documents itself. It uploads a file, asks for the
cleaned text page by page (`want=text`), and stores those pages. Parsing Studio
owns everything about getting text out of a file: OCR for scans, docling for
layout, tables rendered as Markdown, Excel and Word. One engine for every
application is the point, so there is deliberately no local fallback here: if
the service is down, a parse fails and says so, and the run can be started again
once it is back. A quiet fallback would hand extraction worse text - no OCR, no
spreadsheets - with nothing on screen to say why the results got worse.

This speaks the HTTP contract directly (`docs/api.md` and
`examples/api_python.py` in parsing-studio-server) rather than through the
`parsing_studio` pip client, for two reasons: that client is synchronous, and
its `text()` returns the joined text only, while Bidsense needs one row per
page. The rules the client lives by are kept here too:

* reads are retried on a dropped connection or a 502/503/504;
* the upload is never retried - a second POST starts, and pays for, a second run;
* the server's refusals are sentences written for people ("File content does
  not match its extension (.xlsx)."), so they are passed on verbatim.

Uploads are deleted from the service once their text has been read. Parsing
Studio has no authentication and keeps documents for 24 hours, and a supplier's
offer should not sit on a shared box readable by anyone who can reach the port.
The delete removes the file, its runs and everything reachable through the API.
It does NOT remove the service's stage cache: that cache is content-addressed
and shared between identical uploads, so the service sweeps it by age (24 hours
after last use) rather than with any one document. Until that sweep the parsed
text remains on the server's disk - not listable over HTTP, but present.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

#: The contract this module was written against; `GET /health` reports the
#: server's. It only moves when an existing route changes incompatibly.
SUPPORTED_API_VERSION = 1

_CONNECT_TIMEOUT_SECONDS = 10.0
# Per request, not per parse: an upload of a large file, or one poll. The
# parse itself is bounded separately by the caller's `timeout_seconds`.
_REQUEST_TIMEOUT_SECONDS = 120.0
_READ_ATTEMPTS = 3
_RETRYABLE_STATUS_CODES = frozenset({502, 503, 504})
# Most documents finish in seconds; a 40-page scan does not need to be asked
# twice a second for ten minutes. Start fast, then back off.
_FIRST_POLL_DELAY_SECONDS = 0.5
_MAX_POLL_DELAY_SECONDS = 5.0

# Servers whose api_version has been checked, so the handshake runs once per
# server per process rather than once per file.
_verified_servers: set[str] = set()


class ParsingStudioError(Exception):
    """Base class. Every message is written to be shown to a reviewer as-is."""


class ParsingServiceUnavailableError(ParsingStudioError):
    """No server answered, or one answered in a way that says it is unwell."""


class UnsupportedDocumentError(ParsingStudioError):
    """The service refused this file - its own sentence says why."""


class DocumentParseFailedError(ParsingStudioError):
    """The run was accepted and then finished in `error`."""


class ParseTimeoutError(ParsingStudioError):
    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Parsing Studio did not finish reading this file within {timeout_seconds:.0f}s"
        )


@dataclass(frozen=True)
class StudioPage:
    """One page as Parsing Studio produced it. `page` is 1-based."""

    page: int
    text: str
    #: The parser that actually produced the text - which is allowed to
    #: differ from the one the classifier recommended.
    parser: str
    #: "ok", or a word for what went wrong: "bad", "fallback", "flagged", ...
    quality: str
    error: str | None
    #: The unit's own name in a non-paged format ("Sheet 'BOQ'"); "" for PDFs.
    page_label: str


@dataclass(frozen=True)
class StudioParse:
    run_id: str
    document_id: str
    server: str
    pages: tuple[StudioPage, ...]


def parse_server_urls(raw: str) -> list[str]:
    """`PARSING_STUDIO_URLS` is comma-separated, tried in the order given."""
    urls = [part.strip().rstrip("/") for part in (raw or "").split(",")]
    urls = [url for url in urls if url]
    if not urls:
        raise ValueError("PARSING_STUDIO_URLS is empty - it must name at least one server")
    return urls


def _detail(response: httpx.Response) -> str:
    """The server's own explanation, flattened to one sentence."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):  # FastAPI validation errors
        detail = "; ".join(str(item.get("msg", item)) if isinstance(item, dict) else str(item) for item in detail)
    return str(detail or response.text or f"HTTP {response.status_code}").strip()


def join_pages(text_body: dict, extract_body: dict) -> tuple[StudioPage, ...]:
    """Pairs each page's cleaned text with the extract stage's account of it.

    The two routes number pages differently, and that is the whole trap here:
    `/runs/{id}/text` is 1-based (it is for people holding the document) while
    the extract artifact keeps the engine's 0-based `page`. Joining them
    without the +1 would attach page 2's parser and quality to page 1.

    A page present in only one of the two is kept rather than dropped - a page
    whose extraction errored may have no cleaned text, and that error is
    exactly the thing worth recording.
    """
    texts = {int(page["page"]): page.get("text") or "" for page in text_body.get("pages") or []}
    provenance = {int(page["page"]) + 1: page for page in extract_body.get("pages") or []}

    pages = []
    for number in sorted(texts.keys() | provenance.keys()):
        extract = provenance.get(number, {})
        pages.append(
            StudioPage(
                page=number,
                text=texts.get(number, ""),
                parser=extract.get("parser") or "",
                quality=extract.get("quality") or "",
                error=extract.get("error") or None,
                page_label=extract.get("page_label") or "",
            )
        )
    return tuple(pages)


class ParsingStudioClient:
    def __init__(
        self,
        *,
        urls: list[str],
        recipe: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.urls = urls
        self.recipe = recipe
        self.timeout_seconds = timeout_seconds
        # Tests hand in an httpx.MockTransport; production uses the network.
        self._transport = transport

    async def parse_file(
        self,
        path: Path,
        filename: str,
        *,
        on_stage: Callable[[str], Awaitable[None]] | None = None,
        check_cancelled: Callable[[], Awaitable[None]] | None = None,
    ) -> StudioParse:
        """Uploads one file, waits for it, and returns its pages.

        `filename` must carry the real extension - the service decides how to
        read a file from it, and checks the bytes agree.

        `on_stage` is told the name of the stage the run is in whenever it
        changes, for the progress bar. `check_cancelled` is awaited before
        every poll and is expected to raise to stop; a parse of a scanned
        offer can take minutes, and a cancel should not have to wait for it.
        """
        timeout = httpx.Timeout(_REQUEST_TIMEOUT_SECONDS, connect=_CONNECT_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as http:
            content = await asyncio.to_thread(Path(path).read_bytes)
            server, started = await self._start(http, filename, content)
            run_id, document_id = started["run_id"], started["document_id"]

            finished = False
            try:
                state = await self._wait(http, server, run_id, on_stage, check_cancelled)
                finished = True
                if state.get("status") == "error":
                    raise DocumentParseFailedError(
                        f"Parsing Studio could not read {filename}: "
                        f"{state.get('error') or 'the run failed without giving a reason'}"
                    )
                text_body = await self._get_json(http, server, f"/runs/{run_id}/text")
                extract_body = await self._get_json(http, server, f"/runs/{run_id}/stages/extract")
                return StudioParse(
                    run_id=run_id,
                    document_id=document_id,
                    server=server,
                    pages=join_pages(text_body, extract_body),
                )
            finally:
                if finished:
                    await self._delete_document(http, server, document_id)
                else:
                    # There is no cancel route, and a document with a live run
                    # cannot be deleted - so a run abandoned mid-way (timeout,
                    # cancel) is left to the service's own retention.
                    logger.info(
                        "parsing_studio run=%s document=%s abandoned before it finished; "
                        "left to the service's retention",
                        run_id, document_id,
                    )

    async def _start(self, http: httpx.AsyncClient, filename: str, content: bytes) -> tuple[str, dict]:
        """Hands the file to the first server that answers.

        Moving on to the next server is only safe when the request never
        reached this one - a refused or timed-out CONNECTION. Anything later
        (a read timeout after the upload went out) may mean a run already
        started there, and repeating the upload elsewhere would pay for the
        same document twice.
        """
        unreachable: list[str] = []
        for server in self.urls:
            try:
                await self._handshake(http, server)
                response = await http.post(
                    f"{server}/parse",
                    files={"file": (filename, content)},
                    data={"want": "text", "pages": "all", "recipe": self.recipe},
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                unreachable.append(f"{server} ({exc.__class__.__name__})")
                logger.warning("parsing_studio %s unreachable: %s", server, exc)
                continue
            except httpx.HTTPError as exc:
                raise ParsingServiceUnavailableError(
                    f"Parsing Studio at {server} took the upload of {filename} but did not answer ({exc})"
                ) from exc

            if response.status_code == 202:
                return server, response.json()
            detail = _detail(response)
            if response.status_code in (400, 413, 415):
                raise UnsupportedDocumentError(f"Parsing Studio cannot read {filename}: {detail}")
            if response.status_code >= 500:
                raise ParsingServiceUnavailableError(
                    f"Parsing Studio at {server} failed to accept {filename} (HTTP {response.status_code}): {detail}"
                )
            raise ParsingStudioError(
                f"Parsing Studio refused {filename} (HTTP {response.status_code}): {detail}"
            )

        raise ParsingServiceUnavailableError(
            "Parsing Studio could not be reached: " + "; ".join(unreachable)
        )

    async def _handshake(self, http: httpx.AsyncClient, server: str) -> None:
        if server in _verified_servers:
            return
        health = await self._get_json(http, server, "/health", connect_errors_propagate=True)
        version = health.get("api_version")
        if not isinstance(version, int) or version < SUPPORTED_API_VERSION:
            raise ParsingServiceUnavailableError(
                f"Parsing Studio at {server} reports api_version={version}; Bidsense needs "
                f"{SUPPORTED_API_VERSION}. The service is running an older build."
            )
        if version > SUPPORTED_API_VERSION:
            # Newer is not fatal - the routes used here are additive-only by
            # the service's own rule - but it is worth a line in the log.
            logger.warning(
                "parsing_studio %s speaks api_version %s; Bidsense was written against %s",
                server, version, SUPPORTED_API_VERSION,
            )
        _verified_servers.add(server)

    async def _wait(
        self,
        http: httpx.AsyncClient,
        server: str,
        run_id: str,
        on_stage: Callable[[str], Awaitable[None]] | None,
        check_cancelled: Callable[[], Awaitable[None]] | None,
    ) -> dict:
        deadline = time.monotonic() + self.timeout_seconds
        delay = _FIRST_POLL_DELAY_SECONDS
        reported: str | None = None
        while True:
            if check_cancelled is not None:
                await check_cancelled()
            state = await self._get_json(http, server, f"/runs/{run_id}")
            status = state.get("status")
            if status in ("done", "error"):
                return state

            running = next(
                (stage.get("stage") for stage in state.get("stages") or [] if stage.get("status") == "running"),
                None,
            )
            current = running or status or ""
            if on_stage is not None and current and current != reported:
                reported = current
                await on_stage(current)

            if time.monotonic() > deadline:
                raise ParseTimeoutError(self.timeout_seconds)
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, _MAX_POLL_DELAY_SECONDS)

    async def _get_json(
        self,
        http: httpx.AsyncClient,
        server: str,
        path: str,
        *,
        connect_errors_propagate: bool = False,
    ) -> dict:
        """A GET, retried on a dropped connection or a gateway-style 5xx.

        Polling on a pooled connection eventually sends a request down a socket
        the server has just closed on its own keep-alive timeout; without a
        retry that kills a ten-minute wait for no reason anyone could act on.

        `connect_errors_propagate` lets the handshake's refused connection
        reach `_start`, which answers it by trying the next server.
        """
        last_error: str = ""
        for attempt in range(1, _READ_ATTEMPTS + 1):
            try:
                response = await http.get(f"{server}{path}")
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if connect_errors_propagate:
                    raise
                last_error = "connection refused or timed out"
            except httpx.TransportError as exc:
                last_error = f"{exc.__class__.__name__}: {exc}"
            else:
                if response.status_code < 400:
                    return response.json()
                if response.status_code not in _RETRYABLE_STATUS_CODES:
                    raise ParsingStudioError(
                        f"Parsing Studio answered {path} with HTTP {response.status_code}: {_detail(response)}"
                    )
                last_error = f"HTTP {response.status_code}"
            if attempt < _READ_ATTEMPTS:
                await asyncio.sleep(0.3 * 2 ** (attempt - 1))

        raise ParsingServiceUnavailableError(
            f"Parsing Studio at {server} stopped answering ({last_error})"
        )

    async def _delete_document(self, http: httpx.AsyncClient, server: str, document_id: str) -> None:
        """Best effort, and never raises: the pages are already read, and a
        failed clean-up must not fail the parse that produced them. The
        service's retention is the backstop.

        The service de-duplicates uploads by content, so the same bytes
        uploaded by someone else share this document id - deleting it removes
        their copy too. For supplier offers that collision is not a realistic
        concern, and not leaving the offer behind is the stronger rule.
        """
        try:
            response = await http.delete(f"{server}/documents/{document_id}")
        except httpx.HTTPError as exc:
            logger.warning("parsing_studio could not delete document=%s: %s", document_id, exc)
            return
        if response.status_code == 200:
            logger.info("parsing_studio deleted document=%s after reading it", document_id)
        elif response.status_code in (404, 409):
            # 404: already gone. 409: another run is still using the same
            # bytes; that run's own clean-up will delete it.
            logger.info(
                "parsing_studio left document=%s (HTTP %s: %s)",
                document_id, response.status_code, _detail(response),
            )
        else:
            logger.warning(
                "parsing_studio could not delete document=%s (HTTP %s: %s)",
                document_id, response.status_code, _detail(response),
            )
