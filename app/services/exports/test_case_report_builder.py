"""Report builders for the SAP Test Case Generator.

Four formats, all built from the same payload:

* **XLSX** - five sheets: Summary, Test Cases, Steps, Coverage and Methodology.
* **CSV** - the test-case table, which is what people paste into a test
  management tool.
* **JSON** - the complete payload for a downstream system.
* **PDF** - the readable test script: one page-flowing section per test case,
  for the reviewer who wants to read it rather than filter it.

Two shapes matter and both are produced:

*The table* (CSV, and the Test Cases sheet) carries one row per test case with
the steps flattened into a single numbered cell, because that is what a
spreadsheet and a test management import expect.

*The step table* (the Steps sheet) carries one row per step, because that is
what an execution tracker needs when a tester records a result per step.

Every format carries the disclaimer: these are drafts produced from a typed
process description, not test cases that have been executed or validated in a
live SAP system.
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
from app.services.documents.pdf_writer import build_text_pdf
from app.services.exports.workbook import workbook_to_bytes

logger = get_logger(__name__)

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(bold=True, size=14)
SECTION_FONT = Font(bold=True, size=11)

#: (payload key, column label) for the flat test-case export.
TEST_CASE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("test_case_id", "Test Case ID"),
    ("test_type_label", "Test Type"),
    ("title", "Title"),
    ("objective", "Objective"),
    ("priority", "Priority"),
    ("preconditions", "Preconditions"),
    ("test_data", "Test Data"),
    ("steps", "Test Steps"),
    ("expected_result", "Expected Result"),
    ("owner", "Owner"),
    ("status", "Status"),
    ("actual_result", "Actual Result"),
    ("execution_result", "Pass / Fail"),
    ("execution_is_stale", "Result Predates The Current Script"),
    ("evidence_reference", "Evidence Reference"),
    ("comments", "Comments"),
    ("source", "Drafted By"),
    ("output_origin", "Output Origin"),
    ("approved_by", "Approved By"),
    ("executed_by", "Executed By"),
    ("executed_at", "Executed At"),
)

STEP_COLUMNS: tuple[tuple[str, str], ...] = (
    ("test_case_id", "Test Case ID"),
    ("title", "Title"),
    ("step_number", "Step"),
    ("action", "Action"),
    ("test_data", "Step Test Data"),
    ("expected_result", "Step Expected Result"),
)

COVERAGE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("label", "Test Type"),
    ("planned", "Planned"),
    ("generated", "In Suite"),
    ("ai_drafted", "AI Drafted"),
    ("template_built", "Template Built"),
    ("manual", "Added By Hand"),
)


def test_case_disclaimer(payload: dict[str, Any] | None = None) -> str:
    """The disclaimer printed on every test case export."""
    if payload and payload.get("disclaimer"):
        return str(payload["disclaimer"])
    return (
        "These test cases were drafted from a process description entered in this "
        "application. They have NOT been executed or validated in a live SAP system, and "
        "this application is not connected to one. Review and adjust them against the actual "
        "configuration before use."
    )


# ---------------------------------------------------------------------------
# JSON and CSV
# ---------------------------------------------------------------------------


def build_test_case_json_report(payload: dict[str, Any]) -> bytes:
    """Serialise the full suite payload as JSON."""
    document = {
        "report_type": "sap_test_case_suite",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": test_case_disclaimer(payload),
        **payload,
    }
    return json.dumps(document, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def build_test_case_csv_report(test_cases: list[dict[str, Any]]) -> bytes:
    """Serialise the test-case table as CSV (UTF-8 with BOM for Excel)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([label for _, label in TEST_CASE_COLUMNS])
    for case in test_cases:
        writer.writerow([_cell(case, key) for key, _ in TEST_CASE_COLUMNS])
    return buffer.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------


def build_test_case_xlsx_report(payload: dict[str, Any]) -> bytes:
    """Build the multi-sheet test suite workbook."""
    workbook = Workbook()
    workbook.remove(workbook.active)

    _summary_sheet(workbook.create_sheet("Summary"), payload)
    _table_sheet(
        workbook.create_sheet("Test Cases"), payload.get("test_cases", []), TEST_CASE_COLUMNS
    )
    _table_sheet(
        workbook.create_sheet("Steps"), _step_rows(payload.get("test_cases", [])), STEP_COLUMNS
    )
    _table_sheet(
        workbook.create_sheet("Coverage"), payload.get("coverage", []), COVERAGE_COLUMNS
    )
    _methodology_sheet(workbook.create_sheet("Methodology"), payload)

    payload_bytes = workbook_to_bytes(workbook)
    logger.info(
        "Built test case XLSX: %d test case(s)", len(payload.get("test_cases", []))
    )
    return payload_bytes


