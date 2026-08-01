"""Report builders for the Invoice Validator.

Three formats, all built from the same payload:

* **XLSX** - five sheets: Summary, Exceptions, Three-way Match, Supplier Summary
  and Methodology.
* **CSV** - the exceptions table, which is what AP teams usually want in Excel.
* **JSON** - the complete payload for a downstream system.

Every format carries the validation disclaimer, so a file that leaves the
application cannot be mistaken for validated SAP output.
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
from app.services.exports.workbook import workbook_to_bytes

logger = get_logger(__name__)

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(bold=True, size=14)
SECTION_FONT = Font(bold=True, size=11)

#: (payload key, column label) for the exceptions export.
EXCEPTION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("exception_id", "Exception ID"),
    ("rule_id", "Rule"),
    ("exception_type", "Exception Type"),
    ("severity", "Severity"),
    ("invoice_number", "Invoice Number"),
    ("supplier_id", "Supplier ID"),
    ("supplier_name", "Supplier"),
    ("po_number", "Purchase Order"),
    ("po_item", "PO Item"),
    ("gr_number", "Goods Receipt"),
    ("expected_value", "Expected Value"),
    ("actual_value", "Actual Value"),
    ("difference", "Difference"),
    ("difference_amount", "Difference Amount"),
    ("currency", "Currency"),
    ("explanation", "Explanation (rule-based)"),
    ("recommended_action", "Recommended Action"),
)

THREE_WAY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("invoice_number", "Invoice"),
    ("supplier_id", "Supplier"),
    ("po_number", "PO"),
    ("po_item", "PO Item"),
    ("invoice_quantity", "Invoice Qty"),
    ("po_quantity", "PO Qty"),
    ("received_quantity", "Received Qty"),
    ("accepted_quantity", "Accepted Qty"),
    ("invoice_unit_price", "Invoice Price"),
    ("po_unit_price", "PO Price"),
    ("invoice_currency", "Inv Ccy"),
    ("po_currency", "PO Ccy"),
    ("matched_po", "Matched PO"),
    ("matched_gr", "Matched GR"),
    ("exception_count", "Exceptions"),
    ("status", "Status"),
)


def invoice_validator_disclaimer() -> str:
    """The disclaimer printed on every invoice validation export."""
    return (
        "Invoice exceptions are calculated deterministically by comparing the uploaded invoices "
        "against the uploaded purchase orders and goods receipts, using the documented tolerances "
        "and rules in the configuration. Figures are indicative and describe the uploaded files "
        "only. This application is not connected to a live SAP system and no result has been "
        "validated in a live SAP environment. Any AI generated text summarises the exceptions and "
        "never determines them."
    )


def build_invoice_validator_json_report(payload: dict[str, Any]) -> bytes:
    """Serialise the full validation payload as JSON."""
    document = {
        "report_type": "sap_invoice_validation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": invoice_validator_disclaimer(),
        **payload,
    }
    return json.dumps(document, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def build_invoice_validator_csv_report(exceptions: list[dict[str, Any]]) -> bytes:
    """Serialise the exceptions table as CSV (UTF-8 with BOM for Excel)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([label for _, label in EXCEPTION_COLUMNS])
    for exception in exceptions:
        writer.writerow([_cell(exception, key) for key, _ in EXCEPTION_COLUMNS])
    return buffer.getvalue().encode("utf-8-sig")


