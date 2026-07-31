"""Report builders for the Contract Assistant.

Three formats, all built from the same payload:

* **XLSX** - six sheets: Summary, Key Dates, Clauses, Obligations, Risks and
  Methodology.
* **CSV** - the clause table, which is what people paste into a contract
  register.
* **JSON** - the complete payload for a downstream system.

Every format carries the page number, the section heading, the excerpt and the
confidence for each row, because an extracted clause that a reviewer cannot
trace back to a page is not usable evidence. Every format also carries the
contract disclaimer, so a file that leaves the application cannot be mistaken
for legal advice or for validated SAP output.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from app.core.logging import get_logger

logger = get_logger(__name__)

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(bold=True, size=14)
SECTION_FONT = Font(bold=True, size=11)

#: (payload key, column label) for the clause export.
CLAUSE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("clause_type", "Clause Type"),
    ("label", "Clause"),
    ("present", "Found"),
    ("required", "Required"),
    ("importance", "Importance"),
    ("confidence", "Confidence"),
    ("needs_review", "Needs Review"),
    ("page_number", "Page"),
    ("section_heading", "Section Heading"),
    ("excerpt", "Supporting Excerpt"),
    ("values", "Extracted Values"),
    ("matched_terms", "Matched Terms"),
    ("ai_summary", "AI Summary (not a source)"),
)

RISK_COLUMNS: tuple[tuple[str, str], ...] = (
    ("rule_id", "Rule"),
    ("severity", "Severity"),
    ("category", "Category"),
    ("title", "Finding"),
    ("explanation", "Explanation (rule-based)"),
    ("recommended_action", "Recommended Action"),
    ("clause_type", "Clause"),
    ("page_number", "Page"),
    ("section_heading", "Section Heading"),
    ("excerpt", "Supporting Excerpt"),
    ("evidence", "Evidence"),
)

OBLIGATION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("obligation_id", "ID"),
    ("party", "Party"),
    ("party_role", "Role"),
    ("duty_type", "Duty Type"),
    ("is_prohibition", "Prohibition"),
    ("clause_type", "Clause"),
    ("page_number", "Page"),
    ("section_heading", "Section Heading"),
    ("text", "Obligation (verbatim)"),
    ("confidence", "Confidence"),
)

KEY_DATE_ROWS: tuple[tuple[str, str], ...] = (
    ("effective_date", "Effective date"),
    ("expiration_date", "Expiration date"),
    ("renewal_date", "Renewal date"),
    ("notice_deadline", "Notice deadline"),
    ("signature_date", "Signature date"),
    ("term_length_label", "Initial term"),
    ("notice_period_label", "Termination notice period"),
    ("renewal_term_label", "Renewal term"),
    ("renewal_notice_label", "Renewal notice period"),
    ("auto_renewal", "Auto-renewal"),
    ("days_to_expiration", "Days to expiration"),
    ("days_to_notice_deadline", "Days to notice deadline"),
)


def contract_disclaimer() -> str:
    """The disclaimer printed on every contract export."""
    return (
        "Clauses, dates, obligations and risks in this report were extracted from the uploaded "
        "document by deterministic pattern matching. Each row carries the page, the section "
        "heading, a supporting excerpt and a confidence score so it can be verified against the "
        "original. This is an assistive review, not legal advice, and it is not a substitute for "
        "reading the contract. The application is not connected to a live SAP system and nothing "
        "here has been validated in a live SAP environment. Any AI generated text summarises the "
        "extracted results and never determines them."
    )


def build_contract_json_report(payload: dict[str, Any]) -> bytes:
    """Serialise the full contract payload as JSON."""
    document = {
        "report_type": "sap_contract_analysis",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": contract_disclaimer(),
        **payload,
    }
    return json.dumps(document, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def build_contract_csv_report(clauses: list[dict[str, Any]]) -> bytes:
    """Serialise the clause table as CSV (UTF-8 with BOM for Excel)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([label for _, label in CLAUSE_COLUMNS])
    for clause in clauses:
        writer.writerow([_cell(clause, key) for key, _ in CLAUSE_COLUMNS])
    return buffer.getvalue().encode("utf-8-sig")


