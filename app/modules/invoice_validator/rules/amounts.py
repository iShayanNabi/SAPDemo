"""Amount and quantity rules.

* **IV-R005** price mismatch - invoiced unit price differs from the PO price.
* **IV-R006** quantity mismatch - invoiced quantity differs from the received
  quantity (or the ordered quantity when no receipt exists).
* **IV-R007** tax mismatch - invoiced tax differs from the expected tax on the
  net amount.
* **IV-R010** freight mismatch - freight exceeds the configured freight ceiling.
* **IV-R013** overbilling - cumulative invoicing exceeds the ordered quantity or
  value for a PO line.
"""

from __future__ import annotations

from datetime import date

from app.modules.invoice_validator.matching import MatchContext, item_key, number_key
from app.modules.invoice_validator.rules.base import BaseInvoiceRule, ExceptionFinding

_MIN_DATE = date(1900, 1, 1)


class PriceMismatchRule(BaseInvoiceRule):
    """IV-R005: invoiced unit price differs from the purchase order price."""

    rule_id = "IV-R005"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        tolerance = context.config.tolerances.price
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            po_line = context.po_line_for(invoice)
            if po_line is None or invoice.unit_price is None or po_line.unit_price is None:
                continue
            # A currency difference is handled by IV-R008; compare like with like.
            if invoice.currency and po_line.currency and invoice.currency != po_line.currency:
                continue
            if not tolerance.exceeds(po_line.unit_price, invoice.unit_price):
                continue
            diff = float(invoice.unit_price) - float(po_line.unit_price)
            quantity = float(invoice.quantity) if invoice.quantity is not None else 1.0
            rate = context.config.conversion_rate(invoice.currency)
            exposure = round(abs(diff) * quantity * rate, 2)
            findings.append(
                self.make_exception(
                    exception_type="price_mismatch",
                    severity=context.escalate_severity(self.base_severity, exposure),
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    currency=invoice.currency or context.base_currency,
                    expected_value=f"{po_line.unit_price:g} (PO price)",
                    actual_value=f"{invoice.unit_price:g} (invoiced)",
                    difference=f"{diff:+g} per unit",
                    difference_amount=exposure,
                    explanation=(
                        f"Invoice {invoice.invoice_number} bills {invoice.unit_price:g} per unit for "
                        f"PO {invoice.po_number} item {invoice.po_item or '(none)'}, but the purchase "
                        f"order price is {po_line.unit_price:g}. Over {quantity:g} unit(s) that is "
                        f"about {exposure:,.2f} {context.base_currency}."
                    ),
                    evidence={
                        "invoice_unit_price": float(invoice.unit_price),
                        "po_unit_price": float(po_line.unit_price),
                        "quantity": quantity,
                        "unit_difference": round(diff, 4),
                        "tolerance_pct": tolerance.pct,
                        "tolerance_abs": tolerance.abs,
                        "currency": invoice.currency,
                        "base_currency": context.base_currency,
                    },
                )
            )
        return findings


class QuantityMismatchRule(BaseInvoiceRule):
    """IV-R006: invoiced quantity differs from received (or ordered) quantity."""

    rule_id = "IV-R006"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        tolerance = context.config.tolerances.quantity
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            if invoice.quantity is None:
                continue
            receipts = context.goods_receipts_for(invoice.po_number, invoice.po_item)
            reference = context.received_quantity(receipts)
            basis = "received"
            po_line = context.po_line_for(invoice)
            if reference is None:
                if po_line is None or po_line.quantity is None:
                    continue
                reference = float(po_line.quantity)
                basis = "ordered"
            if not tolerance.exceeds(reference, invoice.quantity):
                continue
            diff = float(invoice.quantity) - float(reference)
            unit_price_base = invoice.unit_price_base
            if unit_price_base is None and po_line is not None:
                unit_price_base = po_line.unit_price_base
            exposure = round(abs(diff) * float(unit_price_base), 2) if unit_price_base is not None else 0.0
            findings.append(
                self.make_exception(
                    exception_type="quantity_mismatch",
                    severity=context.escalate_severity(self.base_severity, exposure),
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    currency=context.base_currency,
                    expected_value=f"{reference:g} ({basis})",
                    actual_value=f"{invoice.quantity:g} (invoiced)",
                    difference=f"{diff:+g} units",
                    difference_amount=exposure,
                    explanation=(
                        f"Invoice {invoice.invoice_number} bills {invoice.quantity:g} units, but the "
                        f"{basis} quantity for PO {invoice.po_number} item "
                        f"{invoice.po_item or '(none)'} is {reference:g}."
                    ),
                    evidence={
                        "invoiced_quantity": float(invoice.quantity),
                        "reference_quantity": float(reference),
                        "reference_basis": basis,
                        "quantity_difference": round(diff, 4),
                        "base_currency": context.base_currency,
                    },
                )
            )
        return findings


