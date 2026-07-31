"""Savings opportunity rules.

Six transparent, configurable models. Each one states its own arithmetic in the
``method`` field so a user can check the number rather than trust it, and each
carries the realization factor that was applied.

**These are estimates, not commitments.** Every opportunity is a modelled
figure derived from the uploaded file under the assumptions in
``config/spend_rules.json``. Nothing here has been negotiated, agreed with a
supplier, or validated in a live SAP environment - and the wording throughout
the module says so.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from app.core.logging import get_logger
from app.modules.spend.metrics import SupplierSpend, _safe_pct
from app.modules.spend.thresholds import SavingsRuleSettings, SpendConfig

logger = get_logger(__name__)

SAVINGS_ENGINE_VERSION = "1.0.0"


@dataclass
class SavingsOpportunity:
    """One modelled savings opportunity."""

    opportunity_id: str
    rule_id: str
    rule_name: str
    opportunity_type: str
    scope: str
    scope_value: str
    scope_label: str | None
    title: str
    description: str
    method: str
    addressable_spend_base: float
    gross_saving_base: float
    realization_factor: float
    estimated_saving_base: float
    confidence: float
    transaction_count: int
    supplier_count: int
    evidence: dict[str, Any] = field(default_factory=dict)
    is_estimate: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SavingsResult:
    """Everything the savings engine produced for one analysis."""

    opportunities: list[SavingsOpportunity]
    rule_executions: list[dict[str, Any]]
    rule_errors: list[dict[str, Any]]
    engine_version: str = SAVINGS_ENGINE_VERSION

    @property
    def total_estimated_saving(self) -> float:
        return round(sum(o.estimated_saving_base for o in self.opportunities), 2)

    def by_rule(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for opportunity in self.opportunities:
            totals[opportunity.rule_id] = round(
                totals.get(opportunity.rule_id, 0.0) + opportunity.estimated_saving_base, 2
            )
        return totals


def _make_id(rule_id: str, scope_value: str, index: int) -> str:
    """Stable, readable opportunity identifier."""
    safe = "".join(ch for ch in str(scope_value) if ch.isalnum() or ch in "-_")[:24]
    return f"{rule_id}-{safe or 'all'}-{index:03d}"


# ---------------------------------------------------------------------------
# SAV-01 price harmonisation
# ---------------------------------------------------------------------------
def price_harmonisation(
    frame: pd.DataFrame, config: SpendConfig, settings: SavingsRuleSettings
) -> list[SavingsOpportunity]:
    """Model paying the target percentile price on every line above it.

    Only materials bought several times at meaningfully different prices
    qualify, so normal price movement does not become an "opportunity".
    """
    percentile = float(settings.param("target_percentile", 25))
    min_observations = int(settings.param("min_observations", 4))
    min_spread = float(settings.param("min_price_spread_pct", 10.0))
    min_spend = float(settings.param("min_material_spend_base", 10000.0))

    opportunities: list[SavingsOpportunity] = []
    if frame.empty or "material" not in frame.columns:
        return opportunities

    for index, (material, group) in enumerate(frame.groupby(frame["material"].dropna()), start=1):
        priced = group[group["current_price_base"].notna() & (group["current_price_base"] > 0)]
        if len(priced) < min_observations:
            continue
        material_spend = float(priced["spend_base"].sum())
        if material_spend < min_spend:
            continue

        prices = priced["current_price_base"].astype(float)
        minimum, maximum = float(prices.min()), float(prices.max())
        spread_pct = _safe_pct(maximum - minimum, minimum) if minimum else 0.0
        if spread_pct < min_spread:
            continue

        target_price = float(prices.quantile(percentile / 100.0))
        above = priced[priced["current_price_base"].astype(float) > target_price]
        if above.empty:
            continue

        gross = 0.0
        for price, quantity in zip(above["current_price_base"], above["quantity"]):
            units = 0.0 if quantity is None or pd.isna(quantity) else float(quantity)
            gross += (float(price) - target_price) * units
        if gross <= 0:
            continue

        estimated = gross * settings.realization_factor
        opportunities.append(
            SavingsOpportunity(
                opportunity_id=_make_id("SAV-01", str(material), index),
                rule_id="SAV-01",
                rule_name=settings.name,
                opportunity_type="price_harmonisation",
                scope="material",
                scope_value=str(material),
                scope_label=_first_label(group, "material_description"),
                title=f"Harmonise the price paid for material {material}",
                description=(
                    f"This material was bought {len(priced)} times at prices between "
                    f"{minimum:,.2f} and {maximum:,.2f} {config.base_currency} per unit, "
                    f"a spread of {spread_pct:.1f}%."
                ),
                method=(
                    f"Target price = {percentile:.0f}th percentile of prices paid "
                    f"({target_price:,.2f}). Gross saving = sum over lines above target of "
                    f"(price paid - target) x quantity = {gross:,.2f}. "
                    f"Estimate = gross x realization factor {settings.realization_factor:.2f}."
                ),
                addressable_spend_base=round(float(above["spend_base"].sum()), 2),
                gross_saving_base=round(gross, 2),
                realization_factor=settings.realization_factor,
                estimated_saving_base=round(estimated, 2),
                confidence=settings.confidence,
                transaction_count=int(len(above)),
                supplier_count=int(priced["supplier_id"].nunique()),
                evidence={
                    "target_price_base": round(target_price, 4),
                    "min_price_base": round(minimum, 4),
                    "max_price_base": round(maximum, 4),
                    "price_spread_pct": spread_pct,
                    "observations": int(len(priced)),
                    "material_spend_base": round(material_spend, 2),
                    "threshold_min_price_spread_pct": min_spread,
                    "threshold_min_observations": min_observations,
                },
            )
        )
    return opportunities


# ---------------------------------------------------------------------------
# SAV-02 contract compliance
# ---------------------------------------------------------------------------
def contract_compliance(
    frame: pd.DataFrame, config: SpendConfig, settings: SavingsRuleSettings
) -> list[SavingsOpportunity]:
    """Model bringing a supplier's non-contracted spend under contract."""
    saving_pct = float(settings.param("assumed_saving_pct", 8.0))
    min_spend = float(settings.param("min_supplier_spend_base", 25000.0))
    min_share = float(settings.param("min_non_contracted_share_pct", 20.0))

    opportunities: list[SavingsOpportunity] = []
    if frame.empty:
        return opportunities

    for index, (supplier_id, group) in enumerate(frame.groupby("supplier_id"), start=1):
        total = float(group["spend_base"].sum())
        if total < min_spend:
            continue
        non_contracted = group[~group["is_contracted"]]
        leaked = float(non_contracted["spend_base"].sum())
        share = _safe_pct(leaked, total)
        if leaked <= 0 or share < min_share:
            continue

        gross = leaked * saving_pct / 100.0
        estimated = gross * settings.realization_factor
        already_contracted = bool(group["is_contracted"].any())
        opportunities.append(
            SavingsOpportunity(
                opportunity_id=_make_id("SAV-02", str(supplier_id), index),
                rule_id="SAV-02",
                rule_name=settings.name,
                opportunity_type="contract_compliance",
                scope="supplier",
                scope_value=str(supplier_id),
                scope_label=_first_label(group, "supplier_name"),
                title=f"Bring non-contracted spend with supplier {supplier_id} under contract",
                description=(
                    f"{leaked:,.2f} {config.base_currency} ({share:.1f}% of the spend with this "
                    "supplier) was placed without a contract reference."
                    + (
                        " This supplier already holds a contract for other lines, so this is "
                        "contract leakage rather than a gap in coverage."
                        if already_contracted
                        else " No contracted lines were found for this supplier at all."
                    )
                ),
                method=(
                    f"Gross saving = non-contracted spend {leaked:,.2f} x assumed rate "
                    f"{saving_pct:.1f}% = {gross:,.2f}. Estimate = gross x realization factor "
                    f"{settings.realization_factor:.2f}. The assumed rate is a configured "
                    "planning assumption, not a negotiated discount."
                ),
                addressable_spend_base=round(leaked, 2),
                gross_saving_base=round(gross, 2),
                realization_factor=settings.realization_factor,
                estimated_saving_base=round(estimated, 2),
                confidence=settings.confidence,
                transaction_count=int(len(non_contracted)),
                supplier_count=1,
                evidence={
                    "supplier_total_spend_base": round(total, 2),
                    "non_contracted_spend_base": round(leaked, 2),
                    "non_contracted_share_pct": share,
                    "supplier_holds_contract_elsewhere": already_contracted,
                    "assumed_saving_pct": saving_pct,
                    "threshold_min_supplier_spend_base": min_spend,
                    "threshold_min_non_contracted_share_pct": min_share,
                },
            )
        )
    return opportunities


