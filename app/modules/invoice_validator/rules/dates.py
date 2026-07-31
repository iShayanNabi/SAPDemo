"""Date-plausibility rules.

* **IV-R014** invoice dated before the purchase order.
* **IV-R015** invoice dated before the goods receipt.
* **IV-R016** future invoice date (after the validation reference date).
"""

from __future__ import annotations

from datetime import timedelta

from app.modules.invoice_validator.matching import MatchContext
from app.modules.invoice_validator.rules.base import BaseInvoiceRule, ExceptionFinding


class InvoiceBeforePurchaseOrderRule(BaseInvoiceRule):
    """IV-R014: the invoice date precedes the purchase order date."""

    rule_id = "IV-R014"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            po_line = context.po_line_for(invoice)
            if po_line is None or invoice.invoice_date is None or po_line.order_date is None:
                continue
            if invoice.invoice_date >= po_line.order_date:
                continue
            days = (po_line.order_date - invoice.invoice_date).days
            exposure = float(invoice.total_amount_base or 0.0)
            findings.append(
                self.make_exception(
                    exception_type="invoice_before_po",
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    currency=context.base_currency,
                    expected_value=f"on or after {po_line.order_date.isoformat()} (PO date)",
                    actual_value=invoice.invoice_date.isoformat(),
                    difference=f"{days} day(s) before the PO",
                    difference_amount=exposure,
                    explanation=(
                        f"Invoice {invoice.invoice_number} is dated {invoice.invoice_date.isoformat()}, "
                        f"{days} day(s) before purchase order {invoice.po_number} was raised on "
                        f"{po_line.order_date.isoformat()}. An invoice cannot predate its PO."
                    ),
                    evidence={
                        "invoice_date": invoice.invoice_date.isoformat(),
                        "po_order_date": po_line.order_date.isoformat(),
                        "days_before": days,
                    },
                )
            )
        return findings


class InvoiceBeforeReceiptRule(BaseInvoiceRule):
    """IV-R015: the invoice date precedes the earliest goods receipt."""

    rule_id = "IV-R015"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            if invoice.invoice_date is None:
                continue
            receipts = context.goods_receipts_for(invoice.po_number, invoice.po_item)
            earliest = context.earliest_receipt_date(receipts)
            if earliest is None or invoice.invoice_date >= earliest:
                continue
            days = (earliest - invoice.invoice_date).days
            exposure = float(invoice.total_amount_base or 0.0)
            gr_number = next((r.gr_number for r in receipts if r.gr_number), None)
            findings.append(
                self.make_exception(
                    exception_type="invoice_before_receipt",
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    gr_number=gr_number,
                    currency=context.base_currency,
                    expected_value=f"on or after {earliest.isoformat()} (goods receipt)",
                    actual_value=invoice.invoice_date.isoformat(),
                    difference=f"{days} day(s) before the receipt",
                    difference_amount=exposure,
                    explanation=(
                        f"Invoice {invoice.invoice_number} is dated {invoice.invoice_date.isoformat()}, "
                        f"{days} day(s) before the goods were received on {earliest.isoformat()}. "
                        f"Verify the invoice date and that the goods were actually delivered."
                    ),
                    evidence={
                        "invoice_date": invoice.invoice_date.isoformat(),
                        "earliest_receipt_date": earliest.isoformat(),
                        "days_before": days,
                    },
                )
            )
        return findings


class FutureInvoiceDateRule(BaseInvoiceRule):
    """IV-R016: the invoice date is in the future relative to the validation date."""

    rule_id = "IV-R016"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        grace = timedelta(days=int(context.config.future_date_grace_days))
        cutoff = context.as_of_date + grace
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            if invoice.invoice_date is None or invoice.invoice_date <= cutoff:
                continue
            days = (invoice.invoice_date - context.as_of_date).days
            findings.append(
                self.make_exception(
                    exception_type="future_invoice_date",
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    currency=context.base_currency,
                    expected_value=f"on or before {context.as_of_date.isoformat()}",
                    actual_value=invoice.invoice_date.isoformat(),
                    difference=f"{days} day(s) in the future",
                    difference_amount=float(invoice.total_amount_base or 0.0),
                    explanation=(
                        f"Invoice {invoice.invoice_number} is dated "
                        f"{invoice.invoice_date.isoformat()}, {days} day(s) after the validation "
                        f"date {context.as_of_date.isoformat()}. Confirm the date before posting."
                    ),
                    evidence={
                        "invoice_date": invoice.invoice_date.isoformat(),
                        "as_of_date": context.as_of_date.isoformat(),
                        "grace_days": context.config.future_date_grace_days,
                        "days_in_future": days,
                    },
                )
            )
        return findings
