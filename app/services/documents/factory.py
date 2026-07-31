"""Resolve the right extractor for a document and run it.

This is the only function the rest of the lab calls. Its job is to pick an
extractor from the extension, run it, and - when the result turns out to hold
no text - hand the payload to the configured OCR provider *if there is one*.

The fallback is what makes the honesty guarantee work: when no OCR provider is
configured a scanned file comes back as an :class:`ExtractionResult` with
``needs_ocr=True`` and an explanation, never as a silently empty contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.documents.base import (
    DocumentExtractionError,
    DocumentExtractor,
    ExtractionResult,
)
from app.services.documents.ocr import (
    OCR_EXTENSIONS,
    describe_ocr_providers,
    get_ocr_provider,
)
from app.services.documents.text_extractors import (
    DocxExtractor,
    PdfTextExtractor,
    PlainTextExtractor,
)

logger = get_logger(__name__)

#: Extractors that need no external service, in resolution order.
TEXT_EXTRACTORS: tuple[DocumentExtractor, ...] = (
    PdfTextExtractor(),
    DocxExtractor(),
    PlainTextExtractor(),
)


def get_extractor(extension: str) -> DocumentExtractor | None:
    """Return the text extractor that claims ``extension``, or ``None``."""
    for extractor in TEXT_EXTRACTORS:
        if extractor.supports(extension):
            return extractor
    return None


def extract_document(
    content: bytes, filename: str, *, allow_ocr: bool = True
) -> ExtractionResult:
    """Extract per-page text from an uploaded document.

    Args:
        content: The raw bytes of the document.
        filename: The (already sanitised) filename - only its suffix is used.
        allow_ocr: When ``False``, never fall back to OCR even if one is
            configured. Used by tests and by the "text only" analysis path.

    Raises:
        DocumentExtractionError: when nothing can read the payload at all.
    """
    extension = Path(filename or "").suffix.lower()
    extractor = get_extractor(extension)

    if extractor is None:
        if extension in OCR_EXTENSIONS:
            return _run_ocr(content, filename, extension, allow_ocr=allow_ocr)
        raise DocumentExtractionError(
            f"No extractor is available for '{extension or 'a file with no extension'}'. "
            f"Supported document types: {', '.join(sorted(settings.allowed_document_extension_set))}.",
            details={"extension": extension},
        )

    result = extractor.extract(content, filename=filename)

    if result.needs_ocr and allow_ocr and settings.resolved_ocr_provider() != "none":
        logger.info(
            "No text found in %s; retrying with OCR provider '%s'",
            extension,
            settings.resolved_ocr_provider(),
        )
        try:
            return _run_ocr(content, filename, extension, allow_ocr=True)
        except DocumentExtractionError as exc:
            # OCR failing does not lose the (empty) text result: the caller
            # still learns exactly why the document could not be processed.
            result.notes.append(f"OCR fallback failed: {exc.message}")
    return result


def _run_ocr(
    content: bytes, filename: str, extension: str, *, allow_ocr: bool
) -> ExtractionResult:
    """Run the configured OCR provider, or explain why there is none."""
    provider = get_ocr_provider() if allow_ocr else get_ocr_provider("none")
    return provider.extract(content, filename=filename)


def describe_extractors() -> dict[str, Any]:
    """Describe what this installation can and cannot read.

    Used by the API and the Streamlit page so a user is told up front that a
    scanned file will not work, instead of finding out after uploading one.
    """
    return {
        "text_extractors": [
            {
                "name": extractor.name,
                "extensions": list(extractor.extensions),
                "requires_external_service": False,
            }
            for extractor in TEXT_EXTRACTORS
        ],
        "document_extensions": sorted(settings.allowed_document_extension_set),
        "max_document_bytes": settings.max_document_bytes,
        "max_document_pages": settings.max_document_pages,
        "min_chars_per_text_page": settings.min_chars_per_text_page,
        "ocr": describe_ocr_providers(),
    }
