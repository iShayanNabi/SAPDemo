"""OCR providers - the extension point for scanned documents.

The first version of the Contract Assistant deliberately ships **no working
OCR**: it works with text-based PDFs, DOCX and TXT and nothing else. What it
does ship is the seam, so adding a provider later is one class here plus one
dependency, and no change anywhere else in the lab.

Three providers are declared because they are the three the module is specified
around:

``local``
    A locally installed engine (Tesseract via ``pytesseract``). No cloud, no
    account, no cost - but it needs a system package the lab does not install.
``aws_textract``
    AWS Textract. Needs credentials and a region, and it costs money per page.
``azure_document_intelligence``
    Azure AI Document Intelligence. Needs an endpoint and a key, and it costs
    money per page.

Every one of them is *declared but unconfigured* by default, and asking for one
that is not installed raises a clear, actionable message. That is the opposite
of a fake integration: nothing here pretends to have read a scan it did not
read, and no button in the UI claims a capability the environment lacks.
"""

from __future__ import annotations

import importlib.util
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any

from app.core.config import OcrProviderName, settings
from app.core.logging import get_logger
from app.services.documents.base import (
    DocumentExtractionError,
    DocumentExtractor,
    ExtractedPage,
    ExtractionResult,
    normalise_text,
)

logger = get_logger(__name__)

#: Image types an OCR provider is expected to accept.
OCR_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf")


