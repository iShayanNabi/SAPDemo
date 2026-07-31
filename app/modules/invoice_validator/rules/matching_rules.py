"""Cross-document matching rules.

* **IV-R003** missing purchase order - the invoice has no PO reference, or names
  a PO / PO line that is not present in the purchase order file.
* **IV-R004** missing goods receipt - no goods receipt exists for the invoiced
  PO line (GR-based invoice verification).
* **IV-R012** three-way-match exception - the invoiced quantity exceeds the
  quantity accepted at goods receipt.
* **IV-R017** closed purchase-order invoicing - the invoice is booked against a
  PO line flagged closed / delivery complete.
"""

from __future__ import annotations

from app.modules.invoice_validator.matching import MatchContext
from app.modules.invoice_validator.rules.base import BaseInvoiceRule, ExceptionFinding


class MissingPurchaseOrderRule(BaseInvoiceRule):
    """IV-R003: the invoice cannot be matched to a purchase order."""

    rule_id = "IV-R003"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            exposure = float(invoice.total_amount_base or 0.0)
            if not invoice.po_number:
                reason = "the invoice carries no purchase order reference"
                actual = "no PO reference"
            elif not context.po_number_exists(invoice.po_number):
                reason = f"purchase order {invoice.po_number} is not in the purchase order file"
                actual = f"PO {invoice.po_number} not found"
            elif context.po_line_for(invoice) is None:
                reason = (
                    f"purchase order {invoice.po_number} exists but item "
                    f"{invoice.po_item or '(none)'} could not be matched"
                )
                actual = f"PO {invoice.po_number} item {invoice.po_item or '(none)'} not found"
            else:
                continue
            findings.append(
                self.make_exception(
                    exception_type="missing_purchase_order",
                    severity=context.escalate_severity(self.base_severity, exposure),
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    currency=context.base_currency,
                    expected_value="a matching purchase order line",
                    actual_value=actual,
                    difference=f"{exposure:,.2f} {context.base_currency} unmatched",
                    difference_amount=exposure,
                    explanation=(
                        f"Invoice {invoice.invoice_number} cannot be three-way matched because "
                        f"{reason}. An unreferenced invoice should not be paid without a PO."
                    ),
                    evidence={
                        "invoice_po_number": invoice.po_number,
                        "invoice_po_item": invoice.po_item,
                        "amount_base": round(exposure, 2),
                        "base_currency": context.base_currency,
                    },
                )
            )
        return findings


class MissingGoodsReceiptRule(BaseInvoiceRule):
    """IV-R004: no goods receipt exists for the invoiced PO line."""

    rule_id = "IV-R004"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            if not invoice.po_number:
                continue
            # If a PO dataset is loaded, only assess invoices whose PO exists.
            if context.has_po_dataset and not context.po_number_exists(invoice.po_number):
                continue
            receipts = context.goods_receipts_for(invoice.po_number, invoice.po_item)
            if receipts:
                continue
            exposure = float(invoice.subtotal_base or invoice.total_amount_base or 0.0)
            findings.append(
                self.make_exception(
                    exception_type="missing_goods_receipt",
                    severity=context.escalate_severity(self.base_severity, exposure),
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    currency=context.base_currency,
                    expected_value="a posted goods receipt for the PO line",
                    actual_value="no goods receipt found",
                    difference=f"{exposure:,.2f} {context.base_currency} invoiced without a receipt",
                    difference_amount=exposure,
                    explanation=(
                        f"Invoice {invoice.invoice_number} is billed against purchase order "
                        f"{invoice.po_number} item {invoice.po_item or '(none)'}, but no goods "
                        f"receipt was found for that line. Confirm delivery before payment."
                    ),
                    evidence={
                        "invoice_po_number": invoice.po_number,
                        "invoice_po_item": invoice.po_item,
                        "gr_reference_on_invoice": invoice.gr_reference,
                        "amount_base": round(exposure, 2),
                        "base_currency": context.base_currency,
                    },
                )
            )
        return findings


class ThreeWayMatchRule(BaseInvoiceRule):
    """IV-R012: invoiced quantity exceeds the accepted goods-receipt quantity."""

    rule_id = "IV-R012"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        quantity_tol = context.config.tolerances.quantity
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            if invoice.quantity is None:
                continue
            receipts = context.goods_receipts_for(invoice.po_number, invoice.po_item)
            if not receipts:
                continue
            accepted = context.accepted_quantity(receipts)
            if accepted is None:
                continue
            over = float(invoice.quantity) - float(accepted)
            if over <= 0 or not quantity_tol.exceeds(accepted, invoice.quantity):
                continue
            unit_price_base = invoice.unit_price_base
            po_line = context.po_line_for(invoice)
            if unit_price_base is None and po_line is not None:
                unit_price_base = po_line.unit_price_base
            exposure = round(over * float(unit_price_base), 2) if unit_price_base is not None else 0.0
            gr_number = next((r.gr_number for r in receipts if r.gr_number), None)
            findings.append(
                self.make_exception(
                    exception_type="three_way_match_exception",
                    severity=context.escalate_severity(self.base_severity, exposure),
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    gr_number=gr_number,
                    currency=context.base_currency,
                    expected_value=f"{accepted:g} accepted",
                    actual_value=f"{invoice.quantity:g} invoiced",
                    difference=f"{over:g} over the accepted quantity",
                    difference_amount=exposure,
                    explanation=(
                        f"Invoice {invoice.invoice_number} bills {invoice.quantity:g} units for PO "
                        f"{invoice.po_number} item {invoice.po_item or '(none)'}, but only "
                        f"{accepted:g} units were received and accepted. Paying the difference means "
                        f"paying for goods that were not accepted."
                    ),
                    evidence={
                        "invoiced_quantity": float(invoice.quantity),
                        "accepted_quantity": float(accepted),
                        "received_quantity": context.received_quantity(receipts),
                        "over_quantity": round(over, 4),
                        "unit_price_base": unit_price_base,
                        "base_currency": context.base_currency,
                    },
                )
            )
        return findings


class ClosedPurchaseOrderInvoicingRule(BaseInvoiceRule):
    """IV-R017: invoicing against a closed / delivery-complete PO line."""

    rule_id = "IV-R017"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            po_line = context.po_line_for(invoice)
            if po_line is None or not context.config.is_closed_status(po_line.po_status):
                continue
            exposure = float(invoice.total_amount_base or 0.0)
            findings.append(
                self.make_exception(
                    exception_type="closed_po_invoicing",
                    severity=context.escalate_severity(self.base_severity, exposure),
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    currency=context.base_currency,
                    expected_value="an open purchase order line",
                    actual_value=f"PO status '{po_line.po_status}'",
                    difference=f"{exposure:,.2f} {context.base_currency} billed after closure",
                    difference_amount=exposure,
                    explanation=(
                        f"Invoice {invoice.invoice_number} is booked against purchase order "
                        f"{invoice.po_number} item {invoice.po_item or '(none)'}, which is flagged "
                        f"'{po_line.po_status}'. A further invoice on a closed line needs investigation."
                    ),
                    evidence={
                        "po_status": po_line.po_status,
                        "amount_base": round(exposure, 2),
                        "base_currency": context.base_currency,
                    },
                )
            )
        return findings
