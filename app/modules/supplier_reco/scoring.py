"""Deterministic weighted scoring for eligible suppliers.

Nine normalised sub-scores (0-100, higher is always better) are computed for
each eligible supplier, then combined into an overall score with the
user-supplied weights. Everything here is ordinary Python arithmetic - no AI is
involved in any figure.

Scoring formulas
----------------
Several dimensions are *relative*: a supplier is scored against the other
eligible suppliers with min-max normalisation. This keeps every dimension on the
same 0-100 scale regardless of its natural units.

* ``min-max (higher better)`` = ``100 x (value - min) / (max - min)``
* ``min-max (lower better)``  = ``100 x (max - value) / (max - min)``
* When every supplier shares the same value the whole pool scores 100.

**Missing data scores 0.** An attribute that a supplier did not provide cannot
count in its favour, so it is treated as the worst possible value.

* **Cost** - min-max (lower better) of the unit price in base currency.
* **Delivery** - ``on_time_weight`` x on-time-delivery-rate + ``lead_time_weight``
  x min-max (lower better) of the lead time.
* **Quality** - ``quality_weight`` x quality score + ``defect_weight`` x
  ``(100 - defect_rate x defect_rate_scale)``.
* **Capacity** - ``available_capacity / (quantity x target_coverage_ratio) x 100``
  capped at 100; when no quantity is given, min-max of available capacity.
* **Risk** - ``100 - risk_score`` (a low risk score scores highly).
* **ESG** - the ESG score, used directly.
* **Contract** - a fixed score per contract classification (active / expiring /
  none / unknown), with an expiring penalty when the contract lapses before the
  required delivery date.
* **Geographic** - share of the specified location criteria (preferred region,
  requested plant) the supplier satisfies; 100 when none is specified.
* **Past performance** - ``order_weight`` x min-max of the historical order count
  + ``spend_weight`` x min-max of the historical spend.

``overall = sum(weight_d / 100 x score_d)`` over the nine dimensions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.supplier_reco.normalizer import NormalizedSupplier
from app.modules.supplier_reco.requirement import Requirement
from app.modules.supplier_reco.thresholds import (
    SCORE_DIMENSIONS,
    SupplierRecoConfig,
    Weights,
)

SCORING_ENGINE_VERSION = "1.0.0"


@dataclass
class SupplierScores:
    """The nine sub-scores and the weighted overall score for one supplier."""

    cost: float = 0.0
    delivery: float = 0.0
    quality: float = 0.0
    capacity: float = 0.0
    risk: float = 0.0
    esg: float = 0.0
    contract: float = 0.0
    geographic: float = 0.0
    past_performance: float = 0.0
    overall: float = 0.0
    contract_class: str = "unknown"
    components: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, float]:
        return {dim: float(getattr(self, dim)) for dim in SCORE_DIMENSIONS}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _range(values: list[float | None]) -> tuple[float, float] | None:
    """Min/max over the present (non-None) values, or ``None`` when all missing."""
    present = [v for v in values if v is not None]
    if not present:
        return None
    return min(present), max(present)


def _minmax(value: float | None, bounds: tuple[float, float] | None, *, higher_better: bool) -> float:
    """Normalise ``value`` to 0-100 within ``bounds``. Missing data scores 0."""
    if value is None or bounds is None:
        return 0.0
    low, high = bounds
    if high == low:
        return 100.0
    if higher_better:
        return _clamp(100.0 * (value - low) / (high - low))
    return _clamp(100.0 * (high - value) / (high - low))


def classify_contract(
    supplier: NormalizedSupplier, requirement: Requirement, config: SupplierRecoConfig
) -> str:
    """Classify a supplier's contract as active / expiring / none / unknown."""
    settings = config.classification
    status = (supplier.contract_status or "").strip().lower()
    active = {v.lower() for v in settings.active_contract_values}
    expiring = {v.lower() for v in settings.expiring_contract_values}
    none_values = {v.lower() for v in settings.no_contract_values}

    if not status:
        return "unknown"
    if status in none_values:
        return "none"
    if status in expiring:
        return "expiring"
    if status in active:
        expiration = supplier.contract_expiration
        if expiration is not None:
            # A contract that lapses before the goods are needed is effectively expiring.
            if requirement.required_delivery_date and expiration < requirement.required_delivery_date:
                return "expiring"
            if (
                requirement.order_date
                and (expiration - requirement.order_date).days <= config.scoring.contract.expiring_within_days
            ):
                return "expiring"
        return "active"
    return "unknown"


def validate_weights(weights: Weights, config: SupplierRecoConfig) -> None:
    """Validate that ``weights`` sum to the configured total (raises on failure)."""
    config.validate_weights(weights)


