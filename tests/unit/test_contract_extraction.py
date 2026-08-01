"""Document extraction tests for the Contract Assistant.

These cover the layer beneath the analysis: turning PDF, DOCX and TXT bytes
into per-page text, deciding when a document needs OCR, and refusing what
cannot safely be read.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import FileValidationError
from app.services.documents.base import DocumentExtractionError, normalise_text
from app.services.documents.factory import (
    describe_extractors,
    extract_document,
    get_extractor,
)
from app.services.documents.ocr import (
    AwsTextractProvider,
    AzureDocumentIntelligenceProvider,
    LocalOcrProvider,
    NoOcrProvider,
    describe_ocr_providers,
    get_ocr_provider,
)
from app.services.documents.pdf_writer import build_text_pdf
from app.services.documents.text_extractors import (
    DocxExtractor,
    PdfTextExtractor,
    PlainTextExtractor,
)
from app.services.files.validation import validate_document_upload, validate_upload
from tests.factories import (
    CONTRACT_TEMPLATE,
    contract_docx_bytes,
    contract_pdf_bytes,
    contract_txt_bytes,
    scanned_pdf_bytes,
)

# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


class TestPdfExtraction:
    def test_extracts_text_from_a_text_based_pdf(self):
        result = extract_document(contract_pdf_bytes(), "contract.pdf")

        assert result.extractor == "pdf_text"
        assert result.source_format == "pdf"
        assert result.page_basis == "pdf_page"
        assert result.needs_ocr is False
        assert "MASTER SERVICES AGREEMENT" in result.text
        assert "net 30 days" in result.text

    def test_keeps_one_entry_per_page(self):
        text = "PAGE ONE\nFirst page body.\fPAGE TWO\nSecond page body.\fPAGE THREE\nThird."
        result = extract_document(build_text_pdf(text).content, "multi.pdf")

        assert result.page_count == 3
        assert [page.page_number for page in result.pages] == [1, 2, 3]
        assert "First page body." in result.page_text(1)
        assert "Second page body." in result.page_text(2)
        assert "First page body." not in result.page_text(2)

    def test_reads_the_document_title_from_the_pdf_metadata(self):
        result = extract_document(
            build_text_pdf("Body text here.", title="Demo Agreement").content, "d.pdf"
        )
        assert result.metadata.get("title") == "Demo Agreement"

    def test_a_pdf_with_no_text_is_reported_as_needing_ocr(self):
        result = extract_document(scanned_pdf_bytes(3), "scan.pdf")

        assert result.needs_ocr is True
        assert result.page_count == 3
        assert result.char_count == 0
        assert any("OCR" in note or "scan" in note for note in result.notes)

    def test_a_corrupt_pdf_is_rejected_with_a_safe_message(self):
        with pytest.raises(DocumentExtractionError) as error:
            extract_document(b"%PDF-1.4\nthis is not a pdf body", "broken.pdf")

        assert "could not be read" in error.value.message.lower()
        # The message must not leak a path or a stack frame.
        assert "Traceback" not in error.value.message

    def test_page_limit_is_enforced(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "max_document_pages", 2)
        content = build_text_pdf("One\fTwo\fThree").content

        with pytest.raises(DocumentExtractionError) as error:
            extract_document(content, "long.pdf")

        assert "page limit" in error.value.message


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


class TestDocxExtraction:
    def test_extracts_text_from_a_word_document(self):
        result = extract_document(contract_docx_bytes(), "contract.docx")

        assert result.extractor == "docx"
        assert result.source_format == "docx"
        assert result.needs_ocr is False
        assert "MASTER SERVICES AGREEMENT" in result.text
        assert "net 30 days" in result.text

    def test_flattens_tables_into_rows(self):
        import io

        import docx

        document = docx.Document()
        document.add_paragraph("SCHEDULE 1")
        table = document.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = "Item"
        table.rows[0].cells[1].text = "Price"
        row = table.add_row().cells
        row[0].text, row[1].text = "ITM-1001", "EUR 42.00"
        buffer = io.BytesIO()
        document.save(buffer)

        result = extract_document(buffer.getvalue(), "schedule.docx")

        assert "ITM-1001 | EUR 42.00" in result.text
        assert any("table" in note for note in result.notes)

    def test_an_empty_word_document_is_reported_as_needing_ocr(self):
        import io

        import docx

        buffer = io.BytesIO()
        docx.Document().save(buffer)

        result = extract_document(buffer.getvalue(), "empty.docx")

        assert result.needs_ocr is True

    def test_a_non_docx_payload_is_rejected(self):
        with pytest.raises(DocumentExtractionError):
            extract_document(b"PK\x03\x04not really a docx", "fake.docx")


# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------


class TestPlainTextExtraction:
    def test_extracts_text_from_a_txt_file(self):
        result = extract_document(contract_txt_bytes(), "contract.txt")

        assert result.extractor == "plain_text"
        assert result.needs_ocr is False
        assert "MASTER SERVICES AGREEMENT" in result.text

    def test_form_feeds_become_pages(self):
        result = extract_document(b"Page one text.\fPage two text.", "two.txt")

        assert result.page_count == 2
        assert result.page_basis == "page_break"

    def test_long_text_without_page_breaks_is_split_on_a_char_budget(self):
        block = ("Lorem ipsum dolor sit amet. " * 40).strip()
        content = "\n\n".join([block] * 6).encode("utf-8")

        result = extract_document(content, "long.txt")

        assert result.page_count > 1
        assert result.page_basis == "char_budget"
        # A paragraph is never cut in half by the synthetic page boundary.
        for page in result.pages:
            assert page.text.strip().endswith(".")

    def test_a_short_txt_file_stays_one_page(self):
        result = extract_document(b"A very short note.", "short.txt")

        assert result.page_count == 1
        assert result.page_basis == "char_budget"

    def test_legacy_encodings_still_decode(self):
        """SAP exports arrive as cp1252 as often as utf-8; both must read."""
        result = PlainTextExtractor().extract(
            "1. TERM\nEffective as of 1 März 2026.".encode("cp1252"), filename="latin.txt"
        )

        assert "TERM" in result.text
        assert result.needs_ocr is False

    def test_binary_content_is_rejected_before_it_reaches_the_extractor(self):
        """Null bytes are the signal that a .txt is not text at all."""
        with pytest.raises(FileValidationError) as error:
            validate_document_upload("binary.txt", b"text\x00\x00binary payload")

        assert "text based" in error.value.message.lower()


# ---------------------------------------------------------------------------
# Routing, normalisation and capability reporting
# ---------------------------------------------------------------------------


class TestExtractorRouting:
    @pytest.mark.parametrize(
        ("extension", "expected"),
        [(".pdf", PdfTextExtractor), (".docx", DocxExtractor), (".txt", PlainTextExtractor),
         (".md", PlainTextExtractor)],
    )
    def test_each_extension_routes_to_its_extractor(self, extension, expected):
        assert isinstance(get_extractor(extension), expected)

    def test_an_unknown_extension_has_no_extractor(self):
        assert get_extractor(".xlsx") is None

    def test_an_unsupported_extension_raises(self):
        with pytest.raises(DocumentExtractionError) as error:
            extract_document(b"data", "book.epub")

        assert "No extractor is available" in error.value.message

    def test_normalise_text_keeps_line_structure(self):
        text = "Heading\r\n\r\n\r\n\r\nBody text  \nMore"
        # Windows line endings normalise and trailing spaces go, but the blank
        # lines the formatter keeps (up to two) survive: they are structure.
        assert normalise_text(text) == "Heading\n\n\nBody text\nMore"


class TestCapabilityReporting:
    def test_describe_extractors_lists_the_three_text_formats(self):
        described = describe_extractors()
        names = {item["name"] for item in described["text_extractors"]}

        assert names == {"pdf_text", "docx", "plain_text"}
        assert all(not item["requires_external_service"] for item in described["text_extractors"])

    def test_ocr_is_off_by_default_and_says_so(self):
        described = describe_ocr_providers()

        assert described["resolved_provider"] == "none"
        assert described["ocr_available"] is False
        assert described["scanned_documents_supported"] is False

    def test_all_three_ocr_providers_are_declared(self):
        providers = {item["provider"] for item in describe_ocr_providers()["providers"]}

        assert providers == {
            "none",
            "local",
            "aws_textract",
            "azure_document_intelligence",
        }

    def test_no_credential_is_ever_reported(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "aws_access_key_id", "AKIA-SECRET-VALUE")
        monkeypatch.setattr(settings, "azure_document_intelligence_key", "azure-secret")

        import json

        payload = json.dumps(describe_ocr_providers())

        assert "AKIA-SECRET-VALUE" not in payload
        assert "azure-secret" not in payload

    @pytest.mark.parametrize(
        "provider_class",
        [NoOcrProvider, LocalOcrProvider, AwsTextractProvider, AzureDocumentIntelligenceProvider],
    )
    def test_an_unconfigured_provider_explains_itself_instead_of_failing_silently(
        self, provider_class
    ):
        provider = provider_class()

        with pytest.raises(DocumentExtractionError) as error:
            provider.extract(b"image-bytes", filename="scan.png")

        assert error.value.message
        assert "OCR" in error.value.message or "ocr" in error.value.message.lower()

    def test_get_ocr_provider_falls_back_to_none(self):
        assert isinstance(get_ocr_provider("does-not-exist"), NoOcrProvider)
        assert isinstance(get_ocr_provider(), NoOcrProvider)


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------


class TestDocumentUploadValidation:
    def test_accepts_pdf_docx_and_txt(self):
        for filename, content in (
            ("contract.pdf", contract_pdf_bytes()),
            ("contract.docx", contract_docx_bytes()),
            ("contract.txt", contract_txt_bytes()),
        ):
            validated = validate_document_upload(filename, content)
            assert validated.extension == f".{filename.rsplit('.', 1)[1]}"

    def test_rejects_a_spreadsheet(self):
        with pytest.raises(FileValidationError) as error:
            validate_document_upload("data.xlsx", b"PK\x03\x04payload")

        assert "not a supported document" in error.value.message

    def test_rejects_a_legacy_doc_with_a_helpful_message(self):
        with pytest.raises(FileValidationError) as error:
            validate_document_upload("old.doc", b"\xd0\xcf\x11\xe0payload")

        assert ".docx" in error.value.message

    def test_rejects_a_pdf_that_is_not_a_pdf(self):
        with pytest.raises(FileValidationError) as error:
            validate_document_upload("fake.pdf", b"just some text, no header")

        assert "valid PDF" in error.value.message

    def test_rejects_an_image_when_no_ocr_provider_is_configured(self):
        with pytest.raises(FileValidationError) as error:
            validate_document_upload("scan.png", b"\x89PNG\r\n\x1a\n" + b"0" * 100)

        assert "OCR" in error.value.message
        assert error.value.details["requires_ocr"] is True

    def test_rejects_an_empty_document(self):
        with pytest.raises(FileValidationError):
            validate_document_upload("empty.pdf", b"")

    def test_rejects_a_document_over_the_size_limit(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "max_document_bytes", 100)

        with pytest.raises(FileValidationError) as error:
            validate_document_upload("big.txt", b"x" * 500)

        assert "larger than" in error.value.message

    def test_a_path_traversal_filename_is_sanitised(self):
        validated = validate_document_upload("../../etc/passwd.txt", CONTRACT_TEMPLATE.encode())

        assert validated.safe_filename == "passwd.txt"
        assert "/" not in validated.safe_filename

    def test_the_tabular_allow_list_still_rejects_a_pdf(self):
        """Growing the document list must never widen the spreadsheet modules."""
        with pytest.raises(FileValidationError) as error:
            validate_upload("contract.pdf", contract_pdf_bytes())

        assert "not supported" in error.value.message