# ---------------------------------------------------------------------------
# SAV-03 supplier consolidation
# ---------------------------------------------------------------------------
def supplier_consolidation(
    frame: pd.DataFrame, config: SpendConfig, settings: SavingsRuleSettings
) -> list[SavingsOpportunity]:
    """Model consolidating a fragmented material group onto fewer suppliers."""
    min_suppliers = int(settings.param("min_suppliers_in_group", 4))
    saving_pct = float(settings.param("assumed_saving_pct", 6.0))
    min_group_spend = float(settings.param("min_group_spend_base", 50000.0))
    consolidation_share = float(settings.param("consolidation_share_pct", 60.0))

    opportunities: list[SavingsOpportunity] = []
    if frame.empty or "material_group" not in frame.columns:
        return opportunities

    for index, (group_value, group) in enumerate(
        frame.groupby(frame["material_group"].dropna()), start=1
    ):
        group_spend = float(group["spend_base"].sum())
        supplier_count = int(group["supplier_id"].nunique())
        if group_spend < min_group_spend or supplier_count < min_suppliers:
            continue

        addressable = group_spend * consolidation_share / 100.0
        gross = addressable * saving_pct / 100.0
        estimated = gross * settings.realization_factor
        by_supplier = group.groupby("supplier_id")["spend_base"].sum().sort_values(ascending=False)

        opportunities.append(
            SavingsOpportunity(
                opportunity_id=_make_id("SAV-03", str(group_value), index),
                rule_id="SAV-03",
                rule_name=settings.name,
                opportunity_type="supplier_consolidation",
                scope="material_group",
                scope_value=str(group_value),
                scope_label=None,
                title=f"Consolidate suppliers in material group {group_value}",
                description=(
                    f"{supplier_count} suppliers share {group_spend:,.2f} {config.base_currency} "
                    f"of spend in this group. The largest holds "
                    f"{_safe_pct(float(by_supplier.iloc[0]), group_spend):.1f}%."
                ),
                method=(
                    f"Addressable spend = group spend {group_spend:,.2f} x "
                    f"{consolidation_share:.0f}% = {addressable:,.2f}. Gross saving = addressable "
                    f"x assumed rate {saving_pct:.1f}% = {gross:,.2f}. Estimate = gross x "
                    f"realization factor {settings.realization_factor:.2f}. Consolidation "
                    "feasibility depends on technical qualification, which this model does not test."
                ),
                addressable_spend_base=round(addressable, 2),
                gross_saving_base=round(gross, 2),
                realization_factor=settings.realization_factor,
                estimated_saving_base=round(estimated, 2),
                confidence=settings.confidence,
                transaction_count=int(len(group)),
                supplier_count=supplier_count,
                evidence={
                    "group_spend_base": round(group_spend, 2),
                    "supplier_count": supplier_count,
                    "largest_supplier_id": str(by_supplier.index[0]),
                    "largest_supplier_share_pct": _safe_pct(
                        float(by_supplier.iloc[0]), group_spend
                    ),
                    "consolidation_share_pct": consolidation_share,
                    "assumed_saving_pct": saving_pct,
                    "threshold_min_suppliers_in_group": min_suppliers,
                    "threshold_min_group_spend_base": min_group_spend,
                },
            )
        )
    return opportunities


