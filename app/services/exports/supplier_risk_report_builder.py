"""Report builders for the Supplier Risk Copilot.

Three formats, all built from one payload:

* **XLSX** - six sheets: Summary, Portfolio, Category Scores, Evidence &
  Missing Data, Recommended Actions and Methodology.
* **CSV** - the portfolio table, which is what goes into a review meeting.
* **JSON** - the whole payload, for a downstream system.

The shape of this module follows the other seven builders; the styling and
value-flattening come from :mod:`app.services.exports.styling` rather than
another private copy of them.

Two things this report has to do that a ranking report does not.

**A score has to carry its arithmetic.** The overall figure is a weighted sum of
ten category scores, so the Category Scores sheet prints the score, the
configured weight, the *normalised* weight and the contribution in points. A
reader can add the contribution column up and get the overall score back. A risk
number somebody cannot reconstruct is a number they will argue with rather than
act on.

**"Not scored" is not "scored zero".** A category with no data does not drag the
supplier's score down; its weight is redistributed over the categories that do
have data. That is invisible in a report that only prints scores, so the
Evidence & Missing Data sheet lists, per supplier, which categories were scored,
which were not, which specific metrics were missing and how complete the data
was. Without it a 42 built from four categories looks exactly like a 42 built
from ten.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.core.logging import get_logger
from app.services.exports.styling import (
    SECTION_FONT,
    TITLE_FONT,
    WRAP,
    cell_value,
    humanise,
    scalar,
    write_header,
    write_key_values,
    write_paragraph,
)
from app.services.exports.workbook import workbook_to_bytes

logger = get_logger(__name__)

#: (payload key, column label) for the portfolio table.
PORTFOLIO_COLUMNS: tuple[tuple[str, str], ...] = (
    ("rank", "Rank"),
    ("supplier_id", "Supplier ID"),
    ("supplier_name", "Supplier Name"),
    ("overall_score", "Overall Risk Score"),
    ("overall_band", "Risk Band"),
    ("country", "Country"),
    ("spend_category", "Spend Category"),
    ("total_spend_base", "Total Spend (base)"),
    ("data_completeness_pct", "Data Completeness %"),
    ("limited_data", "Limited Data"),
    ("trend_direction", "Trend"),
    ("contract_status", "Contract Status"),
    ("contract_expiration", "Contract Expiry"),
    ("contract_expiring_soon", "Expiring Soon"),
    ("on_time_delivery_rate", "On-Time Delivery %"),
    ("late_delivery_count", "Late Deliveries"),
    ("invoice_exception_count", "Invoice Exceptions"),
    ("output_origin", "Origin"),
)


def supplier_risk_disclaimer() -> str:
    """The disclaimer printed on every supplier risk export.

    It says two separate things, because they are two separate limitations and a
    reader needs both. The first is the standing one: this is demo software on
    fictional data with nothing validated in SAP. The second is specific to risk
    scoring and is the one people forget - **every figure here was computed from
    the uploaded records only.** No credit bureau, no sanctions list, no news
    feed and no ESG rating agency was consulted. A supplier scoring low risk here
    has a clean internal history, which is not the same claim as a clean record.
    """
    return (
        "Supplier risk scores are calculated deterministically from the uploaded supplier and "
        "event records only, using the documented categories, weights and thresholds in the "
        "configuration. NO EXTERNAL DATA SOURCE WAS CONSULTED: no credit bureau, sanctions list, "
        "news feed, court register or ESG rating agency contributed to any score in this report. "
        "A low score therefore means a clean internal record, not a clean record. Categories with "
        "no supporting data are excluded from the weighted score rather than scored zero, and are "
        "listed per supplier in the Evidence & Missing Data sheet. This application is not "
        "connected to a live SAP system and no assessment here has been validated in a live SAP "
        "environment. Any AI generated text explains the scores and never determines them."
    )


# ---------------------------------------------------------------------------
# JSON / CSV
# ---------------------------------------------------------------------------


def build_supplier_risk_json_report(payload: dict[str, Any]) -> bytes:
    """Serialise the whole assessment payload as JSON."""
    document = {
        "report_type": "sap_supplier_risk_assessment",
        "generated_at": datetime.now(UTC).isoformat(),
        "disclaimer": supplier_risk_disclaimer(),
        **payload,
    }
    return json.dumps(document, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def build_supplier_risk_csv_report(suppliers: list[dict[str, Any]]) -> bytes:
    """Serialise the portfolio table as CSV (UTF-8 with BOM, so Excel opens it)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([label for _, label in PORTFOLIO_COLUMNS])
    for supplier in suppliers:
        writer.writerow([cell_value(supplier, key) for key, _ in PORTFOLIO_COLUMNS])
    return buffer.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------


