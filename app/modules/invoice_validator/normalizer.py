"""Turn the three raw uploaded files into canonical, typed records.

One normaliser per dataset (invoices, purchase orders, goods receipts). Each one
reuses the shared type-coercion pass, records unreadable cells as data-quality
issues rather than raising, and derives the base-currency amounts the rules
compare across currencies.

Nothing here decides whether an invoice is *valid* - that is the job of the
rules. This layer only decides whether the data is *usable*.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.modules.invoice_validator.field_definitions import (
    GOODS_RECEIPT_CANONICAL_FIELDS,
    GOODS_RECEIPT_REGISTRY,
    INVOICE_CANONICAL_FIELDS,
    INVOICE_REGISTRY,
    PO_CANONICAL_FIELDS,
    PO_REGISTRY,
)
from app.modules.invoice_validator.thresholds import InvoiceValidatorConfig
from app.services.tabular.field_registry import FieldRegistry
from app.services.tabular.parsing import (
    DataQualityIssue,
    build_canonical_frame,
    check_required_completeness,
    coerce_types,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Canonical records
# ---------------------------------------------------------------------------
@dataclass
class NormalizedInvoice:
    """One canonical, parsed invoice line."""

    row_number: int
    invoice_number: str
    supplier_id: str | None = None
    supplier_name: str | None = None
    po_number: str | None = None
    po_item: str | None = None
    invoice_date: date | None = None
    posting_date: date | None = None
    quantity: float | None = None
    unit_price: float | None = None
    subtotal: float | None = None
    tax: float | None = None
    freight: float | None = None
    currency: str | None = None
    total_amount: float | None = None
    payment_terms: str | None = None
    gr_reference: str | None = None
    # derived, base currency
    unit_price_base: float | None = None
    subtotal_base: float | None = None
    tax_base: float | None = None
    freight_base: float | None = None
    total_amount_base: float | None = None

    def to_record(self) -> dict[str, Any]:
        """A JSON/DB-safe dictionary of this invoice line."""
        return {
            "row_number": self.row_number,
            "invoice_number": self.invoice_number,
            "supplier_id": self.supplier_id,
            "supplier_name": self.supplier_name,
            "po_number": self.po_number,
            "po_item": self.po_item,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "posting_date": self.posting_date.isoformat() if self.posting_date else None,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "subtotal": self.subtotal,
            "tax": self.tax,
            "freight": self.freight,
            "currency": self.currency,
            "total_amount": self.total_amount,
            "payment_terms": self.payment_terms,
            "gr_reference": self.gr_reference,
            "unit_price_base": self.unit_price_base,
            "subtotal_base": self.subtotal_base,
            "tax_base": self.tax_base,
            "freight_base": self.freight_base,
            "total_amount_base": self.total_amount_base,
        }


@dataclass
class NormalizedPoLine:
    """One canonical purchase order line, joined against invoices and receipts."""

    row_number: int
    po_number: str
    po_item: str | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None
    material: str | None = None
    material_description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    currency: str | None = None
    payment_terms: str | None = None
    order_date: date | None = None
    po_status: str | None = None
    unit_price_base: float | None = None
    line_value_base: float | None = None


@dataclass
class NormalizedGoodsReceipt:
    """One canonical goods-receipt line."""

    row_number: int
    gr_number: str | None = None
    po_number: str | None = None
    po_item: str | None = None
    receipt_date: date | None = None
    received_quantity: float | None = None
    accepted_quantity: float | None = None
    rejected_quantity: float | None = None


@dataclass
class NormalizedDataset:
    """A normalised dataset plus how it was mapped and any data-quality issues."""

    records: list[Any]
    issues: list[DataQualityIssue]
    applied_mapping: dict[str, str]
    unmapped_columns: list[str]
    present_fields: list[str]
    missing_fields: list[str]

    @property
    def count(self) -> int:
        return len(self.records)

    def issues_as_dicts(self) -> list[dict[str, Any]]:
        return [issue.to_dict() for issue in self.issues]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _cell(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def _float(value: Any) -> float | None:
    value = _cell(value)
    return None if value is None else float(value)


def _int_str(value: Any) -> str | None:
    value = _cell(value)
    return None if value is None else str(value)


def _as_date(value: Any) -> date | None:
    value = _cell(value)
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.date()
    return None


def _prepare_frame(
    raw: pd.DataFrame, mapping: dict[str, str], registry: FieldRegistry
) -> tuple[pd.DataFrame, list[DataQualityIssue]]:
    """Build the canonical, type-coerced frame and collect data-quality issues."""
    missing_required = [f for f in registry.required if f not in set(mapping.values())]
    if missing_required:
        raise ValidationError(
            "The column mapping is missing required fields.",
            details={"missing_required_fields": missing_required},
        )
    frame = build_canonical_frame(raw, mapping, registry)
    issues: list[DataQualityIssue] = []
    frame = coerce_types(frame, registry, issues)
    check_required_completeness(frame, registry, issues)
    return frame, issues


def _dataset_meta(
    raw: pd.DataFrame, mapping: dict[str, str], canonical_fields: tuple[str, ...]
) -> tuple[list[str], list[str], list[str]]:
    present_fields = sorted(set(mapping.values()))
    missing_fields = [f for f in canonical_fields if f not in present_fields]
    unmapped_columns = [c for c in raw.columns if c not in mapping]
    return present_fields, missing_fields, unmapped_columns


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
def normalize_invoice_dataframe(
    raw: pd.DataFrame, mapping: dict[str, str], config: InvoiceValidatorConfig
) -> NormalizedDataset:
    """Apply ``mapping`` to ``raw`` and produce canonical invoice records."""
    if raw.empty:
        raise ValidationError("The invoice file contains no rows to validate.")
    frame, issues = _prepare_frame(raw, mapping, INVOICE_REGISTRY)

    records: list[NormalizedInvoice] = []
    for record in frame.to_dict(orient="records"):
        invoice_number = _cell(record.get("invoice_number"))
        if invoice_number is None:
            continue  # reported by check_required_completeness
        currency = _cell(record.get("currency"))
        rate = config.conversion_rate(currency)
        unit_price = _float(record.get("unit_price"))
        subtotal = _float(record.get("subtotal"))
        tax = _float(record.get("tax"))
        freight = _float(record.get("freight"))
        total_amount = _float(record.get("total_amount"))
        records.append(
            NormalizedInvoice(
                row_number=int(record.get("row_number") or 0),
                invoice_number=str(invoice_number),
                supplier_id=_int_str(record.get("supplier_id")),
                supplier_name=_cell(record.get("supplier_name")),
                po_number=_int_str(record.get("po_number")),
                po_item=_int_str(record.get("po_item")),
                invoice_date=_as_date(record.get("invoice_date")),
                posting_date=_as_date(record.get("posting_date")),
                quantity=_float(record.get("quantity")),
                unit_price=unit_price,
                subtotal=subtotal,
                tax=tax,
                freight=freight,
                currency=currency,
                total_amount=total_amount,
                payment_terms=_int_str(record.get("payment_terms")),
                gr_reference=_int_str(record.get("gr_reference")),
                unit_price_base=None if unit_price is None else round(unit_price * rate, 4),
                subtotal_base=None if subtotal is None else round(subtotal * rate, 2),
                tax_base=None if tax is None else round(tax * rate, 2),
                freight_base=None if freight is None else round(freight * rate, 2),
                total_amount_base=None if total_amount is None else round(total_amount * rate, 2),
            )
        )

    if not records:
        raise ValidationError("No usable invoice rows were found (every row lacked an invoice number).")

    present, missing, unmapped = _dataset_meta(raw, mapping, INVOICE_CANONICAL_FIELDS)
    logger.info("Normalised %d invoices | %d data quality issues", len(records), len(issues))
    return NormalizedDataset(records, issues, dict(mapping), unmapped, present, missing)


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------
def normalize_po_dataframe(
    raw: pd.DataFrame, mapping: dict[str, str], config: InvoiceValidatorConfig
) -> NormalizedDataset:
    """Apply ``mapping`` to ``raw`` and produce canonical purchase order lines."""
    if raw.empty:
        raise ValidationError("The purchase order file contains no rows.")
    frame, issues = _prepare_frame(raw, mapping, PO_REGISTRY)

    records: list[NormalizedPoLine] = []
    for record in frame.to_dict(orient="records"):
        po_number = _cell(record.get("po_number"))
        if po_number is None:
            continue
        currency = _cell(record.get("currency"))
        rate = config.conversion_rate(currency)
        unit_price = _float(record.get("unit_price"))
        quantity = _float(record.get("quantity"))
        total_value = _float(record.get("total_value"))
        # line value: use supplied total when present, otherwise quantity x price.
        if total_value is not None:
            line_value_base = round(total_value * rate, 2)
        elif unit_price is not None and quantity is not None:
            line_value_base = round(unit_price * quantity * rate, 2)
        else:
            line_value_base = None
        records.append(
            NormalizedPoLine(
                row_number=int(record.get("row_number") or 0),
                po_number=str(po_number),
                po_item=_int_str(record.get("po_item")),
                supplier_id=_int_str(record.get("supplier_id")),
                supplier_name=_cell(record.get("supplier_name")),
                material=_int_str(record.get("material")),
                material_description=_cell(record.get("material_description")),
                quantity=quantity,
                unit_price=unit_price,
                currency=currency,
                payment_terms=_int_str(record.get("payment_terms")),
                order_date=_as_date(record.get("order_date")),
                po_status=_cell(record.get("po_status")),
                unit_price_base=None if unit_price is None else round(unit_price * rate, 4),
                line_value_base=line_value_base,
            )
        )

    present, missing, unmapped = _dataset_meta(raw, mapping, PO_CANONICAL_FIELDS)
    logger.info("Normalised %d purchase order lines | %d data quality issues", len(records), len(issues))
    return NormalizedDataset(records, issues, dict(mapping), unmapped, present, missing)


# ---------------------------------------------------------------------------
# Goods receipts
# ---------------------------------------------------------------------------
def normalize_goods_receipt_dataframe(
    raw: pd.DataFrame, mapping: dict[str, str], config: InvoiceValidatorConfig
) -> NormalizedDataset:
    """Apply ``mapping`` to ``raw`` and produce canonical goods-receipt lines."""
    if raw.empty:
        raise ValidationError("The goods receipt file contains no rows.")
    frame, issues = _prepare_frame(raw, mapping, GOODS_RECEIPT_REGISTRY)

    records: list[NormalizedGoodsReceipt] = []
    for record in frame.to_dict(orient="records"):
        po_number = _cell(record.get("po_number"))
        if po_number is None:
            continue
        received = _float(record.get("received_quantity"))
        accepted = _float(record.get("accepted_quantity"))
        rejected = _float(record.get("rejected_quantity"))
        # Derive accepted when only received/rejected are given, and vice versa.
        if accepted is None and received is not None:
            accepted = round(received - (rejected or 0.0), 4)
        if rejected is None and received is not None and accepted is not None:
            rejected = round(received - accepted, 4)
        records.append(
            NormalizedGoodsReceipt(
                row_number=int(record.get("row_number") or 0),
                gr_number=_int_str(record.get("gr_number")),
                po_number=str(po_number),
                po_item=_int_str(record.get("po_item")),
                receipt_date=_as_date(record.get("receipt_date")),
                received_quantity=received,
                accepted_quantity=accepted,
                rejected_quantity=rejected,
            )
        )

    present, missing, unmapped = _dataset_meta(raw, mapping, GOODS_RECEIPT_CANONICAL_FIELDS)
    logger.info("Normalised %d goods receipts | %d data quality issues", len(records), len(issues))
    return NormalizedDataset(records, issues, dict(mapping), unmapped, present, missing)
