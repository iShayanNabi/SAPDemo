"""Duplication rules.

* **PO-R001** duplicate purchase orders - two different documents raised on the
  same supplier for a near identical value within a short window.
* **PO-R002** duplicate line items - the same material, quantity and price
  appearing more than once inside one purchase order.
"""

from __future__ import annotations

import pandas as pd

from app.modules.po_risk.rules.base import BaseRule, RuleContext, RuleFinding


class DuplicatePurchaseOrderRule(BaseRule):
    """PO-R001: near-identical purchase orders on the same supplier."""

    rule_id = "PO-R001"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        headers = context.po_header_values
        if headers.empty:
            return []

        window_days = int(self.param("date_window_days", 14))
        tolerance_pct = float(self.param("value_tolerance_pct", 1.0))
        min_value = float(self.param("min_total_value_base", 0.0))

        candidates = headers.dropna(subset=["supplier_id", "order_date"])
        candidates = candidates[candidates["total_value_base"] >= min_value]

        findings: list[RuleFinding] = []
        for supplier_id, group in candidates.groupby("supplier_id"):
            rows = group.sort_values(["order_date", "po_number"]).to_dict("records")
            for index, later in enumerate(rows):
                for earlier in rows[:index]:
                    days_apart = (later["order_date"] - earlier["order_date"]).days
                    if days_apart > window_days:
                        continue
                    reference = max(abs(earlier["total_value_base"]), 1e-9)
                    difference_pct = (
                        abs(later["total_value_base"] - earlier["total_value_base"]) / reference * 100.0
                    )
                    if difference_pct > tolerance_pct:
                        continue

                    exposure = float(later["total_value_base"])
                    findings.append(
                        self.make_finding(
                            po_number=later["po_number"],
                            supplier_id=supplier_id,
                            supplier_name=later.get("supplier_name"),
                            severity=context.escalate_severity(self.base_severity, exposure),
                            explanation=(
                                f"Purchase order {later['po_number']} matches purchase order "
                                f"{earlier['po_number']} on the same supplier: the values differ by "
                                f"{difference_pct:.2f}% and the orders were raised {days_apart} day(s) "
                                f"apart. This pattern usually indicates a document created twice."
                            ),
                            evidence={
                                "duplicate_po_number": later["po_number"],
                                "original_po_number": earlier["po_number"],
                                "duplicate_value_base": round(float(later["total_value_base"]), 2),
                                "original_value_base": round(float(earlier["total_value_base"]), 2),
                                "value_difference_pct": round(difference_pct, 3),
                                "days_apart": int(days_apart),
                                "base_currency": context.base_currency,
                                "threshold_value_tolerance_pct": tolerance_pct,
                                "threshold_date_window_days": window_days,
                            },
                            exposure=exposure,
                        )
                    )
                    break  # one finding per duplicated document is enough
        return findings


class DuplicateLineItemRule(BaseRule):
    """PO-R002: the same item repeated inside one purchase order."""

    rule_id = "PO-R002"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        frame = context.frame
        min_value = float(self.param("min_total_value_base", 0.0))

        rows = frame.dropna(subset=["po_number", "quantity", "unit_price"]).copy()
        if rows.empty:
            return []

        rows["_material_key"] = (
            rows["material"].fillna(rows["material_description"]).fillna("<no material>")
        )
        rows["_quantity_key"] = pd.to_numeric(rows["quantity"], errors="coerce").round(4)
        rows["_price_key"] = pd.to_numeric(rows["unit_price"], errors="coerce").round(4)

        findings: list[RuleFinding] = []
        group_keys = ["po_number", "_material_key", "_quantity_key", "_price_key"]
        for (po_number, material_key, quantity, price), group in rows.groupby(group_keys):
            if len(group) < 2:
                continue
            ordered = group.sort_values("po_item")
            first_item = ordered.iloc[0]
            for _, duplicate in ordered.iloc[1:].iterrows():
                exposure = float(duplicate["total_value_base"] or 0.0)
                if exposure < min_value:
                    continue
                findings.append(
                    self.make_finding(
                        po_number=po_number,
                        po_item=duplicate["po_item"],
                        supplier_id=duplicate["supplier_id"],
                        supplier_name=duplicate["supplier_name"],
                        severity=context.escalate_severity(self.base_severity, exposure),
                        explanation=(
                            f"Item {duplicate['po_item']} of purchase order {po_number} repeats "
                            f"item {first_item['po_item']}: same material ({material_key}), same "
                            f"quantity ({quantity:g}) and same unit price ({price:g}). The order "
                            f"therefore requests the same goods twice."
                        ),
                        evidence={
                            "po_number": po_number,
                            "duplicate_item": duplicate["po_item"],
                            "original_item": first_item["po_item"],
                            "material": None if material_key == "<no material>" else str(material_key),
                            "quantity": float(quantity),
                            "unit_price": float(price),
                            "duplicate_count": int(len(group)),
                            "line_value_base": round(exposure, 2),
                            "base_currency": context.base_currency,
                        },
                        exposure=exposure,
                    )
                )
        return findings