class TaxMismatchRule(BaseInvoiceRule):
    """IV-R007: invoiced tax differs from the expected tax on the net amount."""

    rule_id = "IV-R007"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        tolerance = context.config.tolerances.tax
        rate = float(context.config.expected_tax_rate)
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            if invoice.subtotal is None or invoice.tax is None:
                continue
            expected_tax = round(float(invoice.subtotal) * rate, 2)
            if not tolerance.exceeds(expected_tax, invoice.tax):
                continue
            diff = float(invoice.tax) - expected_tax
            conv = context.config.conversion_rate(invoice.currency)
            exposure = round(abs(diff) * conv, 2)
            findings.append(
                self.make_exception(
                    exception_type="tax_mismatch",
                    severity=context.escalate_severity(self.base_severity, exposure),
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    currency=invoice.currency or context.base_currency,
                    expected_value=f"{expected_tax:g} ({rate * 100:g}% of net)",
                    actual_value=f"{invoice.tax:g} (invoiced tax)",
                    difference=f"{diff:+g}",
                    difference_amount=exposure,
                    explanation=(
                        f"Invoice {invoice.invoice_number} charges {invoice.tax:g} tax on a net "
                        f"amount of {invoice.subtotal:g}. At the expected rate of {rate * 100:g}% "
                        f"the tax should be about {expected_tax:g}."
                    ),
                    evidence={
                        "subtotal": float(invoice.subtotal),
                        "invoiced_tax": float(invoice.tax),
                        "expected_tax": expected_tax,
                        "expected_tax_rate": rate,
                        "tolerance_pct": tolerance.pct,
                        "tolerance_abs": tolerance.abs,
                        "currency": invoice.currency,
                    },
                )
            )
        return findings


class FreightMismatchRule(BaseInvoiceRule):
    """IV-R010: freight exceeds the configured freight ceiling."""

    rule_id = "IV-R010"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        policy = context.config.freight_policy
        tolerance = context.config.tolerances.freight
        min_freight = float(self.param("min_freight_base", 0.0))
        findings: list[ExceptionFinding] = []
        for invoice in context.invoices:
            if invoice.freight_base is None or invoice.freight_base < min_freight:
                continue
            subtotal_base = invoice.subtotal_base or 0.0
            cap = max(policy.flat_cap, subtotal_base * policy.max_pct / 100.0)
            if invoice.freight_base <= cap or not tolerance.exceeds(cap, invoice.freight_base):
                continue
            over = round(float(invoice.freight_base) - cap, 2)
            findings.append(
                self.make_exception(
                    exception_type="freight_mismatch",
                    severity=context.escalate_severity(self.base_severity, over),
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id,
                    supplier_name=invoice.supplier_name,
                    po_number=invoice.po_number,
                    po_item=invoice.po_item,
                    currency=context.base_currency,
                    expected_value=f"<= {cap:,.2f} {context.base_currency} (policy ceiling)",
                    actual_value=f"{invoice.freight_base:,.2f} {context.base_currency}",
                    difference=f"{over:,.2f} over the ceiling",
                    difference_amount=over,
                    explanation=(
                        f"Invoice {invoice.invoice_number} charges "
                        f"{invoice.freight_base:,.2f} {context.base_currency} freight, above the "
                        f"policy ceiling of {cap:,.2f} (the greater of a "
                        f"{policy.flat_cap:,.0f} flat cap and {policy.max_pct:g}% of the net amount)."
                    ),
                    evidence={
                        "freight_base": round(float(invoice.freight_base), 2),
                        "subtotal_base": round(subtotal_base, 2),
                        "policy_ceiling_base": round(cap, 2),
                        "flat_cap": policy.flat_cap,
                        "max_pct": policy.max_pct,
                        "base_currency": context.base_currency,
                    },
                )
            )
        return findings


