"""Deterministic spend metrics.

Every number the dashboard shows is calculated here with ordinary pandas and
Python arithmetic. No AI is involved in any figure - the AI layer only writes
prose *about* these results.

All monetary values are in the configured base currency, so a dataset mixing
EUR, USD and GBP aggregates correctly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from app.modules.spend.thresholds import SpendConfig

METRICS_VERSION = "1.0.0"


@dataclass
class SupplierSpend:
    """Spend roll-up for one supplier, including its Pareto classification."""

    supplier_id: str
    supplier_name: str | None
    spend_base: float
    spend_share_pct: float
    cumulative_share_pct: float
    transaction_count: int
    purchase_order_count: int
    material_count: int
    contracted_spend_base: float
    non_contracted_spend_base: float
    maverick_spend_base: float
    is_preferred: bool
    is_tail: bool
    rank: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SpendMetrics:
    """The complete set of headline spend metrics."""

    # Volume
    total_spend: float = 0.0
    purchase_order_count: int = 0
    line_item_count: int = 0
    supplier_count: int = 0
    average_po_value: float = 0.0
    median_po_value: float = 0.0

    # Contract coverage
    contracted_spend: float = 0.0
    non_contracted_spend: float = 0.0
    contracted_spend_pct: float = 0.0
    maverick_spend: float = 0.0
    maverick_spend_pct: float = 0.0
    spend_under_management: float = 0.0
    spend_under_management_pct: float = 0.0

    # Concentration
    supplier_concentration_hhi: float = 0.0
    supplier_concentration_level: str = "unknown"
    top_supplier_share_pct: float = 0.0
    top_supplier_id: str | None = None
    top_five_supplier_share_pct: float = 0.0
    tail_spend: float = 0.0
    tail_spend_pct: float = 0.0
    tail_supplier_count: int = 0

    # Pricing and savings
    price_variance_base: float = 0.0
    price_variance_pct: float = 0.0
    price_variance_line_count: int = 0
    estimated_savings_opportunity: float = 0.0

    # Currency split
    spend_by_currency: list[dict[str, Any]] = field(default_factory=list)

    base_currency: str = "EUR"
    metrics_version: str = METRICS_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_pct(part: float, whole: float) -> float:
    """Percentage that returns 0 instead of dividing by zero."""
    return round(part / whole * 100.0, 2) if whole else 0.0


def purchase_order_totals(frame: pd.DataFrame) -> pd.Series:
    """Total base-currency value per purchase order."""
    if frame.empty or "po_number" not in frame.columns:
        return pd.Series(dtype="float64")
    return frame.groupby("po_number")["spend_base"].sum()


def calculate_supplier_spend(
    frame: pd.DataFrame, config: SpendConfig
) -> list[SupplierSpend]:
    """Roll spend up per supplier and classify tail suppliers.

    Tail classification follows the configured Pareto rule: suppliers are ranked
    by spend and everything beyond the cumulative share threshold is tail. A
    supplier whose individual share is below the small-supplier threshold is
    always tail, even if it falls inside the cumulative band.
    """
    if frame.empty:
        return []

    settings = config.tail_spend
    total = float(frame["spend_base"].sum())

    grouped = frame.groupby("supplier_id", dropna=True)
    rows: list[SupplierSpend] = []
    for supplier_id, group in grouped:
        names = group["supplier_name"].dropna().unique()
        rows.append(
            SupplierSpend(
                supplier_id=str(supplier_id),
                supplier_name=str(names[0]) if len(names) else None,
                spend_base=round(float(group["spend_base"].sum()), 2),
                spend_share_pct=0.0,
                cumulative_share_pct=0.0,
                transaction_count=int(len(group)),
                purchase_order_count=int(group["po_number"].nunique()),
                material_count=int(group["material"].nunique()),
                contracted_spend_base=round(
                    float(group.loc[group["is_contracted"], "spend_base"].sum()), 2
                ),
                non_contracted_spend_base=round(
                    float(group.loc[~group["is_contracted"], "spend_base"].sum()), 2
                ),
                maverick_spend_base=round(
                    float(group.loc[group["is_maverick"], "spend_base"].sum()), 2
                ),
                is_preferred=bool(group["is_preferred_supplier"].any()),
                is_tail=False,
                rank=0,
            )
        )

    rows.sort(key=lambda r: r.spend_base, reverse=True)

    cumulative = 0.0
    classify = len(rows) >= settings.min_suppliers_for_classification
    for index, row in enumerate(rows, start=1):
        row.rank = index
        row.spend_share_pct = _safe_pct(row.spend_base, total)
        cumulative += row.spend_base
        row.cumulative_share_pct = _safe_pct(cumulative, total)
        if classify:
            beyond_pareto = (
                row.cumulative_share_pct > settings.cumulative_share_threshold_pct
                and index > 1
            )
            very_small = row.spend_share_pct < settings.small_supplier_share_pct
            row.is_tail = bool(beyond_pareto or very_small)
    return rows


def herfindahl_index(supplier_rows: list[SupplierSpend]) -> float:
    """Herfindahl-Hirschman Index on a 0-10,000 scale.

    Sum of squared percentage market shares. 10,000 means a single supplier
    holds all spend; a value near 0 means highly fragmented spend.
    """
    return round(sum(row.spend_share_pct**2 for row in supplier_rows), 1)


def concentration_level(hhi: float, config: SpendConfig) -> str:
    """Translate an HHI value into a configured label."""
    settings = config.concentration
    if hhi >= settings.hhi_high:
        return "high"
    if hhi >= settings.hhi_moderate:
        return "moderate"
    return "low"


def calculate_price_variance(
    frame: pd.DataFrame, config: SpendConfig
) -> tuple[float, float, int]:
    """Total purchase price variance in base currency.

    Uses the baseline price where the file supplies one. Lines without a
    baseline fall back to the median price paid for the same material, provided
    the material has at least the configured number of observations.

    Returns:
        ``(variance_base, variance_pct_of_spend, line_count)``.
    """
    if frame.empty:
        return 0.0, 0.0, 0

    settings = config.price_variance
    working = frame.copy()

    baseline = working["baseline_price_base"].astype("object")
    if settings.fallback_basis == "material_median":
        prices = working[["material", "current_price_base"]].dropna()
        counts = prices.groupby("material")["current_price_base"].count()
        medians = prices.groupby("material")["current_price_base"].median()
        eligible = set(counts[counts >= settings.min_observations].index)
        fallback = working["material"].map(
            lambda m: float(medians[m]) if m in eligible else None
        )
        baseline = [
            fb if (b is None or pd.isna(b)) else b for b, fb in zip(baseline, fallback)
        ]

    variance_total = 0.0
    line_count = 0
    for base_price, current, quantity, line_value in zip(
        baseline,
        working["current_price_base"],
        working["quantity"],
        working["spend_base"],
    ):
        if base_price is None or current is None or pd.isna(base_price) or pd.isna(current):
            continue
        if not base_price or float(line_value or 0.0) < settings.min_line_value_base:
            continue
        units = 0.0 if quantity is None or pd.isna(quantity) else float(quantity)
        difference = (float(current) - float(base_price)) * units
        if difference:
            variance_total += difference
            line_count += 1

    total_spend = float(working["spend_base"].sum())
    return round(variance_total, 2), _safe_pct(variance_total, total_spend), line_count


def spend_by_currency(frame: pd.DataFrame, config: SpendConfig) -> list[dict[str, Any]]:
    """Spend split by document currency, with the base-currency equivalent."""
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    total_base = float(frame["spend_base"].sum())
    for currency, group in frame.groupby(frame["currency"].fillna("(not set)")):
        base_value = float(group["spend_base"].sum())
        rows.append(
            {
                "currency": str(currency),
                "spend_document_currency": round(float(group["total_value"].sum()), 2),
                "spend_base": round(base_value, 2),
                "share_pct": _safe_pct(base_value, total_base),
                "transaction_count": int(len(group)),
                "conversion_rate": config.conversion_rate(
                    None if currency == "(not set)" else str(currency)
                ),
            }
        )
    rows.sort(key=lambda r: r["spend_base"], reverse=True)
    return rows


def calculate_metrics(
    frame: pd.DataFrame,
    config: SpendConfig,
    supplier_rows: list[SupplierSpend] | None = None,
    estimated_savings: float = 0.0,
) -> SpendMetrics:
    """Calculate every headline metric for the given (already filtered) frame."""
    metrics = SpendMetrics(base_currency=config.base_currency)
    if frame.empty:
        return metrics

    suppliers = supplier_rows if supplier_rows is not None else calculate_supplier_spend(frame, config)

    total = float(frame["spend_base"].sum())
    po_totals = purchase_order_totals(frame)

    metrics.total_spend = round(total, 2)
    metrics.purchase_order_count = int(frame["po_number"].nunique())
    metrics.line_item_count = int(len(frame))
    metrics.supplier_count = int(frame["supplier_id"].nunique())
    metrics.average_po_value = round(float(po_totals.mean()), 2) if len(po_totals) else 0.0
    metrics.median_po_value = round(float(po_totals.median()), 2) if len(po_totals) else 0.0

    contracted = float(frame.loc[frame["is_contracted"], "spend_base"].sum())
    metrics.contracted_spend = round(contracted, 2)
    metrics.non_contracted_spend = round(total - contracted, 2)
    metrics.contracted_spend_pct = _safe_pct(contracted, total)

    maverick = float(frame.loc[frame["is_maverick"], "spend_base"].sum())
    metrics.maverick_spend = round(maverick, 2)
    metrics.maverick_spend_pct = _safe_pct(maverick, total)

    managed = float(frame.loc[frame["is_under_management"], "spend_base"].sum())
    metrics.spend_under_management = round(managed, 2)
    metrics.spend_under_management_pct = _safe_pct(managed, total)

    metrics.supplier_concentration_hhi = herfindahl_index(suppliers)
    metrics.supplier_concentration_level = concentration_level(
        metrics.supplier_concentration_hhi, config
    )
    if suppliers:
        metrics.top_supplier_share_pct = suppliers[0].spend_share_pct
        metrics.top_supplier_id = suppliers[0].supplier_id
        metrics.top_five_supplier_share_pct = round(
            sum(row.spend_share_pct for row in suppliers[:5]), 2
        )

    tail_suppliers = [row for row in suppliers if row.is_tail]
    tail_total = sum(row.spend_base for row in tail_suppliers)
    metrics.tail_spend = round(tail_total, 2)
    metrics.tail_spend_pct = _safe_pct(tail_total, total)
    metrics.tail_supplier_count = len(tail_suppliers)

    variance, variance_pct, variance_lines = calculate_price_variance(frame, config)
    metrics.price_variance_base = variance
    metrics.price_variance_pct = variance_pct
    metrics.price_variance_line_count = variance_lines

    metrics.estimated_savings_opportunity = round(float(estimated_savings), 2)
    metrics.spend_by_currency = spend_by_currency(frame, config)
    return metrics


def methodology(config: SpendConfig) -> dict[str, Any]:
    """Describe how the metrics were produced, for the UI and the export."""
    maverick = config.classification.maverick_definition
    managed = config.classification.spend_under_management_definition
    return {
        "calculation_basis": "deterministic pandas aggregation, no AI involvement",
        "metrics_version": METRICS_VERSION,
        "config_version": config.config_version,
        "base_currency": config.base_currency,
        "currency_rates": config.currency_rates,
        "maverick_definition": maverick.description,
        "spend_under_management_definition": managed.description,
        "tail_spend_definition": (
            f"Suppliers beyond {config.tail_spend.cumulative_share_threshold_pct:.0f}% cumulative "
            f"spend, or holding less than {config.tail_spend.small_supplier_share_pct:.2f}% "
            "of total spend individually."
        ),
        "concentration_definition": (
            "Herfindahl-Hirschman Index: sum of squared supplier spend shares on a 0-10,000 "
            f"scale. Moderate from {config.concentration.hhi_moderate:.0f}, "
            f"high from {config.concentration.hhi_high:.0f}."
        ),
        "price_variance_definition": (
            f"(price paid - {config.price_variance.comparison_basis}) x quantity, in base "
            f"currency, for lines worth at least "
            f"{config.price_variance.min_line_value_base:,.0f}. Lines without a baseline fall "
            f"back to the material median once a material has "
            f"{config.price_variance.min_observations} or more observations."
        ),
        "savings_disclaimer": config.reporting.opportunity_disclaimer,
        "data_disclaimer": (
            "All figures describe the uploaded file only. This application is not connected "
            "to any SAP system and no result has been validated in a live SAP environment."
        ),
    }
