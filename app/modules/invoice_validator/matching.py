"""The shared, pre-computed view of the three datasets handed to every rule.

Joining invoices to purchase orders and goods receipts is the heart of this
module. :class:`MatchContext` builds the join indexes once per validation and
exposes small, deterministic helpers so a rule never has to re-scan the data or
re-implement the key normalisation.

Join keys are normalised so that ``"00010"`` (SAP item) and ``"10"`` match, and
purchase-order numbers are compared as trimmed strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.modules.invoice_validator.normalizer import (
    NormalizedGoodsReceipt,
    NormalizedInvoice,
    NormalizedPoLine,
)
from app.modules.invoice_validator.thresholds import InvoiceValidatorConfig
from app.schemas.common import Severity


def number_key(value: Any) -> str | None:
    """Normalise a purchase-order number for joining (trimmed string)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def item_key(value: Any) -> str | None:
    """Normalise a PO item number for joining, tolerating SAP leading zeros."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    stripped = text.lstrip("0")
    return stripped or "0"


@dataclass
class LineAggregate:
    """Cumulative invoiced quantity/amount booked against one PO line key."""

    invoiced_quantity: float = 0.0
    invoiced_amount_base: float = 0.0
    invoice_count: int = 0


class MatchContext:
    """Indexed, pre-computed view of invoices, purchase orders and receipts."""

    def __init__(
        self,
        invoices: list[NormalizedInvoice],
        po_lines: list[NormalizedPoLine],
        goods_receipts: list[NormalizedGoodsReceipt],
        config: InvoiceValidatorConfig,
        *,
        has_po_dataset: bool,
        has_gr_dataset: bool,
        as_of_date: date,
    ) -> None:
        self.invoices = invoices
        self.po_lines = po_lines
        self.goods_receipts = goods_receipts
        self.config = config
        self.base_currency = config.base_currency
        self.has_po_dataset = has_po_dataset
        self.has_gr_dataset = has_gr_dataset
        self.as_of_date = as_of_date

        self._build_po_indexes()
        self._build_gr_indexes()
        self._build_invoice_aggregates()

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------
    def _build_po_indexes(self) -> None:
        self._po_by_key: dict[tuple[str, str | None], NormalizedPoLine] = {}
        self._po_by_number: dict[str, list[NormalizedPoLine]] = {}
        for line in self.po_lines:
            num = number_key(line.po_number)
            if num is None:
                continue
            self._po_by_key.setdefault((num, item_key(line.po_item)), line)
            self._po_by_number.setdefault(num, []).append(line)

    def _build_gr_indexes(self) -> None:
        self._gr_by_number: dict[str, list[NormalizedGoodsReceipt]] = {}
        for receipt in self.goods_receipts:
            num = number_key(receipt.po_number)
            if num is None:
                continue
            self._gr_by_number.setdefault(num, []).append(receipt)

    def _build_invoice_aggregates(self) -> None:
        self._line_aggregates: dict[tuple[str, str | None], LineAggregate] = {}
        for invoice in self.invoices:
            num = number_key(invoice.po_number)
            if num is None:
                continue
            key = (num, item_key(invoice.po_item))
            aggregate = self._line_aggregates.setdefault(key, LineAggregate())
            if invoice.quantity is not None:
                aggregate.invoiced_quantity += float(invoice.quantity)
            amount = invoice.subtotal_base if invoice.subtotal_base is not None else invoice.total_amount_base
            if amount is not None:
                aggregate.invoiced_amount_base += float(amount)
            aggregate.invoice_count += 1

    # ------------------------------------------------------------------
    # Purchase order lookups
    # ------------------------------------------------------------------
    def po_number_exists(self, po_number: str | None) -> bool:
        """Whether any PO line carries this purchase-order number."""
        num = number_key(po_number)
        return num is not None and num in self._po_by_number

    def po_line_for(self, invoice: NormalizedInvoice) -> NormalizedPoLine | None:
        """Return the PO line an invoice references, if it can be resolved.

        Matches on (number, item). When the invoice omits the item and the PO
        number has exactly one line, that single line is used.
        """
        num = number_key(invoice.po_number)
        if num is None:
            return None
        exact = self._po_by_key.get((num, item_key(invoice.po_item)))
        if exact is not None:
            return exact
        if invoice.po_item is None:
            lines = self._po_by_number.get(num, [])
            if len(lines) == 1:
                return lines[0]
        return None

    # ------------------------------------------------------------------
    # Goods receipt lookups
    # ------------------------------------------------------------------
    def goods_receipts_for(
        self, po_number: str | None, po_item: str | None
    ) -> list[NormalizedGoodsReceipt]:
        """Return receipts for a PO line (item-agnostic when the item is absent)."""
        num = number_key(po_number)
        if num is None:
            return []
        wanted_item = item_key(po_item)
        matches: list[NormalizedGoodsReceipt] = []
        for receipt in self._gr_by_number.get(num, []):
            receipt_item = item_key(receipt.po_item)
            if wanted_item is None or receipt_item is None or receipt_item == wanted_item:
                matches.append(receipt)
        return matches

    @staticmethod
    def received_quantity(receipts: list[NormalizedGoodsReceipt]) -> float | None:
        """Sum of received quantities across ``receipts`` (``None`` if unknown)."""
        values = [r.received_quantity for r in receipts if r.received_quantity is not None]
        return round(sum(values), 4) if values else None

    @staticmethod
    def accepted_quantity(receipts: list[NormalizedGoodsReceipt]) -> float | None:
        """Sum of accepted quantities across ``receipts`` (``None`` if unknown)."""
        values = [r.accepted_quantity for r in receipts if r.accepted_quantity is not None]
        return round(sum(values), 4) if values else None

    @staticmethod
    def earliest_receipt_date(receipts: list[NormalizedGoodsReceipt]) -> date | None:
        """Earliest receipt date across ``receipts``."""
        dates = [r.receipt_date for r in receipts if r.receipt_date is not None]
        return min(dates) if dates else None

    # ------------------------------------------------------------------
    # Invoice aggregates
    # ------------------------------------------------------------------
    def line_aggregate(self, po_number: str | None, po_item: str | None) -> LineAggregate:
        """Cumulative invoiced quantity/amount booked against a PO line key."""
        num = number_key(po_number)
        if num is None:
            return LineAggregate()
        return self._line_aggregates.get((num, item_key(po_item)), LineAggregate())

    # ------------------------------------------------------------------
    # Severity
    # ------------------------------------------------------------------
    def escalate_severity(self, base: Severity, exposure_base: float) -> Severity:
        """Raise ``base`` when the exposed value crosses a configured band."""
        escalation = self.config.severity_value_escalation
        if not escalation.enabled:
            return base
        if exposure_base >= escalation.critical_value_base:
            return max(base, Severity.CRITICAL, key=lambda s: s.rank)
        if exposure_base >= escalation.high_value_base:
            return max(base, Severity.HIGH, key=lambda s: s.rank)
        return base
