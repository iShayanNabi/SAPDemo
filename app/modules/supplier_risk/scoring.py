"""The deterministic supplier risk scoring model.

Nothing here is AI. Every number is arithmetic over the loaded records, and
every number carries its own audit trail: for each input metric the model
records the raw value, the weight it was given, the normalised 0-100 risk it
produced and how much that contributed to the category and the overall score.

The scale is consistent everywhere: **0 means no risk, 100 means maximum
risk**. Metrics where a high raw value is good (an on-time rate, a credit
score) are inverted during normalisation, so a reader never has to remember
which direction a particular metric runs.

Missing data is never invented. A metric with no value is dropped and the
remaining metric weights inside its category are renormalised; a category with
no usable metric at all is excluded from the overall score and the remaining
category weights are renormalised. What was dropped is reported, not hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.modules.supplier_risk.normalizer import NormalizedSupplierProfile
from app.modules.supplier_risk.thresholds import (
    RISK_CATEGORIES,
    CategorySpec,
    CategoryWeights,
    MetricSpec,
    SupplierRiskConfig,
)

__all__ = [
    "SCORING_ENGINE_VERSION",
    "CategoryScore",
    "MetricContribution",
    "SupplierRiskScore",
    "normalize_metric",
    "score_category",
    "score_supplier",
]

#: Bumped whenever the scoring maths changes in a way that moves recorded scores.
SCORING_ENGINE_VERSION = "1.0.0"


@dataclass
class MetricContribution:
    """One input metric's audited journey into a category score."""

    metric: str
    label: str
    raw_value: Any
    unit: str
    direction: str
    weight: float
    normalized_weight: float
    normalized_score: float
    contribution: float
    available: bool
    basis: str
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "label": self.label,
            "raw_value": self.raw_value,
            "unit": self.unit,
            "direction": self.direction,
            "weight": self.weight,
            "normalized_weight": self.normalized_weight,
            "normalized_score": self.normalized_score,
            "contribution": self.contribution,
            "available": self.available,
            "basis": self.basis,
            "note": self.note,
        }


@dataclass
class CategoryScore:
    """One risk category's score and the metrics behind it."""

    category: str
    label: str
    description: str
    score: float | None
    band: str | None
    weight: float
    normalized_weight: float
    contribution: float
    data_available: bool
    metrics: list[MetricContribution] = field(default_factory=list)
    missing_metrics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "label": self.label,
            "description": self.description,
            "score": self.score,
            "band": self.band,
            "weight": self.weight,
            "normalized_weight": self.normalized_weight,
            "contribution": self.contribution,
            "data_available": self.data_available,
            "metrics": [metric.to_dict() for metric in self.metrics],
            "missing_metrics": list(self.missing_metrics),
        }


