"""Report builders for the Supplier Recommendation Engine.

Three formats, all built from the same payload:

* **XLSX** - five sheets: Summary, Requirement & Weights, Ranked Suppliers,
  Score Breakdown and Methodology.
* **CSV** - the ranked-supplier table, which is what people usually want in Excel.
* **JSON** - the complete payload for a downstream system.

Every format carries the recommendation disclaimer, so a file that leaves the
application cannot be mistaken for validated SAP output or for a firm quotation.
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

#: (payload key, column label) for the ranked-supplier export.
ENTRY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("rank", "Rank"),
    ("supplier_id", "Supplier ID"),
    ("supplier_name", "Supplier Name"),
    ("eligibility_status", "Eligibility"),
    ("overall_score", "Overall Score"),
    ("cost_score", "Cost"),
    ("delivery_score", "Delivery"),
    ("quality_score", "Quality"),
    ("capacity_score", "Capacity"),
    ("risk_score", "Risk"),
    ("esg_score", "ESG"),
    ("contract_score", "Contract"),
    ("geographic_score", "Geographic"),
    ("past_performance_score", "Past Performance"),
    ("estimated_total_cost_base", "Estimated Total Cost (base)"),
    ("estimated_delivery_date", "Estimated Delivery"),
    ("lead_time_days", "Lead Time (days)"),
    ("contract_status", "Contract Status"),
    ("advantages", "Advantages"),
    ("risks", "Risks"),
    ("explanation", "Explanation (rule-based)"),
    ("ineligibility_reasons", "Ineligibility Reasons"),
)


def supplier_reco_disclaimer() -> str:
    """The disclaimer printed on every supplier recommendation export."""
    return (
        "Supplier scores and ranking are calculated deterministically from the supplier data "
        "provided, using the documented weights and formulas in the configuration. Estimated costs "
        "and delivery dates are indicative planning figures, not quotations or commitments. This "
        "application is not connected to a live SAP system and no recommendation has been validated "
        "in a live SAP environment. Any AI generated text summarises the ranking and never "
        "determines it."
    )


def build_supplier_reco_json_report(payload: dict[str, Any]) -> bytes:
    """Serialise the full recommendation payload as JSON."""
    document = {
        "report_type": "sap_supplier_recommendation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": supplier_reco_disclaimer(),
        **payload,
    }
    return json.dumps(document, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def build_supplier_reco_csv_report(entries: list[dict[str, Any]]) -> bytes:
    """Serialise the ranked-supplier table as CSV (UTF-8 with BOM for Excel)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([label for _, label in ENTRY_COLUMNS])
    for entry in entries:
        writer.writerow([_cell(entry, key) for key, _ in ENTRY_COLUMNS])
    return buffer.getvalue().encode("utf-8-sig")


def build_supplier_reco_xlsx_report(payload: dict[str, Any]) -> bytes:
    """Build the multi-sheet recommendation workbook."""
    workbook = Workbook()
    workbook.remove(workbook.active)

    _summary_sheet(workbook.create_sheet("Summary"), payload)
    _requirement_sheet(workbook.create_sheet("Requirement & Weights"), payload)
    _ranked_sheet(workbook.create_sheet("Ranked Suppliers"), payload.get("results", []))
    _breakdown_sheet(workbook.create_sheet("Score Breakdown"), payload.get("results", []))
    _methodology_sheet(workbook.create_sheet("Methodology"), payload)

    payload_bytes = workbook_to_bytes(workbook)
    logger.info(
        "Built supplier recommendation XLSX: %d ranked entries", len(payload.get("results", []))
    )
    return payload_bytes


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------


