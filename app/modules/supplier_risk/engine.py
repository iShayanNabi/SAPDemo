"""Assemble scored risk profiles for every loaded supplier.

The engine is pure: no database, no HTTP, no AI. It takes normalised profiles
and events and returns a complete assessment - per-supplier category scores,
risk trend, the supporting internal records, and rule-based recommended
actions.

Everything the copilot later answers with is computed here, so an answer and
the supplier page can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.core.logging import get_logger
from app.core.rounding import decimal_mean, round_half_up
from app.modules.supplier_risk.normalizer import (
    NormalizedRiskEvent,
    NormalizedSupplierProfile,
)
from app.modules.supplier_risk.scoring import (
    SCORING_ENGINE_VERSION,
    SupplierRiskScore,
    score_supplier,
)
from app.modules.supplier_risk.thresholds import (
    RISK_CATEGORIES,
    CategoryWeights,
    SupplierRiskConfig,
)

logger = get_logger(__name__)

__all__ = [
    "ENGINE_VERSION",
    "RecommendedAction",
    "RiskAssessmentResult",
    "RiskTrend",
    "SupplierRiskProfile",
    "find_alternatives",
    "run_risk_assessment",
]

ENGINE_VERSION = SCORING_ENGINE_VERSION

#: Event types that count as delivery problems, quality problems and so on.
DELIVERY_EVENT_TYPES = {"late_delivery", "delivery_shortfall"}
QUALITY_EVENT_TYPES = {"quality_incident", "quality_defect"}
INVOICE_EVENT_TYPES = {"invoice_exception", "invoice_dispute"}
COMPLIANCE_EVENT_TYPES = {"compliance_finding", "audit_finding"}
CONTRACT_EVENT_TYPES = {"contract_event", "contract_expiry"}


@dataclass
class RiskTrend:
    """How a supplier's recorded risk events moved between two equal windows."""

    direction: str
    recent_weight: float
    previous_weight: float
    delta: float
    recent_event_count: int
    previous_event_count: int
    window_days: int
    basis: str
    data_available: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "recent_weight": self.recent_weight,
            "previous_weight": self.previous_weight,
            "delta": self.delta,
            "recent_event_count": self.recent_event_count,
            "previous_event_count": self.previous_event_count,
            "window_days": self.window_days,
            "basis": self.basis,
            "data_available": self.data_available,
        }


@dataclass
class RecommendedAction:
    """One rule-based action, tied to the category that triggered it."""

    category: str
    category_label: str
    priority: str
    action: str
    trigger: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "category_label": self.category_label,
            "priority": self.priority,
            "action": self.action,
            "trigger": self.trigger,
        }


@dataclass
class SupplierRiskProfile:
    """Everything the UI and the copilot need about one supplier."""

    supplier_id: str
    supplier_name: str | None
    country: str | None
    spend_category: str | None
    materials_supplied: list[str]
    regions_served: list[str]

    score: SupplierRiskScore
    trend: RiskTrend
    actions: list[RecommendedAction] = field(default_factory=list)

    # Supporting figures shown on the supplier profile
    total_spend: float | None = None
    total_spend_base: float | None = None
    currency: str | None = None
    purchase_order_count: int | None = None
    open_purchase_order_count: int | None = None
    active_contract_count: int | None = None
    contract_status: str | None = None
    contract_expiration: date | None = None
    contract_number: str | None = None
    days_to_contract_expiry: int | None = None
    contract_expiring_soon: bool = False
    on_time_delivery_rate: float | None = None
    late_delivery_count: int | None = None
    delivery_count: int | None = None
    quality_score: float | None = None
    defect_rate: float | None = None
    quality_incident_count: int | None = None
    invoice_count: int | None = None
    invoice_exception_count: int | None = None
    disputed_invoice_count: int | None = None
    compliance_finding_count: int | None = None
    esg_score: float | None = None
    credit_score: float | None = None

    delivery_issues: list[dict[str, Any]] = field(default_factory=list)
    invoice_issues: list[dict[str, Any]] = field(default_factory=list)
    quality_issues: list[dict[str, Any]] = field(default_factory=list)
    compliance_issues: list[dict[str, Any]] = field(default_factory=list)
    event_count: int = 0

    @property
    def overall_score(self) -> float | None:
        return self.score.overall_score

    @property
    def overall_band(self) -> str | None:
        return self.score.overall_band

    def category_score(self, name: str) -> float | None:
        category = self.score.categories.get(name)
        return category.score if category else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier_id": self.supplier_id,
            "supplier_name": self.supplier_name,
            "country": self.country,
            "spend_category": self.spend_category,
            "materials_supplied": list(self.materials_supplied),
            "regions_served": list(self.regions_served),
            "overall_score": self.overall_score,
            "overall_band": self.overall_band,
            "score": self.score.to_dict(),
            "trend": self.trend.to_dict(),
            "actions": [action.to_dict() for action in self.actions],
            "total_spend": self.total_spend,
            "total_spend_base": self.total_spend_base,
            "currency": self.currency,
            "purchase_order_count": self.purchase_order_count,
            "open_purchase_order_count": self.open_purchase_order_count,
            "active_contract_count": self.active_contract_count,
            "contract_status": self.contract_status,
            "contract_expiration": (
                self.contract_expiration.isoformat() if self.contract_expiration else None
            ),
            "contract_number": self.contract_number,
            "days_to_contract_expiry": self.days_to_contract_expiry,
            "contract_expiring_soon": self.contract_expiring_soon,
            "on_time_delivery_rate": self.on_time_delivery_rate,
            "late_delivery_count": self.late_delivery_count,
            "delivery_count": self.delivery_count,
            "quality_score": self.quality_score,
            "defect_rate": self.defect_rate,
            "quality_incident_count": self.quality_incident_count,
            "invoice_count": self.invoice_count,
            "invoice_exception_count": self.invoice_exception_count,
            "disputed_invoice_count": self.disputed_invoice_count,
            "compliance_finding_count": self.compliance_finding_count,
            "esg_score": self.esg_score,
            "credit_score": self.credit_score,
            "delivery_issues": list(self.delivery_issues),
            "invoice_issues": list(self.invoice_issues),
            "quality_issues": list(self.quality_issues),
            "compliance_issues": list(self.compliance_issues),
            "event_count": self.event_count,
        }