def build_supplier_risk_xlsx_report(payload: dict[str, Any]) -> bytes:
    """Build the multi-sheet supplier risk workbook."""
    workbook = Workbook()
    workbook.remove(workbook.active)

    suppliers = payload.get("suppliers", []) or []
    profiles = payload.get("profiles", []) or []

    _summary_sheet(workbook.create_sheet("Summary"), payload)
    _portfolio_sheet(workbook.create_sheet("Portfolio"), suppliers)
    _category_sheet(workbook.create_sheet("Category Scores"), profiles or suppliers)
    _evidence_sheet(workbook.create_sheet("Evidence & Missing Data"), profiles)
    _actions_sheet(workbook.create_sheet("Recommended Actions"), profiles)
    _methodology_sheet(workbook.create_sheet("Methodology"), payload)

    payload_bytes = workbook_to_bytes(workbook)
    logger.info(
        "Built supplier risk XLSX: %d suppliers, %d full profiles", len(suppliers), len(profiles)
    )
    return payload_bytes


def _summary_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    assessment = payload.get("assessment", {}) or {}
    summary = payload.get("summary", {}) or {}
    narrative = payload.get("ai_narrative", {}) or {}

    sheet["A1"] = "SAP Supplier Risk Assessment - Summary"
    sheet["A1"].font = TITLE_FONT
    row = write_paragraph(sheet, supplier_risk_disclaimer(), 2, height=6)

    row += 1
    sheet.cell(row=row, column=1, value="Assessment").font = SECTION_FONT
    row = write_key_values(
        sheet,
        [
            ("Assessment ID", assessment.get("assessment_id")),
            ("Dataset ID", assessment.get("dataset_id")),
            ("Status", assessment.get("status")),
            ("Source file", assessment.get("source_filename")),
            ("As of date", assessment.get("as_of_date")),
            ("Created", assessment.get("created_at")),
            ("Base currency", assessment.get("base_currency")),
            ("Configuration version", assessment.get("config_version")),
            ("Engine version", assessment.get("engine_version")),
        ],
        row + 1,
    )

    row += 1
    sheet.cell(row=row, column=1, value="Portfolio").font = SECTION_FONT
    row = write_key_values(
        sheet, [(humanise(key), value) for key, value in summary.items()], row + 1
    )

    if narrative.get("summary"):
        row += 1
        origin = narrative.get("origin") or "ai"
        sheet.cell(
            row=row, column=1, value=f"Narrative ({origin} - not a source of any score)"
        ).font = SECTION_FONT
        row = write_paragraph(sheet, str(narrative["summary"]), row + 1)

    errors = payload.get("rule_errors") or []
    if errors:
        row += 1
        sheet.cell(row=row, column=1, value="Scoring errors").font = SECTION_FONT
        row += 1
        for error in errors:
            sheet.cell(row=row, column=1, value=scalar(error))
            row += 1

    sheet.column_dimensions["A"].width = 34
    sheet.column_dimensions["B"].width = 46


def _portfolio_sheet(sheet: Worksheet, suppliers: list[dict[str, Any]]) -> None:
    write_header(sheet, [label for _, label in PORTFOLIO_COLUMNS])
    for index, supplier in enumerate(suppliers, start=2):
        for column, (key, _label) in enumerate(PORTFOLIO_COLUMNS, start=1):
            sheet.cell(row=index, column=column, value=cell_value(supplier, key))
    sheet.freeze_panes = "A2"
    sheet.column_dimensions["B"].width = 16
    sheet.column_dimensions["C"].width = 30


def _category_sheet(sheet: Worksheet, records: list[dict[str, Any]]) -> None:
    """One row per supplier per category, with the arithmetic behind the score."""
    sheet["A1"] = "Category scores and weighted contributions (rule-based)"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = (
        "Contribution = score x normalised weight. The contributions of the scored "
        "categories sum to the supplier's overall score. A category with no data is "
        "excluded and its weight redistributed - it is not scored zero."
    )
    sheet["A2"].alignment = WRAP
    headers = [
        "Supplier ID",
        "Supplier Name",
        "Overall Score",
        "Category",
        "Category Label",
        "Score",
        "Band",
        "Configured Weight",
        "Normalised Weight",
        "Contribution",
        "Data Available",
        "Missing Metrics",
    ]
    write_header(sheet, headers, row=4)

    row = 5
    for record in records:
        for category in record.get("categories", record.get("category_scores", [])) or []:
            values = [
                record.get("supplier_id"),
                record.get("supplier_name"),
                record.get("overall_score"),
                category.get("category"),
                category.get("label"),
                category.get("score"),
                category.get("band"),
                category.get("weight"),
                category.get("normalized_weight"),
                category.get("contribution"),
                category.get("data_available"),
                category.get("missing_metrics"),
            ]
            for column, value in enumerate(values, start=1):
                sheet.cell(row=row, column=column, value=scalar(value))
            row += 1

    sheet.freeze_panes = "A5"
    sheet.column_dimensions["B"].width = 30
    sheet.column_dimensions["E"].width = 26
    sheet.column_dimensions["L"].width = 40


