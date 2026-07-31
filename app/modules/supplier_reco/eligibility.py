"""Eligibility filtering - the hard constraints applied *before* ranking.

A supplier that fails any enforced constraint is marked ineligible and is not
scored or ranked. Every rejection carries a human-readable reason, so a buyer
can see exactly why a supplier was excluded rather than just missing from the
list.

Each constraint maps to a field on the purchasing requirement and can be turned
off in the configuration file (``eligibility.enforce_*``).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.supplier_reco.normalizer import NormalizedSupplier
from app.modules.supplier_reco.requirement import Requirement
from app.modules.supplier_reco.thresholds import SupplierRecoConfig


@dataclass
class EligibilityResult:
    """The outcome of the eligibility check for one supplier."""

    is_eligible: bool
    reasons: list[str]

    @property
    def status(self) -> str:
        return "eligible" if self.is_eligible else "ineligible"


def _contains(haystack: list[str], needle: str | None) -> bool:
    """Case-insensitive membership test tolerant of surrounding whitespace."""
    if not needle:
        return False
    wanted = needle.strip().lower()
    return any(item.strip().lower() == wanted for item in haystack)


def evaluate_eligibility(
    supplier: NormalizedSupplier,
    requirement: Requirement,
    config: SupplierRecoConfig,
) -> EligibilityResult:
    """Return whether ``supplier`` may be ranked for ``requirement``.

    The checks are deterministic and independent; every failed one is recorded
    so the full reason list is returned, not just the first failure.
    """
    settings = config.eligibility
    reasons: list[str] = []

    # 1. Must supply the requested material.
    if settings.enforce_material_match and requirement.material:
        if not _contains(supplier.materials_supplied, requirement.material):
            reasons.append(
                f"Does not supply material {requirement.material}."
            )

    # 2. Must serve the requested plant.
    if settings.enforce_plant_match and requirement.plant:
        if supplier.plants_served and not _contains(supplier.plants_served, requirement.plant):
            reasons.append(f"Does not serve plant {requirement.plant}.")

    # 3. Must have enough available capacity.
    if settings.enforce_min_capacity:
        minimum = requirement.minimum_available_capacity
        if minimum is not None:
            if supplier.available_capacity is None:
                reasons.append("Available capacity is not known.")
            elif supplier.available_capacity < minimum:
                reasons.append(
                    f"Available capacity {supplier.available_capacity:g} is below the required "
                    f"minimum {minimum:g}."
                )
        if (
            settings.require_capacity_covers_quantity
            and requirement.quantity
            and supplier.available_capacity is not None
            and supplier.available_capacity < requirement.quantity
        ):
            reasons.append(
                f"Available capacity {supplier.available_capacity:g} cannot cover the requested "
                f"quantity {requirement.quantity:g}."
            )

    # 4. Must meet the minimum quality score.
    if settings.enforce_min_quality and requirement.minimum_quality_score is not None:
        if supplier.quality_score is None:
            reasons.append("Quality score is not known.")
        elif supplier.quality_score < requirement.minimum_quality_score:
            reasons.append(
                f"Quality score {supplier.quality_score:g} is below the required minimum "
                f"{requirement.minimum_quality_score:g}."
            )

    # 5. Must sit within the risk tolerance.
    if settings.enforce_risk_tolerance:
        max_risk = settings.max_risk_for(requirement.risk_tolerance)
        if supplier.risk_score is not None and supplier.risk_score > max_risk:
            reasons.append(
                f"Risk score {supplier.risk_score:g} exceeds the '{requirement.risk_tolerance}' "
                f"tolerance ceiling of {max_risk:g}."
            )

    # 6. Must meet the sustainability requirement (minimum ESG score).
    if settings.enforce_sustainability and requirement.sustainability_requirement is not None:
        if supplier.esg_score is None:
            reasons.append("ESG score is not known.")
        elif supplier.esg_score < requirement.sustainability_requirement:
            reasons.append(
                f"ESG score {supplier.esg_score:g} is below the required minimum "
                f"{requirement.sustainability_requirement:g}."
            )

    # 7. Must hold a contract when the requirement demands one.
    if settings.enforce_contract_requirement and requirement.contract_requirement:
        if not _has_active_contract(supplier, config):
            reasons.append("No active contract, which is required for this requirement.")

    return EligibilityResult(is_eligible=not reasons, reasons=reasons)


def _has_active_contract(supplier: NormalizedSupplier, config: SupplierRecoConfig) -> bool:
    """True when the supplier's contract status classifies as active."""
    status = (supplier.contract_status or "").strip().lower()
    if not status:
        return False
    active = {v.lower() for v in config.classification.active_contract_values}
    return status in active