def build_invoice_validator_xlsx_report(payload: dict[str, Any]) -> bytes:
    """Build the multi-sheet invoice validation workbook."""
    workbook = Workbook()
    workbook.remove(workbook.active)

    _summary_sheet(workbook.create_sheet("Summary"), payload)
    _exceptions_sheet(workbook.create_sheet("Exceptions"), payload.get("exceptions", []))
    _three_way_sheet(workbook.create_sheet("Three-way Match"), payload.get("three_way_matches", []))
    _supplier_sheet(workbook.create_sheet("Supplier Summary"), payload.get("supplier_summary", []))
    _methodology_sheet(workbook.create_sheet("Methodology"), payload)

    payload_bytes = workbook_to_bytes(workbook)
    logger.info("Built invoice validation XLSX: %d exceptions", len(payload.get("exceptions", [])))
    return payload_bytes


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------
def _summary_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    validation = payload.get("validation", {}) or {}
    kpis = payload.get("kpis", {}) or {}
    narrative = payload.get("ai_narrative", {}) or {}
    currency = validation.get("base_currency", "EUR")

    sheet["A1"] = "SAP Invoice Validation - Summary"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = invoice_validator_disclaimer()
    sheet["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet.merge_cells("A2:F6")

    severity = kpis.get("severity_counts", {}) or {}
    row = 8
    sheet.cell(row=row, column=1, value="Validation").font = SECTION_FONT
    row += 1
    for label, value in (
        ("Validation ID", validation.get("validation_id")),
        ("Created", validation.get("created_at")),
        ("Invoices", validation.get("invoice_count")),
        ("Purchase order lines", validation.get("purchase_order_line_count")),
        ("Goods receipts", validation.get("goods_receipt_count")),
        ("Fully three-way matched", kpis.get("fully_three_way_matched")),
        ("Exceptions", validation.get("exceptions_count")),
        ("Critical / High", f"{severity.get('critical', 0)} / {severity.get('high', 0)}"),
        ("Medium / Low", f"{severity.get('medium', 0)} / {severity.get('low', 0)}"),
        ("Estimated exposure", validation.get("estimated_exposure")),
        ("Exception score", validation.get("exception_score")),
        ("Base currency", currency),
        ("Configuration version", validation.get("config_version")),
        ("Engine version", validation.get("engine_version")),
    ):
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(value))
        row += 1

    if narrative.get("summary"):
        row += 1
        origin = narrative.get("origin", "ai")
        sheet.cell(
            row=row, column=1, value=f"Narrative ({origin} - not a source of any exception)"
        ).font = SECTION_FONT
        row += 1
        sheet.cell(row=row, column=1, value=narrative["summary"]).alignment = Alignment(wrap_text=True)
        sheet.merge_cells(start_row=row, start_column=1, end_row=row + 3, end_column=6)

    sheet.column_dimensions["A"].width = 30
    sheet.column_dimensions["B"].width = 42


def _exceptions_sheet(sheet: Worksheet, exceptions: list[dict[str, Any]]) -> None:
    _write_header(sheet, [label for _, label in EXCEPTION_COLUMNS])
    for index, exception in enumerate(exceptions, start=2):
        for column, (key, _label) in enumerate(EXCEPTION_COLUMNS, start=1):
            sheet.cell(row=index, column=column, value=_cell(exception, key))
    sheet.freeze_panes = "A2"
    sheet.column_dimensions["G"].width = 26
    sheet.column_dimensions["P"].width = 60
    sheet.column_dimensions["Q"].width = 50


def _three_way_sheet(sheet: Worksheet, matches: list[dict[str, Any]]) -> None:
    sheet["A1"] = "Three-way match comparison (invoice vs purchase order vs goods receipt)"
    sheet["A1"].font = TITLE_FONT
    _write_header(sheet, [label for _, label in THREE_WAY_COLUMNS], row=3)
    for index, match in enumerate(matches, start=4):
        for column, (key, _label) in enumerate(THREE_WAY_COLUMNS, start=1):
            sheet.cell(row=index, column=column, value=_scalar(match.get(key)))
    sheet.freeze_panes = "A4"


def _supplier_sheet(sheet: Worksheet, suppliers: list[dict[str, Any]]) -> None:
    sheet["A1"] = "Supplier summary"
    sheet["A1"].font = TITLE_FONT
    columns = [
        ("supplier_id", "Supplier ID"), ("supplier_name", "Supplier"),
        ("invoice_count", "Invoices"), ("invoiced_value_base", "Invoiced Value"),
        ("exceptions_count", "Exceptions"), ("critical_count", "Critical"),
        ("high_count", "High"), ("medium_count", "Medium"), ("low_count", "Low"),
        ("estimated_exposure_base", "Exposure"), ("top_exception_type", "Top Exception"),
    ]
    _write_header(sheet, [label for _, label in columns], row=3)
    for index, supplier in enumerate(suppliers, start=4):
        for column, (key, _label) in enumerate(columns, start=1):
            sheet.cell(row=index, column=column, value=_scalar(supplier.get(key)))
    sheet.freeze_panes = "A4"
    sheet.column_dimensions["B"].width = 28


def _methodology_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    methodology = payload.get("methodology", {}) or {}
    sheet["A1"] = "Methodology"
    sheet["A1"].font = TITLE_FONT

    row = 3
    for key, value in methodology.items():
        sheet.cell(row=row, column=1, value=_humanise(key))
        sheet.cell(row=row, column=2, value=_scalar(value)).alignment = Alignment(wrap_text=True)
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Disclaimer").font = SECTION_FONT
    row += 1
    sheet.cell(row=row, column=1, value=invoice_validator_disclaimer()).alignment = Alignment(wrap_text=True)
    sheet.merge_cells(start_row=row, start_column=1, end_row=row + 4, end_column=6)

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
    label = key.replace("_base", " (base)").replace("_", " ").strip()
    return label[:1].upper() + label[1:]


def _scalar(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)[:2000]
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return value


def _cell(record: dict[str, Any], key: str) -> Any:
    value = record.get(key)
    if isinstance(value, list):
        return " | ".join(str(item) for item in value)
    return _scalar(value)