@dataclass
class SupplierRiskScore:
    """The complete, auditable risk score for one supplier."""

    supplier_id: str
    overall_score: float | None
    overall_band: str | None
    categories: dict[str, CategoryScore] = field(default_factory=dict)
    scored_categories: list[str] = field(default_factory=list)
    unscored_categories: list[str] = field(default_factory=list)
    data_completeness_pct: float = 0.0
    limited_data: bool = False
    weights_used: dict[str, float] = field(default_factory=dict)

    @property
    def ordered_categories(self) -> list[CategoryScore]:
        """Category scores in the configured display order."""
        return [self.categories[name] for name in RISK_CATEGORIES if name in self.categories]

    def top_drivers(self, limit: int = 3) -> list[CategoryScore]:
        """The categories contributing most to the overall score."""
        scored = [item for item in self.categories.values() if item.data_available]
        return sorted(scored, key=lambda item: (-item.contribution, item.category))[:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier_id": self.supplier_id,
            "overall_score": self.overall_score,
            "overall_band": self.overall_band,
            "categories": {name: score.to_dict() for name, score in self.categories.items()},
            "scored_categories": list(self.scored_categories),
            "unscored_categories": list(self.unscored_categories),
            "data_completeness_pct": self.data_completeness_pct,
            "limited_data": self.limited_data,
            "weights_used": dict(self.weights_used),
        }


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def normalize_metric(
    spec: MetricSpec,
    value: Any,
    config: SupplierRiskConfig,
) -> tuple[float | None, str, str | None]:
    """Turn one raw metric value into a 0-100 risk score.

    Returns ``(score, basis, note)``. ``score`` is ``None`` when the metric has
    no usable value, in which case the caller drops it. ``basis`` explains in
    words how the score was reached, so the UI and the copilot can show the
    reasoning instead of a bare number.
    """
    if spec.direction == "flag":
        flag = value
        if flag is None:
            return None, "no value recorded", None
        score = spec.flag_true_score if bool(flag) else spec.flag_false_score
        basis = f"flag is {'set' if flag else 'not set'} -> {score:g}"
        return _clamp(float(score)), basis, None

    if spec.direction == "categorical":
        text = None if value is None else str(value).strip()
        if not text:
            return None, "no value recorded", None
        score_map = config.score_map(str(spec.score_map_key))
        score, matched = score_map.score_for(text)
        if matched:
            basis = f"'{text}' maps to {score:g} in the {spec.score_map_key} score map"
            return _clamp(float(score)), basis, None
        basis = f"'{text}' is not in the {spec.score_map_key} score map; configured default {score:g} used"
        return _clamp(float(score)), basis, f"Unrecognised value '{text}'."

    # Linear normalisation between the configured best and worst anchors.
    if value is None:
        return None, "no value recorded", None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None, "value is not numeric", f"Could not read '{value}' as a number."

    best = float(spec.best_value)  # validated non-None for linear directions
    worst = float(spec.worst_value)
    ratio = (numeric - best) / (worst - best)
    score = _clamp(ratio * 100.0)
    basis = (
        f"{numeric:g}{spec.unit and ' ' + spec.unit} against best {best:g} / worst {worst:g} "
        f"-> {score:.1f}"
    )
    return round(score, 4), basis, None


def _metric_value(
    profile: NormalizedSupplierProfile,
    metric_name: str,
    as_of: date,
) -> Any:
    """Read a metric from the profile, including the derived ratios."""
    if metric_name == "late_delivery_ratio":
        return profile.late_delivery_ratio
    if metric_name == "invoice_exception_rate":
        return profile.invoice_exception_rate
    if metric_name == "region_coverage_count":
        return profile.region_coverage_count
    if metric_name == "days_to_contract_expiry":
        return profile.days_to_contract_expiry(as_of)
    if metric_name == "country_risk_index":
        return profile.country
    return getattr(profile, metric_name, None)


def score_category(
    name: str,
    spec: CategorySpec,
    profile: NormalizedSupplierProfile,
    weight: float,
    config: SupplierRiskConfig,
    as_of: date,
) -> CategoryScore:
    """Score one risk category for one supplier.

    Metric weights are renormalised across the metrics that actually have data,
    so a supplier missing one input is not silently scored as if that input
    were zero risk.
    """
    contributions: list[MetricContribution] = []
    missing: list[str] = []
    available_weight = 0.0

    for metric_name, metric_spec in spec.metrics.items():
        raw = _metric_value(profile, metric_name, as_of)
        score, basis, note = normalize_metric(metric_spec, raw, config)
        raw_display = raw.isoformat() if isinstance(raw, date) else raw

        if score is None:
            missing.append(metric_name)
            contributions.append(
                MetricContribution(
                    metric=metric_name,
                    label=metric_spec.label,
                    raw_value=raw_display,
                    unit=metric_spec.unit,
                    direction=metric_spec.direction,
                    weight=metric_spec.weight,
                    normalized_weight=0.0,
                    normalized_score=0.0,
                    contribution=0.0,
                    available=False,
                    basis=basis,
                    note=note,
                )
            )
            continue

        available_weight += metric_spec.weight
        contributions.append(
            MetricContribution(
                metric=metric_name,
                label=metric_spec.label,
                raw_value=raw_display,
                unit=metric_spec.unit,
                direction=metric_spec.direction,
                weight=metric_spec.weight,
                normalized_weight=0.0,  # filled in below, once the total is known
                normalized_score=round(float(score), 2),
                contribution=0.0,
                available=True,
                basis=basis,
                note=note,
            )
        )

    if available_weight <= 0.0:
        return CategoryScore(
            category=name,
            label=spec.label,
            description=spec.description,
            score=None,
            band=None,
            weight=weight,
            normalized_weight=0.0,
            contribution=0.0,
            data_available=False,
            metrics=contributions,
            missing_metrics=missing,
        )

    renormalise = config.missing_data.renormalise_metric_weights
    divisor = available_weight if renormalise else spec.metric_weight_total()

    total = 0.0
    for contribution in contributions:
        if not contribution.available:
            continue
        share = contribution.weight / divisor if divisor else 0.0
        contribution.normalized_weight = round(share, 6)
        contribution.contribution = round(share * contribution.normalized_score, 4)
        total += share * contribution.normalized_score

    score = round(_clamp(total), 2)
    return CategoryScore(
        category=name,
        label=spec.label,
        description=spec.description,
        score=score,
        band=config.band_for(score),
        weight=weight,
        normalized_weight=0.0,  # filled in by score_supplier across categories
        contribution=0.0,
        data_available=True,
        metrics=contributions,
        missing_metrics=missing,
    )