# ---------------------------------------------------------------------------
# SAV-04 tail spend reduction
# ---------------------------------------------------------------------------
def tail_spend_reduction(
    frame: pd.DataFrame,
    config: SpendConfig,
    settings: SavingsRuleSettings,
    supplier_rows: list[SupplierSpend],
) -> list[SavingsOpportunity]:
    """Model rationalising the tail: price leakage plus transaction cost."""
    saving_pct = float(settings.param("assumed_saving_pct", 10.0))
    min_tail_spend = float(settings.param("min_tail_spend_base", 20000.0))
    cost_per_transaction = float(settings.param("cost_per_transaction_base", 45.0))

    tail = [row for row in supplier_rows if row.is_tail]
    if not tail:
        return []

    tail_spend = sum(row.spend_base for row in tail)
    if tail_spend < min_tail_spend:
        return []

    tail_transactions = sum(row.transaction_count for row in tail)
    price_component = tail_spend * saving_pct / 100.0
    process_component = tail_transactions * cost_per_transaction
    gross = price_component + process_component
    estimated = gross * settings.realization_factor

    return [
        SavingsOpportunity(
            opportunity_id=_make_id("SAV-04", "tail", 1),
            rule_id="SAV-04",
            rule_name=settings.name,
            opportunity_type="tail_spend_reduction",
            scope="portfolio",
            scope_value="tail_suppliers",
            scope_label=f"{len(tail)} tail suppliers",
            title=f"Rationalise {len(tail)} tail suppliers",
            description=(
                f"{len(tail)} suppliers account for {tail_spend:,.2f} {config.base_currency} "
                f"across {tail_transactions:,} transactions but sit outside the top "
                f"{config.tail_spend.cumulative_share_threshold_pct:.0f}% of spend."
            ),
            method=(
                f"Price component = tail spend {tail_spend:,.2f} x {saving_pct:.1f}% = "
                f"{price_component:,.2f}. Process component = {tail_transactions:,} transactions "
                f"x {cost_per_transaction:,.2f} handling cost = {process_component:,.2f}. "
                f"Estimate = (price + process) x realization factor "
                f"{settings.realization_factor:.2f}. The handling cost is a configured "
                "assumption, not a measured figure from your finance system."
            ),
            addressable_spend_base=round(tail_spend, 2),
            gross_saving_base=round(gross, 2),
            realization_factor=settings.realization_factor,
            estimated_saving_base=round(estimated, 2),
            confidence=settings.confidence,
            transaction_count=tail_transactions,
            supplier_count=len(tail),
            evidence={
                "tail_supplier_count": len(tail),
                "tail_spend_base": round(tail_spend, 2),
                "tail_transaction_count": tail_transactions,
                "price_component_base": round(price_component, 2),
                "process_component_base": round(process_component, 2),
                "cost_per_transaction_base": cost_per_transaction,
                "assumed_saving_pct": saving_pct,
                "threshold_min_tail_spend_base": min_tail_spend,
            },
        )
    ]


