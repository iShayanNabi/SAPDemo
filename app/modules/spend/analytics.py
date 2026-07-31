"""Spend breakdowns that power the charts and the drill-down tables.

Each function returns plain dictionaries so the same payload serves the
Streamlit page today and a React dashboard later. Every breakdown carries the
``dimension`` and the ``value`` of each row, which is what makes drill-down
work: the UI sends those two back to the transactions endpoint and gets exactly
the lines behind the bar the user clicked.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.modules.spend.metrics import SupplierSpend, _safe_pct
from app.modules.spend.thresholds import SpendConfig

ANALYTICS_VERSION = "1.0.0"

#: Breakdown key -> canonical column it groups by. Also the set of dimensions
#: the drill-down endpoint accepts.
BREAKDOWN_DIMENSIONS: dict[str, str] = {
    "supplier": "supplier_id",
    "category": "category",
    "subcategory": "subcategory",
    "material_group": "material_group",
    "material": "material",
    "plant": "plant",
    "company_code": "company_code",
    "purchasing_org": "purchasing_org",
    "purchasing_group": "purchasing_group",
    "currency": "currency",
    "spend_month": "spend_month",
}


def _group_breakdown(
    frame: pd.DataFrame,
    column: str,
    dimension: str,
    *,
    top_n: int | None = None,
    label_column: str | None = None,
) -> list[dict[str, Any]]:
    """Aggregate spend by one column and return sorted, share-annotated rows."""
    if frame.empty or column not in frame.columns:
        return []

    total = float(frame["spend_base"].sum())
    rows: list[dict[str, Any]] = []
    for value, group in frame.groupby(frame[column].fillna("(not set)")):
        spend = float(group["spend_base"].sum())
        label = None
        if label_column and label_column in group.columns:
            labels = group[label_column].dropna().unique()
            label = str(labels[0]) if len(labels) else None
        rows.append(
            {
                "dimension": dimension,
                "value": str(value),
                "label": label,
                "spend_base": round(spend, 2),
                "share_pct": _safe_pct(spend, total),
                "transaction_count": int(len(group)),
                "purchase_order_count": int(group["po_number"].nunique()),
                "supplier_count": int(group["supplier_id"].nunique()),
                "contracted_spend_base": round(
                    float(group.loc[group["is_contracted"], "spend_base"].sum()), 2
                ),
                "maverick_spend_base": round(
                    float(group.loc[group["is_maverick"], "spend_base"].sum()), 2
                ),
            }
        )

    rows.sort(key=lambda r: r["spend_base"], reverse=True)
    return rows[:top_n] if top_n else rows


def monthly_spend(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Spend per calendar month, oldest first, with a month-over-month delta."""
    if frame.empty:
        return []
    dated = frame[frame["spend_month"].notna()]
    if dated.empty:
        return []

    rows: list[dict[str, Any]] = []
    for month, group in dated.groupby("spend_month"):
        rows.append(
            {
                "dimension": "spend_month",
                "value": str(month),
                "spend_base": round(float(group["spend_base"].sum()), 2),
                "transaction_count": int(len(group)),
                "purchase_order_count": int(group["po_number"].nunique()),
                "supplier_count": int(group["supplier_id"].nunique()),
                "contracted_spend_base": round(
                    float(group.loc[group["is_contracted"], "spend_base"].sum()), 2
                ),
                "maverick_spend_base": round(
                    float(group.loc[group["is_maverick"], "spend_base"].sum()), 2
                ),
            }
        )
    rows.sort(key=lambda r: r["value"])

    previous: float | None = None
    for row in rows:
        row["change_vs_previous_pct"] = (
            None if previous in (None, 0) else round((row["spend_base"] - previous) / previous * 100.0, 2)
        )
        previous = row["spend_base"]
    return rows


def spend_by_supplier(
    supplier_rows: list[SupplierSpend], top_n: int | None = None
) -> list[dict[str, Any]]:
    """Supplier roll-up rows, already ranked by spend."""
    rows = [row.to_dict() | {"dimension": "supplier", "value": row.supplier_id}
            for row in supplier_rows]
    return rows[:top_n] if top_n else rows