def score_suppliers(
    eligible: list[NormalizedSupplier],
    requirement: Requirement,
    weights: Weights,
    config: SupplierRecoConfig,
) -> dict[str, SupplierScores]:
    """Score every eligible supplier. Returns ``{supplier_id: SupplierScores}``.

    The relative (min-max) dimensions need the whole eligible pool, so the ranges
    are computed once up front and reused for every supplier.
    """
    if not eligible:
        return {}

    price_bounds = _range([s.unit_price_base for s in eligible])
    lead_bounds = _range([float(s.lead_time_days) if s.lead_time_days is not None else None for s in eligible])
    capacity_bounds = _range([s.available_capacity for s in eligible])
    order_bounds = _range(
        [float(s.historical_order_count) if s.historical_order_count is not None else None for s in eligible]
    )
    spend_bounds = _range([s.historical_spend_base for s in eligible])

    scoring = config.scoring
    weight_map = weights.as_dict()

    results: dict[str, SupplierScores] = {}
    for supplier in eligible:
        scores = SupplierScores()

        # 1. Cost - cheaper is better.
        scores.cost = round(_minmax(supplier.unit_price_base, price_bounds, higher_better=False), 2)

        # 2. Delivery - on-time reliability blended with lead-time fitness.
        ontime = _clamp(supplier.on_time_delivery_rate) if supplier.on_time_delivery_rate is not None else 0.0
        lead = _minmax(
            float(supplier.lead_time_days) if supplier.lead_time_days is not None else None,
            lead_bounds,
            higher_better=False,
        )
        scores.delivery = round(
            scoring.delivery.on_time_weight * ontime + scoring.delivery.lead_time_weight * lead, 2
        )

        # 3. Quality - quality score blended with a defect-rate penalty.
        quality_component = _clamp(supplier.quality_score) if supplier.quality_score is not None else 0.0
        if supplier.defect_rate is None:
            defect_component = 0.0
        else:
            defect_component = _clamp(100.0 - supplier.defect_rate * scoring.quality.defect_rate_scale)
        scores.quality = round(
            scoring.quality.quality_weight * quality_component
            + scoring.quality.defect_weight * defect_component,
            2,
        )

        # 4. Capacity - headroom over the requested quantity.
        scores.capacity = round(_capacity_score(supplier, requirement, capacity_bounds, config), 2)

        # 5. Risk - inverse of the risk score.
        scores.risk = round(
            _clamp(100.0 - supplier.risk_score) if supplier.risk_score is not None else 0.0, 2
        )

        # 6. ESG - used directly.
        scores.esg = round(_clamp(supplier.esg_score) if supplier.esg_score is not None else 0.0, 2)

        # 7. Contract - fixed score per classification.
        scores.contract_class = classify_contract(supplier, requirement, config)
        scores.contract = round(_contract_score(scores.contract_class, config), 2)

        # 8. Geographic fit.
        scores.geographic = round(_geographic_score(supplier, requirement, config), 2)

        # 9. Past performance.
        order_component = _minmax(
            float(supplier.historical_order_count) if supplier.historical_order_count is not None else None,
            order_bounds,
            higher_better=True,
        )
        spend_component = _minmax(supplier.historical_spend_base, spend_bounds, higher_better=True)
        scores.past_performance = round(
            scoring.past_performance.order_weight * order_component
            + scoring.past_performance.spend_weight * spend_component,
            2,
        )

        overall = sum(weight_map[dim] / 100.0 * getattr(scores, dim) for dim in SCORE_DIMENSIONS)
        scores.overall = round(overall, 2)
        scores.components = {
            "ontime_component": round(ontime, 2),
            "lead_time_component": round(lead, 2),
            "quality_component": round(quality_component, 2),
            "defect_component": round(defect_component, 2),
            "order_component": round(order_component, 2),
            "spend_component": round(spend_component, 2),
        }
        results[supplier.supplier_id] = scores

    return results


def _capacity_score(
    supplier: NormalizedSupplier,
    requirement: Requirement,
    capacity_bounds: tuple[float, float] | None,
    config: SupplierRecoConfig,
) -> float:
    """Capacity fitness: reward headroom over the requested quantity."""
    capacity = supplier.available_capacity
    if capacity is None:
        return 0.0
    if requirement.quantity and requirement.quantity > 0:
        target = requirement.quantity * config.scoring.capacity.target_coverage_ratio
        if target <= 0:
            return 100.0
        return _clamp(capacity / target * 100.0)
    # No quantity to size against: rank by absolute available capacity.
    return _minmax(capacity, capacity_bounds, higher_better=True)


def _contract_score(contract_class: str, config: SupplierRecoConfig) -> float:
    settings = config.scoring.contract
    return {
        "active": settings.active_score,
        "expiring": settings.expiring_score,
        "none": settings.none_score,
        "unknown": settings.unknown_score,
    }.get(contract_class, settings.unknown_score)


def _geographic_score(
    supplier: NormalizedSupplier, requirement: Requirement, config: SupplierRecoConfig
) -> float:
    """Share of the specified location criteria the supplier satisfies."""
    settings = config.scoring.geographic
    applicable = 0.0
    earned = 0.0

    if requirement.preferred_region:
        applicable += settings.region_match_score
        if _contains(supplier.regions_served, requirement.preferred_region):
            earned += settings.region_match_score

    if requirement.plant:
        applicable += settings.plant_match_score
        if _contains(supplier.plants_served, requirement.plant):
            earned += settings.plant_match_score

    if applicable <= 0:
        return settings.no_preference_score
    return _clamp(100.0 * earned / applicable)


def _contains(haystack: list[str], needle: str | None) -> bool:
    if not needle:
        return False
    wanted = needle.strip().lower()
    return any(item.strip().lower() == wanted for item in haystack)
