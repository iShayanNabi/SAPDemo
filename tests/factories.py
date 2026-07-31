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


# ---------------------------------------------------------------------------
# Supplier Recommendation factories
# ---------------------------------------------------------------------------

#: A healthy, well-rounded supplier. A test overrides only what it exercises.
DEFAULT_SUPPLIER: dict[str, Any] = {
    "supplier_id": "0000300001",
    "supplier_name": "Nordwind Industrie GmbH",
    "materials_supplied": ["MAT-1000"],
    "plants_served": ["1010"],
    "regions_served": ["EU"],
    "unit_price": 100.0,
    "currency": "EUR",
    "lead_time_days": 14,
    "available_capacity": 1000.0,
    "on_time_delivery_rate": 95.0,
    "quality_score": 90.0,
    "defect_rate": 1.5,
    "risk_score": 25.0,
    "esg_score": 80.0,
    "contract_status": "Active",
    "contract_expiration": date(2028, 1, 1),
    "payment_terms": "NT30",
    "historical_order_count": 40,
    "historical_spend": 400000.0,
}


def make_supplier(**overrides: Any):
    """Build one :class:`NormalizedSupplier` on top of a healthy default."""
    from app.modules.supplier_reco.normalizer import NormalizedSupplier
    from app.modules.supplier_reco.thresholds import get_supplier_reco_config

    data = {**DEFAULT_SUPPLIER, **overrides}
    config = get_supplier_reco_config()
    rate = config.conversion_rate(data["currency"])
    price = data["unit_price"]
    spend = data["historical_spend"]
    return NormalizedSupplier(
        row_number=overrides.get("row_number", 2),
        supplier_id=str(data["supplier_id"]),
        supplier_name=data["supplier_name"],
        materials_supplied=list(data["materials_supplied"]),
        plants_served=list(data["plants_served"]),
        regions_served=list(data["regions_served"]),
        unit_price=price,
        currency=data["currency"],
        unit_price_base=None if price is None else round(price * rate, 4),
        lead_time_days=data["lead_time_days"],
        available_capacity=data["available_capacity"],
        on_time_delivery_rate=data["on_time_delivery_rate"],
        quality_score=data["quality_score"],
        defect_rate=data["defect_rate"],
        risk_score=data["risk_score"],
        esg_score=data["esg_score"],
        contract_status=data["contract_status"],
        contract_expiration=data["contract_expiration"],
        payment_terms=data["payment_terms"],
        historical_order_count=data["historical_order_count"],
        historical_spend=spend,
        historical_spend_base=None if spend is None else round(spend * rate, 2),
    )


def make_suppliers(count: int, **overrides: Any) -> list[Any]:
    """Build ``count`` suppliers with incrementing supplier ids."""
    suppliers = []
    for index in range(count):
        data = dict(overrides)
        data.setdefault("supplier_id", f"{300001 + index:010d}")
        if "supplier_id" not in overrides:
            data["supplier_id"] = f"{300001 + index:010d}"
        suppliers.append(make_supplier(**data))
    return suppliers


def make_requirement(**overrides: Any):
    """Build a :class:`Requirement` with sensible defaults for the canonical material."""
    from app.modules.supplier_reco.requirement import Requirement

    defaults: dict[str, Any] = {
        "material": "MAT-1000",
        "quantity": 100.0,
        "plant": "1010",
        "preferred_region": "EU",
        "required_delivery_date": date(2026, 10, 1),
        "order_date": date(2026, 8, 1),
        "target_price": 120.0,
        "currency": "EUR",
        "risk_tolerance": "medium",
    }
    defaults.update(overrides)
    return Requirement(**defaults)


def supplier_rows_to_csv(rows: list[dict[str, Any]], headers: dict[str, str] | None = None) -> bytes:
    """Serialise supplier rows as CSV, optionally renaming the headers.

    List fields (materials/plants/regions) are joined with ``;``.
    """
    from app.modules.supplier_reco.field_definitions import CANONICAL_FIELDS as SUPPLIER_FIELDS

    headers = headers or {}
    field_names = [headers.get(name, name) for name in SUPPLIER_FIELDS]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=field_names, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {headers.get(name, name): _supplier_cell(row.get(name)) for name in SUPPLIER_FIELDS}
        )
    return buffer.getvalue().encode("utf-8")