@dataclass
class RiskAssessmentResult:
    """The outcome of assessing every loaded supplier."""

    profiles: list[SupplierRiskProfile] = field(default_factory=list)
    as_of_date: date | None = None
    weights: dict[str, float] = field(default_factory=dict)
    supplier_count: int = 0
    scored_count: int = 0
    event_count: int = 0
    band_counts: dict[str, int] = field(default_factory=dict)
    category_averages: dict[str, float | None] = field(default_factory=dict)
    average_overall_score: float | None = None
    highest_risk_supplier_id: str | None = None
    highest_risk_score: float | None = None
    contracts_expiring_count: int = 0
    limited_data_count: int = 0
    rule_errors: list[dict[str, Any]] = field(default_factory=list)
    engine_version: str = ENGINE_VERSION

    def by_id(self, supplier_id: str) -> SupplierRiskProfile | None:
        for profile in self.profiles:
            if profile.supplier_id == supplier_id:
                return profile
        return None


def _events_by_supplier(
    events: list[NormalizedRiskEvent],
) -> dict[str, list[NormalizedRiskEvent]]:
    grouped: dict[str, list[NormalizedRiskEvent]] = {}
    for event in events:
        grouped.setdefault(event.supplier_id, []).append(event)
    return grouped


def _event_record(event: NormalizedRiskEvent) -> dict[str, Any]:
    """The citable shape of one internal record."""
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "event_date": event.event_date.isoformat() if event.event_date else None,
        "reference": event.reference,
        "severity": event.severity,
        "description": event.description,
        "amount": event.amount,
        "amount_base": event.amount_base,
        "currency": event.currency,
    }


def compute_trend(
    events: list[NormalizedRiskEvent],
    config: SupplierRiskConfig,
    as_of: date,
) -> RiskTrend:
    """Compare severity-weighted event volume in the recent window against the previous one.

    With too few dated events the trend is reported as ``unknown``. The lab does
    not guess a direction from a single record.
    """
    window = config.trend.window_days
    recent_start = as_of - timedelta(days=window)
    previous_start = as_of - timedelta(days=window * 2)

    recent_weight = 0.0
    previous_weight = 0.0
    recent_count = 0
    previous_count = 0

    for event in events:
        if event.event_date is None:
            continue
        weight = config.trend.severity_weight(event.severity)
        if recent_start < event.event_date <= as_of:
            recent_weight += weight
            recent_count += 1
        elif previous_start < event.event_date <= recent_start:
            previous_weight += weight
            previous_count += 1

    dated_total = recent_count + previous_count
    if dated_total < config.trend.minimum_events:
        return RiskTrend(
            direction="unknown",
            recent_weight=round_half_up(recent_weight),
            previous_weight=round_half_up(previous_weight),
            delta=0.0,
            recent_event_count=recent_count,
            previous_event_count=previous_count,
            window_days=window,
            basis=(
                f"Only {dated_total} dated risk record(s) in the last {window * 2} days; "
                f"at least {config.trend.minimum_events} are needed to state a trend."
            ),
            data_available=False,
        )

    # The shipped severity weights are whole numbers, so this subtraction is
    # exact today. It is rounded through the same decimal policy anyway,
    # because ``delta`` is both a reported figure and the input to the
    # improving/deteriorating comparison below, and the weights are
    # configurable - a retune to 1.5 / 2.3 would make it drift.
    delta = round_half_up(recent_weight - previous_weight)
    if delta <= config.trend.improving_delta:
        direction = "improving"
    elif delta >= config.trend.deteriorating_delta:
        direction = "deteriorating"
    else:
        direction = "stable"

    basis = (
        f"Severity-weighted risk records: {recent_weight:g} in the last {window} days "
        f"({recent_count} record(s)) against {previous_weight:g} in the {window} days before "
        f"({previous_count} record(s)); change {delta:+g}."
    )
    return RiskTrend(
        direction=direction,
        recent_weight=round_half_up(recent_weight),
        previous_weight=round_half_up(previous_weight),
        delta=delta,
        recent_event_count=recent_count,
        previous_event_count=previous_count,
        window_days=window,
        basis=basis,
        data_available=True,
    )


