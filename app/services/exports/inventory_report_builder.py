"""Report builders for the Inventory Predictor.

Three formats, all built from the same payload:

* **XLSX** - six sheets: Summary, Materials, Forecast, Reorder Plan,
  Data Quality and Methodology. The Forecast sheet is the long-format table a
  planner pastes into their own chart: one row per material per future period,
  with the demand forecast, the confidence range and the projected stock level.
* **CSV** - the materials table, which is what a planner usually wants in Excel.
* **JSON** - the complete payload for a downstream system.

Every format carries the forecast disclaimer, so a file that leaves this
application cannot be mistaken for a committed plan or for validated SAP output.
Each numeric sheet also states that the figures are statistical estimates, next
to the numbers rather than only on the front page.
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

#: (payload key, column label) for the per-material export.
ITEM_COLUMNS: tuple[tuple[str, str], ...] = (
    ("material", "Material"),
    ("material_description", "Description"),
    ("plant", "Plant"),
    ("storage_location", "Storage Location"),
    ("supplier_id", "Supplier"),
    ("status", "Status"),
    ("model_label", "Model Used"),
    ("selection_basis", "Model Chosen By"),
    ("frequency", "Period"),
    ("history_period_count", "History Periods"),
    ("missing_period_count", "Missing Periods"),
    ("total_forecast_demand", "Forecast Demand (horizon)"),
    ("opening_inventory", "Stock On Hand"),
    ("minimum_projected_inventory", "Lowest Projected Stock"),
    ("ending_projected_inventory", "Projected Stock (end of horizon)"),
    ("predicted_shortage_date", "Predicted Shortage Date"),
    ("days_to_shortage", "Days To Shortage"),
    ("recommended_reorder_date", "Recommended Reorder Date"),
    ("recommended_reorder_quantity", "Recommended Reorder Qty"),
    ("calculated_reorder_point", "Calculated Reorder Point"),
    ("recommended_safety_stock", "Recommended Safety Stock"),
    ("order_urgency", "Order Urgency"),
    ("expedite_recommended", "Expedite Open PO"),
    ("movement_class", "Movement Class"),
    ("is_slow_moving", "Slow Moving"),
    ("is_dead_stock", "Dead Stock"),
    ("overstock_risk", "Overstock Risk"),
    ("days_of_cover", "Days Of Cover"),
    ("annual_turnover", "Annual Turnover"),
    ("accuracy_basis", "Accuracy Basis"),
    ("mae", "MAE"),
    ("rmse", "RMSE"),
    ("mape", "MAPE %"),
    ("smape", "sMAPE %"),
    ("mase", "MASE"),
    ("warning_count", "Warnings"),
)

FORECAST_COLUMNS: tuple[tuple[str, str], ...] = (
    ("material", "Material"),
    ("plant", "Plant"),
    ("storage_location", "Storage Location"),
    ("period_date", "Period"),
    ("model_label", "Model"),
    ("demand", "Forecast Demand"),
    ("lower", "Lower Bound"),
    ("upper", "Upper Bound"),
    ("projected_ending", "Projected Stock"),
    ("projected_ending_low", "Projected Stock (worst case)"),
    ("projected_ending_high", "Projected Stock (best case)"),
    ("scheduled_receipts", "Scheduled Receipts"),
    ("below_safety_stock", "Below Safety Stock"),
    ("stockout", "Stockout"),
)

REORDER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("material", "Material"),
    ("material_description", "Description"),
    ("plant", "Plant"),
    ("supplier_id", "Supplier"),
    ("order_urgency", "Urgency"),
    ("recommended_reorder_date", "Reorder On"),
    ("recommended_reorder_quantity", "Order Quantity"),
    ("calculated_reorder_point", "Reorder Point (calculated)"),
    ("master_reorder_point", "Reorder Point (material master)"),
    ("recommended_safety_stock", "Safety Stock (recommended)"),
    ("master_safety_stock", "Safety Stock (material master)"),
    ("lead_time_days", "Lead Time (days)"),
    ("lead_time_source", "Lead Time From"),
    ("expedite_recommended", "Expedite Open PO"),
    ("predicted_shortage_date", "Predicted Shortage Date"),
    ("expedite_reason", "Note"),
)


def inventory_disclaimer() -> str:
    """The disclaimer printed on every inventory export."""
    return (
        "Demand forecasts, confidence ranges, projected stock levels, shortage dates, reorder "
        "dates and quantities, safety-stock figures and stock classifications in this file are "
        "statistical estimates calculated from the uploaded history using the documented models "
        "and thresholds. They are planning indications, not commitments, orders or guaranteed "
        "outcomes, and actual demand will differ. This application is not connected to a live "
        "SAP system and no figure here has been validated in a live SAP environment. Any AI "
        "generated text in this file explains these numbers and never produces them."
    )


def build_inventory_json_report(payload: dict[str, Any]) -> bytes:
    """Serialise the full forecast payload as JSON."""
    document = {
        "report_type": "sap_inventory_forecast",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": inventory_disclaimer(),
        **payload,
    }
    return json.dumps(document, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def build_inventory_csv_report(items: list[dict[str, Any]]) -> bytes:
    """Serialise the per-material table as CSV (UTF-8 with BOM for Excel)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([label for _, label in ITEM_COLUMNS])
    for item in items:
        writer.writerow([_cell(item, key) for key, _ in ITEM_COLUMNS])
    return buffer.getvalue().encode("utf-8-sig")