# ---------------------------------------------------------------------------
# SAV-05 move to preferred suppliers
# ---------------------------------------------------------------------------
def preferred_supplier_migration(
    frame: pd.DataFrame, config: SpendConfig, settings: SavingsRuleSettings
) -> list[SavingsOpportunity]:
    """Model moving a material to a preferred supplier that already sells it cheaper.

    This rule needs real evidence on both sides: a preferred supplier with
    enough observations of the same material, and a measurable price gap.
    """
    min_gap = float(settings.param("min_price_gap_pct", 5.0))
    min_spend = float(settings.param("min_spend_base", 5000.0))
    min_preferred_observations = int(settings.param("min_preferred_observations", 2))

    opportunities: list[SavingsOpportunity] = []
    if frame.empty or "material" not in frame.columns:
        return opportunities

    for index, (material, group) in enumerate(frame.groupby(frame["material"].dropna()), start=1):
        preferred = group[group["is_preferred_supplier"] & group["current_price_base"].notna()]
        other = group[~group["is_preferred_supplier"] & group["current_price_base"].notna()]
        if len(preferred) < min_preferred_observations or other.empty:
            continue

        preferred_price = float(preferred["current_price_base"].astype(float).median())
        if preferred_price <= 0:
            continue

        above = other[other["current_price_base"].astype(float) > preferred_price]
        addressable = float(above["spend_base"].sum())
        if addressable < min_spend:
            continue

        gross = 0.0
        for price, quantity in zip(above["current_price_base"], above["quantity"]):
            units = 0.0 if quantity is None or pd.isna(quantity) else float(quantity)
            gross += (float(price) - preferred_price) * units
        if gross <= 0:
            continue

        average_other_price = float(above["current_price_base"].astype(float).mean())
        gap_pct = _safe_pct(average_other_price - preferred_price, preferred_price)
        if gap_pct < min_gap:
            continue

        estimated = gross * settings.realization_factor
        preferred_suppliers = sorted({str(s) for s in preferred["supplier_id"].dropna().unique()})
        opportunities.append(
            SavingsOpportunity(
                opportunity_id=_make_id("SAV-05", str(material), index),
                rule_id="SAV-05",
                rule_name=settings.name,
                opportunity_type="preferred_supplier_migration",
                scope="material",
                scope_value=str(material),
                scope_label=_first_label(group, "material_description"),
                title=f"Move material {material} to a preferred supplier",
                description=(
                    f"Preferred supplier(s) {', '.join(preferred_suppliers)} sell this material at "
                    f"a median of {preferred_price:,.2f} {config.base_currency} per unit, while "
                    f"non-preferred suppliers averaged {average_other_price:,.2f} - a gap of "
                    f"{gap_pct:.1f}%."
                ),
                method=(
                    f"Gross saving = sum over non-preferred lines priced above the preferred "
                    f"median of (price paid - {preferred_price:,.2f}) x quantity = {gross:,.2f}. "
                    f"Estimate = gross x realization factor {settings.realization_factor:.2f}. "
                    "Assumes the preferred supplier can absorb the additional volume at the "
                    "same price, which is not verified here."
                ),
                addressable_spend_base=round(addressable, 2),
                gross_saving_base=round(gross, 2),
                realization_factor=settings.realization_factor,
                estimated_saving_base=round(estimated, 2),
                confidence=settings.confidence,
                transaction_count=int(len(above)),
                supplier_count=int(above["supplier_id"].nunique()),
                evidence={
                    "preferred_price_base": round(preferred_price, 4),
                    "average_non_preferred_price_base": round(average_other_price, 4),
                    "price_gap_pct": gap_pct,
                    "preferred_suppliers": preferred_suppliers,
                    "preferred_observations": int(len(preferred)),
                    "threshold_min_price_gap_pct": min_gap,
                    "threshold_min_spend_base": min_spend,
                },
            )
        )
    return opportunities


