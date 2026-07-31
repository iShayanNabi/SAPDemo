"""Upload validation.

Everything that arrives from a browser is untrusted. Before a byte is written
to disk we check, in order:

1. the sanitised extension is on the allow list;
2. the payload is not empty and not larger than the configured limit;
3. the leading bytes match the claimed format (a ``.xlsx`` must really be a ZIP
   container, a ``.csv``/``.json`` must be decodable text);
4. the payload contains no null bytes when it claims to be text.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import FileValidationError
from app.core.security import sanitize_filename, sha256_of_bytes

# Magic byte prefixes used for a light-weight content sniff.
_ZIP_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0"  # legacy .xls - rejected with a helpful message
_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


@dataclass(frozen=True)
class ValidatedUpload:
    """A payload that passed every validation step."""

    original_filename: str
    safe_filename: str
    extension: str
    size_bytes: int
    sha256: str
    content: bytes


def validate_upload(filename: str, content: bytes) -> ValidatedUpload:
    """Validate an uploaded payload.

    Args:
        filename: Client supplied filename (untrusted).
        content: Raw bytes of the upload.

    Returns:
        A :class:`ValidatedUpload` describing the accepted payload.

    Raises:
        FileValidationError: with a user-safe message for any rejection.
    """
    safe_filename = sanitize_filename(filename)
    extension = Path(safe_filename).suffix.lower()

    allowed = sorted(settings.allowed_extension_set)
    if not extension:
        raise FileValidationError(
            "The file has no extension. Allowed types: " + ", ".join(allowed),
            details={"allowed_extensions": allowed},
        )
    if extension not in settings.allowed_extension_set:
        if extension == ".xls":
            raise FileValidationError(
                "Legacy .xls files are not supported. Save the workbook as .xlsx and retry.",
                details={"allowed_extensions": allowed},
            )
        raise FileValidationError(
            f"File type '{extension}' is not supported. Allowed types: " + ", ".join(allowed),
            details={"allowed_extensions": allowed},
        )

    size = len(content)
    if size == 0:
        raise FileValidationError("The uploaded file is empty.")
    if size > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes / (1024 * 1024)
        raise FileValidationError(
            f"The file is larger than the {limit_mb:.0f} MB limit.",
            details={"size_bytes": size, "max_bytes": settings.max_upload_bytes},
        )

    _sniff_content(extension, content)

    return ValidatedUpload(
        original_filename=filename,
        safe_filename=safe_filename,
        extension=extension,
        size_bytes=size,
        sha256=sha256_of_bytes(content),
        content=content,
    )


def _sniff_content(extension: str, content: bytes) -> None:
    """Confirm the payload really looks like the extension claims."""
    head = content[:8]

    if extension == ".xlsx":
        if head.startswith(_OLE2_MAGIC):
            raise FileValidationError(
                "This looks like a legacy .xls workbook. Save it as .xlsx and retry."
            )
        if not head.startswith(_ZIP_MAGIC):
            raise FileValidationError(
                "The file does not look like a valid .xlsx workbook.",
                details={"expected": "xlsx (zip container)"},
            )
        return

    # CSV and JSON must be decodable text without null bytes.
    if b"\x00" in content[:4096]:
        raise FileValidationError(
            f"The file does not look like a text based {extension.lstrip('.').upper()} file."
        )
    if head.startswith(_ZIP_MAGIC):
        raise FileValidationError(
            f"A compressed/binary file was uploaded with the {extension} extension.",
        )
    if decode_text(content) is None:
        raise FileValidationError(
            f"The {extension.lstrip('.').upper()} file could not be decoded as text."
        )


def decode_text(content: bytes) -> str | None:
    """Decode bytes using the encodings commonly produced by SAP exports."""
    for encoding in _TEXT_ENCODINGS:
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return None