def build_inventory_xlsx_report(payload: dict[str, Any]) -> bytes:
    """Build the multi-sheet inventory forecast workbook."""
    workbook = Workbook()
    workbook.remove(workbook.active)

    items = payload.get("items", []) or []
    _summary_sheet(workbook.create_sheet("Summary"), payload)
    _items_sheet(workbook.create_sheet("Materials"), items)
    _forecast_sheet(workbook.create_sheet("Forecast"), items)
    _reorder_sheet(workbook.create_sheet("Reorder Plan"), items)
    _data_quality_sheet(workbook.create_sheet("Data Quality"), payload, items)
    _methodology_sheet(workbook.create_sheet("Methodology"), payload)

    buffer = io.BytesIO()
    workbook.save(buffer)
    logger.info("Built inventory forecast XLSX: %d materials", len(items))
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------
def _summary_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    forecast = payload.get("forecast", {}) or {}
    summary = payload.get("summary", {}) or {}
    narrative = payload.get("ai_narrative", {}) or {}
    accuracy = summary.get("accuracy_summary", {}) or {}

    sheet["A1"] = "SAP Inventory Forecast - Summary"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = inventory_disclaimer()
    sheet["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet.merge_cells("A2:F7")

    row = 9
    sheet.cell(row=row, column=1, value="Run").font = SECTION_FONT
    row += 1
    for label, value in (
        ("Forecast ID", forecast.get("forecast_id")),
        ("Created", forecast.get("created_at")),
        ("Source file", forecast.get("source_filename")),
        ("As-of date", forecast.get("as_of_date")),
        ("Horizon (periods)", forecast.get("horizon_periods")),
        ("Confidence level", forecast.get("confidence_level")),
        ("Service level (reorder policy)", forecast.get("service_level")),
        ("Model", forecast.get("requested_model") or "auto (selected by backtesting)"),
        ("Model selection metric", forecast.get("selection_metric")),
        ("Configuration version", forecast.get("config_version")),
        ("Engine version", forecast.get("engine_version")),
    ):
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(value))
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Results").font = SECTION_FONT
    row += 1
    for label, value in (
        ("Material/plant combinations", summary.get("series_count")),
        ("Forecast produced", summary.get("forecast_count")),
        ("Too little history to forecast", summary.get("insufficient_data_count")),
        ("Projected shortages", summary.get("shortage_count")),
        ("Reorder needed now", summary.get("reorder_now_count")),
        ("Overstock risk", summary.get("overstock_count")),
        ("Slow moving", summary.get("slow_moving_count")),
        ("Dead stock", summary.get("dead_stock_count")),
        ("Total forecast demand over the horizon", summary.get("total_forecast_demand")),
    ):
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(value))
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Model usage").font = SECTION_FONT
    row += 1
    for model, count in (summary.get("model_usage", {}) or {}).items():
        sheet.cell(row=row, column=1, value=_humanise(model))
        sheet.cell(row=row, column=2, value=count)
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Average accuracy across materials").font = SECTION_FONT
    row += 1
    for label, key in (
        ("Mean MAE", "mean_mae"),
        ("Mean RMSE", "mean_rmse"),
        ("Mean sMAPE %", "mean_smape"),
        ("Mean MAPE % (materials with no zero-demand period)", "mean_mape"),
        ("Mean MASE (below 1 beats a naive forecast)", "mean_mase"),
        ("Materials with a backtest", "series_with_backtest"),
    ):
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(accuracy.get(key)))
        row += 1

    if narrative.get("summary"):
        row += 1
        origin = narrative.get("origin", "ai")
        sheet.cell(
            row=row,
            column=1,
            value=f"Narrative ({origin} - explains the figures, never produces them)",
        ).font = SECTION_FONT
        row += 1
        sheet.cell(row=row, column=1, value=narrative["summary"]).alignment = Alignment(
            wrap_text=True, vertical="top"
        )
        sheet.merge_cells(start_row=row, start_column=1, end_row=row + 3, end_column=6)

    sheet.column_dimensions["A"].width = 48
    sheet.column_dimensions["B"].width = 42


