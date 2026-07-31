"""Orchestrates one supplier recommendation, end to end.

    suppliers + requirement + weights
        -> eligibility filter        (drop suppliers that fail a hard constraint)
        -> weighted scoring          (nine sub-scores + overall, for the eligible)
        -> ranking                   (deterministic, stable tie-breaks)
        -> estimated cost / delivery, advantages, risks, explanation

Every figure and every ranking decision is deterministic. The AI layer, if
enabled, only summarises the finished ranking - it never changes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.core.logging import get_logger
from app.modules.supplier_reco.eligibility import evaluate_eligibility
from app.modules.supplier_reco.normalizer import NormalizedSupplier
from app.modules.supplier_reco.requirement import Requirement
from app.modules.supplier_reco.scoring import (
    SCORING_ENGINE_VERSION,
    SupplierScores,
    score_suppliers,
)
from app.modules.supplier_reco.thresholds import SupplierRecoConfig, Weights

logger = get_logger(__name__)


@dataclass
class RankedSupplier:
    """One supplier's place in the recommendation."""

    supplier_id: str
    supplier_name: str | None
    rank: int | None
    eligibility_status: str
    is_eligible: bool
    overall_score: float
    cost_score: float
    delivery_score: float
    quality_score: float
    capacity_score: float
    risk_score: float
    esg_score: float
    contract_score: float
    geographic_score: float
    past_performance_score: float
    estimated_unit_price_base: float | None
    estimated_total_cost_base: float | None
    estimated_delivery_date: date | None
    lead_time_days: int | None
    contract_status: str | None
    contract_classification: str
    advantages: list[str]
    risks: list[str]
    explanation: str
    ineligibility_reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier_id": self.supplier_id,
            "supplier_name": self.supplier_name,
            "rank": self.rank,
            "eligibility_status": self.eligibility_status,
            "is_eligible": self.is_eligible,
            "overall_score": self.overall_score,
            "cost_score": self.cost_score,
            "delivery_score": self.delivery_score,
            "quality_score": self.quality_score,
            "capacity_score": self.capacity_score,
            "risk_score": self.risk_score,
            "esg_score": self.esg_score,
            "contract_score": self.contract_score,
            "geographic_score": self.geographic_score,
            "past_performance_score": self.past_performance_score,
            "estimated_unit_price_base": self.estimated_unit_price_base,
            "estimated_total_cost_base": self.estimated_total_cost_base,
            "estimated_delivery_date": self.estimated_delivery_date.isoformat()
            if self.estimated_delivery_date
            else None,
            "lead_time_days": self.lead_time_days,
            "contract_status": self.contract_status,
            "contract_classification": self.contract_classification,
            "advantages": list(self.advantages),
            "risks": list(self.risks),
            "explanation": self.explanation,
            "ineligibility_reasons": list(self.ineligibility_reasons),
            "evidence": self.evidence,
        }


@dataclass
class RecommendationResult:
    """The complete deterministic outcome of one recommendation run."""

    ranked: list[RankedSupplier]
    total_supplier_count: int
    eligible_count: int
    ineligible_count: int
    weights: dict[str, float]
    base_currency: str
    scoring_engine_version: str = SCORING_ENGINE_VERSION
    top_supplier_id: str | None = None
    top_supplier_score: float | None = None

    @property
    def eligible(self) -> list[RankedSupplier]:
        return [entry for entry in self.ranked if entry.is_eligible]


def run_recommendation(
    suppliers: list[NormalizedSupplier],
    requirement: Requirement,
    weights: Weights,
    config: SupplierRecoConfig,
) -> RecommendationResult:
    """Run eligibility, scoring and ranking for a requirement over a catalogue."""
    # Deterministic starting order (min/max ranges are order-independent, but a
    # stable input order keeps everything downstream reproducible).
    ordered = sorted(suppliers, key=lambda s: s.supplier_id)

    eligible: list[NormalizedSupplier] = []
    reasons_by_id: dict[str, list[str]] = {}
    for supplier in ordered:
        result = evaluate_eligibility(supplier, requirement, config)
        if result.is_eligible:
            eligible.append(supplier)
        else:
            reasons_by_id[supplier.supplier_id] = result.reasons

    scores = score_suppliers(eligible, requirement, weights, config)

    ranked_eligible = sorted(
        eligible,
        key=lambda s: (
            -scores[s.supplier_id].overall,
            s.unit_price_base if s.unit_price_base is not None else float("inf"),
            s.supplier_id,
        ),
    )

    ranked: list[RankedSupplier] = []
    for position, supplier in enumerate(ranked_eligible, start=1):
        ranked.append(
            _build_eligible_entry(
                supplier, scores[supplier.supplier_id], position, len(ranked_eligible),
                requirement, config,
            )
        )

    if config.reporting.include_ineligible_in_results:
        for supplier in ordered:
            if supplier.supplier_id in reasons_by_id:
                ranked.append(
                    _build_ineligible_entry(supplier, reasons_by_id[supplier.supplier_id])
                )

    top = ranked_eligible[0] if ranked_eligible else None
    logger.info(
        "Recommendation over %d suppliers: %d eligible, top=%s",
        len(ordered), len(eligible), top.supplier_id if top else None,
    )
    return RecommendationResult(
        ranked=ranked,
        total_supplier_count=len(ordered),
        eligible_count=len(eligible),
        ineligible_count=len(reasons_by_id),
        weights=weights.as_dict(),
        base_currency=config.base_currency,
        top_supplier_id=top.supplier_id if top else None,
        top_supplier_score=scores[top.supplier_id].overall if top else None,
    )


