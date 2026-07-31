"""Contract compliance rules.

* **PO-R007** off-contract purchase - the material is normally bought under an
  outline agreement from this supplier, but this line has no contract.
* **PO-R008** missing contract reference on a significant order.
* **PO-R016** payment terms that deviate from the approved list.
* **PO-R019** maverick spend - the material is under contract with supplier A
  and was bought from supplier B without any contract.
"""

from __future__ import annotations

import pandas as pd

from app.modules.po_risk.rules.base import BaseRule, RuleContext, RuleFinding


class OffContractPurchaseRule(BaseRule):
    """PO-R007: no contract reference although the same supplier/material pair is contracted."""

    rule_id = "PO-R007"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        min_observations = int(self.param("min_contract_observations", 2))
        min_value = float(self.param("min_total_value_base", 0.0))
        contracted = context.contracted_material_suppliers
        if not contracted:
            return []

        rows = context.frame[
            context.frame["contract_number"].isna() & context.frame["material"].notna()
        ]

        findings: list[RuleFinding] = []
        for row in rows.to_dict("records"):
            material = str(row["material"])
            supplier_id = row.get("supplier_id")
            suppliers = contracted.get(material, {})
            observations = suppliers.get(str(supplier_id), 0)
            if observations < min_observations:
                continue
            value = float(row["total_value_base"] or 0.0)
            if value < min_value:
                continue

            findings.append(
                self.make_finding(
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    supplier_id=supplier_id,
                    supplier_name=row.get("supplier_name"),
                    severity=context.escalate_severity(self.base_severity, value),
                    explanation=(
                        f"Material {material} was ordered from supplier {supplier_id} without a "
                        f"contract reference, although {observations} other line item(s) in this "
                        "dataset buy the same material from the same supplier under an outline "
                        "agreement. Contracted conditions were therefore probably not applied."
                    ),
                    evidence={
                        "material": material,
                        "supplier_id": supplier_id,
                        "contracted_lines_for_pair": observations,
                        "line_value_base": round(value, 2),
                        "contract_number": None,
                        "base_currency": context.base_currency,
                        "threshold_min_contract_observations": min_observations,
                    },
                    exposure=value,
                )
            )
        return findings


class MissingContractReferenceRule(BaseRule):
    """PO-R008: significant order value without any contract reference."""

    rule_id = "PO-R008"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        min_value = float(self.param("min_total_value_base", 25000.0))
        rows = context.frame[
            context.frame["contract_number"].isna()
            & (pd.to_numeric(context.frame["total_value_base"], errors="coerce") >= min_value)
        ]

        findings: list[RuleFinding] = []
        for row in rows.to_dict("records"):
            value = float(row["total_value_base"])
            findings.append(
                self.make_finding(
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    supplier_id=row.get("supplier_id"),
                    supplier_name=row.get("supplier_name"),
                    severity=context.escalate_severity(self.base_severity, value),
                    explanation=(
                        f"Line item {row['po_item']} of purchase order {row['po_number']} is worth "
                        f"{value:,.2f} {context.base_currency} but carries no outline agreement "
                        f"reference. The configured review level for free-text purchases is "
                        f"{min_value:,.0f} {context.base_currency}."
                    ),
                    evidence={
                        "line_value_base": round(value, 2),
                        "material": row.get("material"),
                        "material_group": row.get("material_group"),
                        "base_currency": context.base_currency,
                        "threshold_min_total_value_base": min_value,
                    },
                    exposure=value,
                )
            )
        return findings


class UnusualPaymentTermsRule(BaseRule):
    """PO-R016: payment terms outside the approved list."""

    rule_id = "PO-R016"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        min_value = float(self.param("min_total_value_base", 0.0))
        standard = {term.strip().upper() for term in context.config.standard_payment_terms}
        if not standard:
            return []

        rows = context.frame.dropna(subset=["payment_terms"])
        findings: list[RuleFinding] = []
        for row in rows.to_dict("records"):
            terms = str(row["payment_terms"]).strip().upper()
            if terms in standard:
                continue
            value = float(row["total_value_base"] or 0.0)
            if value < min_value:
                continue

            findings.append(
                self.make_finding(
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    supplier_id=row.get("supplier_id"),
                    supplier_name=row.get("supplier_name"),
                    severity=context.escalate_severity(self.base_severity, value),
                    explanation=(
                        f"Purchase order {row['po_number']} uses payment terms '{terms}', which are "
                        f"not part of the approved set ({', '.join(sorted(standard))}). "
                        "Non-standard terms change the cash-out profile and are often agreed "
                        "outside the treasury policy."
                    ),
                    evidence={
                        "payment_terms": terms,
                        "approved_payment_terms": sorted(standard),
                        "line_value_base": round(value, 2),
                        "base_currency": context.base_currency,
                        "threshold_min_total_value_base": min_value,
                    },
                    exposure=value,
                )
            )
        return findings


class MaverickSpendRule(BaseRule):
    """PO-R019: bought off-contract from a supplier while another holds the contract."""

    rule_id = "PO-R019"

    def evaluate(self, context: RuleContext) -> list[RuleFinding]:
        min_value = float(self.param("min_total_value_base", 0.0))
        min_observations = int(self.param("min_contract_observations", 2))
        contracted = context.contracted_material_suppliers
        if not contracted:
            return []

        rows = context.frame[
            context.frame["contract_number"].isna()
            & context.frame["material"].notna()
            & context.frame["supplier_id"].notna()
        ]

        findings: list[RuleFinding] = []
        for row in rows.to_dict("records"):
            material = str(row["material"])
            supplier_id = str(row["supplier_id"])
            suppliers = contracted.get(material, {})
            other_suppliers = {
                sid: count
                for sid, count in suppliers.items()
                if sid != supplier_id and count >= min_observations
            }
            if not other_suppliers:
                continue
            # If this supplier is itself contracted for the material, PO-R007 owns the case.
            if suppliers.get(supplier_id, 0) >= min_observations:
                continue

            value = float(row["total_value_base"] or 0.0)
            if value < min_value:
                continue

            preferred = max(other_suppliers, key=lambda sid: other_suppliers[sid])
            findings.append(
                self.make_finding(
                    po_number=row["po_number"],
                    po_item=row["po_item"],
                    supplier_id=supplier_id,
                    supplier_name=row.get("supplier_name"),
                    severity=context.escalate_severity(self.base_severity, value),
                    explanation=(
                        f"Material {material} was bought from supplier {supplier_id} with no "
                        f"contract, while supplier {preferred} "
                        f"({context.supplier_name_for(preferred) or 'contracted supplier'}) supplies "
                        f"the same material under an outline agreement on "
                        f"{other_suppliers[preferred]} line item(s). This is classic maverick spend: "
                        "negotiated conditions and rebates are lost."
                    ),
                    evidence={
                        "material": material,
                        "purchased_from_supplier": supplier_id,
                        "contracted_suppliers": other_suppliers,
                        "preferred_supplier": preferred,
                        "line_value_base": round(value, 2),
                        "base_currency": context.base_currency,
                        "threshold_min_total_value_base": min_value,
                    },
                    exposure=value,
                )
            )
        return findings