def _module_available(name: str) -> bool:
    """Return ``True`` when an optional client library can be imported.

    ``find_spec`` answers "is it installed?" without importing it, so checking
    for a provider never has the side effects of loading it.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        # A namespace package whose parent is missing raises rather than
        # returning None, which still means "not available".
        return False


@dataclass(frozen=True)
class OcrCapability:
    """What one OCR provider needs before it can be used."""

    provider: str
    label: str
    configured: bool
    installed: bool
    requires: tuple[str, ...]
    cost_note: str
    setup_hint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "label": self.label,
            "configured": self.configured,
            "installed": self.installed,
            "available": self.configured and self.installed,
            "requires": list(self.requires),
            "cost_note": self.cost_note,
            "setup_hint": self.setup_hint,
        }


class OcrProvider(DocumentExtractor):
    """Interface every OCR provider implements.

    An OCR provider is just a :class:`DocumentExtractor` that happens to work on
    images, which is what lets the factory treat "text-based PDF" and "scanned
    PDF pushed through Textract" as the same kind of thing.
    """

    extensions = OCR_EXTENSIONS
    label: str = "OCR"
    requires: tuple[str, ...] = ()
    cost_note: str = ""
    setup_hint: str = ""

    @abstractmethod
    def is_configured(self) -> bool:
        """Return ``True`` when the credentials/settings this provider needs exist."""

    @abstractmethod
    def is_installed(self) -> bool:
        """Return ``True`` when the client library this provider needs is importable."""

    def capability(self) -> OcrCapability:
        """Describe this provider without ever revealing a credential."""
        return OcrCapability(
            provider=self.name,
            label=self.label,
            configured=self.is_configured(),
            installed=self.is_installed(),
            requires=self.requires,
            cost_note=self.cost_note,
            setup_hint=self.setup_hint,
        )

    def _unavailable(self) -> DocumentExtractionError:
        """The error raised when this provider is selected but cannot run."""
        missing: list[str] = []
        if not self.is_installed():
            missing.append("the client library is not installed")
        if not self.is_configured():
            missing.append("it is not configured")
        return DocumentExtractionError(
            f"OCR provider '{self.name}' cannot be used because "
            f"{' and '.join(missing) or 'it is unavailable'}. {self.setup_hint}",
            details={"ocr_provider": self.name, "capability": self.capability().to_dict()},
        )


class NoOcrProvider(OcrProvider):
    """The default: OCR is not configured, and says so."""

    name = "none"
    label = "No OCR provider"
    cost_note = "No cost - nothing is called."
    setup_hint = (
        "Set OCR_PROVIDER to 'local', 'aws_textract' or 'azure_document_intelligence' and "
        "supply its credentials to process scanned documents."
    )

    def is_configured(self) -> bool:
        return False

    def is_installed(self) -> bool:
        return True

    def extract(self, content: bytes, *, filename: str = "") -> ExtractionResult:
        raise DocumentExtractionError(
            "This document has no selectable text and no OCR provider is configured, so its "
            "text cannot be extracted. Upload a text-based PDF, DOCX or TXT file, or configure "
            "OCR_PROVIDER.",
            details={"ocr_provider": "none", "requires_ocr": True},
        )


class LocalOcrProvider(OcrProvider):
    """Local OCR through Tesseract (``pytesseract`` + the tesseract binary)."""

    name = "local"
    label = "Local OCR (Tesseract)"
    requires = ("pytesseract", "Pillow", "the tesseract binary on PATH")
    cost_note = "No API cost - runs entirely on this machine."
    setup_hint = (
        "Install the tesseract binary and 'pip install pytesseract Pillow', then set "
        "OCR_PROVIDER=local."
    )

    def is_configured(self) -> bool:
        return settings.ocr_provider == "local"

    def is_installed(self) -> bool:
        return _module_available("pytesseract") and _module_available("PIL")

    def extract(self, content: bytes, *, filename: str = "") -> ExtractionResult:
        if not (self.is_configured() and self.is_installed()):
            raise self._unavailable()

        import io  # pragma: no cover - optional dependency path

        import pytesseract  # pragma: no cover
        from PIL import Image  # pragma: no cover

        try:  # pragma: no cover - exercised only with the optional dependency
            image = Image.open(io.BytesIO(content))
            text = pytesseract.image_to_string(image, lang=settings.ocr_language)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover
            logger.warning("Local OCR failed: %s", type(exc).__name__)
            raise DocumentExtractionError(
                "Local OCR could not read this image."
            ) from exc

        return ExtractionResult(  # pragma: no cover
            pages=[ExtractedPage(page_number=1, text=normalise_text(text))],
            extractor=self.name,
            source_format="image",
            page_basis="ocr_page",
            ocr_used=True,
            ocr_provider=self.name,
            notes=["Text was produced by local OCR and may contain recognition errors."],
        )


class AwsTextractProvider(OcrProvider):
    """AWS Textract. Declared, unconfigured by default, never called for free."""

    name = "aws_textract"
    label = "AWS Textract"
    requires = ("boto3", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_TEXTRACT_REGION")
    cost_note = "Billed by AWS per page. Nothing in this lab calls it unless you configure it."
    setup_hint = (
        "'pip install boto3', set AWS_TEXTRACT_REGION, AWS_ACCESS_KEY_ID and "
        "AWS_SECRET_ACCESS_KEY, then set OCR_PROVIDER=aws_textract."
    )

    def is_configured(self) -> bool:
        return settings.resolved_ocr_provider() == "aws_textract"

    def is_installed(self) -> bool:
        return _module_available("boto3")

    def extract(self, content: bytes, *, filename: str = "") -> ExtractionResult:
        if not (self.is_configured() and self.is_installed()):
            raise self._unavailable()
        # Implementing the call is a deliberate non-goal of module 6: it costs
        # money per page and cannot be tested in this lab. The seam is here so
        # that adding it is a change to this method and nothing else.
        raise DocumentExtractionError(  # pragma: no cover
            "AWS Textract is configured but the call is not implemented in this lab. "
            "Implement AwsTextractProvider.extract to enable it.",
            details={"ocr_provider": self.name},
        )


class AzureDocumentIntelligenceProvider(OcrProvider):
    """Azure AI Document Intelligence. Declared, unconfigured by default."""

    name = "azure_document_intelligence"
    label = "Azure AI Document Intelligence"
    requires = (
        "azure-ai-documentintelligence",
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT",
        "AZURE_DOCUMENT_INTELLIGENCE_KEY",
    )
    cost_note = "Billed by Azure per page. Nothing in this lab calls it unless you configure it."
    setup_hint = (
        "'pip install azure-ai-documentintelligence', set "
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and AZURE_DOCUMENT_INTELLIGENCE_KEY, then set "
        "OCR_PROVIDER=azure_document_intelligence."
    )

    def is_configured(self) -> bool:
        return settings.resolved_ocr_provider() == "azure_document_intelligence"

    def is_installed(self) -> bool:
        return _module_available("azure.ai.documentintelligence")

    def extract(self, content: bytes, *, filename: str = "") -> ExtractionResult:
        if not (self.is_configured() and self.is_installed()):
            raise self._unavailable()
        raise DocumentExtractionError(  # pragma: no cover
            "Azure Document Intelligence is configured but the call is not implemented in this "
            "lab. Implement AzureDocumentIntelligenceProvider.extract to enable it.",
            details={"ocr_provider": self.name},
        )


#: Every declared provider, in the order the UI should list them.
OCR_PROVIDERS: tuple[type[OcrProvider], ...] = (
    NoOcrProvider,
    LocalOcrProvider,
    AwsTextractProvider,
    AzureDocumentIntelligenceProvider,
)


def get_ocr_provider(provider_name: OcrProviderName | str | None = None) -> OcrProvider:
    """Return the requested OCR provider, falling back to :class:`NoOcrProvider`."""
    requested = str(provider_name or settings.resolved_ocr_provider()).lower()
    for provider_class in OCR_PROVIDERS:
        if provider_class.name == requested:
            return provider_class()
    logger.warning("Unknown OCR provider '%s'; OCR stays disabled.", requested)
    return NoOcrProvider()


def describe_ocr_providers() -> dict[str, Any]:
    """Describe OCR availability for the UI. Credentials are never included."""
    capabilities = [provider_class().capability().to_dict() for provider_class in OCR_PROVIDERS]
    resolved = settings.resolved_ocr_provider()
    return {
        "configured_provider": settings.ocr_provider,
        "resolved_provider": resolved,
        "ocr_available": resolved != "none",
        "scanned_documents_supported": resolved != "none",
        "image_extensions": sorted(settings.allowed_image_extension_set),
        "providers": capabilities,
        "note": (
            "Text-based PDF, DOCX and TXT need no OCR provider and always work. Scanned "
            "documents and images need one of the providers above to be installed and "
            "configured; until then they are reported as unprocessable rather than analysed "
            "as empty."
        ),
    }