def _summary_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    analysis = payload.get("recommendation", {}) or {}
    narrative = payload.get("ai_narrative", {}) or {}
    currency = analysis.get("base_currency", "EUR")

    sheet["A1"] = "SAP Supplier Recommendation - Summary"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = supplier_reco_disclaimer()
    sheet["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet.merge_cells("A2:F5")

    row = 7
    sheet.cell(row=row, column=1, value="Recommendation").font = SECTION_FONT
    row += 1
    for label, value in (
        ("Recommendation ID", analysis.get("recommendation_id")),
        ("Catalogue ID", analysis.get("catalog_id")),
        ("Created", analysis.get("created_at")),
        ("Suppliers assessed", analysis.get("total_supplier_count")),
        ("Eligible suppliers", analysis.get("eligible_count")),
        ("Ineligible suppliers", analysis.get("ineligible_count")),
        ("Top supplier", analysis.get("top_supplier_id")),
        ("Top supplier score", analysis.get("top_supplier_score")),
        ("Configuration version", analysis.get("config_version")),
        ("Scoring engine version", analysis.get("scoring_engine_version")),
        ("Base currency", currency),
    ):
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(value))
        row += 1

    if narrative.get("summary"):
        row += 1
        origin = narrative.get("origin", "ai")
        sheet.cell(
            row=row, column=1, value=f"Narrative ({origin} - not a source of any score)"
        ).font = SECTION_FONT
        row += 1
        sheet.cell(row=row, column=1, value=narrative["summary"]).alignment = Alignment(wrap_text=True)
        sheet.merge_cells(start_row=row, start_column=1, end_row=row + 3, end_column=6)

    sheet.column_dimensions["A"].width = 30
    sheet.column_dimensions["B"].width = 40


def _requirement_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    requirement = payload.get("requirement", {}) or {}
    weights = payload.get("weights", {}) or {}

    sheet["A1"] = "Requirement"
    sheet["A1"].font = TITLE_FONT
    row = 3
    for key, value in requirement.items():
        sheet.cell(row=row, column=1, value=_humanise(key))
        sheet.cell(row=row, column=2, value=_scalar(value))
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Scoring weights (%)").font = SECTION_FONT
    row += 1
    _write_header(sheet, ["Dimension", "Weight %"], row)
    row += 1
    for key, value in weights.items():
        sheet.cell(row=row, column=1, value=_humanise(key))
        sheet.cell(row=row, column=2, value=_scalar(value))
        row += 1
    sheet.cell(row=row, column=1, value="Total").font = SECTION_FONT
    sheet.cell(row=row, column=2, value=_scalar(round(sum(float(v) for v in weights.values()), 2)))

    sheet.column_dimensions["A"].width = 30
    sheet.column_dimensions["B"].width = 30


def _ranked_sheet(sheet: Worksheet, entries: list[dict[str, Any]]) -> None:
    _write_header(sheet, [label for _, label in ENTRY_COLUMNS])
    for index, entry in enumerate(entries, start=2):
        for column, (key, _label) in enumerate(ENTRY_COLUMNS, start=1):
            sheet.cell(row=index, column=column, value=_cell(entry, key))
    sheet.freeze_panes = "A2"
    sheet.column_dimensions["C"].width = 28
    sheet.column_dimensions["S"].width = 50
    sheet.column_dimensions["T"].width = 50
    sheet.column_dimensions["U"].width = 60


def _breakdown_sheet(sheet: Worksheet, entries: list[dict[str, Any]]) -> None:
    eligible = [e for e in entries if e.get("is_eligible")]
    sheet["A1"] = "Score breakdown (eligible suppliers, rule-based)"
    sheet["A1"].font = TITLE_FONT
    dims = [
        ("overall_score", "Overall"), ("cost_score", "Cost"), ("delivery_score", "Delivery"),
        ("quality_score", "Quality"), ("capacity_score", "Capacity"), ("risk_score", "Risk"),
        ("esg_score", "ESG"), ("contract_score", "Contract"),
        ("geographic_score", "Geographic"), ("past_performance_score", "Past Performance"),
    ]
    headers = ["Rank", "Supplier"] + [label for _, label in dims]
    _write_header(sheet, headers, row=3)
    for index, entry in enumerate(eligible, start=4):
        sheet.cell(row=index, column=1, value=_scalar(entry.get("rank")))
        sheet.cell(row=index, column=2, value=_scalar(entry.get("supplier_name") or entry.get("supplier_id")))
        for offset, (key, _label) in enumerate(dims, start=3):
            sheet.cell(row=index, column=offset, value=_scalar(entry.get(key)))
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
    sheet.cell(row=row, column=1, value=supplier_reco_disclaimer()).alignment = Alignment(wrap_text=True)
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
    label = label.replace("pct", "%")
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