def tail_spend_suppliers(supplier_rows: list[SupplierSpend]) -> list[dict[str, Any]]:
    """Only the suppliers classified as tail, smallest first."""
    tail = [row.to_dict() | {"dimension": "supplier", "value": row.supplier_id}
            for row in supplier_rows if row.is_tail]
    tail.sort(key=lambda r: r["spend_base"])
    return tail


def supplier_concentration(
    frame: pd.DataFrame, config: SpendConfig
) -> list[dict[str, Any]]:
    """Categories where a single supplier holds an outsized share.

    Reported for material groups that clear the configured minimum spend, so a
    tiny category with one supplier does not generate noise.
    """
    if frame.empty or "material_group" not in frame.columns:
        return []

    settings = config.concentration
    rows: list[dict[str, Any]] = []
    for group_value, group in frame.groupby(frame["material_group"].fillna("(not set)")):
        group_spend = float(group["spend_base"].sum())
        if group_spend < settings.min_category_spend_base:
            continue
        by_supplier = group.groupby("supplier_id")["spend_base"].sum().sort_values(ascending=False)
        if by_supplier.empty:
            continue
        top_supplier = str(by_supplier.index[0])
        top_share = _safe_pct(float(by_supplier.iloc[0]), group_spend)
        names = group.loc[group["supplier_id"] == top_supplier, "supplier_name"].dropna().unique()
        rows.append(
            {
                "dimension": "material_group",
                "value": str(group_value),
                "group_spend_base": round(group_spend, 2),
                "supplier_count": int(by_supplier.size),
                "top_supplier_id": top_supplier,
                "top_supplier_name": str(names[0]) if len(names) else None,
                "top_supplier_spend_base": round(float(by_supplier.iloc[0]), 2),
                "top_supplier_share_pct": top_share,
                "exceeds_warning_threshold": top_share >= settings.category_concentration_warning_pct,
                "warning_threshold_pct": settings.category_concentration_warning_pct,
            }
        )
    rows.sort(key=lambda r: (not r["exceeds_warning_threshold"], -r["group_spend_base"]))
    return rows