def supplier_rows_to_xlsx(rows: list[dict[str, Any]]) -> bytes:
    """Serialise supplier rows as an XLSX workbook."""
    from app.modules.supplier_reco.field_definitions import CANONICAL_FIELDS as SUPPLIER_FIELDS

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Suppliers"
    sheet.append(list(SUPPLIER_FIELDS))
    for row in rows:
        sheet.append([_supplier_cell(row.get(name)) for name in SUPPLIER_FIELDS])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def supplier_row(**overrides: Any) -> dict[str, Any]:
    """Build a raw canonical supplier row dict (lists as Python lists) for file builders."""
    return {**DEFAULT_SUPPLIER, **overrides}


def _supplier_cell(value: Any) -> Any:
    """Render a supplier cell the way a file export would."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ";".join(str(item) for item in value)
    if isinstance(value, date):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------
# Invoice Validator factories
# ---------------------------------------------------------------------------
INVOICE_BASE_DATE = date(2026, 3, 20)
INVOICE_TAX_RATE = 0.19


def make_invoice(**overrides: Any):
    """Build one :class:`NormalizedInvoice` on top of a clean default.

    The default is a fully-matched EUR invoice (quantity 10 at 100), with the
    base-currency amounts derived just like the normaliser does, so a test only
    states the one field it exercises.
    """
    from app.modules.invoice_validator.normalizer import NormalizedInvoice
    from app.modules.invoice_validator.thresholds import get_invoice_validator_config

    config = get_invoice_validator_config()
    quantity = overrides.pop("quantity", 10.0)
    unit_price = overrides.pop("unit_price", 100.0)
    currency = overrides.pop("currency", "EUR")
    subtotal = overrides.pop("subtotal", round(quantity * unit_price, 2) if unit_price is not None else None)
    tax = overrides.pop("tax", round(subtotal * INVOICE_TAX_RATE, 2) if subtotal is not None else None)
    freight = overrides.pop("freight", 10.0)
    total = overrides.pop(
        "total_amount",
        round((subtotal or 0) + (tax or 0) + (freight or 0), 2) if subtotal is not None else None,
    )
    rate = config.conversion_rate(currency)
    data: dict[str, Any] = {
        "row_number": overrides.pop("row_number", 2),
        "invoice_number": overrides.pop("invoice_number", "INV-1"),
        "supplier_id": overrides.pop("supplier_id", "0000700001"),
        "supplier_name": overrides.pop("supplier_name", "Nordwind Industrie GmbH"),
        "po_number": overrides.pop("po_number", "4500000001"),
        "po_item": overrides.pop("po_item", "00010"),
        "invoice_date": overrides.pop("invoice_date", INVOICE_BASE_DATE),
        "posting_date": overrides.pop("posting_date", INVOICE_BASE_DATE + timedelta(days=1)),
        "quantity": quantity,
        "unit_price": unit_price,
        "subtotal": subtotal,
        "tax": tax,
        "freight": freight,
        "currency": currency,
        "total_amount": total,
        "payment_terms": overrides.pop("payment_terms", "NT30"),
        "gr_reference": overrides.pop("gr_reference", "5000000001"),
        "unit_price_base": None if unit_price is None else round(unit_price * rate, 4),
        "subtotal_base": None if subtotal is None else round(subtotal * rate, 2),
        "tax_base": None if tax is None else round(tax * rate, 2),
        "freight_base": None if freight is None else round(freight * rate, 2),
        "total_amount_base": None if total is None else round(total * rate, 2),
    }
    data.update(overrides)
    return NormalizedInvoice(**data)


def make_po_line(**overrides: Any):
    """Build one :class:`NormalizedPoLine` matching the default invoice."""
    from app.modules.invoice_validator.normalizer import NormalizedPoLine
    from app.modules.invoice_validator.thresholds import get_invoice_validator_config

    config = get_invoice_validator_config()
    quantity = overrides.pop("quantity", 10.0)
    unit_price = overrides.pop("unit_price", 100.0)
    currency = overrides.pop("currency", "EUR")
    rate = config.conversion_rate(currency)
    data: dict[str, Any] = {
        "row_number": overrides.pop("row_number", 2),
        "po_number": overrides.pop("po_number", "4500000001"),
        "po_item": overrides.pop("po_item", "00010"),
        "supplier_id": overrides.pop("supplier_id", "0000700001"),
        "supplier_name": overrides.pop("supplier_name", "Nordwind Industrie GmbH"),
        "material": overrides.pop("material", "MAT-100010"),
        "material_description": overrides.pop("material_description", "Stainless bearing type A"),
        "quantity": quantity,
        "unit_price": unit_price,
        "currency": currency,
        "payment_terms": overrides.pop("payment_terms", "NT30"),
        "order_date": overrides.pop("order_date", INVOICE_BASE_DATE - timedelta(days=19)),
        "po_status": overrides.pop("po_status", "Open"),
        "unit_price_base": None if unit_price is None else round(unit_price * rate, 4),
        "line_value_base": None
        if unit_price is None or quantity is None
        else round(unit_price * quantity * rate, 2),
    }
    data.update(overrides)
    return NormalizedPoLine(**data)


def make_goods_receipt(**overrides: Any):
    """Build one :class:`NormalizedGoodsReceipt` matching the default invoice."""
    from app.modules.invoice_validator.normalizer import NormalizedGoodsReceipt

    received = overrides.pop("received_quantity", 10.0)
    rejected = overrides.pop("rejected_quantity", 0.0)
    accepted = overrides.pop(
        "accepted_quantity",
        round(received - rejected, 4) if received is not None else None,
    )
    data: dict[str, Any] = {
        "row_number": overrides.pop("row_number", 2),
        "gr_number": overrides.pop("gr_number", "5000000001"),
        "po_number": overrides.pop("po_number", "4500000001"),
        "po_item": overrides.pop("po_item", "00010"),
        "receipt_date": overrides.pop("receipt_date", INVOICE_BASE_DATE - timedelta(days=9)),
        "received_quantity": received,
        "accepted_quantity": accepted,
        "rejected_quantity": rejected,
    }
    data.update(overrides)
    return NormalizedGoodsReceipt(**data)


def run_invoice_validation(
    invoices: list[Any],
    po_lines: list[Any] | None = None,
    goods_receipts: list[Any] | None = None,
    *,
    as_of_date: date | None = None,
    config: Any = None,
    enabled_rules: list[str] | None = None,
):
    """Run the invoice engine over the given records (defaults to a match date)."""
    from app.modules.invoice_validator.engine import InvoiceValidationEngine
    from app.modules.invoice_validator.thresholds import get_invoice_validator_config

    config = config or get_invoice_validator_config()
    return InvoiceValidationEngine(config).run(
        invoices,
        po_lines or [],
        goods_receipts or [],
        as_of_date=as_of_date or date(2026, 6, 30),
        enabled_rules=enabled_rules,
    )


def invoice_rule_ids(result: Any) -> set[str]:
    """The set of rule ids that fired in a validation result."""
    return {exception.rule_id for exception in result.exceptions}


# File builders for the invoice API tests --------------------------------
INVOICE_TECHNICAL_HEADERS = {
    "invoice_number": "BELNR", "supplier_id": "LIFNR", "supplier_name": "NAME1",
    "po_number": "EBELN", "po_item": "EBELP", "invoice_date": "BLDAT", "posting_date": "BUDAT",
    "quantity": "MENGE", "unit_price": "NETPR", "subtotal": "WRBTR", "tax": "MWSTS",
    "freight": "FREIGHT", "currency": "WAERS", "total_amount": "RMWWR", "payment_terms": "ZTERM",
    "gr_reference": "LFBNR",
}


def invoice_rows_to_csv(rows: list[dict[str, Any]], dataset: str, headers: dict[str, str] | None = None) -> bytes:
    """Serialise canonical rows for one invoice dataset as CSV."""
    from app.modules.invoice_validator.field_definitions import (
        GOODS_RECEIPT_CANONICAL_FIELDS,
        INVOICE_CANONICAL_FIELDS,
    )

    if dataset == "invoices":
        fields = list(INVOICE_CANONICAL_FIELDS)
    elif dataset == "goods_receipts":
        fields = list(GOODS_RECEIPT_CANONICAL_FIELDS)
    else:  # purchase_orders
        fields = [
            "po_number", "po_item", "supplier_id", "supplier_name", "material",
            "quantity", "unit_price", "currency", "payment_terms", "order_date", "po_status",
        ]
    headers = headers or {}
    field_names = [headers.get(name, name) for name in fields]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=field_names, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({headers.get(name, name): _as_text(row.get(name)) for name in fields})
    return buffer.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Module 5 - Supplier Risk Copilot
# ---------------------------------------------------------------------------

RISK_AS_OF = date(2026, 7, 1)

#: A well-behaved supplier: every metric present, every category low risk.
DEFAULT_RISK_PROFILE: dict[str, Any] = {
    "supplier_id": "0000300001",
    "supplier_name": "Bluepeak Value Supply Ltd",
    "country": "DE",
    "spend_category": "Components",
    "materials_supplied": ["MAT-1000"],
    "plants_served": ["1010"],
    "regions_served": ["EU", "NA"],
    "currency": "EUR",
    "historical_spend": 500000.0,
    "historical_order_count": 40,
    "open_purchase_order_count": 4,
    "active_contract_count": 1,
    "contract_number": "4600000001",
    "contract_status": "Active",
    "contract_expiration": date(2027, 6, 30),
    "delivery_count": 100,
    "late_delivery_count": 4,
    "average_delay_days": 1.0,
    "on_time_delivery_rate": 96.0,
    "quality_score": 94.0,
    "defect_rate": 1.0,
    "quality_incident_count": 1,
    "invoice_count": 100,
    "invoice_exception_count": 2,
    "disputed_invoice_count": 0,
    "credit_score": 82.0,
    "days_payable_outstanding": 35.0,
    "payment_default_count": 0,
    "financial_distress_flag": False,
    "category_spend_share": 15.0,
    "single_source_material_count": 0,
    "alternative_supplier_count": 3,
    "compliance_finding_count": 0,
    "certification_status": "Valid",
    "audit_status": "Passed",
    "last_audit_date": date(2026, 2, 1),
    "esg_score": 78.0,
    "lead_time_days": 15,
    "lead_time_variability_days": 2.0,
    "capacity_utilization": 65.0,
}


def make_risk_profile(**overrides: Any):
    """Build one :class:`NormalizedSupplierProfile` on top of a healthy default."""
    from app.modules.supplier_risk.normalizer import NormalizedSupplierProfile
    from app.modules.supplier_risk.thresholds import get_supplier_risk_config

    data = {**DEFAULT_RISK_PROFILE, **overrides}
    config = get_supplier_risk_config()
    spend = data.get("historical_spend")
    rate = config.conversion_rate(data.get("currency"))

    return NormalizedSupplierProfile(
        row_number=overrides.get("row_number", 2),
        supplier_id=str(data["supplier_id"]),
        historical_spend_base=None if spend is None else round(float(spend) * rate, 2),
        **{
            key: value
            for key, value in data.items()
            if key not in {"supplier_id", "row_number"}
        },
    )


def make_risk_profiles(count: int, **overrides: Any) -> list[Any]:
    """Build ``count`` risk profiles with incrementing supplier ids."""
    profiles = []
    for index in range(count):
        data = dict(overrides)
        if "supplier_id" not in overrides:
            data["supplier_id"] = f"{300001 + index:010d}"
        profiles.append(make_risk_profile(**data))
    return profiles


def make_risk_event(**overrides: Any):
    """Build one :class:`NormalizedRiskEvent` with sensible defaults."""
    from app.modules.supplier_risk.normalizer import NormalizedRiskEvent

    defaults: dict[str, Any] = {
        "row_number": 2,
        "event_id": "EVT-0001",
        "supplier_id": "0000300001",
        "event_type": "late_delivery",
        "event_date": RISK_AS_OF - timedelta(days=30),
        "reference": "4500000001",
        "severity": "medium",
        "description": "Delivery arrived after the confirmed date",
        "amount": None,
        "currency": "EUR",
        "amount_base": None,
    }
    return NormalizedRiskEvent(**{**defaults, **overrides})


def run_risk_assessment_for(
    profiles: list[Any],
    events: list[Any] | None = None,
    *,
    as_of: date | None = None,
    weights: Any = None,
    config: Any = None,
):
    """Run the real risk engine over hand-built records."""
    from app.modules.supplier_risk.engine import run_risk_assessment
    from app.modules.supplier_risk.thresholds import get_supplier_risk_config

    config = config or get_supplier_risk_config()
    return run_risk_assessment(
        profiles,
        events or [],
        weights or config.default_weights,
        config,
        as_of or RISK_AS_OF,
    )


def risk_profile_rows_to_csv(
    rows: list[dict[str, Any]], headers: dict[str, str] | None = None
) -> bytes:
    """Serialise supplier risk profile rows as CSV, optionally renaming headers."""
    from app.modules.supplier_risk.field_definitions import CANONICAL_FIELDS as RISK_FIELDS

    headers = headers or {}
    field_names = [headers.get(name, name) for name in RISK_FIELDS]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=field_names, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {headers.get(name, name): _supplier_cell(row.get(name)) for name in RISK_FIELDS}
        )
    return buffer.getvalue().encode("utf-8")


def risk_event_rows_to_csv(
    rows: list[dict[str, Any]], headers: dict[str, str] | None = None
) -> bytes:
    """Serialise risk event rows as CSV."""
    from app.modules.supplier_risk.field_definitions import EVENT_CANONICAL_FIELDS

    headers = headers or {}
    field_names = [headers.get(name, name) for name in EVENT_CANONICAL_FIELDS]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=field_names, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                headers.get(name, name): _supplier_cell(row.get(name))
                for name in EVENT_CANONICAL_FIELDS
            }
        )
    return buffer.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Module 6 - Contract Assistant
# ---------------------------------------------------------------------------

CONTRACT_AS_OF = date(2026, 7, 1)

#: A small but complete contract. A test overrides only the clause it exercises
#: by passing ``extra`` text or by replacing a numbered section.
CONTRACT_TEMPLATE = """MASTER SERVICES AGREEMENT

