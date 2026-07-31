"""Duplicate detection rules.

* **IV-R001** duplicate invoices - two invoices on the same supplier for a
  near-identical amount within a short date window (the classic double-payment
  signal, even when the invoice numbers differ).
* **IV-R002** duplicate invoice number for a supplier - the same invoice number
  used more than once by one supplier.
"""

from __future__ import annotations

from datetime import date

from app.modules.invoice_validator.matching import MatchContext
from app.modules.invoice_validator.rules.base import BaseInvoiceRule, ExceptionFinding

_MIN_DATE = date(1900, 1, 1)


def _days_between(earlier, later) -> int | None:
    """Absolute days between two invoices, or ``None`` when a date is missing."""
    if earlier.invoice_date is None or later.invoice_date is None:
        return None
    return abs((later.invoice_date - earlier.invoice_date).days)


class DuplicateInvoiceRule(BaseInvoiceRule):
    """IV-R001: near-identical invoices on the same supplier."""

    rule_id = "IV-R001"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        settings = context.config.duplicate
        amount_tol = float(settings.amount_tolerance_abs)
        window_days = int(settings.date_window_days)
        min_value = float(self.param("min_total_value_base", 0.0))

        # Group by supplier; an invoice with no supplier still groups under "".
        by_supplier: dict[str, list] = {}
        for invoice in context.invoices:
            if invoice.total_amount_base is None or invoice.total_amount_base < min_value:
                continue
            by_supplier.setdefault(invoice.supplier_id or "", []).append(invoice)

        findings: list[ExceptionFinding] = []
        for supplier_id, invoices in by_supplier.items():
            ordered = sorted(
                invoices,
                key=lambda inv: (inv.invoice_date or _MIN_DATE, str(inv.invoice_number)),
            )
            for index, later in enumerate(ordered):
                for earlier in ordered[:index]:
                    if later is earlier:
                        continue
                    if abs(later.total_amount_base - earlier.total_amount_base) > amount_tol:
                        continue
                    days_apart = _days_between(earlier, later)
                    if days_apart is not None and days_apart > window_days:
                        continue
                    exposure = float(later.total_amount_base)
                    findings.append(
                        self.make_exception(
                            exception_type="duplicate_invoice",
                            severity=context.escalate_severity(self.base_severity, exposure),
                            invoice_number=later.invoice_number,
                            supplier_id=supplier_id or None,
                            supplier_name=later.supplier_name,
                            po_number=later.po_number,
                            po_item=later.po_item,
                            currency=context.base_currency,
                            expected_value=f"first invoice {earlier.invoice_number}",
                            actual_value=f"duplicate invoice {later.invoice_number}",
                            difference=f"{exposure:,.2f} {context.base_currency} at risk of double payment",
                            difference_amount=exposure,
                            explanation=(
                                f"Invoice {later.invoice_number} matches invoice "
                                f"{earlier.invoice_number} on supplier {supplier_id or 'unknown'}: "
                                f"both total {exposure:,.2f} {context.base_currency}"
                                + (f" and were dated {days_apart} day(s) apart" if days_apart is not None else "")
                                + ". This is a strong double-payment signal."
                            ),
                            evidence={
                                "duplicate_invoice_number": later.invoice_number,
                                "original_invoice_number": earlier.invoice_number,
                                "amount_base": round(exposure, 2),
                                "days_apart": days_apart,
                                "amount_tolerance_abs": amount_tol,
                                "date_window_days": window_days,
                                "base_currency": context.base_currency,
                            },
                        )
                    )
                    break  # one finding per duplicated invoice is enough
        return findings


class DuplicateInvoiceNumberRule(BaseInvoiceRule):
    """IV-R002: the same invoice number reused by one supplier."""

    rule_id = "IV-R002"

    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:
        by_key: dict[tuple[str, str], list] = {}
        for invoice in context.invoices:
            if not invoice.supplier_id:
                continue
            number = str(invoice.invoice_number).strip()
            by_key.setdefault((invoice.supplier_id, number), []).append(invoice)

        findings: list[ExceptionFinding] = []
        for (supplier_id, number), invoices in by_key.items():
            if len(invoices) < 2:
                continue
            ordered = sorted(invoices, key=lambda inv: (inv.invoice_date or _MIN_DATE, inv.row_number))
            first = ordered[0]
            for duplicate in ordered[1:]:
                exposure = float(duplicate.total_amount_base or 0.0)
                findings.append(
                    self.make_exception(
                        exception_type="duplicate_invoice_number",
                        invoice_number=duplicate.invoice_number,
                        supplier_id=supplier_id,
                        supplier_name=duplicate.supplier_name,
                        po_number=duplicate.po_number,
                        po_item=duplicate.po_item,
                        currency=context.base_currency,
                        expected_value="a unique invoice number per supplier",
                        actual_value=f"invoice number {number} used {len(invoices)} times",
                        difference=f"{len(invoices) - 1} repeat use(s)",
                        difference_amount=exposure,
                        explanation=(
                            f"Supplier {supplier_id} used invoice number {number} on "
                            f"{len(invoices)} invoices (rows {first.row_number} and "
                            f"{duplicate.row_number}). A reused invoice number can cause a "
                            f"duplicate posting."
                        ),
                        evidence={
                            "supplier_id": supplier_id,
                            "invoice_number": number,
                            "occurrences": len(invoices),
                            "first_row": first.row_number,
                            "duplicate_row": duplicate.row_number,
                            "amount_base": round(exposure, 2),
                            "base_currency": context.base_currency,
                        },
                    )
                )
        return findings