def _items_sheet(sheet: Worksheet, items: list[dict[str, Any]]) -> None:
    sheet["A1"] = "Materials - forecast, projection and recommendations (statistical estimates)"
    sheet["A1"].font = TITLE_FONT
    _write_header(sheet, [label for _, label in ITEM_COLUMNS], row=3)
    for index, item in enumerate(items, start=4):
        for column, (key, _label) in enumerate(ITEM_COLUMNS, start=1):
            sheet.cell(row=index, column=column, value=_cell(item, key))
    sheet.freeze_panes = "A4"
    sheet.column_dimensions["B"].width = 30
    sheet.column_dimensions["G"].width = 30


def _forecast_sheet(sheet: Worksheet, items: list[dict[str, Any]]) -> None:
    sheet["A1"] = (
        "Demand forecast and projected stock, one row per material per period "
        "(estimates with a confidence range, not commitments)"
    )
    sheet["A1"].font = TITLE_FONT
    _write_header(sheet, [label for _, label in FORECAST_COLUMNS], row=3)

    row = 4
    for item in items:
        payload = item.get("payload", {}) or {}
        projection_periods = {
            period.get("index"): period
            for period in ((payload.get("projection", {}) or {}).get("periods", []) or [])
        }
        for point in payload.get("forecast", []) or []:
            projected = projection_periods.get(point.get("index"), {})
            record = {
                "material": item.get("material"),
                "plant": item.get("plant"),
                "storage_location": item.get("storage_location"),
                "period_date": point.get("period_date"),
                "model_label": item.get("model_label"),
                "demand": point.get("demand"),
                "lower": point.get("lower"),
                "upper": point.get("upper"),
                "projected_ending": projected.get("projected_ending"),
                "projected_ending_low": projected.get("projected_ending_low"),
                "projected_ending_high": projected.get("projected_ending_high"),
                "scheduled_receipts": projected.get("scheduled_receipts"),
                "below_safety_stock": projected.get("below_safety_stock"),
                "stockout": projected.get("stockout"),
            }
            for column, (key, _label) in enumerate(FORECAST_COLUMNS, start=1):
                sheet.cell(row=row, column=column, value=_cell(record, key))
            row += 1

    sheet.freeze_panes = "A4"
    sheet.column_dimensions["E"].width = 30


def _reorder_sheet(sheet: Worksheet, items: list[dict[str, Any]]) -> None:
    sheet["A1"] = "Reorder plan - materials that need an order inside the horizon"
    sheet["A1"].font = TITLE_FONT
    _write_header(sheet, [label for _, label in REORDER_COLUMNS], row=3)

    row = 4
    for item in items:
        if not item.get("recommended_reorder_date") and not item.get("expedite_recommended"):
            continue
        reorder = ((item.get("payload", {}) or {}).get("projection", {}) or {}).get(
            "reorder", {}
        ) or {}
        record = {
            **item,
            "master_reorder_point": reorder.get("master_reorder_point"),
            "master_safety_stock": reorder.get("master_safety_stock"),
            "lead_time_days": reorder.get("lead_time_days"),
            "lead_time_source": reorder.get("lead_time_source"),
            "expedite_reason": reorder.get("expedite_reason"),
        }
        for column, (key, _label) in enumerate(REORDER_COLUMNS, start=1):
            sheet.cell(row=row, column=column, value=_cell(record, key))
        row += 1

    if row == 4:
        sheet.cell(
            row=4, column=1, value="No material needs a replenishment order inside the horizon."
        )
    sheet.freeze_panes = "A4"
    sheet.column_dimensions["B"].width = 30
    sheet.column_dimensions["P"].width = 80


