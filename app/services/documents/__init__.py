"""Shared document services: turn PDF, DOCX and TXT bytes into per-page text.

Reuse these rather than reaching for ``pypdf``/``python-docx`` directly, so
that page numbering, text normalisation and the "this file is a scan" signal
stay identical for every module.
"""

from app.services.documents.base import (
    DocumentExtractionError,
    DocumentExtractor,
    ExtractedPage,
    ExtractionResult,
    normalise_text,
)
from app.services.documents.factory import (
    TEXT_EXTRACTORS,
    describe_extractors,
    extract_document,
    get_extractor,
)
from app.services.documents.ocr import (
    OCR_PROVIDERS,
    OcrCapability,
    OcrProvider,
    describe_ocr_providers,
    get_ocr_provider,
)
from app.services.documents.text_extractors import (
    DocxExtractor,
    PdfTextExtractor,
    PlainTextExtractor,
)

__all__ = [
    "DocumentExtractionError",
    "DocumentExtractor",
    "DocxExtractor",
    "ExtractedPage",
    "ExtractionResult",
    "OCR_PROVIDERS",
    "OcrCapability",
    "OcrProvider",
    "PdfTextExtractor",
    "PlainTextExtractor",
    "TEXT_EXTRACTORS",
    "describe_extractors",
    "describe_ocr_providers",
    "extract_document",
    "get_extractor",
    "get_ocr_provider",
    "normalise_text",
]