def build_contract_xlsx_report(payload: dict[str, Any]) -> bytes:
    """Build the multi-sheet contract workbook."""
    workbook = Workbook()
    workbook.remove(workbook.active)

    _summary_sheet(workbook.create_sheet("Summary"), payload)
    _key_dates_sheet(workbook.create_sheet("Key Dates"), payload)
    _table_sheet(workbook.create_sheet("Clauses"), payload.get("clauses", []), CLAUSE_COLUMNS)
    _table_sheet(
        workbook.create_sheet("Obligations"),
        payload.get("obligations", []),
        OBLIGATION_COLUMNS,
    )
    _table_sheet(workbook.create_sheet("Risks"), payload.get("risks", []), RISK_COLUMNS)
    _methodology_sheet(workbook.create_sheet("Methodology"), payload)

    buffer = io.BytesIO()
    workbook.save(buffer)
    logger.info(
        "Built contract XLSX: %d clauses, %d risks, %d obligations",
        len(payload.get("clauses", [])),
        len(payload.get("risks", [])),
        len(payload.get("obligations", [])),
    )
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------


def _summary_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    contract = payload.get("contract", {}) or {}
    summary = payload.get("summary", {}) or {}
    narrative = payload.get("ai_narrative", {}) or {}
    parties = payload.get("parties", []) or []
    missing = payload.get("missing_clauses", []) or []

    sheet["A1"] = "SAP Contract Assistant - Summary"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = contract_disclaimer()
    sheet["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet.merge_cells("A2:F6")

    row = 8
    sheet.cell(row=row, column=1, value="Contract").font = SECTION_FONT
    row += 1
    for label, value in (
        ("Contract ID", contract.get("contract_id")),
        ("Title (extracted)", contract.get("contract_title")),
        ("Source file", contract.get("filename")),
        ("Status", contract.get("status")),
        ("Pages", summary.get("page_count")),
        ("Sections detected", summary.get("section_count")),
        ("Characters extracted", summary.get("char_count")),
        ("Clauses found", f"{summary.get('clauses_found')} of {summary.get('clauses_expected')}"),
        ("Missing required clauses", summary.get("missing_clause_count")),
        ("Obligations extracted", summary.get("obligation_count")),
        ("Risk findings", summary.get("risk_count")),
        ("Risk score (0-100)", summary.get("risk_score")),
        ("Risk band", summary.get("risk_band")),
        ("Assessment date", contract.get("as_of_date")),
        ("Configuration version", contract.get("config_version")),
        ("Engine version", contract.get("engine_version")),
    ):
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(value))
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Parties").font = SECTION_FONT
    row += 1
    _write_header(sheet, ["Name", "Role", "Page", "Confidence"], row)
    row += 1
    for party in parties:
        sheet.cell(row=row, column=1, value=_scalar(party.get("name")))
        sheet.cell(row=row, column=2, value=_scalar(party.get("role")))
        sheet.cell(row=row, column=3, value=_scalar(party.get("page_number")))
        sheet.cell(row=row, column=4, value=_scalar(party.get("confidence")))
        row += 1

    if missing:
        row += 1
        sheet.cell(row=row, column=1, value="Missing clauses").font = SECTION_FONT
        row += 1
        _write_header(sheet, ["Clause", "Importance", "Why it matters"], row)
        row += 1
        for item in missing:
            sheet.cell(row=row, column=1, value=_scalar(item.get("label")))
            sheet.cell(row=row, column=2, value=_scalar(item.get("importance")))
            sheet.cell(row=row, column=3, value=_scalar(item.get("message")))
            row += 1

    if narrative.get("summary"):
        row += 1
        origin = narrative.get("origin", "ai")
        sheet.cell(
            row=row,
            column=1,
            value=f"Narrative ({origin} - explains the extraction, never a source of it)",
        ).font = SECTION_FONT
        row += 1
        sheet.cell(row=row, column=1, value=narrative["summary"]).alignment = Alignment(
            wrap_text=True
        )
        sheet.merge_cells(start_row=row, start_column=1, end_row=row + 3, end_column=6)

    sheet.column_dimensions["A"].width = 30
    sheet.column_dimensions["B"].width = 44
    sheet.column_dimensions["C"].width = 60


