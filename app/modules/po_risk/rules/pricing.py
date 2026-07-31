"""Pricing rules.

* **PO-R005** unusual unit price increase against the previous purchase of the
  same material from the same supplier.
* **PO-R006** price variance against the median price paid for the material
  across all suppliers in the dataset.

Both rules compare *base currency* prices so that a EUR order and a USD order
for the same material are comparable.
"""

from __future__ import annotations


from app.modules.po_risk.rules.base import BaseRule, RuleContext, RuleFinding


class UnitPriceIncreaseRule(BaseRule):
    """PO-R005: price jump versus the previous order of the same material."""

    rule_id = "PO-R005"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        increase_pct = float(self.param("increase_pct", 20.0))
        min_previous_price = float(self.param("min_previous_price", 0.0))
        lookback_days = int(self.param("lookback_days", 365))

        rows = context.priced_rows.dropna(subset=["material", "supplier_id", "order_date"])
        if rows.empty:
            return []

        findings: list[RuleFinding] = []
        for (material, supplier_id), group in rows.groupby(["material", "supplier_id"]):
            ordered = group.sort_values(["order_date", "po_number", "po_item"]).to_dict("records")
            if len(ordered) < 2:
                continue
            for index in range(1, len(ordered)):
                current, previous = ordered[index], ordered[index - 1]
                previous_price = float(previous["unit_price_base"])
                current_price = float(current["unit_price_base"])
                if previous_price < min_previous_price or previous_price <= 0:
                    continue
                days_between = (current["order_date"] - previous["order_date"]).days
                if days_between > lookback_days:
                    continue
                change_pct = (current_price - previous_price) / previous_price * 100.0
                if change_pct < increase_pct:
                    continue

                quantity = float(current["quantity"] or 0.0)
                exposure = (current_price - previous_price) * quantity
                findings.append(
                    self.make_finding(
                        po_number=current["po_number"],
                        po_item=current["po_item"],
                        supplier_id=supplier_id,
                        supplier_name=current.get("supplier_name"),
                        severity=context.escalate_severity(self.base_severity, exposure),
                        explanation=(
                            f"The unit price for material {material} from supplier {supplier_id} "
                            f"rose {change_pct:.1f}% (from {previous_price:,.2f} to "
                            f"{current_price:,.2f} {context.base_currency}) between purchase order "
                            f"{previous['po_number']} and {current['po_number']}, "
                            f"{days_between} day(s) apart. The configured alert level is "
                            f"{increase_pct:.0f}%."
                        ),
                        evidence={
                            "material": material,
                            "previous_po_number": previous["po_number"],
                            "previous_unit_price_base": round(previous_price, 4),
                            "previous_order_date": previous["order_date"],
                            "current_unit_price_base": round(current_price, 4),
                            "current_order_date": current["order_date"],
                            "increase_pct": round(change_pct, 2),
                            "quantity": quantity,
                            "days_between_orders": int(days_between),
                            "base_currency": context.base_currency,
                            "threshold_increase_pct": increase_pct,
                        },
                        exposure=exposure,
                    )
                )
        return findings


class MaterialPriceVarianceRule(BaseRule):
    """PO-R006: price paid deviates from the material median."""

    rule_id = "PO-R006"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        deviation_pct = float(self.param("deviation_pct", 25.0))
        min_observations = int(self.param("min_observations", 4))
        min_unit_price = float(self.param("min_unit_price", 0.0))

        stats = context.material_price_stats
        if stats.empty:
            return []

        eligible = stats[stats["observations"] >= min_observations]
        if eligible.empty:
            return []

        rows = context.priced_rows.dropna(subset=["material"])
        rows = rows[rows["material"].isin(eligible.index)]

        findings: list[RuleFinding] = []
        for row in rows.to_dict("records"):
            material = row["material"]
            median_price = float(eligible.loc[material, "median_price"])
            unit_price = float(row["unit_price_base"])
            if median_price <= 0 or unit_price < min_unit_price:
                continue
            variance = (unit_price - median_price) / median_price * 100.0
            if variance < deviation_pct:
                continue

            quantity = float(row["quantity"] or 0.0)
            exposure = (unit_price - median_price) * quantity
            findings.append(
                self.make_finding(
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    supplier_id=row["supplier_id"],
                    supplier_name=row["supplier_name"],
                    severity=context.escalate_severity(self.base_severity, exposure),
                    explanation=(
                        f"Material {material} was purchased at {unit_price:,.2f} "
                        f"{context.base_currency} per unit, {variance:.1f}% above the median of "
                        f"{median_price:,.2f} {context.base_currency} observed across "
                        f"{int(eligible.loc[material, 'observations'])} line items in this dataset. "
                        f"Paying the median price would have saved approximately "
                        f"{exposure:,.2f} {context.base_currency} on this line."
                    ),
                    evidence={
                        "material": material,
                        "unit_price_base": round(unit_price, 4),
                        "median_unit_price_base": round(median_price, 4),
                        "variance_pct": round(variance, 2),
                        "observations": int(eligible.loc[material, "observations"]),
                        "min_price_base": round(float(eligible.loc[material, "min_price"]), 4),
                        "max_price_base": round(float(eligible.loc[material, "max_price"]), 4),
                        "quantity": quantity,
                        "base_currency": context.base_currency,
                        "threshold_deviation_pct": deviation_pct,
                        "benchmark_method": "median unit price per material in the uploaded dataset",
                    },
                    exposure=exposure,
                )
            )
        return findings
