"""The deterministic invoice validation engine.

The engine joins the three datasets, executes every enabled rule against the
:class:`MatchContext`, collects the exceptions and computes aggregate KPIs. It
contains no AI and no I/O, so the same input always produces the same output - a
property the tests rely on.

Failure handling mirrors the other modules: if one rule raises, the failure is
recorded in ``rule_errors`` and the remaining rules still run. Rules that need a
dataset which was not uploaded (purchase orders or goods receipts) are reported
as skipped rather than silently producing nothing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.logging import get_logger
from app.modules.invoice_validator.matching import MatchContext
from app.modules.invoice_validator.normalizer import (
    NormalizedGoodsReceipt,
    NormalizedInvoice,
    NormalizedPoLine,
)
from app.modules.invoice_validator.rules import (
    GR_DEPENDENT_RULES,
    PO_DEPENDENT_RULES,
    RULE_CLASSES,
    ExceptionFinding,
)
from app.modules.invoice_validator.thresholds import InvoiceValidatorConfig
from app.schemas.common import Severity

logger = get_logger(__name__)

ENGINE_VERSION = "1.0.0"

#: Points assigned per severity when computing the aggregate exception score.
SEVERITY_WEIGHTS: dict[Severity, int] = {
    Severity.LOW: 1,
    Severity.MEDIUM: 3,
    Severity.HIGH: 8,
    Severity.CRITICAL: 20,
}


@dataclass
class RuleExecution:
    """Bookkeeping for one rule run."""

    rule_id: str
    rule_name: str
    enabled: bool
    exception_count: int
    duration_ms: int
    skipped_reason: str | None = None
    error: str | None = None


@dataclass
class ValidationResult:
    """Everything the engine produced for one validation run."""

    exceptions: list[ExceptionFinding]
    summary: dict[str, Any]
    supplier_summary: list[dict[str, Any]]
    three_way_matches: list[dict[str, Any]]
    executions: list[RuleExecution]
    engine_version: str = ENGINE_VERSION
    config_version: str = ""
    duration_ms: int = 0
    rule_errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def exceptions_as_dicts(self) -> list[dict[str, Any]]:
        return [exception.to_dict() for exception in self.exceptions]


class InvoiceValidationEngine:
    """Runs the configured rule set over the three joined datasets."""

    def __init__(self, config: InvoiceValidatorConfig) -> None:
        self.config = config

    def run(
        self,
        invoices: list[NormalizedInvoice],
        po_lines: list[NormalizedPoLine],
        goods_receipts: list[NormalizedGoodsReceipt],
        *,
        as_of_date: date,
        enabled_rules: list[str] | None = None,
    ) -> ValidationResult:
        """Execute all rules against the three datasets."""
        started = time.perf_counter()
        has_po = bool(po_lines)
        has_gr = bool(goods_receipts)
        context = MatchContext(
            invoices, po_lines, goods_receipts, self.config,
            has_po_dataset=has_po, has_gr_dataset=has_gr, as_of_date=as_of_date,
        )

        exceptions: list[ExceptionFinding] = []
        executions: list[RuleExecution] = []
        rule_errors: list[dict[str, str]] = []

        for rule_class in RULE_CLASSES:
            rule = rule_class(self.config)
            selected = enabled_rules is None or rule.rule_id in enabled_rules
            skipped_reason = self._skip_reason(rule.rule_id, has_po, has_gr)

            if not rule.enabled or not selected:
                executions.append(
                    RuleExecution(rule.rule_id, rule.name, False, 0, 0, skipped_reason="disabled")
                )
                continue
            if skipped_reason:
                executions.append(
                    RuleExecution(rule.rule_id, rule.name, True, 0, 0, skipped_reason=skipped_reason)
                )
                continue

            rule_started = time.perf_counter()
            try:
                rule_exceptions = rule.evaluate(context)
            except Exception as exc:  # noqa: BLE001 - one bad rule must not kill the run
                duration = int((time.perf_counter() - rule_started) * 1000)
                message = f"{type(exc).__name__}: {exc}"
                logger.exception("Invoice rule %s failed", rule.rule_id)
                executions.append(RuleExecution(rule.rule_id, rule.name, True, 0, duration, error=message))
                rule_errors.append({"rule_id": rule.rule_id, "error": message})
                continue

            duration = int((time.perf_counter() - rule_started) * 1000)
            exceptions.extend(rule_exceptions)
            executions.append(RuleExecution(rule.rule_id, rule.name, True, len(rule_exceptions), duration))

        exceptions.sort(
            key=lambda e: (-e.severity.rank, -e.difference_amount, e.rule_id, str(e.invoice_number))
        )
        summary = self._build_summary(context, exceptions, executions)
        supplier_summary = self._build_supplier_summary(context, exceptions)
        three_way_matches = self._build_three_way_matches(context, exceptions)
        total_duration = int((time.perf_counter() - started) * 1000)

        logger.info(
            "Invoice validation finished: %d exceptions from %d rules over %d invoices in %d ms",
            len(exceptions), sum(1 for e in executions if e.enabled and not e.skipped_reason),
            len(invoices), total_duration,
        )
        return ValidationResult(
            exceptions=exceptions,
            summary=summary,
            supplier_summary=supplier_summary,
            three_way_matches=three_way_matches,
            executions=executions,
            config_version=self.config.config_version,
            duration_ms=total_duration,
            rule_errors=rule_errors,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _skip_reason(rule_id: str, has_po: bool, has_gr: bool) -> str | None:
        if rule_id in PO_DEPENDENT_RULES and not has_po:
            return "no_purchase_order_dataset"
        if rule_id in GR_DEPENDENT_RULES and not has_gr:
            return "no_goods_receipt_dataset"
        return None

    # ------------------------------------------------------------------
    def _build_summary(
        self, context: MatchContext, exceptions: list[ExceptionFinding], executions: list[RuleExecution]
    ) -> dict[str, Any]:
        severity_counts = {severity.value: 0 for severity in Severity}
        category_counts: dict[str, int] = {}
        rule_counts: dict[str, dict[str, Any]] = {}
        for exception in exceptions:
            severity_counts[exception.severity.value] += 1
            category_counts[exception.category] = category_counts.get(exception.category, 0) + 1
            entry = rule_counts.setdefault(
                exception.rule_id,
                {"rule_id": exception.rule_id, "rule_name": exception.rule_name,
                 "category": exception.category, "count": 0, "exposure": 0.0},
            )
            entry["count"] += 1
            entry["exposure"] += exception.difference_amount

        invoices = context.invoices
        total_invoice_amount = round(
            sum(float(inv.total_amount_base) for inv in invoices if inv.total_amount_base is not None), 2
        )
        flagged_invoice_numbers = {e.invoice_number for e in exceptions if e.invoice_number is not None}
        flagged_value = round(
            sum(
                float(inv.total_amount_base or 0.0)
                for inv in invoices
                if inv.invoice_number in flagged_invoice_numbers
            ),
            2,
        )
        matched_po = sum(1 for inv in invoices if context.po_line_for(inv) is not None)
        matched_gr = sum(
            1 for inv in invoices if context.goods_receipts_for(inv.po_number, inv.po_item)
        )
        fully_matched = sum(
            1
            for inv in invoices
            if context.po_line_for(inv) is not None
            and context.goods_receipts_for(inv.po_number, inv.po_item)
        )

        weighted_points = sum(SEVERITY_WEIGHTS[e.severity] for e in exceptions)
        invoice_count = max(len(invoices), 1)
        exception_score = min(100.0, round(weighted_points / invoice_count * 10.0, 1))

        return {
            "invoice_count": len(invoices),
            "purchase_order_line_count": len(context.po_lines),
            "goods_receipt_count": len(context.goods_receipts),
            "supplier_count": len({inv.supplier_id for inv in invoices if inv.supplier_id}),
            "base_currency": self.config.base_currency,
            "total_invoice_amount_base": total_invoice_amount,
            "matched_to_po": matched_po,
            "matched_to_goods_receipt": matched_gr,
            "fully_three_way_matched": fully_matched,
            "exceptions_count": len(exceptions),
            "severity_counts": severity_counts,
            "category_counts": dict(sorted(category_counts.items())),
            "rule_counts": sorted(
                ({**entry, "exposure": round(entry["exposure"], 2)} for entry in rule_counts.values()),
                key=lambda entry: -entry["count"],
            ),
            "flagged_invoice_count": len(flagged_invoice_numbers),
            "flagged_value_base": flagged_value,
            "flagged_value_share_pct": round(flagged_value / total_invoice_amount * 100.0, 2)
            if total_invoice_amount
            else 0.0,
            "estimated_exposure_base": round(sum(e.difference_amount for e in exceptions), 2),
            "exposure_note": (
                "Sum of per-exception difference amounts. One invoice can raise several exceptions, "
                "so this figure is an upper bound, not a netted loss estimate."
            ),
            "exception_score": exception_score,
            "exception_score_method": (
                "weighted severity points (low=1, medium=3, high=8, critical=20) divided by the "
                "number of invoice lines, multiplied by 10, capped at 100"
            ),
            "rules_executed": sum(1 for e in executions if e.enabled and not e.skipped_reason),
            "rules_skipped": sum(1 for e in executions if e.skipped_reason),
            "engine_version": ENGINE_VERSION,
            "config_version": self.config.config_version,
        }

    def _build_supplier_summary(
        self, context: MatchContext, exceptions: list[ExceptionFinding]
    ) -> list[dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for invoice in context.invoices:
            key = invoice.supplier_id or "(unknown)"
            row = rows.setdefault(
                key,
                {"supplier_id": invoice.supplier_id, "supplier_name": invoice.supplier_name,
                 "invoice_count": 0, "invoiced_value_base": 0.0, "exceptions_count": 0,
                 "critical_count": 0, "high_count": 0, "medium_count": 0, "low_count": 0,
                 "estimated_exposure_base": 0.0, "top_exception_type": None},
            )
            row["invoice_count"] += 1
            row["invoiced_value_base"] += float(invoice.total_amount_base or 0.0)
            if invoice.supplier_name and not row["supplier_name"]:
                row["supplier_name"] = invoice.supplier_name

        types: dict[str, dict[str, int]] = {}
        for exception in exceptions:
            key = exception.supplier_id or "(unknown)"
            row = rows.get(key)
            if row is None:
                continue
            row["exceptions_count"] += 1
            row[f"{exception.severity.value}_count"] += 1
            row["estimated_exposure_base"] += exception.difference_amount
            bucket = types.setdefault(key, {})
            bucket[exception.exception_type] = bucket.get(exception.exception_type, 0) + 1

        for key, row in rows.items():
            row["invoiced_value_base"] = round(row["invoiced_value_base"], 2)
            row["estimated_exposure_base"] = round(row["estimated_exposure_base"], 2)
            bucket = types.get(key)
            if bucket:
                row["top_exception_type"] = max(bucket, key=lambda name: bucket[name])

        return sorted(
            rows.values(),
            key=lambda row: (-row["exceptions_count"], -row["estimated_exposure_base"]),
        )

    def _build_three_way_matches(
        self, context: MatchContext, exceptions: list[ExceptionFinding]
    ) -> list[dict[str, Any]]:
        """One compact comparison row per invoice, for the three-way-match view."""
        exceptions_by_invoice: dict[str, int] = {}
        for exception in exceptions:
            if exception.invoice_number is not None:
                exceptions_by_invoice[exception.invoice_number] = (
                    exceptions_by_invoice.get(exception.invoice_number, 0) + 1
                )

        limit = self.config.reporting.max_matches_stored
        rows: list[dict[str, Any]] = []
        for invoice in context.invoices[:limit]:
            po_line = context.po_line_for(invoice)
            receipts = context.goods_receipts_for(invoice.po_number, invoice.po_item)
            matched_po = po_line is not None
            matched_gr = bool(receipts)
            exception_count = exceptions_by_invoice.get(invoice.invoice_number, 0)
            if exception_count:
                status = "exception"
            elif not matched_po and context.has_po_dataset:
                status = "unmatched"
            else:
                status = "matched"
            rows.append(
                {
                    "invoice_number": invoice.invoice_number,
                    "supplier_id": invoice.supplier_id,
                    "supplier_name": invoice.supplier_name,
                    "po_number": invoice.po_number,
                    "po_item": invoice.po_item,
                    "invoice_quantity": invoice.quantity,
                    "po_quantity": po_line.quantity if po_line else None,
                    "received_quantity": context.received_quantity(receipts),
                    "accepted_quantity": context.accepted_quantity(receipts),
                    "invoice_unit_price": invoice.unit_price,
                    "po_unit_price": po_line.unit_price if po_line else None,
                    "invoice_currency": invoice.currency,
                    "po_currency": po_line.currency if po_line else None,
                    "invoice_total_base": invoice.total_amount_base,
                    "matched_po": matched_po,
                    "matched_gr": matched_gr,
                    "exception_count": exception_count,
                    "status": status,
                }
            )
        return rows