def build_actions(
    score: SupplierRiskScore,
    config: SupplierRiskConfig,
) -> list[RecommendedAction]:
    """Rule-based recommended actions, highest-scoring category first."""
    trigger_rank = config.risk_bands.rank(config.actions.trigger_band)
    actions: list[RecommendedAction] = []

    if (
        config.actions.overall_critical_action
        and score.overall_band is not None
        and config.risk_bands.rank(score.overall_band) >= config.risk_bands.rank("critical")
    ):
        actions.append(
            RecommendedAction(
                category="overall",
                category_label="Overall supplier risk",
                priority="critical",
                action=config.actions.overall_critical_action,
                trigger=(
                    f"Overall risk {score.overall_score:g} is in the "
                    f"'{score.overall_band}' band."
                ),
            )
        )

    rules_by_category = {rule.category: rule for rule in config.actions.rules}
    triggered = [
        category
        for category in score.categories.values()
        if category.data_available
        and category.band is not None
        and config.risk_bands.rank(category.band) >= trigger_rank
        and category.category in rules_by_category
    ]
    triggered.sort(key=lambda item: (-(item.score or 0.0), item.category))

    for category in triggered:
        rule = rules_by_category[category.category]
        actions.append(
            RecommendedAction(
                category=category.category,
                category_label=category.label,
                priority=rule.priority,
                action=rule.action,
                trigger=(
                    f"{category.label} scored {category.score:g} "
                    f"('{category.band}' band)."
                ),
            )
        )

    return actions[: config.actions.max_actions]


def find_alternatives(
    profile: SupplierRiskProfile,
    all_profiles: list[SupplierRiskProfile],
    config: SupplierRiskConfig,
) -> list[SupplierRiskProfile]:
    """Suppliers comparable to ``profile`` that carry meaningfully lower risk.

    A candidate must supply something comparable - the same spend category, or
    failing that an overlapping material - and must beat the supplier by at
    least the configured margin.
    """
    if profile.overall_score is None:
        return []

    settings = config.alternatives
    materials = {item.lower() for item in profile.materials_supplied}
    candidates: list[SupplierRiskProfile] = []

    for other in all_profiles:
        if other.supplier_id == profile.supplier_id or other.overall_score is None:
            continue

        comparable = False
        if (
            settings.match_on_spend_category
            and profile.spend_category
            and other.spend_category
            and other.spend_category.strip().lower() == profile.spend_category.strip().lower()
        ):
            comparable = True
        if not comparable and settings.match_on_material and materials:
            if materials & {item.lower() for item in other.materials_supplied}:
                comparable = True
        if not comparable:
            continue

        if profile.overall_score - other.overall_score >= settings.minimum_improvement:
            candidates.append(other)

    candidates.sort(key=lambda item: (item.overall_score or 0.0, item.supplier_id))
    return candidates[: settings.max_alternatives]