def score_supplier(
    profile: NormalizedSupplierProfile,
    weights: CategoryWeights,
    config: SupplierRiskConfig,
    as_of: date,
    errors: list[dict[str, Any]] | None = None,
) -> SupplierRiskScore:
    """Produce the complete risk score for one supplier.

    Category weights are renormalised across the categories that have data, so
    the overall score always represents 100% of what could actually be measured.

    Each category is scored in isolation: if one category raises, it is recorded
    in ``errors``, reported as having no data, and the remaining nine categories
    still produce a result. A single malformed configuration entry can therefore
    never take down an entire assessment.
    """
    weight_map = weights.as_dict()
    categories: dict[str, CategoryScore] = {}

    for name in RISK_CATEGORIES:
        weight = weight_map.get(name, 0.0)
        try:
            spec = config.category(name)
            categories[name] = score_category(name, spec, profile, weight, config, as_of)
        except Exception as exc:  # noqa: BLE001 - reported per category, never fatal
            if errors is not None:
                errors.append(
                    {
                        "supplier_id": profile.supplier_id,
                        "category": name,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
            categories[name] = CategoryScore(
                category=name,
                label=name.replace("_", " ").title(),
                description="",
                score=None,
                band=None,
                weight=weight,
                normalized_weight=0.0,
                contribution=0.0,
                data_available=False,
                metrics=[],
                missing_metrics=[],
            )

    scored = [name for name in RISK_CATEGORIES if categories[name].data_available]
    unscored = [name for name in RISK_CATEGORIES if not categories[name].data_available]

    available_weight = sum(weight_map.get(name, 0.0) for name in scored)
    renormalise = config.missing_data.renormalise_category_weights
    divisor = available_weight if renormalise else config.weight_total

    overall: float | None = None
    if scored and divisor > 0 and len(scored) >= config.missing_data.minimum_categories_for_overall:
        total = 0.0
        for name in scored:
            category = categories[name]
            share = weight_map.get(name, 0.0) / divisor
            category.normalized_weight = round(share, 6)
            category.contribution = round(share * float(category.score or 0.0), 4)
            total += share * float(category.score or 0.0)
        overall = round(_clamp(total), 2)
    else:
        # Not enough categories to state an overall risk. Individual category
        # scores are still reported; the overall figure is withheld rather than
        # computed from a fragment of the model.
        for name in scored:
            categories[name].normalized_weight = 0.0
            categories[name].contribution = 0.0

    completeness = round(available_weight / config.weight_total * 100.0, 2) if config.weight_total else 0.0

    return SupplierRiskScore(
        supplier_id=profile.supplier_id,
        overall_score=overall,
        overall_band=config.band_for(overall),
        categories=categories,
        scored_categories=scored,
        unscored_categories=unscored,
        data_completeness_pct=completeness,
        limited_data=completeness < config.missing_data.flag_below_completeness_pct,
        weights_used=weight_map,
    )