This Master Services Agreement is entered into between Nordwind Industrie GmbH (the "Customer")
and Kestrel Field Maintenance BV (the "Supplier").

1. TERM
This Agreement is effective as of 1 January 2026 and shall remain in force until 31 December 2027.

2. TERMINATION
Either party may terminate this Agreement for convenience on 90 days written notice.

3. PAYMENT TERMS
The Customer shall pay all undisputed invoices net 30 days from the date of invoice.

4. PRICING
Prices are as set out in the rate card in Schedule 1 and are exclusive of VAT.

5. LIMITATION OF LIABILITY
The total aggregate liability of each party shall not exceed EUR 500,000.

6. INDEMNIFICATION
Each party shall indemnify and hold harmless the other party against third party claims.

7. CONFIDENTIALITY
Each party shall keep the other party's Confidential Information confidential.

8. DATA PROTECTION
The Supplier processes personal data as data processor under the General Data Protection
Regulation, in accordance with the data processing agreement in Schedule 3.

9. GOVERNING LAW
This Agreement is governed by and construed in accordance with the laws of Germany.

10. DISPUTE RESOLUTION
Any dispute shall be finally settled by arbitration in Hamburg.
"""


def contract_text(*extra_sections: str) -> str:
    """Return the template contract with extra numbered sections appended."""
    body = CONTRACT_TEMPLATE
    for index, section in enumerate(extra_sections, start=11):
        body += f"\n{index}. {section.strip()}\n"
    return body


def contract_txt_bytes(text: str | None = None) -> bytes:
    """Serialise a contract as a UTF-8 .txt upload."""
    return (text if text is not None else CONTRACT_TEMPLATE).encode("utf-8")


def contract_pdf_bytes(text: str | None = None, *, title: str = "Contract") -> bytes:
    """Serialise a contract as a real, text-based PDF."""
    from app.services.documents.pdf_writer import build_text_pdf

    return build_text_pdf(text if text is not None else CONTRACT_TEMPLATE, title=title).content


def contract_docx_bytes(text: str | None = None) -> bytes:
    """Serialise a contract as a .docx with real heading styles."""
    import docx

    body = text if text is not None else CONTRACT_TEMPLATE
    document = docx.Document()
    for index, line in enumerate(body.split("\n")):
        stripped = line.strip()
        if not stripped:
            continue
        if index == 0:
            document.add_heading(stripped, level=1)
        elif _looks_like_contract_heading(stripped):
            document.add_heading(stripped, level=2)
        else:
            document.add_paragraph(stripped)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _looks_like_contract_heading(line: str) -> bool:
    """``<number>. ALL CAPS`` is a clause heading in the test contracts."""
    number, _, rest = line.partition(".")
    if not number.strip().isdigit():
        return False
    title = rest.strip()
    return bool(title) and title == title.upper() and len(title.split()) <= 8


def scanned_pdf_bytes(page_count: int = 2) -> bytes:
    """A structurally valid PDF whose pages carry no text at all.

    This is what a scan looks like to ``pypdf``: real pages, no text operators.
    It is how the "needs OCR" path is exercised without shipping an image.
    """
    pages = []
    objects = []
    for index in range(page_count):
        page_id = 4 + index * 2
        stream_id = page_id + 1
        pages.append(page_id)
        objects.append(
            (
                page_id,
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << >> /Contents {stream_id} 0 R >>"
                ).encode("ascii"),
            )
        )
        objects.append((stream_id, b"<< /Length 0 >>\nstream\n\nendstream"))

    kids = " ".join(f"{page_id} 0 R" for page_id in pages)
    objects = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, f"<< /Type /Pages /Count {len(pages)} /Kids [{kids}] >>".encode("ascii")),
        (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        *objects,
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for object_id, payload in objects:
        offsets[object_id] = len(out)
        out += f"{object_id} 0 obj\n".encode("ascii") + payload + b"\nendobj\n"

    xref_offset = len(out)
    highest = max(offsets)
    out += f"xref\n0 {highest + 1}\n".encode("ascii") + b"0000000000 65535 f \n"
    for object_id in range(1, highest + 1):
        out += f"{offsets[object_id]:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {highest + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


def analyze_contract_text(
    text: str | None = None, *, as_of: date | None = None, config: Any = None, fmt: str = "txt"
):
    """Run the real pipeline over a contract string in the chosen format."""
    from app.modules.contract_assistant.engine import analyze_contract
    from app.modules.contract_assistant.thresholds import get_contract_config
    from app.services.documents.factory import extract_document

    builders = {
        "txt": (contract_txt_bytes, "contract.txt"),
        "pdf": (contract_pdf_bytes, "contract.pdf"),
        "docx": (contract_docx_bytes, "contract.docx"),
    }
    builder, filename = builders[fmt]
    extraction = extract_document(builder(text), filename)
    return analyze_contract(
        extraction, config or get_contract_config(), as_of_date=as_of or CONTRACT_AS_OF
    )


def contract_rule_ids(result: Any) -> set[str]:
    """The set of rule ids that fired in a contract analysis."""
    return {finding.rule_id for finding in result.risks}
