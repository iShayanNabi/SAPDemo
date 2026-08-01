"""Reading an upload off the wire without trusting how big it is.

Every upload route used to do this::

    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise FileValidationError(...)

which enforces the limit *after* the whole payload is in memory. A 2 GB POST is
therefore 2 GB of resident memory before the check that rejects it runs, and the
limit protects the analysis but not the process. Locally that is a hang; on any
shared host it is the whole application, because one request can exhaust the
machine for every other request in flight.

:func:`read_upload_within_limit` reads in chunks and stops at the first byte
past the limit, so an oversized upload costs one chunk more than the limit and
is rejected with the same message it always produced.
"""

from __future__ import annotations

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import FileValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Chunk size for streaming reads. Large enough that a 25 MB file is ~32 reads,
#: small enough that the overshoot past the limit is negligible.
CHUNK_BYTES = 512 * 1024


async def read_upload_within_limit(
    file: UploadFile,
    *,
    max_bytes: int | None = None,
    what: str = "file",
) -> bytes:
    """Read ``file`` fully, refusing anything larger than ``max_bytes``.

    Args:
        file: The multipart upload as received by FastAPI.
        max_bytes: The limit. Defaults to ``settings.max_upload_bytes``; the
            document routes pass ``settings.max_document_bytes`` instead.
        what: The noun used in the error message ("file", "document").

    Returns:
        The payload bytes.

    Raises:
        FileValidationError: if the payload is empty or exceeds the limit. The
            message names the limit in MB, because "too large" without a number
            tells a user nothing about what to do next.
    """
    limit = settings.max_upload_bytes if max_bytes is None else max_bytes
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await file.read(CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            # Stop reading immediately: the rest of the body is not worth the
            # memory, and the client is told the same thing either way.
            logger.warning(
                "Rejected an oversized upload: more than %s bytes (limit %s).", total, limit
            )
            raise FileValidationError(
                f"The {what} is larger than the {limit / (1024 * 1024):.0f} MB limit.",
                details={"max_bytes": limit},
            )
        chunks.append(chunk)

    if total == 0:
        raise FileValidationError(f"The uploaded {what} is empty.")

    return b"".join(chunks)
