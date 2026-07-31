"""Delivery and date consistency rules.

* **PO-R010** late delivery beyond the configured grace period.
* **PO-R011** requested delivery date earlier than the order date.
* **PO-R012** goods receipt earlier than the order date.

PO-R011 and PO-R012 are date *consistency* checks: they cannot be true in a
correctly maintained document, so their confidence is 1.0.
"""

from __future__ import annotations

from app.schemas.common import Severity
from app.modules.po_risk.rules.base import BaseRule, RuleContext, RuleFinding


class LateDeliveryRule(BaseRule):
    """PO-R010: actual delivery later than requested."""

    rule_id = "PO-R010"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        grace_days = int(self.param("grace_days", 0))
        high_days = int(self.param("high_severity_days", 30))
        critical_days = int(self.param("critical_days", 60))
        cost_rate = float(self.param("delay_cost_rate_pct_per_30_days", 0.0))

        rows = context.frame.dropna(subset=["requested_delivery_date", "actual_delivery_date"])
        findings: list[RuleFinding] = []

        for row in rows.to_dict("records"):
            delay_days = (row["actual_delivery_date"] - row["requested_delivery_date"]).days
            if delay_days <= grace_days:
                continue

            value = float(row["total_value_base"] or 0.0)
            if delay_days >= critical_days:
                severity = Severity.CRITICAL
            elif delay_days >= high_days:
                severity = Severity.HIGH
            else:
                severity = self.base_severity

            # Deterministic proxy for the cost of a delay - documented, not a prediction.
            exposure = value * (cost_rate / 100.0) * (delay_days / 30.0)

            findings.append(
                self.make_finding(
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    supplier_id=row.get("supplier_id"),
                    supplier_name=row.get("supplier_name"),
                    severity=severity,
                    explanation=(
                        f"Item {row['po_item']} of purchase order {row['po_number']} was delivered "
                        f"{delay_days} day(s) after the requested date "
                        f"({row['requested_delivery_date']} requested, "
                        f"{row['actual_delivery_date']} received). The configured grace period is "
                        f"{grace_days} day(s)."
                    ),
                    evidence={
                        "requested_delivery_date": row["requested_delivery_date"],
                        "actual_delivery_date": row["actual_delivery_date"],
                        "delay_days": int(delay_days),
                        "line_value_base": round(value, 2),
                        "exposure_method": (
                            f"line value x {cost_rate}% per 30 days of delay (configured proxy)"
                        ),
                        "base_currency": context.base_currency,
                        "threshold_grace_days": grace_days,
                        "threshold_high_severity_days": high_days,
                        "threshold_critical_days": critical_days,
                    },
                    exposure=exposure,
                )
            )
        return findings


class RequestedBeforeOrderRule(BaseRule):
    """PO-R011: requested delivery date precedes the order date."""

    rule_id = "PO-R011"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        tolerance = int(self.param("tolerance_days", 0))
        rows = context.frame.dropna(subset=["order_date", "requested_delivery_date"])

        findings: list[RuleFinding] = []
        for row in rows.to_dict("records"):
            difference = (row["order_date"] - row["requested_delivery_date"]).days
            if difference <= tolerance:
                continue
            value = float(row["total_value_base"] or 0.0)
            findings.append(
                self.make_finding(
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    supplier_id=row.get("supplier_id"),
                    supplier_name=row.get("supplier_name"),
                    severity=context.escalate_severity(self.base_severity, value),
                    explanation=(
                        f"Item {row['po_item']} of purchase order {row['po_number']} requests "
                        f"delivery on {row['requested_delivery_date']}, which is {difference} "
                        f"day(s) before the order date {row['order_date']}. A requirement date in "
                        "the past distorts MRP and makes the supplier late on arrival."
                    ),
                    evidence={
                        "order_date": row["order_date"],
                        "requested_delivery_date": row["requested_delivery_date"],
                        "days_before_order": int(difference),
                        "line_value_base": round(value, 2),
                        "base_currency": context.base_currency,
                        "threshold_tolerance_days": tolerance,
                    },
                    exposure=value,
                )
            )
        return findings


class DeliveryBeforeOrderRule(BaseRule):
    """PO-R012: goods receipt posted before the order date."""

    rule_id = "PO-R012"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        tolerance = int(self.param("tolerance_days", 0))
        rows = context.frame.dropna(subset=["order_date", "actual_delivery_date"])

        findings: list[RuleFinding] = []
        for row in rows.to_dict("records"):
            difference = (row["order_date"] - row["actual_delivery_date"]).days
            if difference <= tolerance:
                continue
            value = float(row["total_value_base"] or 0.0)
            findings.append(
                self.make_finding(
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    supplier_id=row.get("supplier_id"),
                    supplier_name=row.get("supplier_name"),
                    severity=context.escalate_severity(self.base_severity, value),
                    explanation=(
                        f"Item {row['po_item']} of purchase order {row['po_number']} records a "
                        f"goods receipt on {row['actual_delivery_date']}, {difference} day(s) "
                        f"before the order date {row['order_date']}. This normally means the "
                        "purchase order was created after the goods had already been delivered."
                    ),
                    evidence={
                        "order_date": row["order_date"],
                        "actual_delivery_date": row["actual_delivery_date"],
                        "days_before_order": int(difference),
                        "line_value_base": round(value, 2),
                        "pattern": "after-the-fact purchase order",
                        "base_currency": context.base_currency,
                        "threshold_tolerance_days": tolerance,
                    },
                    exposure=value,
                )
            )
        return findings