def contract_leakage(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Suppliers bought from both on and off contract.

    Leakage is the non-contracted spend with a supplier that *does* hold a
    contract - the clearest, least arguable form of contract non-compliance.
    """
    if frame.empty:
        return []

    rows: list[dict[str, Any]] = []
    for supplier_id, group in frame.groupby("supplier_id"):
        contracted = float(group.loc[group["is_contracted"], "spend_base"].sum())
        leaked = float(group.loc[~group["is_contracted"], "spend_base"].sum())
        if contracted <= 0 or leaked <= 0:
            continue
        names = group["supplier_name"].dropna().unique()
        supplier_total = contracted + leaked
        rows.append(
            {
                "dimension": "supplier",
                "value": str(supplier_id),
                "supplier_name": str(names[0]) if len(names) else None,
                "total_spend_base": round(supplier_total, 2),
                "contracted_spend_base": round(contracted, 2),
                "leaked_spend_base": round(leaked, 2),
                "leakage_share_pct": _safe_pct(leaked, supplier_total),
                "leaked_transaction_count": int((~group["is_contracted"]).sum()),
            }
        )
    rows.sort(key=lambda r: r["leaked_spend_base"], reverse=True)
    return rows


def maverick_spend_breakdown(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Maverick spend grouped by supplier, with its share of that supplier."""
    if frame.empty:
        return []

    maverick = frame[frame["is_maverick"]]
    if maverick.empty:
        return []

    supplier_totals = frame.groupby("supplier_id")["spend_base"].sum()
    rows: list[dict[str, Any]] = []
    for supplier_id, group in maverick.groupby("supplier_id"):
        spend = float(group["spend_base"].sum())
        names = group["supplier_name"].dropna().unique()
        rows.append(
            {
                "dimension": "supplier",
                "value": str(supplier_id),
                "supplier_name": str(names[0]) if len(names) else None,
                "maverick_spend_base": round(spend, 2),
                "supplier_total_spend_base": round(float(supplier_totals.get(supplier_id, 0.0)), 2),
                "maverick_share_of_supplier_pct": _safe_pct(
                    spend, float(supplier_totals.get(supplier_id, 0.0))
                ),
                "transaction_count": int(len(group)),
                "top_category": _most_common(group, "category"),
            }
        )
    rows.sort(key=lambda r: r["maverick_spend_base"], reverse=True)
    return rows


def purchase_price_variance(frame: pd.DataFrame, config: SpendConfig) -> list[dict[str, Any]]:
    """Per-material purchase price variance against the configured basis."""
    if frame.empty or "material" not in frame.columns:
        return []

    settings = config.price_variance
    rows: list[dict[str, Any]] = []
    for material, group in frame.groupby(frame["material"].dropna()):
        prices = [
            float(p) for p in group["current_price_base"]
            if p is not None and not pd.isna(p) and float(p) > 0
        ]
        if len(prices) < settings.min_observations:
            continue

        baselines = [
            float(b) for b in group["baseline_price_base"]
            if b is not None and not pd.isna(b) and float(b) > 0
        ]
        if baselines:
            basis_value = sum(baselines) / len(baselines)
            basis = "baseline_price"
        else:
            basis_value = float(pd.Series(prices).median())
            basis = "material_median"

        minimum, maximum = min(prices), max(prices)
        spread_pct = _safe_pct(maximum - minimum, minimum) if minimum else 0.0

        variance_total = 0.0
        for current, quantity, line_value in zip(
            group["current_price_base"], group["quantity"], group["spend_base"]
        ):
            if current is None or pd.isna(current):
                continue
            if float(line_value or 0.0) < settings.min_line_value_base:
                continue
            units = 0.0 if quantity is None or pd.isna(quantity) else float(quantity)
            variance_total += (float(current) - basis_value) * units

        variance_pct = _safe_pct(float(maximum) - basis_value, basis_value)
        rows.append(
            {
                "dimension": "material",
                "value": str(material),
                "material_description": _most_common(group, "material_description"),
                "comparison_basis": basis,
                "basis_price_base": round(basis_value, 4),
                "min_price_base": round(minimum, 4),
                "max_price_base": round(maximum, 4),
                "price_spread_pct": spread_pct,
                "variance_base": round(variance_total, 2),
                "max_variance_pct": variance_pct,
                "observation_count": len(prices),
                "supplier_count": int(group["supplier_id"].nunique()),
                "spend_base": round(float(group["spend_base"].sum()), 2),
                "exceeds_alert_threshold": spread_pct >= settings.variance_alert_pct,
                "alert_threshold_pct": settings.variance_alert_pct,
            }
        )
    rows.sort(key=lambda r: r["variance_base"], reverse=True)
    return rows


def top_materials(frame: pd.DataFrame, top_n: int = 10) -> list[dict[str, Any]]:
    """Highest spend materials, with their description and supplier count."""
    return _group_breakdown(
        frame, "material", "material", top_n=top_n, label_column="material_description"
    )


def _most_common(group: pd.DataFrame, column: str) -> str | None:
    """Most frequent non-null value of a column inside a group."""
    if column not in group.columns:
        return None
    values = group[column].dropna()
    if values.empty:
        return None
    return str(values.mode().iloc[0])


def build_analytics(
    frame: pd.DataFrame,
    config: SpendConfig,
    supplier_rows: list[SupplierSpend],
    top_n: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Produce every breakdown the dashboard needs, in one pass."""
    limit = top_n or config.reporting.top_n_default
    return {
        "monthly_spend": monthly_spend(frame),
        "spend_by_supplier": spend_by_supplier(supplier_rows, top_n=limit),
        "spend_by_category": _group_breakdown(frame, "category", "category"),
        "spend_by_subcategory": _group_breakdown(frame, "subcategory", "subcategory", top_n=limit),
        "spend_by_material_group": _group_breakdown(frame, "material_group", "material_group"),
        "spend_by_plant": _group_breakdown(frame, "plant", "plant"),
        "spend_by_company_code": _group_breakdown(frame, "company_code", "company_code"),
        "spend_by_purchasing_org": _group_breakdown(frame, "purchasing_org", "purchasing_org"),
        "spend_by_purchasing_group": _group_breakdown(frame, "purchasing_group", "purchasing_group"),
        "top_materials": top_materials(frame, top_n=limit),
        "tail_spend_suppliers": tail_spend_suppliers(supplier_rows),
        "supplier_concentration": supplier_concentration(frame, config),
        "contract_leakage": contract_leakage(frame),
        "maverick_spend": maverick_spend_breakdown(frame),
        "purchase_price_variance": purchase_price_variance(frame, config),
    }
