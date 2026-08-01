"""Data quality rules.

* **PO-R013** quantity anomalies (non-positive or extreme versus the material median).
* **PO-R014** currency anomalies against the dominant currency of a company code.
* **PO-R015** missing values in fields required for reliable processing.
"""

from __future__ import annotations

import pandas as pd

from app.modules.po_risk.field_definitions import FIELD_BY_NAME
from app.modules.po_risk.rules.base import BaseRule, RuleContext, RuleFinding
from app.schemas.common import Severity


class QuantityAnomalyRule(BaseRule):
    """PO-R013: implausible ordered quantities."""

    rule_id = "PO-R013"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        min_valid = float(self.param("min_valid_quantity", 0.0))
        outlier_multiple = float(self.param("outlier_multiple_of_median", 20.0))
        min_observations = int(self.param("min_observations", 4))

        frame = context.frame
        stats = context.material_quantity_stats
        findings: list[RuleFinding] = []

        rows = frame[frame["quantity"].notna()]
        for row in rows.to_dict("records"):
            quantity = float(row["quantity"])
            value = float(row["total_value_base"] or 0.0)

            if quantity < min_valid:
                findings.append(
                    self.make_finding(
                        po_number=row["po_number"],
                        po_item=row["po_item"],
                        supplier_id=row.get("supplier_id"),
                        supplier_name=row.get("supplier_name"),
                        severity=context.escalate_severity(Severity.HIGH, value),
                        confidence=1.0,
                        explanation=(
                            f"Item {row['po_item']} of purchase order {row['po_number']} has a "
                            f"quantity of {quantity:g}, which is not a valid order quantity "
                            f"(minimum {min_valid:g}). The line cannot be received as it stands."
                        ),
                        evidence={
                            "quantity": quantity,
                            "unit_of_measure": row.get("unit_of_measure"),
                            "anomaly_type": "non_positive_quantity",
                            "threshold_min_valid_quantity": min_valid,
                        },
                        exposure=abs(value),
                    )
                )
                continue

            material = row.get("material")
            if material is None or material not in stats.index:
                continue
            observations = int(stats.loc[material, "observations"])
            median_quantity = float(stats.loc[material, "median_quantity"])
            if observations < min_observations or median_quantity <= 0:
                continue
            if quantity < median_quantity * outlier_multiple:
                continue

            findings.append(
                self.make_finding(
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    supplier_id=row.get("supplier_id"),
                    supplier_name=row.get("supplier_name"),
                    severity=context.escalate_severity(self.base_severity, value),
                    explanation=(
                        f"Item {row['po_item']} of purchase order {row['po_number']} orders "
                        f"{quantity:g} {row.get('unit_of_measure') or 'units'} of material "
                        f"{material}, which is {quantity / median_quantity:.1f}x the median order "
                        f"quantity of {median_quantity:g} across {observations} line items. "
                        "A keying error (an extra digit or a unit of measure mix-up) is the most "
                        "common cause."
                    ),
                    evidence={
                        "material": material,
                        "quantity": quantity,
                        "median_quantity": median_quantity,
                        "multiple_of_median": round(quantity / median_quantity, 2),
                        "observations": observations,
                        "unit_of_measure": row.get("unit_of_measure"),
                        "anomaly_type": "quantity_outlier",
                        "threshold_outlier_multiple": outlier_multiple,
                    },
                    exposure=value,
                )
            )
        return findings


class CurrencyAnomalyRule(BaseRule):
    """PO-R014: document currency deviating from the company code norm."""

    rule_id = "PO-R014"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        dominant_share = float(self.param("dominant_share_pct", 80.0))
        min_observations = int(self.param("min_observations", 5))
        expected_map = {
            str(k): str(v).upper()
            for k, v in context.config.expected_currencies_by_company_code.items()
        }

        rows = context.frame.dropna(subset=["currency", "company_code"])
        if rows.empty:
            return []

        findings: list[RuleFinding] = []
        for company_code, group in rows.groupby("company_code"):
            counts = group["currency"].value_counts()
            total = int(counts.sum())
            if total < min_observations:
                continue

            configured = expected_map.get(str(company_code))
            observed_dominant = str(counts.index[0])
            observed_share = float(counts.iloc[0]) / total * 100.0

            if configured:
                expected_currency = configured
                basis = "configured company code currency"
            elif observed_share >= dominant_share:
                expected_currency = observed_dominant
                basis = f"dominant currency in the dataset ({observed_share:.0f}% of lines)"
            else:
                continue

            deviating = group[group["currency"] != expected_currency]
            for row in deviating.to_dict("records"):
                value = float(row["total_value_base"] or 0.0)
                findings.append(
                    self.make_finding(
                        po_number=row["po_number"],
                        po_item=row["po_item"],
                        supplier_id=row.get("supplier_id"),
                        supplier_name=row.get("supplier_name"),
                        severity=context.escalate_severity(self.base_severity, value),
                        explanation=(
                            f"Purchase order {row['po_number']} in company code {company_code} is "
                            f"issued in {row['currency']}, while {expected_currency} is expected "
                            f"({basis}). A wrong document currency misstates the order value and "
                            "the commitment in the ledger."
                        ),
                        evidence={
                            "company_code": company_code,
                            "document_currency": row["currency"],
                            "expected_currency": expected_currency,
                            "basis": basis,
                            "line_value_document_currency": row.get("total_value"),
                            "line_value_base": round(value, 2),
                            "base_currency": context.base_currency,
                            "threshold_dominant_share_pct": dominant_share,
                        },
                        exposure=value,
                    )
                )
        return findings


class MissingRequiredFieldsRule(BaseRule):
    """PO-R015: mandatory or governance-relevant fields left empty."""

    rule_id = "PO-R015"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        critical_fields = list(self.param("critical_fields", []))
        watch_fields = list(self.param("watch_fields", []))
        frame = context.frame

        findings: list[RuleFinding] = []
        for row in frame.to_dict("records"):
            missing_critical = [
                f for f in critical_fields if f in frame.columns and _is_missing(row.get(f))
            ]
            missing_watch = [
                f for f in watch_fields if f in frame.columns and _is_missing(row.get(f))
            ]
            if not missing_critical and not missing_watch:
                continue

            value = float(row.get("total_value_base") or 0.0)
            severity = Severity.HIGH if missing_critical else self.base_severity
            labels = [
                FIELD_BY_NAME[f].label for f in (*missing_critical, *missing_watch) if f in FIELD_BY_NAME
            ]
            findings.append(
                self.make_finding(
                    po_number=row.get("po_number"),
                    po_item=row.get("po_item"),
                    supplier_id=row.get("supplier_id"),
                    supplier_name=row.get("supplier_name"),
                    severity=context.escalate_severity(severity, value),
                    explanation=(
                        f"Row {row.get('row_number')} (purchase order "
                        f"{row.get('po_number') or 'unknown'}) is missing "
                        f"{len(labels)} field(s): {', '.join(labels)}. Incomplete documents cannot "
                        "be matched automatically and weaken downstream reporting."
                    ),
                    evidence={
                        "row_number": row.get("row_number"),
                        "missing_critical_fields": missing_critical,
                        "missing_watch_fields": missing_watch,
                        "line_value_base": round(value, 2),
                        "base_currency": context.base_currency,
                    },
                    exposure=value if missing_critical else 0.0,
                )
            )
        return findings


def _is_missing(value: object) -> bool:
    """Return whether a cell counts as empty."""
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False
