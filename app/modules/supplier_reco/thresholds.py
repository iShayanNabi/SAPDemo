"""Typed, validated access to the Supplier Recommendation configuration.

Every weight, scoring blend, eligibility rule and classification list the module
uses is declared in ``config/supplier_reco_rules.json`` and validated here at
load time. The engine reads values through this object, so retuning the model is
a JSON edit rather than a code change.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "supplier_reco_rules.json"

#: The nine scoring dimensions, in the order the UI should show them.
SCORE_DIMENSIONS: tuple[str, ...] = (
    "cost", "delivery", "quality", "capacity", "risk", "esg", "contract",
    "geographic", "past_performance",
)


class Weights(BaseModel):
    """The nine scoring weights. Percentages that must sum to the configured total."""

    cost: float = Field(ge=0.0, le=100.0)
    delivery: float = Field(ge=0.0, le=100.0)
    quality: float = Field(ge=0.0, le=100.0)
    capacity: float = Field(ge=0.0, le=100.0)
    risk: float = Field(ge=0.0, le=100.0)
    esg: float = Field(ge=0.0, le=100.0)
    contract: float = Field(ge=0.0, le=100.0)
    geographic: float = Field(ge=0.0, le=100.0)
    past_performance: float = Field(ge=0.0, le=100.0)

    def total(self) -> float:
        """Sum of every weight."""
        return round(sum(getattr(self, dim) for dim in SCORE_DIMENSIONS), 6)

    def as_dict(self) -> dict[str, float]:
        return {dim: float(getattr(self, dim)) for dim in SCORE_DIMENSIONS}


class DeliveryScoring(BaseModel):
    description: str = ""
    on_time_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    lead_time_weight: float = Field(default=0.4, ge=0.0, le=1.0)


class QualityScoring(BaseModel):
    description: str = ""
    quality_weight: float = Field(default=0.75, ge=0.0, le=1.0)
    defect_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    defect_rate_scale: float = Field(default=10.0, ge=0.0)


class CapacityScoring(BaseModel):
    description: str = ""
    target_coverage_ratio: float = Field(default=1.5, gt=0.0)


class ContractScoring(BaseModel):
    description: str = ""
    active_score: float = 100.0
    expiring_score: float = 60.0
    none_score: float = 20.0
    unknown_score: float = 40.0
    expiring_within_days: int = Field(default=90, ge=0)


class GeographicScoring(BaseModel):
    description: str = ""
    region_match_score: float = Field(default=60.0, ge=0.0)
    plant_match_score: float = Field(default=40.0, ge=0.0)
    no_preference_score: float = Field(default=100.0, ge=0.0, le=100.0)


class PastPerformanceScoring(BaseModel):
    description: str = ""
    order_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    spend_weight: float = Field(default=0.5, ge=0.0, le=1.0)


class SimpleScoring(BaseModel):
    """A scoring block that only carries a description (risk, esg)."""

    description: str = ""


class ScoringSettings(BaseModel):
    """All per-dimension scoring parameters."""

    delivery: DeliveryScoring = Field(default_factory=DeliveryScoring)
    quality: QualityScoring = Field(default_factory=QualityScoring)
    capacity: CapacityScoring = Field(default_factory=CapacityScoring)
    risk: SimpleScoring = Field(default_factory=SimpleScoring)
    esg: SimpleScoring = Field(default_factory=SimpleScoring)
    contract: ContractScoring = Field(default_factory=ContractScoring)
    geographic: GeographicScoring = Field(default_factory=GeographicScoring)
    past_performance: PastPerformanceScoring = Field(default_factory=PastPerformanceScoring)


class EligibilitySettings(BaseModel):
    """Which hard constraints are enforced before ranking."""

    description: str = ""
    risk_tolerance_max_score: dict[str, float] = Field(
        default_factory=lambda: {"low": 30.0, "medium": 60.0, "high": 100.0}
    )
    default_risk_tolerance: str = "medium"
    enforce_material_match: bool = True
    enforce_plant_match: bool = True
    enforce_min_capacity: bool = True
    enforce_min_quality: bool = True
    enforce_risk_tolerance: bool = True
    enforce_sustainability: bool = True
    enforce_contract_requirement: bool = True
    require_capacity_covers_quantity: bool = True

    def max_risk_for(self, tolerance: str | None) -> float:
        """Maximum acceptable risk score for a tolerance level."""
        key = (tolerance or self.default_risk_tolerance).strip().lower()
        return float(self.risk_tolerance_max_score.get(key, self.risk_tolerance_max_score.get("medium", 60.0)))


class ClassificationSettings(BaseModel):
    """Value lists that interpret the free-text contract status column."""

    active_contract_values: list[str] = Field(default_factory=list)
    expiring_contract_values: list[str] = Field(default_factory=list)
    no_contract_values: list[str] = Field(default_factory=list)


class AdvantagesSettings(BaseModel):
    """Thresholds for generating rule-based advantages and risks."""

    description: str = ""
    high_score_threshold: float = 80.0
    low_score_threshold: float = 45.0
    elevated_risk_score: float = 60.0
    high_defect_rate_pct: float = 5.0
    max_advantages: int = Field(default=4, ge=0)
    max_risks: int = Field(default=4, ge=0)


class ReportingSettings(BaseModel):
    """Presentation defaults and the standing disclaimer."""

    top_n_default: int = 10
    max_suppliers_per_catalog: int = 5000
    include_ineligible_in_results: bool = True
    recommendation_disclaimer: str = ""


class SupplierRecoConfig(BaseModel):
    """The complete, validated Supplier Recommendation configuration."""

    config_version: str
    description: str = ""
    base_currency: str = "EUR"
    currency_rates: dict[str, float] = Field(default_factory=lambda: {"EUR": 1.0})
    default_weights: Weights
    weight_total: float = 100.0
    weight_total_tolerance: float = Field(default=0.01, ge=0.0)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    eligibility: EligibilitySettings = Field(default_factory=EligibilitySettings)
    classification: ClassificationSettings = Field(default_factory=ClassificationSettings)
    advantages: AdvantagesSettings = Field(default_factory=AdvantagesSettings)
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)
    list_delimiters: list[str] = Field(default_factory=lambda: [";", "|", ",", "/"])

    # -- helpers ---------------------------------------------------------
    def conversion_rate(self, currency: str | None) -> float:
        """Rate that converts ``currency`` into the base currency."""
        if not currency:
            return 1.0
        return float(self.currency_rates.get(str(currency).upper(), 1.0))

    def to_base_currency(self, amount: float | None, currency: str | None) -> float | None:
        """Convert an amount into the base currency, preserving ``None``."""
        if amount is None:
            return None
        return float(amount) * self.conversion_rate(currency)

    def validate_weights(self, weights: Weights) -> None:
        """Raise :class:`ConfigurationError` if the weights do not sum to the total."""
        if abs(weights.total() - self.weight_total) > self.weight_total_tolerance:
            raise ConfigurationError(
                f"Scoring weights must sum to {self.weight_total:g}%; got {weights.total():g}%.",
                details={"weights": weights.as_dict(), "total": weights.total()},
            )


def load_supplier_reco_config(path: Path | str | None = None) -> SupplierRecoConfig:
    """Load and validate the supplier recommendation configuration from ``path``."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigurationError(
            f"Supplier recommendation configuration file is missing: {config_path.name}"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Supplier recommendation configuration is not valid JSON: {exc.msg} (line {exc.lineno})"
        ) from exc
    try:
        config = SupplierRecoConfig.model_validate(raw)
    except PydanticValidationError as exc:
        raise ConfigurationError(
            f"Supplier recommendation configuration failed validation: {exc.error_count()} problem(s).",
            details={"errors": exc.errors(include_url=False)[:10]},
        ) from exc

    logger.info(
        "Loaded supplier recommendation configuration v%s (base currency %s)",
        config.config_version, config.base_currency,
    )
    return config


@lru_cache(maxsize=1)
def get_supplier_reco_config() -> SupplierRecoConfig:
    """Return the cached default configuration."""
    return load_supplier_reco_config()