def _build_eligible_entry(
    supplier: NormalizedSupplier,
    scores: SupplierScores,
    rank: int,
    eligible_count: int,
    requirement: Requirement,
    config: SupplierRecoConfig,
) -> RankedSupplier:
    """Assemble a ranked, scored entry for an eligible supplier."""
    estimated_unit = supplier.unit_price_base
    estimated_total = (
        round(estimated_unit * requirement.quantity, 2)
        if estimated_unit is not None and requirement.quantity
        else None
    )
    estimated_delivery = _estimated_delivery_date(supplier, requirement)
    advantages, risks = _advantages_and_risks(supplier, scores, requirement, config)

    explanation = _explanation(supplier, scores, rank, eligible_count, estimated_total, config)

    return RankedSupplier(
        supplier_id=supplier.supplier_id,
        supplier_name=supplier.supplier_name,
        rank=rank,
        eligibility_status="eligible",
        is_eligible=True,
        overall_score=scores.overall,
        cost_score=scores.cost,
        delivery_score=scores.delivery,
        quality_score=scores.quality,
        capacity_score=scores.capacity,
        risk_score=scores.risk,
        esg_score=scores.esg,
        contract_score=scores.contract,
        geographic_score=scores.geographic,
        past_performance_score=scores.past_performance,
        estimated_unit_price_base=estimated_unit,
        estimated_total_cost_base=estimated_total,
        estimated_delivery_date=estimated_delivery,
        lead_time_days=supplier.lead_time_days,
        contract_status=supplier.contract_status,
        contract_classification=scores.contract_class,
        advantages=advantages,
        risks=risks,
        explanation=explanation,
        evidence={
            "scores": scores.as_dict(),
            "components": scores.components,
            "unit_price": supplier.unit_price,
            "unit_price_base": supplier.unit_price_base,
            "currency": supplier.currency,
            "available_capacity": supplier.available_capacity,
            "quantity_required": requirement.quantity,
            "on_time_delivery_rate": supplier.on_time_delivery_rate,
            "quality_score_input": supplier.quality_score,
            "defect_rate": supplier.defect_rate,
            "risk_score_input": supplier.risk_score,
            "esg_score_input": supplier.esg_score,
            "contract_expiration": supplier.contract_expiration.isoformat()
            if supplier.contract_expiration
            else None,
            "historical_order_count": supplier.historical_order_count,
            "historical_spend_base": supplier.historical_spend_base,
        },
    )


def _build_ineligible_entry(
    supplier: NormalizedSupplier, reasons: list[str]
) -> RankedSupplier:
    """Assemble an entry for a supplier excluded before ranking."""
    return RankedSupplier(
        supplier_id=supplier.supplier_id,
        supplier_name=supplier.supplier_name,
        rank=None,
        eligibility_status="ineligible",
        is_eligible=False,
        overall_score=0.0,
        cost_score=0.0,
        delivery_score=0.0,
        quality_score=0.0,
        capacity_score=0.0,
        risk_score=0.0,
        esg_score=0.0,
        contract_score=0.0,
        geographic_score=0.0,
        past_performance_score=0.0,
        estimated_unit_price_base=supplier.unit_price_base,
        estimated_total_cost_base=None,
        estimated_delivery_date=None,
        lead_time_days=supplier.lead_time_days,
        contract_status=supplier.contract_status,
        contract_classification="unknown",
        advantages=[],
        risks=list(reasons),
        explanation="Excluded before ranking: " + " ".join(reasons),
        ineligibility_reasons=list(reasons),
        evidence={"ineligibility_reasons": list(reasons)},
    )


def _estimated_delivery_date(
    supplier: NormalizedSupplier, requirement: Requirement
) -> date | None:
    """Order date plus lead time, when both are known."""
    if requirement.order_date is None or supplier.lead_time_days is None:
        return None
    return requirement.order_date + timedelta(days=int(supplier.lead_time_days))


