"""Report builders for the Spend Analytics Dashboard.

Three formats, all built from the same payload:

* **XLSX** - six sheets: Summary, Spend Breakdowns, Suppliers, Savings
  Opportunities, Transactions and Methodology.
* **CSV** - the transaction table, which is what people usually want in Excel.
* **JSON** - the complete payload for a downstream system.

Every format carries the methodology and the savings disclaimer, so a file that
leaves the application cannot be mistaken for validated SAP output or for
guaranteed savings.
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

#: (payload key, column label) for the transaction export.
TRANSACTION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("po_number", "PO Number"),
    ("po_item", "Item"),
    ("effective_date", "Transaction Date"),
    ("spend_month", "Month"),
    ("supplier_id", "Supplier ID"),
    ("supplier_name", "Supplier Name"),
    ("material", "Material"),
    ("material_description", "Material Description"),
    ("material_group", "Material Group"),
    ("category", "Category"),
    ("subcategory", "Subcategory"),
    ("company_code", "Company Code"),
    ("purchasing_org", "Purchasing Org"),
    ("purchasing_group", "Purchasing Group"),
    ("plant", "Plant"),
    ("quantity", "Quantity"),
    ("unit_of_measure", "UoM"),
    ("unit_price", "Unit Price"),
    ("baseline_price", "Baseline Price"),
    ("current_price", "Current Price"),
    ("currency", "Currency"),
    ("total_value", "Total Value (document)"),
    ("spend_base", "Spend (base currency)"),
    ("contract_number", "Contract"),
    ("contract_status", "Contract Status"),
    ("preferred_supplier_status", "Preferred Supplier Status"),
    ("payment_status", "Payment Status"),
    ("is_contracted", "Contracted"),
    ("is_preferred_supplier", "Preferred Supplier"),
    ("is_maverick", "Maverick Spend"),
    ("is_under_management", "Under Management"),
    ("price_variance_base", "Price Variance (base)"),
    ("price_variance_pct", "Price Variance %"),
)

OPPORTUNITY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("opportunity_id", "Opportunity ID"),
    ("rule_id", "Rule"),
    ("rule_name", "Rule Name"),
    ("opportunity_type", "Type"),
    ("scope", "Scope"),
    ("scope_value", "Scope Value"),
    ("scope_label", "Scope Label"),
    ("title", "Title"),
    ("description", "Description (rule-based)"),
    ("method", "Calculation Method"),
    ("addressable_spend_base", "Addressable Spend"),
    ("gross_saving_base", "Gross Saving (modelled)"),
    ("realization_factor", "Realization Factor"),
    ("estimated_saving_base", "Estimated Saving (not guaranteed)"),
    ("confidence", "Confidence"),
    ("transaction_count", "Transactions"),
    ("supplier_count", "Suppliers"),
)


def spend_disclaimer() -> str:
    """The disclaimer printed on every spend export."""
    return (
        "All figures are calculated deterministically from the uploaded file only. This report "
        "is not connected to a live SAP system and nothing in it has been validated in an SAP "
        "environment. Savings figures are MODELLED ESTIMATES produced from the documented "
        "assumptions in the configuration; they are opportunities for investigation, not "
        "guaranteed, negotiated or committed savings. Any AI generated text is labelled as such "
        "and does not influence any figure."
    )


def build_spend_json_report(payload: dict[str, Any]) -> bytes:
    """Serialise the full spend analysis payload as JSON."""
    document = {
        "report_type": "sap_spend_analysis",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": spend_disclaimer(),
        **payload,
    }
    return json.dumps(document, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def build_spend_csv_report(transactions: list[dict[str, Any]]) -> bytes:
    """Serialise the transaction table as CSV (UTF-8 with BOM for Excel)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([label for _, label in TRANSACTION_COLUMNS])
    for transaction in transactions:
        writer.writerow([_cell(transaction, key) for key, _ in TRANSACTION_COLUMNS])
    return buffer.getvalue().encode("utf-8-sig")


def build_spend_xlsx_report(payload: dict[str, Any]) -> bytes:
    """Build the multi-sheet spend workbook."""
    workbook = Workbook()
    workbook.remove(workbook.active)

    _summary_sheet(workbook.create_sheet("Summary"), payload)
    _breakdown_sheet(workbook.create_sheet("Spend Breakdowns"), payload)
    _supplier_sheet(workbook.create_sheet("Suppliers"), payload.get("supplier_spend", []))
    _opportunity_sheet(
        workbook.create_sheet("Savings Opportunities"), payload.get("opportunities", [])
    )
    _transaction_sheet(workbook.create_sheet("Transactions"), payload.get("transactions", []))
    _methodology_sheet(workbook.create_sheet("Methodology"), payload)

    payload_bytes = workbook_to_bytes(workbook)
    logger.info(
        "Built spend XLSX report: %d transactions, %d opportunities",
        len(payload.get("transactions", [])), len(payload.get("opportunities", [])),
    )
    return payload_bytes


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------