def _build_profile(
    record: NormalizedSupplierProfile,
    events: list[NormalizedRiskEvent],
    weights: CategoryWeights,
    config: SupplierRiskConfig,
    as_of: date,
    rule_errors: list[dict[str, Any]],
) -> SupplierRiskProfile:
    score = score_supplier(record, weights, config, as_of, errors=rule_errors)
    trend = compute_trend(events, config, as_of)

    dated = sorted(
        events,
        key=lambda item: (item.event_date or date.min, item.event_id),
        reverse=True,
    )
    days_to_expiry = record.days_to_contract_expiry(as_of)

    profile = SupplierRiskProfile(
        supplier_id=record.supplier_id,
        supplier_name=record.supplier_name,
        country=record.country,
        spend_category=record.spend_category,
        materials_supplied=list(record.materials_supplied),
        regions_served=list(record.regions_served),
        score=score,
        trend=trend,
        total_spend=record.historical_spend,
        total_spend_base=record.historical_spend_base,
        currency=record.currency,
        purchase_order_count=record.historical_order_count,
        open_purchase_order_count=record.open_purchase_order_count,
        active_contract_count=record.active_contract_count,
        contract_status=record.contract_status,
        contract_expiration=record.contract_expiration,
        contract_number=record.contract_number,
        days_to_contract_expiry=days_to_expiry,
        contract_expiring_soon=(
            days_to_expiry is not None
            and days_to_expiry <= config.contract_expiry.expiring_within_days
        ),
        on_time_delivery_rate=record.on_time_delivery_rate,
        late_delivery_count=record.late_delivery_count,
        delivery_count=record.delivery_count,
        quality_score=record.quality_score,
        defect_rate=record.defect_rate,
        quality_incident_count=record.quality_incident_count,
        invoice_count=record.invoice_count,
        invoice_exception_count=record.invoice_exception_count,
        disputed_invoice_count=record.disputed_invoice_count,
        compliance_finding_count=record.compliance_finding_count,
        esg_score=record.esg_score,
        credit_score=record.credit_score,
        delivery_issues=[_event_record(e) for e in dated if e.event_type in DELIVERY_EVENT_TYPES],
        invoice_issues=[_event_record(e) for e in dated if e.event_type in INVOICE_EVENT_TYPES],
        quality_issues=[_event_record(e) for e in dated if e.event_type in QUALITY_EVENT_TYPES],
        compliance_issues=[
            _event_record(e) for e in dated if e.event_type in COMPLIANCE_EVENT_TYPES
        ],
        event_count=len(events),
    )
    profile.actions = build_actions(score, config)
    if not profile.actions and config.actions.no_action_message:
        profile.actions = []
    return profile


def run_risk_assessment(
    records: list[NormalizedSupplierProfile],
    events: list[NormalizedRiskEvent],
    weights: CategoryWeights,
    config: SupplierRiskConfig,
    as_of: date,
) -> RiskAssessmentResult:
    """Score every supplier and summarise the portfolio.

    Suppliers are processed in a stable id order so repeated runs over the same
    data produce byte-identical results.
    """
    ordered = sorted(records, key=lambda item: item.supplier_id)
    grouped = _events_by_supplier(events)
    rule_errors: list[dict[str, Any]] = []

    profiles: list[SupplierRiskProfile] = []
    for record in ordered:
        try:
            profiles.append(
                _build_profile(
                    record,
                    grouped.get(record.supplier_id, []),
                    weights,
                    config,
                    as_of,
                    rule_errors,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one bad supplier never fails the run
            logger.warning(
                "Supplier %s could not be profiled: %s", record.supplier_id, type(exc).__name__
            )
            rule_errors.append(
                {
                    "supplier_id": record.supplier_id,
                    "category": "profile",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    scored = [item for item in profiles if item.overall_score is not None]
    band_counts: dict[str, int] = {label: 0 for label in config.risk_bands.labels}
    for item in scored:
        if item.overall_band:
            band_counts[item.overall_band] = band_counts.get(item.overall_band, 0) + 1

    # Portfolio aggregates are averages of figures that were already published
    # at two decimals, so they are computed as decimals rather than floats.
    # Summing 54 two-decimal values in binary drifts by ~1e-15, which is enough
    # to flip a mean that lands on a rounding tie: the invoice average here is
    # exactly 20.195, and the float sum reported 20.19 on one interpreter and
    # 20.20 on another from identical inputs. See app/core/rounding.py.
    category_averages: dict[str, float | None] = {}
    for name in RISK_CATEGORIES:
        values = [
            item.score.categories[name].score
            for item in profiles
            if name in item.score.categories and item.score.categories[name].score is not None
        ]
        category_averages[name] = decimal_mean(values)

    average_overall = decimal_mean(item.overall_score for item in scored)

    ranked = sorted(
        scored, key=lambda item: (-(item.overall_score or 0.0), item.supplier_id)
    )
    highest = ranked[0] if ranked else None

    result = RiskAssessmentResult(
        profiles=profiles,
        as_of_date=as_of,
        weights=weights.as_dict(),
        supplier_count=len(profiles),
        scored_count=len(scored),
        event_count=len(events),
        band_counts=band_counts,
        category_averages=category_averages,
        average_overall_score=average_overall,
        highest_risk_supplier_id=highest.supplier_id if highest else None,
        highest_risk_score=highest.overall_score if highest else None,
        contracts_expiring_count=sum(1 for item in profiles if item.contract_expiring_soon),
        limited_data_count=sum(1 for item in profiles if item.score.limited_data),
        rule_errors=rule_errors,
    )

    logger.info(
        "Assessed %d suppliers (%d scored, %d events, %d rule errors)",
        result.supplier_count,
        result.scored_count,
        result.event_count,
        len(rule_errors),
    )
    return result