def _advantages_and_risks(
    supplier: NormalizedSupplier,
    scores: SupplierScores,
    requirement: Requirement,
    config: SupplierRecoConfig,
) -> tuple[list[str], list[str]]:
    """Generate rule-based advantages and risks from the scores and the facts."""
    settings = config.advantages
    high = settings.high_score_threshold
    low = settings.low_score_threshold
    currency = config.base_currency

    advantages: list[str] = []
    risks: list[str] = []

    target_base = requirement.target_price_base(config)

    # --- Cost ----------------------------------------------------------
    if scores.cost >= high:
        advantages.append("Among the most competitively priced eligible suppliers.")
    if target_base is not None and supplier.unit_price_base is not None:
        if supplier.unit_price_base <= target_base:
            advantages.append(
                f"Unit price {supplier.unit_price_base:,.2f} {currency} is at or below the target "
                f"of {target_base:,.2f} {currency}."
            )
        else:
            risks.append(
                f"Unit price {supplier.unit_price_base:,.2f} {currency} is above the target of "
                f"{target_base:,.2f} {currency}."
            )
    elif scores.cost <= low:
        risks.append("Pricing is high relative to the other eligible suppliers.")

    # --- Delivery ------------------------------------------------------
    if scores.delivery >= high:
        detail = []
        if supplier.on_time_delivery_rate is not None:
            detail.append(f"on-time {supplier.on_time_delivery_rate:g}%")
        if supplier.lead_time_days is not None:
            detail.append(f"lead time {supplier.lead_time_days} days")
        advantages.append("Strong delivery profile" + (f" ({', '.join(detail)})." if detail else "."))
    window = requirement.days_until_required()
    if window is not None and supplier.lead_time_days is not None and supplier.lead_time_days > window:
        risks.append(
            f"Lead time {supplier.lead_time_days} days may miss the required delivery date "
            f"(only {window} days available)."
        )
    elif scores.delivery <= low:
        risks.append("Delivery reliability is weaker than the eligible-pool average.")

    # --- Quality -------------------------------------------------------
    if scores.quality >= high and supplier.quality_score is not None:
        advantages.append(f"High quality score ({supplier.quality_score:g}).")
    if supplier.defect_rate is not None and supplier.defect_rate >= settings.high_defect_rate_pct:
        risks.append(f"Elevated defect rate ({supplier.defect_rate:g}%).")
    elif scores.quality <= low:
        risks.append("Quality is below the eligible-pool norm.")

    # --- Capacity ------------------------------------------------------
    if scores.capacity >= high and supplier.available_capacity is not None:
        if requirement.quantity:
            advantages.append(
                f"Ample capacity ({supplier.available_capacity:g} available for "
                f"{requirement.quantity:g} required)."
            )
        else:
            advantages.append(f"High available capacity ({supplier.available_capacity:g}).")
    elif scores.capacity <= low:
        risks.append("Limited spare capacity relative to the requirement.")

    # --- Risk ----------------------------------------------------------
    if scores.risk >= high and supplier.risk_score is not None:
        advantages.append(f"Low supplier risk (risk score {supplier.risk_score:g}).")
    if supplier.risk_score is not None and supplier.risk_score >= settings.elevated_risk_score:
        risks.append(f"Elevated supplier risk (risk score {supplier.risk_score:g}).")

    # --- ESG -----------------------------------------------------------
    if scores.esg >= high and supplier.esg_score is not None:
        advantages.append(f"Strong ESG score ({supplier.esg_score:g}).")
    elif scores.esg <= low:
        risks.append("ESG performance is below the eligible-pool norm.")

    # --- Contract ------------------------------------------------------
    if scores.contract_class == "active":
        advantages.append("Active contract already in place.")
    elif scores.contract_class == "expiring":
        risks.append("Contract is expiring or lapses before the required delivery date.")
    elif scores.contract_class in ("none", "unknown"):
        risks.append("No active contract in place.")

    # --- Geographic ----------------------------------------------------
    if scores.geographic >= high and (requirement.preferred_region or requirement.plant):
        advantages.append("Serves the preferred region and/or requested plant.")

    # --- Past performance ---------------------------------------------
    if scores.past_performance >= high and supplier.historical_order_count is not None:
        advantages.append(
            f"Established relationship ({supplier.historical_order_count:g} historical orders)."
        )

    if supplier.unit_price_base is None:
        risks.append("No unit price provided, so the cost dimension scored zero.")

    return advantages[: settings.max_advantages], risks[: settings.max_risks]


def _explanation(
    supplier: NormalizedSupplier,
    scores: SupplierScores,
    rank: int,
    eligible_count: int,
    estimated_total: float | None,
    config: SupplierRecoConfig,
) -> str:
    """A short, deterministic explanation of the supplier's rank."""
    from app.modules.supplier_reco.thresholds import SCORE_DIMENSIONS

    dimension_labels = {
        "cost": "cost", "delivery": "delivery", "quality": "quality",
        "capacity": "capacity", "risk": "risk", "esg": "ESG", "contract": "contract",
        "geographic": "geographic fit", "past_performance": "past performance",
    }
    top_dims = sorted(SCORE_DIMENSIONS, key=lambda d: getattr(scores, d), reverse=True)[:2]
    drivers = " and ".join(dimension_labels[d] for d in top_dims)
    currency = config.base_currency

    parts = [
        f"Ranked #{rank} of {eligible_count} eligible suppliers with an overall score of "
        f"{scores.overall:g}/100.",
        f"The score is driven mainly by {drivers}.",
    ]
    if estimated_total is not None:
        parts.append(f"Estimated total cost {estimated_total:,.2f} {currency}.")
    if supplier.lead_time_days is not None:
        parts.append(f"Quoted lead time {supplier.lead_time_days} days.")
    return " ".join(parts)