def _data_quality_sheet(
    sheet: Worksheet, payload: dict[str, Any], items: list[dict[str, Any]]
) -> None:
    sheet["A1"] = "Data quality"
    sheet["A1"].font = TITLE_FONT

    row = 3
    sheet.cell(row=row, column=1, value="File level").font = SECTION_FONT
    row += 1
    _write_header(sheet, ["Field", "Issue", "Rows", "Severity", "Message"], row=row)
    row += 1
    for issue in payload.get("data_quality_issues", []) or []:
        sheet.cell(row=row, column=1, value=issue.get("field") or issue.get("field_name"))
        sheet.cell(row=row, column=2, value=issue.get("issue_type"))
        sheet.cell(row=row, column=3, value=issue.get("affected_rows"))
        sheet.cell(row=row, column=4, value=issue.get("severity"))
        sheet.cell(row=row, column=5, value=issue.get("message")).alignment = Alignment(
            wrap_text=True
        )
        row += 1

    row += 2
    sheet.cell(row=row, column=1, value="Material level").font = SECTION_FONT
    row += 1
    _write_header(sheet, ["Material", "Plant", "Code", "Severity", "Message"], row=row)
    row += 1
    for item in items:
        for warning in (item.get("payload", {}) or {}).get("warnings", []) or []:
            sheet.cell(row=row, column=1, value=item.get("material"))
            sheet.cell(row=row, column=2, value=item.get("plant"))
            sheet.cell(row=row, column=3, value=warning.get("code"))
            sheet.cell(row=row, column=4, value=warning.get("severity"))
            sheet.cell(row=row, column=5, value=warning.get("message")).alignment = Alignment(
                wrap_text=True
            )
            row += 1

    errors = payload.get("series_errors", []) or []
    if errors:
        row += 2
        sheet.cell(row=row, column=1, value="Materials that could not be forecast").font = (
            SECTION_FONT
        )
        row += 1
        _write_header(sheet, ["Material", "Plant", "Error", "Message"], row=row)
        row += 1
        for error in errors:
            sheet.cell(row=row, column=1, value=error.get("material"))
            sheet.cell(row=row, column=2, value=error.get("plant"))
            sheet.cell(row=row, column=3, value=error.get("error_type"))
            sheet.cell(row=row, column=4, value=error.get("message"))
            row += 1

    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["C"].width = 26
    sheet.column_dimensions["E"].width = 110


def _methodology_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    methodology = payload.get("methodology", {}) or {}
    sheet["A1"] = "Methodology"
    sheet["A1"].font = TITLE_FONT

    row = 3
    sheet.cell(row=row, column=1, value="Forecasting methods").font = SECTION_FONT
    row += 1
    _write_header(sheet, ["Method", "Minimum history", "Assumptions"], row=row)
    row += 1
    for method in methodology.get("methods", []) or []:
        sheet.cell(row=row, column=1, value=method.get("label"))
        sheet.cell(row=row, column=2, value=method.get("min_observations"))
        sheet.cell(
            row=row, column=3, value=" ".join(method.get("assumptions", []) or [])
        ).alignment = Alignment(wrap_text=True)
        row += 1

    row += 2
    for section in ("selection", "forecast", "reorder", "stock_health", "intermittent", "period"):
        values = methodology.get(section, {}) or {}
        if not values:
            continue
        sheet.cell(row=row, column=1, value=_humanise(section)).font = SECTION_FONT
        row += 1
        for key, value in values.items():
            sheet.cell(row=row, column=1, value=_humanise(key))
            sheet.cell(row=row, column=2, value=_scalar(value)).alignment = Alignment(
                wrap_text=True
            )
            row += 1
        row += 1

    sheet.cell(row=row, column=1, value="Disclaimer").font = SECTION_FONT
    row += 1
    sheet.cell(row=row, column=1, value=inventory_disclaimer()).alignment = Alignment(
        wrap_text=True, vertical="top"
    )
    sheet.merge_cells(start_row=row, start_column=1, end_row=row + 5, end_column=4)

    sheet.column_dimensions["A"].width = 40
    sheet.column_dimensions["B"].width = 60
    sheet.column_dimensions["C"].width = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write_header(sheet: Worksheet, headers: list[str], row: int = 1) -> None:
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(row=row, column=column, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT


def _humanise(key: str) -> str:
    label = str(key).replace("_pct", " %").replace("_", " ").strip()
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
