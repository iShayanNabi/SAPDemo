"""The document extraction contract.

Everything that turns bytes into text implements :class:`DocumentExtractor`.
The rest of the lab only ever sees an :class:`ExtractionResult`, so adding
local OCR, AWS Textract or Azure Document Intelligence later changes exactly
one file (``app/services/documents/ocr.py``) and nothing else.

Two properties of the result matter to every caller:

``pages``
    Text is kept **per page**, never as one blob. A clause cannot cite a page
    number that was thrown away during extraction.
``needs_ocr``
    Set when a document parsed correctly but yielded (almost) no text - the
    signature of a scanned image. The caller reports that honestly instead of
    presenting an empty contract as an analysed one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import AppError


class DocumentExtractionError(AppError):
    """A document could not be turned into text."""

    code = "document_extraction_error"
    http_status = 422


@dataclass(frozen=True)
class ExtractedPage:
    """One page of a document.

    ``page_number`` is 1-based because that is what a reader sees on the page
    and what a citation has to quote. DOCX and TXT have no intrinsic pages, so
    their extractors segment on explicit page breaks or on a configured
    character budget and say so in ``ExtractionResult.page_basis``.
    """

    page_number: int
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass
class ExtractionResult:
    """The text of a document plus how it was obtained."""

    pages: list[ExtractedPage]
    extractor: str
    source_format: str
    #: How pages were determined: ``pdf_page``, ``page_break``, ``char_budget``.
    page_basis: str
    needs_ocr: bool = False
    ocr_used: bool = False
    ocr_provider: str | None = None
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def text(self) -> str:
        """The whole document, pages joined by a form feed."""
        return "\f".join(page.text for page in self.pages)

    @property
    def char_count(self) -> int:
        return sum(page.char_count for page in self.pages)

    @property
    def empty_page_count(self) -> int:
        return sum(1 for page in self.pages if page.is_empty)

    def page_text(self, page_number: int) -> str:
        """Return the text of one 1-based page (empty string when absent)."""
        for page in self.pages:
            if page.page_number == page_number:
                return page.text
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "extractor": self.extractor,
            "source_format": self.source_format,
            "page_basis": self.page_basis,
            "page_count": self.page_count,
            "char_count": self.char_count,
            "empty_page_count": self.empty_page_count,
            "needs_ocr": self.needs_ocr,
            "ocr_used": self.ocr_used,
            "ocr_provider": self.ocr_provider,
            "notes": list(self.notes),
            "metadata": dict(self.metadata),
        }


class DocumentExtractor(ABC):
    """Interface implemented by every text extractor."""

    #: Short stable name recorded on the analysis (``pdf_text``, ``docx`` ...).
    name: str = "base"
    #: Extensions this extractor claims.
    extensions: tuple[str, ...] = ()

    def supports(self, extension: str) -> bool:
        """Return ``True`` when this extractor handles ``extension``."""
        return extension.lower() in self.extensions

    @abstractmethod
    def extract(self, content: bytes, *, filename: str = "") -> ExtractionResult:
        """Turn ``content`` into per-page text.

        Raises:
            DocumentExtractionError: when the payload cannot be parsed at all.
                A document that parses but holds no text is *not* an error - it
                comes back with ``needs_ocr=True``.
        """


def normalise_text(text: str) -> str:
    """Normalise extracted text without destroying its layout.

    Line structure is load bearing for section detection, so lines are kept.
    What is removed is the noise that differs between extractors: carriage
    returns, non-breaking spaces, soft hyphens, trailing whitespace and runs of
    more than two blank lines.
    """
    if not text:
        return ""
    cleaned = (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u00a0", " ")  # non-breaking space
        .replace("\u00ad", "")  # soft hyphen
        .replace("\u2028", "\n")  # line separator
        .replace("\u2029", "\n")  # paragraph separator
        .replace("\x00", "")
    )
    lines = [line.rstrip() for line in cleaned.split("\n")]

    result: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip():
            blank_run = 0
            result.append(line)
            continue
        blank_run += 1
        if blank_run <= 2:
            result.append("")
    return "\n".join(result).strip("\n")