# ---------------------------------------------------------------------------
# SAV-06 reduce high price variance
# ---------------------------------------------------------------------------
def price_variance_reduction(
    frame: pd.DataFrame, config: SpendConfig, settings: SavingsRuleSettings
) -> list[SavingsOpportunity]:
    """Model paying the baseline price on lines bought above it."""
    min_variance = float(settings.param("min_variance_pct", 15.0))
    min_line_value = float(settings.param("min_line_value_base", 250.0))
    min_total = float(settings.param("min_total_opportunity_base", 1000.0))

    opportunities: list[SavingsOpportunity] = []
    if frame.empty:
        return opportunities

    eligible = frame[
        frame["price_variance_pct"].notna()
        & (frame["price_variance_pct"] >= min_variance)
        & (frame["spend_base"] >= min_line_value)
    ]
    if eligible.empty:
        return opportunities

    for index, (material, group) in enumerate(
        eligible.groupby(eligible["material"].fillna("(not set)")), start=1
    ):
        gross = float(group["price_variance_base"].fillna(0.0).sum())
        if gross < min_total:
            continue
        estimated = gross * settings.realization_factor
        worst_pct = float(group["price_variance_pct"].max())
        opportunities.append(
            SavingsOpportunity(
                opportunity_id=_make_id("SAV-06", str(material), index),
                rule_id="SAV-06",
                rule_name=settings.name,
                opportunity_type="price_variance_reduction",
                scope="material",
                scope_value=str(material),
                scope_label=_first_label(group, "material_description"),
                title=f"Close the price gap against baseline for material {material}",
                description=(
                    f"{len(group)} line(s) were bought above the baseline price, the worst by "
                    f"{worst_pct:.1f}%, costing {gross:,.2f} {config.base_currency} more than "
                    "the baseline would have."
                ),
                method=(
                    "Gross saving = sum of (price paid - baseline price) x quantity over lines "
                    f"at least {min_variance:.0f}% above baseline = {gross:,.2f}. "
                    f"Estimate = gross x realization factor {settings.realization_factor:.2f}."
                ),
                addressable_spend_base=round(float(group["spend_base"].sum()), 2),
                gross_saving_base=round(gross, 2),
                realization_factor=settings.realization_factor,
                estimated_saving_base=round(estimated, 2),
                confidence=settings.confidence,
                transaction_count=int(len(group)),
                supplier_count=int(group["supplier_id"].nunique()),
                evidence={
                    "worst_variance_pct": round(worst_pct, 2),
                    "average_variance_pct": round(float(group["price_variance_pct"].mean()), 2),
                    "affected_lines": int(len(group)),
                    "threshold_min_variance_pct": min_variance,
                    "threshold_min_line_value_base": min_line_value,
                },
            )
        )
    return opportunities


