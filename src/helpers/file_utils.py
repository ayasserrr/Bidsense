import hashlib
import os
import uuid
from pathlib import Path

from fastapi import UploadFile

_ALLOWED_FILENAME_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)

# Windows treats these as reserved device names regardless of extension
# (e.g. "con.pdf" fails to open as a real file) - a real supplier filename
# can coincidentally collide with one of these.
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)


class FileTooLargeError(Exception):
    def __init__(self, max_size_bytes: int):
        self.max_size_bytes = max_size_bytes
        super().__init__(f"File exceeds maximum size of {max_size_bytes} bytes")


def sanitize_filename(filename: str) -> str:
    name = os.path.basename(filename or "")
    sanitized_chars: list[str] = []
    previous_was_replaced = False
    for char in name:
        if char in _ALLOWED_FILENAME_CHARS:
            sanitized_chars.append(char)
            previous_was_replaced = False
        elif not previous_was_replaced:
            sanitized_chars.append("_")
            previous_was_replaced = True

    sanitized = "".join(sanitized_chars).strip("._")
    if not sanitized:
        return uuid.uuid4().hex

    stem = sanitized.split(".", 1)[0]
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        return f"_{sanitized}"
    return sanitized


def unique_storage_name(directory: Path, filename: str) -> str:
    candidate = filename
    stem, suffix = os.path.splitext(filename)
    counter = 1
    while (directory / candidate).exists():
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


async def buffer_and_hash(
    file: UploadFile, chunk_size: int, max_size_bytes: int
) -> tuple[bytes, str, int]:
    """Stream-reads `file` in fixed-size chunks, hashing as it goes, and aborts
    as soon as the running size exceeds `max_size_bytes` so an oversized upload
    never has to be fully buffered in memory."""
    hasher = hashlib.sha256()
    buffer = bytearray()

    while chunk := await file.read(chunk_size):
        buffer.extend(chunk)
        if len(buffer) > max_size_bytes:
            raise FileTooLargeError(max_size_bytes)
        hasher.update(chunk)

    return bytes(buffer), hasher.hexdigest(), len(buffer)
