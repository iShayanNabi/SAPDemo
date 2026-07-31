"""Split purchase and threshold avoidance rules.

* **PO-R003** split purchases - several small orders on the same supplier
  inside a short window that together exceed a threshold none of them reaches
  individually.
* **PO-R004** orders that stop just below a release threshold.
"""

from __future__ import annotations

from datetime import timedelta

from app.modules.po_risk.rules.base import BaseRule, RuleContext, RuleFinding


class SplitPurchaseRule(BaseRule):
    """PO-R003: demand split across several small purchase orders."""

    rule_id = "PO-R003"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        headers = context.po_header_values
        if headers.empty:
            return []

        window_days = int(self.param("window_days", 7))
        min_orders = int(self.param("min_order_count", 3))
        combined_threshold = float(self.param("combined_value_threshold_base", 25000.0))
        max_individual = float(self.param("max_individual_value_base", 25000.0))

        candidates = headers.dropna(subset=["supplier_id", "order_date"])
        candidates = candidates[candidates["total_value_base"] < max_individual]

        findings: list[RuleFinding] = []
        for supplier_id, group in candidates.groupby("supplier_id"):
            rows = group.sort_values(["order_date", "po_number"]).to_dict("records")
            reported: set[str] = set()

            for start_index, anchor in enumerate(rows):
                window_end = anchor["order_date"] + timedelta(days=window_days)
                cluster = [
                    row for row in rows[start_index:] if row["order_date"] <= window_end
                ]
                if len(cluster) < min_orders:
                    continue
                combined = sum(float(row["total_value_base"]) for row in cluster)
                if combined < combined_threshold:
                    continue
                po_numbers = tuple(sorted(str(row["po_number"]) for row in cluster))
                if po_numbers in reported or any(
                    set(po_numbers).issubset(existing) for existing in reported
                ):
                    continue
                reported.add(po_numbers)

                crossed = [
                    threshold
                    for threshold in context.config.sorted_approval_thresholds()
                    if max(float(row["total_value_base"]) for row in cluster)
                    < threshold
                    <= combined
                ]
                severity = context.escalate_severity(self.base_severity, combined)
                findings.append(
                    self.make_finding(
                        po_number=str(anchor["po_number"]),
                        supplier_id=supplier_id,
                        supplier_name=anchor.get("supplier_name"),
                        severity=severity,
                        explanation=(
                            f"{len(cluster)} purchase orders were raised on supplier {supplier_id} "
                            f"within {window_days} day(s), each below "
                            f"{max_individual:,.0f} {context.base_currency}, "
                            f"but together worth {combined:,.2f} {context.base_currency}. "
                            + (
                                f"The combined value crosses the "
                                f"{crossed[0]:,.0f} {context.base_currency} approval threshold that "
                                "no individual order reached."
                                if crossed
                                else "Splitting demand this way bypasses volume bundling."
                            )
                        ),
                        evidence={
                            "purchase_orders": list(po_numbers),
                            "order_count": len(cluster),
                            "combined_value_base": round(combined, 2),
                            "largest_single_value_base": round(
                                max(float(row["total_value_base"]) for row in cluster), 2
                            ),
                            "window_start": anchor["order_date"],
                            "window_end": window_end,
                            "crossed_approval_thresholds": crossed,
                            "base_currency": context.base_currency,
                            "threshold_window_days": window_days,
                            "threshold_min_order_count": min_orders,
                            "threshold_combined_value_base": combined_threshold,
                        },
                        exposure=combined,
                    )
                )
        return findings


class ApprovalThresholdProximityRule(BaseRule):
    """PO-R004: order value parked just under a release threshold."""

    rule_id = "PO-R004"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        headers = context.po_header_values
        if headers.empty:
            return []

        proximity_pct = float(self.param("proximity_pct", 3.0))
        min_threshold = float(self.param("min_threshold_base", 0.0))
        thresholds = [t for t in context.config.sorted_approval_thresholds() if t >= min_threshold]
        if not thresholds:
            return []

        findings: list[RuleFinding] = []
        for row in headers.to_dict("records"):
            value = float(row["total_value_base"] or 0.0)
            if value <= 0:
                continue
            for threshold in thresholds:
                if value >= threshold:
                    continue
                gap_pct = (threshold - value) / threshold * 100.0
                if gap_pct > proximity_pct:
                    continue
                findings.append(
                    self.make_finding(
                        po_number=row["po_number"],
                        supplier_id=row.get("supplier_id"),
                        supplier_name=row.get("supplier_name"),
                        severity=context.escalate_severity(self.base_severity, value),
                        explanation=(
                            f"Purchase order {row['po_number']} is worth "
                            f"{value:,.2f} {context.base_currency}, which is only {gap_pct:.2f}% "
                            f"below the {threshold:,.0f} {context.base_currency} approval "
                            "threshold. Values that consistently stop just short of a release "
                            "level are a standard indicator of threshold avoidance."
                        ),
                        evidence={
                            "po_number": row["po_number"],
                            "order_value_base": round(value, 2),
                            "approval_threshold_base": threshold,
                            "gap_to_threshold_base": round(threshold - value, 2),
                            "gap_pct": round(gap_pct, 3),
                            "base_currency": context.base_currency,
                            "threshold_proximity_pct": proximity_pct,
                        },
                        exposure=value,
                    )
                )
                break
        return findings