def _summary_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    analysis = payload.get("analysis", {}) or {}
    metrics = payload.get("metrics", {}) or {}
    narrative = payload.get("ai_narrative", {}) or {}
    currency = metrics.get("base_currency", "EUR")

    sheet["A1"] = "SAP Spend Analytics - Analysis Summary"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = spend_disclaimer()
    sheet["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet.merge_cells("A2:F5")

    row = 7
    sheet.cell(row=row, column=1, value="Analysis").font = SECTION_FONT
    row += 1
    for label, value in (
        ("Analysis ID", analysis.get("analysis_id")),
        ("Source file", analysis.get("source_filename")),
        ("Created", analysis.get("created_at")),
        ("Period", f"{analysis.get('period_start')} to {analysis.get('period_end')}"),
        ("Rows analysed (after filters)", analysis.get("filtered_record_count")),
        ("Rows in file", analysis.get("record_count")),
        ("Filters applied", json.dumps(analysis.get("applied_filter", {}), default=str)),
        ("Configuration version", analysis.get("config_version")),
        ("Metrics version", analysis.get("metrics_version")),
        ("Base currency", currency),
    ):
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(value))
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Headline metrics (rule-based)").font = SECTION_FONT
    row += 1
    for label, key in (
        (f"Total spend ({currency})", "total_spend"),
        ("Purchase orders", "purchase_order_count"),
        ("Line items", "line_item_count"),
        ("Suppliers", "supplier_count"),
        (f"Average PO value ({currency})", "average_po_value"),
        (f"Median PO value ({currency})", "median_po_value"),
        (f"Contracted spend ({currency})", "contracted_spend"),
        (f"Non-contracted spend ({currency})", "non_contracted_spend"),
        (f"Maverick spend ({currency})", "maverick_spend"),
        ("Maverick spend %", "maverick_spend_pct"),
        (f"Spend under management ({currency})", "spend_under_management"),
        ("Spend under management %", "spend_under_management_pct"),
        ("Supplier concentration (HHI)", "supplier_concentration_hhi"),
        ("Concentration level", "supplier_concentration_level"),
        ("Top supplier share %", "top_supplier_share_pct"),
        ("Top 5 supplier share %", "top_five_supplier_share_pct"),
        (f"Tail spend ({currency})", "tail_spend"),
        ("Tail spend %", "tail_spend_pct"),
        ("Tail suppliers", "tail_supplier_count"),
        (f"Price variance ({currency})", "price_variance_base"),
        (f"Estimated savings opportunity ({currency}) - NOT GUARANTEED",
         "estimated_savings_opportunity"),
    ):
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(metrics.get(key)))
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Spend by currency").font = SECTION_FONT
    row += 1
    _write_header(sheet, ["Currency", "Spend (document)", f"Spend ({currency})", "Share %",
                          "Transactions", "Rate"], row)
    row += 1
    for entry in metrics.get("spend_by_currency", []) or []:
        for column, key in enumerate(
            ("currency", "spend_document_currency", "spend_base", "share_pct",
             "transaction_count", "conversion_rate"), start=1
        ):
            sheet.cell(row=row, column=column, value=_scalar(entry.get(key)))
        row += 1

    if narrative.get("summary"):
        row += 1
        origin = narrative.get("origin", "ai")
        sheet.cell(row=row, column=1, value=f"Narrative ({origin} - not a source of figures)").font = SECTION_FONT
        row += 1
        sheet.cell(row=row, column=1, value=narrative["summary"]).alignment = Alignment(wrap_text=True)
        sheet.merge_cells(start_row=row, start_column=1, end_row=row + 3, end_column=6)

    sheet.column_dimensions["A"].width = 46
    sheet.column_dimensions["B"].width = 34