def _first_label(group: pd.DataFrame, column: str) -> str | None:
    """First non-null value of a label column inside a group."""
    if column not in group.columns:
        return None
    values = group[column].dropna()
    return str(values.iloc[0]) if not values.empty else None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def calculate_savings(
    frame: pd.DataFrame,
    config: SpendConfig,
    supplier_rows: list[SupplierSpend],
    enabled_rules: list[str] | None = None,
) -> SavingsResult:
    """Run every enabled savings rule.

    Each rule is isolated: if one fails the others still produce results and the
    failure is reported rather than swallowed.
    """
    runners = {
        "SAV-01": lambda s: price_harmonisation(frame, config, s),
        "SAV-02": lambda s: contract_compliance(frame, config, s),
        "SAV-03": lambda s: supplier_consolidation(frame, config, s),
        "SAV-04": lambda s: tail_spend_reduction(frame, config, s, supplier_rows),
        "SAV-05": lambda s: preferred_supplier_migration(frame, config, s),
        "SAV-06": lambda s: price_variance_reduction(frame, config, s),
    }

    opportunities: list[SavingsOpportunity] = []
    executions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for rule_id, runner in runners.items():
        settings = config.savings_rules.get(rule_id)
        if settings is None:
            continue
        requested = enabled_rules is None or rule_id in enabled_rules
        if not settings.enabled or not requested:
            executions.append(
                {"rule_id": rule_id, "rule_name": settings.name, "enabled": False,
                 "opportunity_count": 0, "estimated_saving_base": 0.0}
            )
            continue
        try:
            produced = runner(settings)
        except Exception as exc:  # noqa: BLE001 - one broken rule must not lose the rest
            logger.exception("Savings rule %s failed", rule_id)
            errors.append(
                {"rule_id": rule_id, "rule_name": settings.name, "error": type(exc).__name__}
            )
            executions.append(
                {"rule_id": rule_id, "rule_name": settings.name, "enabled": True,
                 "opportunity_count": 0, "estimated_saving_base": 0.0, "error": type(exc).__name__}
            )
            continue

        opportunities.extend(produced)
        executions.append(
            {
                "rule_id": rule_id,
                "rule_name": settings.name,
                "enabled": True,
                "opportunity_count": len(produced),
                "estimated_saving_base": round(
                    sum(o.estimated_saving_base for o in produced), 2
                ),
                "realization_factor": settings.realization_factor,
                "confidence": settings.confidence,
            }
        )

    opportunities.sort(key=lambda o: o.estimated_saving_base, reverse=True)
    logger.info(
        "Savings engine produced %d opportunities worth %.2f %s",
        len(opportunities),
        sum(o.estimated_saving_base for o in opportunities),
        config.base_currency,
    )
    return SavingsResult(opportunities=opportunities, rule_executions=executions, rule_errors=errors)


def savings_rule_catalogue(config: SpendConfig) -> list[dict[str, Any]]:
    """Describe every configured savings rule, including its assumptions."""
    return [
        {
            "rule_id": rule_id,
            "name": settings.name,
            "enabled": settings.enabled,
            "description": settings.description,
            "confidence": settings.confidence,
            "realization_factor": settings.realization_factor,
            "params": settings.params,
        }
        for rule_id, settings in config.savings_rules.items()
    ]