def _key_dates_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    key_dates = payload.get("key_dates", {}) or {}

    sheet["A1"] = "Key dates"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = (
        "'Basis' says whether a date was printed in the document (stated) or computed from "
        "other values (derived_...). A derived date is never presented as one the contract "
        "actually stated."
    )
    sheet["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet.merge_cells("A2:E4")

    _write_header(sheet, ["Value", "Result", "Basis", "Page", "Supporting excerpt"], row=6)
    row = 7
    for key, label in KEY_DATE_ROWS:
        value = key_dates.get(key)
        if value is None:
            value = "not stated"
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(value))
        sheet.cell(row=row, column=3, value=_scalar(key_dates.get(f"{key}_basis")))
        sheet.cell(row=row, column=4, value=_scalar(key_dates.get(f"{key}_page")))
        sheet.cell(row=row, column=5, value=_scalar(key_dates.get(f"{key}_excerpt")))
        row += 1

    sheet.column_dimensions["A"].width = 32
    sheet.column_dimensions["B"].width = 22
    sheet.column_dimensions["C"].width = 30
    sheet.column_dimensions["E"].width = 70


def _table_sheet(
    sheet: Worksheet, rows: list[dict[str, Any]], columns: tuple[tuple[str, str], ...]
) -> None:
    _write_header(sheet, [label for _, label in columns])
    for index, record in enumerate(rows, start=2):
        for column, (key, _label) in enumerate(columns, start=1):
            sheet.cell(row=index, column=column, value=_cell(record, key))
    sheet.freeze_panes = "A2"
    for letter, width in (("A", 18), ("B", 24), ("D", 22), ("I", 30), ("J", 70)):
        sheet.column_dimensions[letter].width = width


def _methodology_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    methodology = payload.get("methodology", {}) or {}
    extraction = payload.get("extraction", {}) or {}

    sheet["A1"] = "Methodology"
    sheet["A1"].font = TITLE_FONT

    row = 3
    sheet.cell(row=row, column=1, value="Text extraction").font = SECTION_FONT
    row += 1
    for key in (
        "extractor", "source_format", "page_basis", "page_count", "char_count",
        "empty_page_count", "needs_ocr", "ocr_used", "ocr_provider",
    ):
        sheet.cell(row=row, column=1, value=_humanise(key))
        sheet.cell(row=row, column=2, value=_scalar(extraction.get(key)))
        row += 1
    for note in extraction.get("notes", []) or []:
        sheet.cell(row=row, column=1, value="Note")
        sheet.cell(row=row, column=2, value=_scalar(note)).alignment = Alignment(wrap_text=True)
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Analysis").font = SECTION_FONT
    row += 1
    for key, value in methodology.items():
        sheet.cell(row=row, column=1, value=_humanise(key))
        sheet.cell(row=row, column=2, value=_scalar(value)).alignment = Alignment(wrap_text=True)
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Disclaimer").font = SECTION_FONT
    row += 1
    sheet.cell(row=row, column=1, value=contract_disclaimer()).alignment = Alignment(
        wrap_text=True
    )
    sheet.merge_cells(start_row=row, start_column=1, end_row=row + 5, end_column=6)

    sheet.column_dimensions["A"].width = 38
    sheet.column_dimensions["B"].width = 90


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_header(sheet: Worksheet, headers: list[str], row: int = 1) -> None:
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(row=row, column=column, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT


def _humanise(key: str) -> str:
    label = key.replace("_", " ").strip().replace("pct", "%")
    return label[:1].upper() + label[1:]


def _scalar(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str, ensure_ascii=False)[:2000]
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return value


def _cell(record: dict[str, Any], key: str) -> Any:
    value = record.get(key)
    if isinstance(value, list):
        return " | ".join(str(item) for item in value)
    return _scalar(value)