def _step_rows(test_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten the suite into one row per step."""
    rows: list[dict[str, Any]] = []
    for case in test_cases:
        for step in case.get("steps", []) or []:
            rows.append(
                {
                    "test_case_id": case.get("test_case_id"),
                    "title": case.get("title"),
                    "step_number": step.get("step_number"),
                    "action": step.get("action"),
                    "test_data": step.get("test_data"),
                    "expected_result": step.get("expected_result"),
                }
            )
    return rows


def _summary_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    suite = payload.get("suite", {}) or {}
    context = suite.get("context", {}) or {}
    summary = payload.get("summary", {}) or {}
    ai_info = suite.get("ai", {}) or {}

    sheet["A1"] = "SAP Test Case Generator - Suite Summary"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = test_case_disclaimer(payload)
    sheet["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    sheet.merge_cells("A2:F6")

    row = 8
    sheet.cell(row=row, column=1, value="Process").font = SECTION_FONT
    row += 1
    for label, value in (
        ("Suite", suite.get("name")),
        ("Suite ID", suite.get("suite_id")),
        ("SAP product", context.get("sap_product")),
        ("SAP module", context.get("sap_module")),
        ("Business process", context.get("business_process")),
        ("Process description", context.get("process_description")),
        ("Systems involved", context.get("systems_involved")),
        ("Integrations", context.get("integrations")),
        ("User roles", context.get("user_roles")),
        ("Business rules", context.get("business_rules")),
        ("Preconditions", context.get("preconditions")),
        ("Test data requirements", context.get("test_data_requirements")),
    ):
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(value)).alignment = Alignment(
            wrap_text=True, vertical="top"
        )
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Suite").font = SECTION_FONT
    row += 1
    for label, value in (
        ("Test cases", summary.get("test_case_count")),
        ("Requested", suite.get("requested_count")),
        ("Total steps", summary.get("step_count")),
        ("AI drafted", summary.get("ai_drafted_count")),
        ("Built from template", summary.get("template_built_count")),
        ("Added by hand", summary.get("manual_count")),
        ("Approved", summary.get("approved_count")),
        ("Executed", summary.get("executed_count")),
        ("Passed", summary.get("passed_count")),
        ("Failed", summary.get("failed_count")),
        ("Results predating the current script", summary.get("stale_execution_count")),
        ("Pass rate (%) of decided runs", summary.get("pass_rate_pct")),
        ("Priorities", summary.get("priority_counts")),
        ("Statuses", summary.get("status_counts")),
        ("Configuration version", suite.get("config_version")),
        ("Engine version", suite.get("engine_version")),
    ):
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(value))
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Drafting provenance").font = SECTION_FONT
    row += 1
    for label, value in (
        ("AI requested", ai_info.get("requested")),
        ("AI used", ai_info.get("used")),
        ("Provider", ai_info.get("provider")),
        ("Model", ai_info.get("model")),
        ("Output origin", ai_info.get("origin")),
        ("Prompt version", ai_info.get("prompt_version")),
        ("Estimated cost (USD)", ai_info.get("estimated_cost_usd")),
        ("AI error", ai_info.get("error")),
    ):
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(value))
        row += 1

    for note in suite.get("notes", []) or []:
        sheet.cell(row=row, column=1, value="Note")
        sheet.cell(row=row, column=2, value=_scalar(note)).alignment = Alignment(wrap_text=True)
        row += 1

    sheet.column_dimensions["A"].width = 32
    sheet.column_dimensions["B"].width = 90


def _table_sheet(
    sheet: Worksheet, rows: list[dict[str, Any]], columns: tuple[tuple[str, str], ...]
) -> None:
    _write_header(sheet, [label for _, label in columns])
    for index, record in enumerate(rows, start=2):
        for column, (key, _label) in enumerate(columns, start=1):
            cell = sheet.cell(row=index, column=column, value=_cell(record, key))
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A2"
    for letter, width in (
        ("A", 16), ("B", 22), ("C", 46), ("D", 60), ("E", 12),
        ("F", 46), ("G", 46), ("H", 80), ("I", 60),
    ):
        sheet.column_dimensions[letter].width = width


def _methodology_sheet(sheet: Worksheet, payload: dict[str, Any]) -> None:
    methodology = payload.get("methodology", {}) or {}

    sheet["A1"] = "Methodology"
    sheet["A1"].font = TITLE_FONT

    row = 3
    sheet.cell(row=row, column=1, value="Decided by deterministic Python").font = SECTION_FONT
    row += 1
    for item in methodology.get("deterministic", []) or []:
        sheet.cell(row=row, column=1, value="-")
        sheet.cell(row=row, column=2, value=_scalar(item)).alignment = Alignment(wrap_text=True)
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Written by the AI provider").font = SECTION_FONT
    row += 1
    for item in methodology.get("ai_generated", []) or []:
        sheet.cell(row=row, column=1, value="-")
        sheet.cell(row=row, column=2, value=_scalar(item)).alignment = Alignment(wrap_text=True)
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Rules").font = SECTION_FONT
    row += 1
    for key in ("allocation_weights", "priority_rules", "identifier_template"):
        sheet.cell(row=row, column=1, value=_humanise(key))
        sheet.cell(row=row, column=2, value=_scalar(methodology.get(key))).alignment = Alignment(
            wrap_text=True
        )
        row += 1

    row += 1
    for label, key in (("Coverage note", "coverage_note"), ("AI note", "ai_note")):
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=_scalar(payload.get(key))).alignment = Alignment(
            wrap_text=True
        )
        row += 1

    row += 1
    sheet.cell(row=row, column=1, value="Disclaimer").font = SECTION_FONT
    row += 1
    sheet.cell(row=row, column=1, value=test_case_disclaimer(payload)).alignment = Alignment(
        wrap_text=True
    )
    sheet.merge_cells(start_row=row, start_column=1, end_row=row + 5, end_column=6)

    sheet.column_dimensions["A"].width = 34
    sheet.column_dimensions["B"].width = 100


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def build_test_case_pdf_report(payload: dict[str, Any]) -> bytes:
    """Render the suite as a readable test script PDF.

    Built on the same dependency-free text PDF writer the Contract Assistant
    uses for its fixtures: one column, extractable text, no extra dependency for
    a format that only has to be read.
    """
    return build_text_pdf(
        _pdf_text(payload), title=str((payload.get("suite") or {}).get("name") or "Test suite")
    ).content


def _pdf_text(payload: dict[str, Any]) -> str:
    """Lay the suite out as plain text, one test case per page."""
    suite = payload.get("suite", {}) or {}
    context = suite.get("context", {}) or {}
    summary = payload.get("summary", {}) or {}
    lines: list[str] = []

    lines.append("SAP TEST CASE SUITE")
    lines.append("=" * 70)
    lines.append(f"Suite:            {suite.get('name', '')}")
    lines.append(f"SAP product:      {context.get('sap_product', '')}")
    lines.append(f"SAP module:       {context.get('sap_module', '')}")
    lines.append(f"Business process: {context.get('business_process', '')}")
    lines.append(f"Generated at:     {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append("")
    lines.append(
        f"Test cases: {summary.get('test_case_count', 0)}   "
        f"AI drafted: {summary.get('ai_drafted_count', 0)}   "
        f"From template: {summary.get('template_built_count', 0)}   "
        f"Added by hand: {summary.get('manual_count', 0)}"
    )
    lines.append(
        f"Approved: {summary.get('approved_count', 0)}   "
        f"Executed: {summary.get('executed_count', 0)}   "
        f"Passed: {summary.get('passed_count', 0)}   "
        f"Failed: {summary.get('failed_count', 0)}"
    )
    lines.append("")
    lines.append("Coverage by test type")
    lines.append("-" * 70)
    for item in payload.get("coverage", []) or []:
        lines.append(
            f"  {str(item.get('label', '')):<28} planned {item.get('planned', 0):>3}   "
            f"in suite {item.get('generated', 0):>3}"
        )
    lines.append("")
    lines.append("Process description")
    lines.append("-" * 70)
    lines.append(str(context.get("process_description", "")))
    for label, key in (
        ("Preconditions", "preconditions"),
        ("Business rules", "business_rules"),
        ("Systems involved", "systems_involved"),
        ("Integrations", "integrations"),
        ("User roles", "user_roles"),
        ("Test data requirements", "test_data_requirements"),
    ):
        values = context.get(key) or []
        if values:
            lines.append("")
            lines.append(f"{label}:")
            lines.extend(f"  - {item}" for item in values)
    lines.append("")
    lines.append("Disclaimer")
    lines.append("-" * 70)
    lines.append(test_case_disclaimer(payload))
    if payload.get("ai_note"):
        lines.append("")
        lines.append(str(payload["ai_note"]))

    for case in payload.get("test_cases", []) or []:
        lines.append("\f")
        lines.append(f"{case.get('test_case_id', '')}  -  {case.get('title', '')}")
        lines.append("=" * 70)
        lines.append(f"Test type:   {case.get('test_type_label') or case.get('test_type')}")
        lines.append(f"Priority:    {case.get('priority', '')}")
        lines.append(f"Owner:       {case.get('owner', '')}")
        lines.append(f"Status:      {case.get('status', '')}")
        lines.append(f"Drafted by:  {_source_label(case)}")
        lines.append("")
        lines.append("Objective")
        lines.append("-" * 70)
        lines.append(str(case.get("objective", "")))

        for label, key in (("Preconditions", "preconditions"), ("Test data", "test_data")):
            lines.append("")
            lines.append(label)
            lines.append("-" * 70)
            values = case.get(key) or []
            if values:
                lines.extend(f"  - {item}" for item in values)
            else:
                lines.append("  (none stated)")

        lines.append("")
        lines.append("Test steps")
        lines.append("-" * 70)
        for step in case.get("steps", []) or []:
            lines.append(f"  {step.get('step_number', '')}. {step.get('action', '')}")
            if step.get("test_data"):
                lines.append(f"       Data:     {step['test_data']}")
            if step.get("expected_result"):
                lines.append(f"       Expected: {step['expected_result']}")

        lines.append("")
        lines.append("Expected result")
        lines.append("-" * 70)
        lines.append(str(case.get("expected_result", "")))

        lines.append("")
        lines.append("Execution record")
        lines.append("-" * 70)
        lines.append(f"  Actual result:      {case.get('actual_result') or '(not run)'}")
        lines.append(f"  Pass / fail:        {case.get('execution_result', '')}")
        lines.append(f"  Evidence reference: {case.get('evidence_reference') or '-'}")
        lines.append(f"  Executed by:        {case.get('executed_by') or '-'}")
        lines.append(f"  Approved by:        {case.get('approved_by') or '-'}")
        lines.append(f"  Comments:           {case.get('comments') or '-'}")
        if case.get("execution_is_stale"):
            lines.append(
                "  NOTE: this result was recorded against an earlier version of the "
                "steps above and has not been re-run since."
            )
        for note in case.get("validation_notes") or []:
            lines.append(f"  Drafting note:      {note}")

    return "\n".join(lines)


def _source_label(case: dict[str, Any]) -> str:
    """Say plainly who wrote a test case's words."""
    source = str(case.get("source", ""))
    origin = str(case.get("output_origin", ""))
    labels = {
        "ai_generated": f"AI provider ({origin})",
        "template": "deterministic template (no model involved)",
        "manual": "added by hand",
        "duplicated": "duplicated from another test case",
    }
    return labels.get(source, source or "unknown")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_header(sheet: Worksheet, headers: list[str], row: int = 1) -> None:
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(row=row, column=column, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT


def _humanise(key: str) -> str:
    label = key.replace("_", " ").strip()
    return label[:1].upper() + label[1:]


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, default=str, ensure_ascii=False)[:2000]
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return value


def _cell(record: dict[str, Any], key: str) -> Any:
    """Render one cell, flattening the step list into a numbered block."""
    value = record.get(key)
    if key == "steps" and isinstance(value, list):
        parts: list[str] = []
        for step in value:
            line = f"{step.get('step_number')}. {step.get('action', '')}"
            if step.get("test_data"):
                line += f" [data: {step['test_data']}]"
            if step.get("expected_result"):
                line += f" -> {step['expected_result']}"
            parts.append(line)
        return "\n".join(parts)
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return _scalar(value)
