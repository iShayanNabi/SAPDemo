"""Helpers for building small, readable datasets in unit tests.

A rule test should read like a sentence: "two orders on the same supplier with
the same value three days apart produce one duplicate finding". These factories
supply sensible defaults so a test only writes the fields it cares about.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, timedelta
from typing import Any

import pandas as pd
from openpyxl import Workbook

from app.modules.po_risk.field_definitions import CANONICAL_FIELDS
from app.modules.po_risk.normalizer import normalize_dataframe
from app.modules.po_risk.rules.base import RuleContext
from app.modules.po_risk.thresholds import PoRiskConfig, get_rule_config

BASE_DATE = date(2025, 5, 12)

DEFAULT_ROW: dict[str, Any] = {
    "po_number": "4500000001",
    "po_item": "00010",
    "supplier_id": "0000100001",
    "supplier_name": "Nordwind Industrie GmbH",
    "material": "MAT-100000",
    "material_description": "Stainless bearing type 1",
    "material_group": "MG10",
    "company_code": "1000",
    "purchasing_org": "1000",
    "purchasing_group": "P01",
    "plant": "1010",
    "quantity": 10.0,
    "unit_of_measure": "PC",
    "unit_price": 100.0,
    "currency": "EUR",
    "total_value": 1000.0,
    "order_date": BASE_DATE,
    "requested_delivery_date": BASE_DATE + timedelta(days=14),
    "actual_delivery_date": BASE_DATE + timedelta(days=15),
    "contract_number": None,
    "payment_terms": "NT30",
    "approval_status": "Approved",
    "created_by": "BUYER01",
    "changed_by": "BUYER01",
    "change_count": 1,
}


def make_row(**overrides: Any) -> dict[str, Any]:
    """Build one canonical row, applying ``overrides`` on top of the defaults.

    ``total_value`` is recomputed automatically unless it is overridden.
    """
    row = {**DEFAULT_ROW, **overrides}
    if "total_value" not in overrides and row["quantity"] is not None and row["unit_price"] is not None:
        row["total_value"] = round(float(row["quantity"]) * float(row["unit_price"]), 2)
    return row


def make_rows(count: int, **overrides: Any) -> list[dict[str, Any]]:
    """Build ``count`` rows with incrementing purchase order numbers."""
    rows = []
    for index in range(count):
        row = make_row(**overrides)
        row["po_number"] = str(4500000001 + index)
        rows.append(row)
    return rows


def make_frame(rows: list[dict[str, Any]], config: PoRiskConfig | None = None) -> pd.DataFrame:
    """Run rows through the real normaliser to get a canonical frame."""
    config = config or get_rule_config()
    raw = pd.DataFrame([{key: row.get(key) for key in CANONICAL_FIELDS} for row in rows])
    mapping = {name: name for name in CANONICAL_FIELDS}
    return normalize_dataframe(raw, mapping, config).frame


def make_context(rows: list[dict[str, Any]], config: PoRiskConfig | None = None) -> RuleContext:
    """Build a :class:`RuleContext` from raw rows."""
    config = config or get_rule_config()
    return RuleContext(frame=make_frame(rows, config), config=config)


# ---------------------------------------------------------------------------
# File builders for the upload/API tests
# ---------------------------------------------------------------------------


def rows_to_csv(rows: list[dict[str, Any]], headers: dict[str, str] | None = None) -> bytes:
    """Serialise rows as CSV, optionally renaming the headers."""
    headers = headers or {}
    field_names = [headers.get(name, name) for name in CANONICAL_FIELDS]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=field_names, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {headers.get(name, name): _as_text(row.get(name)) for name in CANONICAL_FIELDS}
        )
    return buffer.getvalue().encode("utf-8")


def rows_to_xlsx(rows: list[dict[str, Any]], headers: dict[str, str] | None = None) -> bytes:
    """Serialise rows as a single sheet XLSX workbook."""
    headers = headers or {}
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Purchase Orders"
    sheet.append([headers.get(name, name) for name in CANONICAL_FIELDS])
    for row in rows:
        sheet.append([_as_text(row.get(name)) for name in CANONICAL_FIELDS])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def rows_to_json(rows: list[dict[str, Any]], wrap: bool = True) -> bytes:
    """Serialise rows as JSON, either wrapped in ``records`` or as a bare list."""
    payload = [{name: _as_text(row.get(name)) for name in CANONICAL_FIELDS} for row in rows]
    document: Any = {"records": payload} if wrap else payload
    return json.dumps(document, indent=2).encode("utf-8")


def _as_text(value: Any) -> Any:
    """Render a value the way a spreadsheet export would."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------