class OverbillingRule(BaseInvoiceRule):
    """IV-R013: cumulative invoicing exceeds the ordered quantity/value for a line."""

    rule_id = "IV-R013"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        quantity_tol = context.config.tolerances.quantity
        price_tol = context.config.tolerances.price

        # Invoices grouped by the PO line they reference, in a stable order.
        grouped: dict[tuple[str, str | None], list] = {}
        for invoice in context.invoices:
            num = number_key(invoice.po_number)
            if num is None:
                continue
            grouped.setdefault((num, item_key(invoice.po_item)), []).append(invoice)

        findings: list[ExceptionFinding] = []
        for po_line in context.po_lines:
            key = (number_key(po_line.po_number), item_key(po_line.po_item))
            invoices = grouped.get(key)
            if not invoices:
                continue
            ordered = sorted(invoices, key=lambda inv: (inv.invoice_date or _MIN_DATE, inv.row_number))

            finding = self._quantity_overbilling(context, po_line, ordered, quantity_tol)
            # Value-based overbilling is a fallback only when the PO carries no
            # ordered quantity; otherwise a simple price mismatch (same quantity,
            # higher price) would also read as value overbilling.
            if finding is None and po_line.quantity is None:
                finding = self._value_overbilling(context, po_line, ordered, price_tol)
            if finding is not None:
                findings.append(finding)
        return findings

    def _quantity_overbilling(self, context, po_line, invoices, tolerance):
        if po_line.quantity is None:
            return None
        ordered_qty = float(po_line.quantity)
        running = 0.0
        for invoice in invoices:
            if invoice.quantity is None:
                continue
            running += float(invoice.quantity)
            if running > ordered_qty and tolerance.exceeds(ordered_qty, running):
                over = round(running - ordered_qty, 4)
                unit_price_base = invoice.unit_price_base or po_line.unit_price_base
                exposure = round(over * float(unit_price_base), 2) if unit_price_base is not None else 0.0
                return self.make_exception(
                    exception_type="overbilling",
                    severity=context.escalate_severity(self.base_severity, exposure),
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id or po_line.supplier_id,
                    supplier_name=invoice.supplier_name or po_line.supplier_name,
                    po_number=po_line.po_number,
                    po_item=po_line.po_item,
                    currency=context.base_currency,
                    expected_value=f"{ordered_qty:g} ordered",
                    actual_value=f"{running:g} invoiced cumulatively",
                    difference=f"{over:g} over the ordered quantity",
                    difference_amount=exposure,
                    explanation=(
                        f"Invoicing on PO {po_line.po_number} item {po_line.po_item or '(none)'} "
                        f"reaches {running:g} units with invoice {invoice.invoice_number}, above the "
                        f"ordered quantity of {ordered_qty:g}. This over-invoices the line."
                    ),
                    evidence={
                        "ordered_quantity": ordered_qty,
                        "cumulative_invoiced_quantity": round(running, 4),
                        "over_quantity": over,
                        "invoice_count_on_line": len(invoices),
                        "base_currency": context.base_currency,
                    },
                )
        return None

    def _value_overbilling(self, context, po_line, invoices, tolerance):
        if po_line.line_value_base is None or po_line.line_value_base <= 0:
            return None
        ordered_value = float(po_line.line_value_base)
        running = 0.0
        for invoice in invoices:
            amount = invoice.subtotal_base if invoice.subtotal_base is not None else invoice.total_amount_base
            if amount is None:
                continue
            running += float(amount)
            if running > ordered_value and tolerance.exceeds(ordered_value, running):
                over = round(running - ordered_value, 2)
                return self.make_exception(
                    exception_type="overbilling",
                    severity=context.escalate_severity(self.base_severity, over),
                    invoice_number=invoice.invoice_number,
                    supplier_id=invoice.supplier_id or po_line.supplier_id,
                    supplier_name=invoice.supplier_name or po_line.supplier_name,
                    po_number=po_line.po_number,
                    po_item=po_line.po_item,
                    currency=context.base_currency,
                    expected_value=f"{ordered_value:,.2f} {context.base_currency} ordered value",
                    actual_value=f"{running:,.2f} {context.base_currency} invoiced cumulatively",
                    difference=f"{over:,.2f} over the ordered value",
                    difference_amount=over,
                    explanation=(
                        f"Cumulative invoicing on PO {po_line.po_number} item "
                        f"{po_line.po_item or '(none)'} reaches "
                        f"{running:,.2f} {context.base_currency} with invoice "
                        f"{invoice.invoice_number}, above the ordered value of "
                        f"{ordered_value:,.2f} {context.base_currency}."
                    ),
                    evidence={
                        "ordered_value_base": round(ordered_value, 2),
                        "cumulative_invoiced_base": round(running, 2),
                        "over_value_base": over,
                        "invoice_count_on_line": len(invoices),
                        "base_currency": context.base_currency,
                    },
                )
        return None