def _breakdown_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    analytics = payload.get("analytics", {}) or {}
    currency = (payload.get("metrics", {}) or {}).get("base_currency", "EUR")

    sheet["A1"] = "Spend breakdowns (deterministic aggregation)"
    sheet["A1"].font = TITLE_FONT
    row = 3

    for key, title in (
        ("monthly_spend", "Monthly spend"),
        ("spend_by_category", "Spend by category"),
        ("spend_by_material_group", "Spend by material group"),
        ("spend_by_plant", "Spend by plant"),
        ("spend_by_company_code", "Spend by company code"),
        ("top_materials", "Top materials"),
        ("contract_leakage", "Contract leakage"),
        ("maverick_spend", "Maverick spend by supplier"),
        ("purchase_price_variance", "Purchase price variance"),
        ("supplier_concentration", "Supplier concentration by material group"),
    ):
        rows = analytics.get(key) or []
        sheet.cell(row=row, column=1, value=title).font = SECTION_FONT
        row += 1
        if not rows:
            sheet.cell(row=row, column=1, value="No data for this breakdown.")
            row += 2
            continue

        headers = list(rows[0].keys())
        _write_header(sheet, [_humanise(h, currency) for h in headers], row)
        row += 1
        for entry in rows:
            for column, header in enumerate(headers, start=1):
                sheet.cell(row=row, column=column, value=_scalar(entry.get(header)))
            row += 1
        row += 1

    sheet.column_dimensions["A"].width = 30
    sheet.column_dimensions["B"].width = 26


def _supplier_sheet(sheet: Worksheet, suppliers: list[dict[str, Any]]) -> None:
    if not suppliers:
        sheet["A1"] = "No supplier spend to report."
        return
    headers = list(suppliers[0].keys())
    _write_header(sheet, [_humanise(h) for h in headers])
    for index, supplier in enumerate(suppliers, start=2):
        for column, header in enumerate(headers, start=1):
            sheet.cell(row=index, column=column, value=_scalar(supplier.get(header)))
    sheet.freeze_panes = "A2"
    sheet.column_dimensions["A"].width = 18
    sheet.column_dimensions["B"].width = 32


def _opportunity_sheet(sheet: Worksheet, opportunities: list[dict[str, Any]]) -> None:
    sheet["A1"] = (
        "ESTIMATED savings opportunities - modelled from the uploaded data, not guaranteed, "
        "not negotiated and not validated in SAP."
    )
    sheet["A1"].font = Font(bold=True, color="9C0006")
    sheet.merge_cells("A1:H1")

    if not opportunities:
        sheet["A3"] = "No opportunity cleared the configured thresholds."
        return

    _write_header(sheet, [label for _, label in OPPORTUNITY_COLUMNS], row=3)
    for index, opportunity in enumerate(opportunities, start=4):
        for column, (key, _label) in enumerate(OPPORTUNITY_COLUMNS, start=1):
            sheet.cell(row=index, column=column, value=_cell(opportunity, key))
    sheet.freeze_panes = "A4"
    sheet.column_dimensions["H"].width = 44
    sheet.column_dimensions["I"].width = 60
    sheet.column_dimensions["J"].width = 60


def _transaction_sheet(sheet: Worksheet, transactions: list[dict[str, Any]]) -> None:
    _write_header(sheet, [label for _, label in TRANSACTION_COLUMNS])
    for index, transaction in enumerate(transactions, start=2):
        for column, (key, _label) in enumerate(TRANSACTION_COLUMNS, start=1):
            sheet.cell(row=index, column=column, value=_cell(transaction, key))
    sheet.freeze_panes = "A2"


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
    sheet.cell(row=row, column=1, value="Savings rules applied").font = SECTION_FONT
    row += 1
    _write_header(
        sheet,
        ["Rule", "Name", "Enabled", "Confidence", "Realization factor", "Assumptions"],
        row,
    )
    row += 1
    for rule in payload.get("savings_rule_catalogue", []) or []:
        sheet.cell(row=row, column=1, value=rule.get("rule_id"))
        sheet.cell(row=row, column=2, value=rule.get("name"))
        sheet.cell(row=row, column=3, value=_scalar(rule.get("enabled")))
        sheet.cell(row=row, column=4, value=_scalar(rule.get("confidence")))
        sheet.cell(row=row, column=5, value=_scalar(rule.get("realization_factor")))
        sheet.cell(row=row, column=6, value=json.dumps(rule.get("params", {}), default=str))
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Disclaimer").font = SECTION_FONT
    row += 1
    sheet.cell(row=row, column=1, value=spend_disclaimer()).alignment = Alignment(wrap_text=True)
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


def _humanise(key: str, currency: str | None = None) -> str:
    """Turn a payload key into a readable column label."""
    label = key.replace("_base", f" ({currency})" if currency else "").replace("_", " ").strip()
    label = label.replace("pct", "%")
    return label[:1].upper() + label[1:]


def _scalar(value: Any) -> Any:
    """Render a value in a form openpyxl accepts."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)[:2000]
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return value


def _cell(record: dict[str, Any], key: str) -> Any:
    """Read one field of a record for a spreadsheet cell."""
    return _scalar(record.get(key))
