"""Header-consistency rules that compare an invoice against its purchase order.

* **IV-R008** currency mismatch - invoice currency differs from the PO currency.
* **IV-R009** supplier mismatch - invoice supplier differs from the PO supplier.
* **IV-R011** payment-term mismatch - invoice payment terms differ from the PO.
"""

from __future__ import annotations

from app.modules.invoice_validator.matching import MatchContext
from app.modules.invoice_validator.rules.base import BaseInvoiceRule, ExceptionFinding


def _norm(value: str | None) -> str | None:
    return value.strip().upper() if value else None


class CurrencyMismatchRule(BaseInvoiceRule):
    """IV-R008: invoice currency differs from the purchase order currency."""

    rule_id = "IV-R008"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            po_line = context.po_line_for(invoice)
            if po_line is None or not invoice.currency or not po_line.currency:
                continue
            if _norm(invoice.currency) == _norm(po_line.currency):
                continue
            exposure = float(invoice.total_amount_base or 0.0)
            findings.append(
                self.make_exception(
                    exception_type="currency_mismatch",
                    severity=context.escalate_severity(self.base_severity, exposure),
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    currency=invoice.currency,
                    expected_value=po_line.currency,
                    actual_value=invoice.currency,
                    difference=f"{po_line.currency} -> {invoice.currency}",
                    difference_amount=exposure,
                    explanation=(
                        f"Invoice {invoice.invoice_number} is in {invoice.currency}, but purchase "
                        f"order {invoice.po_number} is in {po_line.currency}. A currency difference "
                        f"changes the payable amount and must be corrected before posting."
                    ),
                    evidence={
                        "invoice_currency": invoice.currency,
                        "po_currency": po_line.currency,
                        "invoice_total_base": round(exposure, 2),
                        "base_currency": context.base_currency,
                    },
                )
            )
        return findings


class SupplierMismatchRule(BaseInvoiceRule):
    """IV-R009: invoice supplier differs from the purchase order supplier."""

    rule_id = "IV-R009"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            po_line = context.po_line_for(invoice)
            if po_line is None or not invoice.supplier_id or not po_line.supplier_id:
                continue
            if str(invoice.supplier_id).strip() == str(po_line.supplier_id).strip():
                continue
            exposure = float(invoice.total_amount_base or 0.0)
            findings.append(
                self.make_exception(
                    exception_type="supplier_mismatch",
                    severity=context.escalate_severity(self.base_severity, exposure),
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    currency=context.base_currency,
                    expected_value=f"PO supplier {po_line.supplier_id}",
                    actual_value=f"invoice supplier {invoice.supplier_id}",
                    difference=f"{po_line.supplier_id} != {invoice.supplier_id}",
                    difference_amount=exposure,
                    explanation=(
                        f"Invoice {invoice.invoice_number} is from supplier {invoice.supplier_id}, "
                        f"but purchase order {invoice.po_number} was placed with supplier "
                        f"{po_line.supplier_id}. Verify the invoicing party before payment."
                    ),
                    evidence={
                        "invoice_supplier_id": invoice.supplier_id,
                        "po_supplier_id": po_line.supplier_id,
                        "invoice_total_base": round(exposure, 2),
                        "base_currency": context.base_currency,
                    },
                )
            )
        return findings


class PaymentTermMismatchRule(BaseInvoiceRule):
    """IV-R011: invoice payment terms differ from the purchase order terms."""

    rule_id = "IV-R011"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            po_line = context.po_line_for(invoice)
            if po_line is None or not invoice.payment_terms or not po_line.payment_terms:
                continue
            if _norm(invoice.payment_terms) == _norm(po_line.payment_terms):
                continue
            findings.append(
                self.make_exception(
                    exception_type="payment_term_mismatch",
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    currency=context.base_currency,
                    expected_value=po_line.payment_terms,
                    actual_value=invoice.payment_terms,
                    difference=f"{po_line.payment_terms} -> {invoice.payment_terms}",
                    difference_amount=0.0,
                    explanation=(
                        f"Invoice {invoice.invoice_number} states payment terms "
                        f"'{invoice.payment_terms}', but purchase order {invoice.po_number} agreed "
                        f"'{po_line.payment_terms}'. Align the terms before posting."
                    ),
                    evidence={
                        "invoice_payment_terms": invoice.payment_terms,
                        "po_payment_terms": po_line.payment_terms,
                    },
                )
            )
        return findings