# Spend Analytics factories
# ---------------------------------------------------------------------------

SPEND_BASE_DATE = date(2025, 3, 10)

DEFAULT_SPEND_ROW: dict[str, Any] = {
    **DEFAULT_ROW,
    "po_number": "5500000001",
    "supplier_id": "0000200001",
    "supplier_name": "Nordwind Industrie GmbH",
    "material": "SPM-100000",
    "material_description": "Stainless bearing type 1",
    "material_group": "MG10",
    "contract_number": "4600000123",
    "order_date": SPEND_BASE_DATE - timedelta(days=5),
    "requested_delivery_date": SPEND_BASE_DATE + timedelta(days=14),
    "actual_delivery_date": SPEND_BASE_DATE + timedelta(days=15),
    "transaction_date": SPEND_BASE_DATE,
    "category": "Components",
    "subcategory": "Mechanical",
    "contract_status": "Contracted",
    "preferred_supplier_status": "Preferred",
    "baseline_price": 100.0,
    "current_price": 100.0,
    "payment_status": "Paid",
}


def make_spend_row(**overrides: Any) -> dict[str, Any]:
    """Build one canonical spend row on top of a healthy default.

    The default is contracted, preferred and priced exactly at its baseline, so
    a test only has to state the one thing it is exercising.
    """
    row = {**DEFAULT_SPEND_ROW, **overrides}
    if "total_value" not in overrides and row["quantity"] is not None and row["unit_price"] is not None:
        row["total_value"] = round(float(row["quantity"]) * float(row["unit_price"]), 2)
    if "current_price" not in overrides and "unit_price" in overrides:
        row["current_price"] = row["unit_price"]
    if "baseline_price" not in overrides and "unit_price" in overrides:
        row["baseline_price"] = row["unit_price"]
    return row


def make_spend_rows(count: int, **overrides: Any) -> list[dict[str, Any]]:
    """Build ``count`` spend rows with incrementing purchase order numbers."""
    rows = []
    for index in range(count):
        row = make_spend_row(**overrides)
        row["po_number"] = str(5500000001 + index)
        rows.append(row)
    return rows


def make_spend_frame(rows: list[dict[str, Any]], config: Any = None) -> "pd.DataFrame":
    """Run spend rows through the real normaliser to get a canonical frame."""
    from app.modules.spend.field_definitions import CANONICAL_FIELDS as SPEND_FIELDS
    from app.modules.spend.normalizer import normalize_spend_dataframe
    from app.modules.spend.thresholds import get_spend_config

    config = config or get_spend_config()
    raw = pd.DataFrame([{key: row.get(key) for key in SPEND_FIELDS} for row in rows])
    mapping = {name: name for name in SPEND_FIELDS}
    return normalize_spend_dataframe(raw, mapping, config).frame


def spend_rows_to_csv(
    rows: list[dict[str, Any]], headers: dict[str, str] | None = None
) -> bytes:
    """Serialise spend rows as CSV, optionally renaming the headers."""
    from app.modules.spend.field_definitions import CANONICAL_FIELDS as SPEND_FIELDS

    headers = headers or {}
    field_names = [headers.get(name, name) for name in SPEND_FIELDS]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=field_names, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({headers.get(n, n): _as_text(row.get(n)) for n in SPEND_FIELDS})
    return buffer.getvalue().encode("utf-8")


def spend_rows_to_xlsx(rows: list[dict[str, Any]]) -> bytes:
    """Serialise spend rows as an XLSX workbook."""
    from app.modules.spend.field_definitions import CANONICAL_FIELDS as SPEND_FIELDS

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Spend"
    sheet.append(list(SPEND_FIELDS))
    for row in rows:
        sheet.append([_as_text(row.get(name)) for name in SPEND_FIELDS])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
