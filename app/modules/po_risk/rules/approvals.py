"""Approval and governance rules.

* **PO-R009** high value purchase orders that are not released.
* **PO-R017** documents with an unusual number of manual changes.
"""

from __future__ import annotations

import pandas as pd

from app.schemas.common import Severity
from app.modules.po_risk.rules.base import BaseRule, RuleContext, RuleFinding


class HighValueWithoutApprovalRule(BaseRule):
    """PO-R009: order value above the release threshold but not approved."""

    rule_id = "PO-R009"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        headers = context.po_header_values
        if headers.empty:
            return []

        min_value = float(self.param("min_total_value_base", 10000.0))
        findings: list[RuleFinding] = []

        for row in headers.to_dict("records"):
            value = float(row["total_value_base"] or 0.0)
            if value < min_value:
                continue
            status = row.get("approval_status")
            if context.is_approved(status):
                continue

            status_text = str(status) if status is not None and not pd.isna(status) else "missing"
            highest_crossed = [
                threshold
                for threshold in context.config.sorted_approval_thresholds()
                if value >= threshold
            ]
            findings.append(
                self.make_finding(
                    po_number=row["po_number"],
                    supplier_id=row.get("supplier_id"),
                    supplier_name=row.get("supplier_name"),
                    severity=context.escalate_severity(self.base_severity, value),
                    explanation=(
                        f"Purchase order {row['po_number']} is worth {value:,.2f} "
                        f"{context.base_currency} and has the approval status '{status_text}'. "
                        f"Orders above {min_value:,.0f} {context.base_currency} must be released "
                        "before goods receipt or invoice posting."
                        + (
                            f" The value crosses the "
                            f"{max(highest_crossed):,.0f} {context.base_currency} release level."
                            if highest_crossed
                            else ""
                        )
                    ),
                    evidence={
                        "order_value_base": round(value, 2),
                        "approval_status": status_text,
                        "approved_status_values": context.config.approved_status_values,
                        "crossed_approval_thresholds": highest_crossed,
                        "item_count": int(row.get("item_count") or 0),
                        "created_by": row.get("created_by"),
                        "base_currency": context.base_currency,
                        "threshold_min_total_value_base": min_value,
                    },
                    exposure=value,
                )
            )
        return findings


class ExcessiveChangesRule(BaseRule):
    """PO-R017: too many manual amendments on one document."""

    rule_id = "PO-R017"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        max_changes = int(self.param("max_changes", 5))
        critical_changes = int(self.param("critical_changes", 12))

        rows = context.frame.dropna(subset=["change_count"]).copy()
        if rows.empty:
            return []
        rows["change_count"] = pd.to_numeric(rows["change_count"], errors="coerce")
        rows = rows[rows["change_count"] > max_changes]
        if rows.empty:
            return []

        # Report once per purchase order, using the highest observed change count.
        findings: list[RuleFinding] = []
        for po_number, group in rows.groupby("po_number"):
            worst = group.loc[group["change_count"].idxmax()]
            changes = int(worst["change_count"])
            order_value = float(
                pd.to_numeric(group["total_value_base"], errors="coerce").fillna(0.0).sum()
            )
            severity = Severity.HIGH if changes >= critical_changes else self.base_severity
            severity = context.escalate_severity(severity, order_value)

            findings.append(
                self.make_finding(
                    po_number=po_number,
                    po_item=worst.get("po_item"),
                    supplier_id=worst.get("supplier_id"),
                    supplier_name=worst.get("supplier_name"),
                    severity=severity,
                    explanation=(
                        f"Purchase order {po_number} was manually changed {changes} time(s), above "
                        f"the configured limit of {max_changes}. Frequent amendments after release "
                        "weaken the audit trail and can be used to alter prices or quantities "
                        "after approval."
                    ),
                    evidence={
                        "change_count": changes,
                        "changed_by": worst.get("changed_by"),
                        "created_by": worst.get("created_by"),
                        "order_value_base": round(order_value, 2),
                        "base_currency": context.base_currency,
                        "threshold_max_changes": max_changes,
                        "threshold_critical_changes": critical_changes,
                    },
                    exposure=order_value,
                )
            )
        return findings
