"""Upload validation.

Everything that arrives from a browser is untrusted. Before a byte is written
to disk we check, in order:

1. the sanitised extension is on the allow list;
2. the payload is not empty and not larger than the configured limit;
3. the leading bytes match the claimed format (a ``.xlsx`` must really be a ZIP
   container, a ``.csv``/``.json`` must be decodable text);
4. the payload contains no null bytes when it claims to be text.

Two allow lists exist, deliberately separate:

``validate_upload``
    Tabular uploads (CSV / XLSX / JSON) used by modules 1-5.
``validate_document_upload``
    Documents (PDF / DOCX / TXT, plus images when OCR is configured) used by
    the Contract Assistant. Keeping them apart means growing the document list
    can never make a spend module start accepting PDFs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.demo import ensure_uploads_allowed
from app.core.exceptions import FileValidationError
from app.core.security import sanitize_filename, sha256_of_bytes

# Magic byte prefixes used for a light-weight content sniff.
_ZIP_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0"  # legacy .xls / .doc - rejected with a helpful message
_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_TIFF_MAGICS = (b"II*\x00", b"MM\x00*")
_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

#: Extensions whose payload must be a decodable, null-byte-free text file.
_TEXT_EXTENSIONS = {".csv", ".json", ".txt", ".md"}


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
        DemoModeError: if this is a public demonstration that refuses uploads.
    """
    ensure_uploads_allowed("file")

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


def validate_document_upload(filename: str, content: bytes) -> ValidatedUpload:
    """Validate an uploaded *document* (contract) payload.

    Documents follow the same three checks as tabular uploads - allow-listed
    extension, size, content sniff - against the document allow list and the
    document size limit. Image types are only accepted when an OCR provider is
    actually configured, so an operator is told "OCR is not configured" at
    upload time rather than getting an empty analysis later.

    Raises:
        FileValidationError: with a user-safe message for any rejection.
        DemoModeError: if this is a public demonstration that refuses uploads.
    """
    ensure_uploads_allowed("document")

    safe_filename = sanitize_filename(filename)
    extension = Path(safe_filename).suffix.lower()

    documents = settings.allowed_document_extension_set
    images = settings.allowed_image_extension_set
    ocr_provider = settings.resolved_ocr_provider()
    accepted = sorted(documents | images) if ocr_provider != "none" else sorted(documents)

    if not extension:
        raise FileValidationError(
            "The file has no extension. Supported document types: " + ", ".join(accepted),
            details={"allowed_extensions": accepted},
        )
    if extension in images and ocr_provider == "none":
        raise FileValidationError(
            f"'{extension}' is a scanned image and no OCR provider is configured, so no text "
            f"can be extracted from it. Configure OCR_PROVIDER, or upload a text-based PDF, "
            f"DOCX or TXT file.",
            details={
                "allowed_extensions": accepted,
                "ocr_provider": ocr_provider,
                "requires_ocr": True,
            },
        )
    if extension not in documents and extension not in images:
        if extension == ".doc":
            raise FileValidationError(
                "Legacy .doc documents are not supported. Save the file as .docx and retry.",
                details={"allowed_extensions": accepted},
            )
        raise FileValidationError(
            f"File type '{extension}' is not a supported document. Supported types: "
            + ", ".join(accepted),
            details={"allowed_extensions": accepted},
        )

    size = len(content)
    if size == 0:
        raise FileValidationError("The uploaded document is empty.")
    if size > settings.max_document_bytes:
        limit_mb = settings.max_document_bytes / (1024 * 1024)
        raise FileValidationError(
            f"The document is larger than the {limit_mb:.0f} MB limit.",
            details={"size_bytes": size, "max_bytes": settings.max_document_bytes},
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

    if extension in {".xlsx", ".docx"}:
        if head.startswith(_OLE2_MAGIC):
            legacy = "workbook" if extension == ".xlsx" else "document"
            new_ext = "xlsx" if extension == ".xlsx" else "docx"
            raise FileValidationError(
                f"This looks like a legacy Microsoft Office {legacy}. "
                f"Save it as .{new_ext} and retry."
            )
        if not head.startswith(_ZIP_MAGIC):
            raise FileValidationError(
                f"The file does not look like a valid {extension} file.",
                details={"expected": f"{extension.lstrip('.')} (zip container)"},
            )
        return

    if extension == ".pdf":
        # A PDF may carry a small amount of junk before the header, which real
        # readers tolerate; anything further in is not a PDF.
        if _PDF_MAGIC not in content[:1024]:
            raise FileValidationError(
                "The file does not look like a valid PDF document.",
                details={"expected": "pdf (%PDF- header)"},
            )
        return

    if extension in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        if not (
            content.startswith(_PNG_MAGIC)
            or content.startswith(_JPEG_MAGIC)
            or any(content.startswith(magic) for magic in _TIFF_MAGICS)
        ):
            raise FileValidationError(
                f"The file does not look like a valid {extension.lstrip('.').upper()} image."
            )
        return

    if extension not in _TEXT_EXTENSIONS:  # pragma: no cover - validation rejects earlier
        raise FileValidationError(f"File type '{extension}' cannot be checked.")

    # CSV, JSON, TXT and MD must be decodable text without null bytes.
    if b"\x00" in content[:4096]:
        raise FileValidationError(
            f"The file does not look like a text based {extension.lstrip('.').upper()} file."
        )
    if head.startswith(_ZIP_MAGIC) or head.startswith(_PDF_MAGIC):
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