def _evidence_sheet(sheet: Worksheet, profiles: list[dict[str, Any]]) -> None:
    """What each score rests on, and what was missing when it was calculated."""
    sheet["A1"] = "Supporting evidence and missing data"
    sheet["A1"].font = TITLE_FONT
    headers = [
        "Supplier ID",
        "Supplier Name",
        "Data Completeness %",
        "Limited Data",
        "Scored Categories",
        "Unscored Categories",
        "Delivery Issues",
        "Quality Issues",
        "Invoice Issues",
        "Compliance Issues",
        "Trend",
        "Trend Basis",
        "Events",
        "Purchase Orders",
        "Invoices",
    ]
    write_header(sheet, headers, row=3)

    for index, profile in enumerate(profiles, start=4):
        trend = profile.get("trend", {}) or {}
        values = [
            profile.get("supplier_id"),
            profile.get("supplier_name"),
            profile.get("data_completeness_pct"),
            profile.get("limited_data"),
            profile.get("scored_categories"),
            profile.get("unscored_categories"),
            profile.get("delivery_issues"),
            profile.get("quality_issues"),
            profile.get("invoice_issues"),
            profile.get("compliance_issues"),
            trend.get("direction"),
            trend.get("basis"),
            profile.get("event_count"),
            profile.get("purchase_order_count"),
            profile.get("invoice_count"),
        ]
        for column, value in enumerate(values, start=1):
            sheet.cell(row=index, column=column, value=scalar(value))

    sheet.freeze_panes = "A4"
    sheet.column_dimensions["B"].width = 30
    for letter in ("E", "F", "G", "H", "I", "J"):
        sheet.column_dimensions[letter].width = 40


def _actions_sheet(sheet: Worksheet, profiles: list[dict[str, Any]]) -> None:
    sheet["A1"] = "Recommended actions (rule-based)"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = "Each action names the category and the condition that triggered it."
    write_header(
        sheet,
        ["Supplier ID", "Supplier Name", "Priority", "Category", "Action", "Trigger", "Origin"],
        row=4,
    )

    row = 5
    for profile in profiles:
        for action in profile.get("actions", []) or []:
            values = [
                profile.get("supplier_id"),
                profile.get("supplier_name"),
                action.get("priority"),
                action.get("category_label") or action.get("category"),
                action.get("action"),
                action.get("trigger"),
                action.get("output_origin"),
            ]
            for column, value in enumerate(values, start=1):
                sheet.cell(row=row, column=column, value=scalar(value))
            row += 1

    sheet.freeze_panes = "A5"
    sheet.column_dimensions["B"].width = 30
    sheet.column_dimensions["E"].width = 60
    sheet.column_dimensions["F"].width = 50


def _methodology_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    methodology = payload.get("methodology", {}) or {}
    weights = payload.get("weights", {}) or {}

    sheet["A1"] = "Methodology"
    sheet["A1"].font = TITLE_FONT

    row = 3
    sheet.cell(row=row, column=1, value="Applied weights (%)").font = SECTION_FONT
    row += 1
    write_header(sheet, ["Category", "Weight %"], row)
    row += 1
    for key, value in weights.items():
        sheet.cell(row=row, column=1, value=humanise(key))
        sheet.cell(row=row, column=2, value=scalar(value))
        row += 1
    sheet.cell(row=row, column=1, value="Total").font = SECTION_FONT
    sheet.cell(
        row=row, column=2, value=round(sum(float(v or 0) for v in weights.values()), 2)
    )
    row += 2

    for key, value in methodology.items():
        sheet.cell(row=row, column=1, value=humanise(key))
        sheet.cell(row=row, column=2, value=scalar(value)).alignment = WRAP
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Disclaimer").font = SECTION_FONT
    write_paragraph(sheet, supplier_risk_disclaimer(), row + 1, height=6)

    sheet.column_dimensions["A"].width = 38
    sheet.column_dimensions["B"].width = 90
