"""Supplier risk rules.

* **PO-R018** supplier concentration inside a material group.
* **PO-R020** purchases from suppliers on the configured watch list.
"""

from __future__ import annotations

from app.modules.po_risk.rules.base import BaseRule, RuleContext, RuleFinding
from app.schemas.common import Severity


class SupplierConcentrationRule(BaseRule):
    """PO-R018: one supplier dominates a material group."""

    rule_id = "PO-R018"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        share_threshold = float(self.param("share_pct", 75.0))
        min_group_value = float(self.param("min_group_value_base", 0.0))
        min_orders = int(self.param("min_orders_in_group", 1))

        spend = context.material_group_spend
        if spend.empty:
            return []

        frame = context.frame
        findings: list[RuleFinding] = []

        for row in spend.to_dict("records"):
            if row["share_pct"] < share_threshold:
                continue
            if float(row["group_spend"]) < min_group_value:
                continue

            group_rows = frame[frame["material_group"] == row["material_group"]]
            order_count = int(group_rows["po_number"].nunique())
            if order_count < min_orders:
                continue

            supplier_id = str(row["supplier_id"])
            supplier_orders = group_rows[group_rows["supplier_id"] == supplier_id]
            severity = (
                Severity.HIGH if row["share_pct"] >= 90.0 else self.base_severity
            )
            findings.append(
                self.make_finding(
                    po_number=None,
                    supplier_id=supplier_id,
                    supplier_name=context.supplier_name_for(supplier_id),
                    severity=severity,
                    explanation=(
                        f"Supplier {supplier_id} covers {row['share_pct']:.1f}% of the "
                        f"{float(row['group_spend']):,.2f} {context.base_currency} spend in material "
                        f"group {row['material_group']} across {order_count} purchase order(s). "
                        f"Dependency above {share_threshold:.0f}% leaves the category exposed if "
                        "this supplier fails or raises prices."
                    ),
                    evidence={
                        "material_group": row["material_group"],
                        "supplier_spend_base": round(float(row["spend"]), 2),
                        "material_group_spend_base": round(float(row["group_spend"]), 2),
                        "share_pct": round(float(row["share_pct"]), 2),
                        "supplier_line_items": int(len(supplier_orders)),
                        "purchase_orders_in_group": order_count,
                        "base_currency": context.base_currency,
                        "threshold_share_pct": share_threshold,
                        "threshold_min_group_value_base": min_group_value,
                        "scope": "material group level (not a single purchase order)",
                    },
                    exposure=float(row["spend"]),
                )
            )
        return findings


class HighRiskSupplierRule(BaseRule):
    """PO-R020: order placed with a watch-listed supplier."""

    rule_id = "PO-R020"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        watch_list = context.config.high_risk_supplier_map()
        if not watch_list:
            return []
        min_value = float(self.param("min_total_value_base", 0.0))

        headers = context.po_header_values
        if headers.empty:
            return []

        findings: list[RuleFinding] = []
        for row in headers.to_dict("records"):
            supplier_id = row.get("supplier_id")
            if supplier_id is None:
                continue
            entry = watch_list.get(str(supplier_id))
            if entry is None:
                continue
            value = float(row["total_value_base"] or 0.0)
            if value < min_value:
                continue

            severity = max(entry.risk_level, self.base_severity, key=lambda s: s.rank)
            findings.append(
                self.make_finding(
                    po_number=row["po_number"],
                    supplier_id=supplier_id,
                    supplier_name=row.get("supplier_name") or context.supplier_name_for(supplier_id),
                    severity=context.escalate_severity(severity, value),
                    explanation=(
                        f"Purchase order {row['po_number']} worth {value:,.2f} "
                        f"{context.base_currency} was placed with supplier {supplier_id}, which is "
                        f"on the high-risk watch list ({entry.risk_level.value}): {entry.reason}"
                    ),
                    evidence={
                        "supplier_id": supplier_id,
                        "watch_list_risk_level": entry.risk_level.value,
                        "watch_list_reason": entry.reason,
                        "order_value_base": round(value, 2),
                        "base_currency": context.base_currency,
                        "watch_list_source": "configured high_risk_suppliers list (fictional demo data)",
                    },
                    exposure=value,
                )
            )
        return findings
