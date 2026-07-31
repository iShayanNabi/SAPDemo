"""Typed, validated access to the Supplier Risk Copilot configuration.

Every weight, normalisation anchor, categorical score map, risk band, trend
window and recommended-action rule lives in
``config/supplier_risk_rules.json`` and is validated here at load time. The
scoring model reads values through this object, so retuning the risk model -
or adding a country to the risk index - is a JSON edit, not a code change.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "supplier_risk_rules.json"

#: The ten contributing risk categories, in the order the UI should show them.
#: The eleventh reported figure - the overall supplier risk - is their weighted blend.
RISK_CATEGORIES: tuple[str, ...] = (
    "delivery",
    "quality",
    "financial",
    "spend_concentration",
    "contract",
    "invoice",
    "compliance",
    "esg",
    "geographic",
    "operational",
)

#: Name of the blended figure, kept as a constant so schemas and UI agree.
OVERALL_CATEGORY = "overall"


class CategoryWeights(BaseModel):
    """The ten category weights. Percentages that must sum to the configured total."""

    delivery: float = Field(ge=0.0, le=100.0)
    quality: float = Field(ge=0.0, le=100.0)
    financial: float = Field(ge=0.0, le=100.0)
    spend_concentration: float = Field(ge=0.0, le=100.0)
    contract: float = Field(ge=0.0, le=100.0)
    invoice: float = Field(ge=0.0, le=100.0)
    compliance: float = Field(ge=0.0, le=100.0)
    esg: float = Field(ge=0.0, le=100.0)
    geographic: float = Field(ge=0.0, le=100.0)
    operational: float = Field(ge=0.0, le=100.0)

    def total(self) -> float:
        """Sum of every category weight."""
        return round(sum(getattr(self, name) for name in RISK_CATEGORIES), 6)

    def as_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in RISK_CATEGORIES}


class MetricSpec(BaseModel):
    """How one input metric becomes a 0-100 risk contribution.

    ``direction`` selects the normalisation:

    ``higher_is_better``/``higher_is_worse``
        Linear interpolation between ``best_value`` (risk 0) and ``worst_value``
        (risk 100), clamped at both ends.
    ``categorical``
        Looked up in the score map named by ``score_map_key``.
    ``flag``
        A boolean, scored ``flag_true_score`` or ``flag_false_score``.
    """

    label: str
    weight: float = Field(gt=0.0)
    direction: str
    unit: str = ""
    best_value: float | None = None
    worst_value: float | None = None
    score_map_key: str | None = None
    flag_true_score: float = 100.0
    flag_false_score: float = 0.0

    def model_post_init(self, _context: object) -> None:
        allowed = {"higher_is_better", "higher_is_worse", "categorical", "flag"}
        if self.direction not in allowed:
            raise ValueError(f"direction must be one of {sorted(allowed)}, got '{self.direction}'")
        if self.direction in {"higher_is_better", "higher_is_worse"}:
            if self.best_value is None or self.worst_value is None:
                raise ValueError(
                    f"metric '{self.label}' needs best_value and worst_value for a "
                    f"'{self.direction}' normalisation"
                )
            if self.best_value == self.worst_value:
                raise ValueError(
                    f"metric '{self.label}' has best_value == worst_value, which cannot be scaled"
                )
        if self.direction == "categorical" and not self.score_map_key:
            raise ValueError(f"categorical metric '{self.label}' needs a score_map_key")


class CategorySpec(BaseModel):
    """One risk category and the metrics that feed it."""

    label: str
    description: str = ""
    metrics: dict[str, MetricSpec]

    def metric_weight_total(self) -> float:
        return round(sum(spec.weight for spec in self.metrics.values()), 6)


class ScoreMap(BaseModel):
    """A categorical value -> risk score lookup, with a documented fallback."""

    default: float = Field(ge=0.0, le=100.0)
    values: dict[str, float] = Field(default_factory=dict)

    def score_for(self, value: str | None) -> tuple[float, bool]:
        """Return ``(score, matched)`` for ``value``.

        ``matched`` is False when the fallback was used, so the caller can show
        that the value was not recognised rather than presenting a real score.
        """
        if value is None:
            return self.default, False
        key = str(value).strip().lower()
        if not key:
            return self.default, False
        if key in self.values:
            return float(self.values[key]), True
        # Country codes and status labels are matched case-insensitively.
        for candidate, score in self.values.items():
            if candidate.lower() == key:
                return float(score), True
        return self.default, False


class RiskBand(BaseModel):
    """One labelled band of the 0-100 risk scale."""

    label: str
    min_score: float = Field(ge=0.0, le=100.0)
    max_score: float = Field(ge=0.0, le=100.0)


class RiskBandSettings(BaseModel):
    """The ordered risk bands applied to every score."""

    description: str = ""
    bands: list[RiskBand] = Field(min_length=1)

    def band_for(self, score: float | None) -> str | None:
        """Label the 0-100 ``score``; ``None`` when there is no score to band."""
        if score is None:
            return None
        value = float(score)
        for band in self.bands:
            if band.min_score <= value < band.max_score:
                return band.label
        # The top band includes its upper bound so 100 is always classified.
        top = max(self.bands, key=lambda item: item.max_score)
        if value >= top.max_score:
            return top.label
        bottom = min(self.bands, key=lambda item: item.min_score)
        return bottom.label

    @property
    def labels(self) -> list[str]:
        return [band.label for band in self.bands]

    def rank(self, label: str | None) -> int:
        """Position of ``label`` in the ordered bands (-1 when unknown)."""
        if label is None:
            return -1
        for index, band in enumerate(self.bands):
            if band.label == label:
                return index
        return -1


class TrendSettings(BaseModel):
    """How the risk trend is derived from dated internal records."""

    description: str = ""
    window_days: int = Field(default=180, gt=0)
    minimum_events: int = Field(default=2, ge=0)
    improving_delta: float = -1.5
    deteriorating_delta: float = 1.5
    severity_weights: dict[str, float] = Field(
        default_factory=lambda: {"low": 1.0, "medium": 2.0, "high": 4.0, "critical": 8.0}
    )
    default_severity: str = "medium"

    def severity_weight(self, severity: str | None) -> float:
        key = (severity or self.default_severity).strip().lower()
        if key in self.severity_weights:
            return float(self.severity_weights[key])
        return float(self.severity_weights.get(self.default_severity, 1.0))


class MissingDataSettings(BaseModel):
    """What the engine does when inputs are absent."""

    description: str = ""
    renormalise_category_weights: bool = True
    renormalise_metric_weights: bool = True
    minimum_categories_for_overall: int = Field(default=3, ge=1)
    flag_below_completeness_pct: float = Field(default=60.0, ge=0.0, le=100.0)


class ContractExpirySettings(BaseModel):
    """Windows used when reporting contracts as expiring."""

    description: str = ""
    expiring_within_days: int = Field(default=90, ge=0)
    critical_within_days: int = Field(default=30, ge=0)


class ActionRule(BaseModel):
    """One rule-based recommended action tied to a risk category."""

    category: str
    action: str
    priority: str = "medium"


class ActionSettings(BaseModel):
    """Rule-based recommended actions."""

    description: str = ""
    max_actions: int = Field(default=6, ge=0)
    trigger_band: str = "high"
    rules: list[ActionRule] = Field(default_factory=list)
    overall_critical_action: str = ""
    no_action_message: str = ""


class AlternativeSettings(BaseModel):
    """How lower-risk alternative suppliers are proposed."""

    description: str = ""
    max_alternatives: int = Field(default=3, ge=0)
    minimum_improvement: float = Field(default=5.0, ge=0.0)
    match_on_spend_category: bool = True
    match_on_material: bool = True


class CopilotSettings(BaseModel):
    """Deterministic question-answering behaviour."""

    description: str = ""
    max_suppliers_listed: int = Field(default=5, ge=1)
    minimum_name_match_score: float = Field(default=0.6, ge=0.0, le=1.0)
    top_drivers_in_answer: int = Field(default=3, ge=1)
    unavailable_message: str = "That information is not in the loaded supplier risk records."
    no_data_message: str = "No supplier risk data has been loaded yet."
    disclaimer: str = ""


class ReportingSettings(BaseModel):
    """Presentation defaults and the standing disclaimer."""

    top_n_default: int = 10
    max_suppliers_per_dataset: int = 5000
    risk_disclaimer: str = ""


class SupplierRiskConfig(BaseModel):
    """The complete, validated Supplier Risk Copilot configuration."""

    config_version: str
    description: str = ""
    base_currency: str = "EUR"
    currency_rates: dict[str, float] = Field(default_factory=lambda: {"EUR": 1.0})
    default_weights: CategoryWeights
    weight_total: float = 100.0
    weight_total_tolerance: float = Field(default=0.01, ge=0.0)
    categories: dict[str, CategorySpec]
    score_maps: dict[str, ScoreMap] = Field(default_factory=dict)
    risk_bands: RiskBandSettings
    trend: TrendSettings = Field(default_factory=TrendSettings)
    missing_data: MissingDataSettings = Field(default_factory=MissingDataSettings)
    contract_expiry: ContractExpirySettings = Field(default_factory=ContractExpirySettings)
    actions: ActionSettings = Field(default_factory=ActionSettings)
    alternatives: AlternativeSettings = Field(default_factory=AlternativeSettings)
    copilot: CopilotSettings = Field(default_factory=CopilotSettings)
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)

    def model_post_init(self, _context: object) -> None:
        missing = [name for name in RISK_CATEGORIES if name not in self.categories]
        if missing:
            raise ValueError(f"configuration is missing risk categories: {missing}")
        for name, spec in self.categories.items():
            for metric_name, metric in spec.metrics.items():
                if metric.direction == "categorical" and metric.score_map_key not in self.score_maps:
                    raise ValueError(
                        f"category '{name}' metric '{metric_name}' references unknown "
                        f"score map '{metric.score_map_key}'"
                    )
        for rule in self.actions.rules:
            if rule.category not in RISK_CATEGORIES:
                raise ValueError(f"action rule references unknown category '{rule.category}'")
        if self.actions.trigger_band and self.actions.trigger_band not in self.risk_bands.labels:
            raise ValueError(
                f"actions.trigger_band '{self.actions.trigger_band}' is not one of the "
                f"configured risk bands {self.risk_bands.labels}"
            )

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

    def category(self, name: str) -> CategorySpec:
        """Return one category specification."""
        if name not in self.categories:
            raise ConfigurationError(f"Unknown risk category: {name}")
        return self.categories[name]

    def score_map(self, key: str) -> ScoreMap:
        """Return one categorical score map."""
        if key not in self.score_maps:
            raise ConfigurationError(f"Unknown score map: {key}")
        return self.score_maps[key]

    def band_for(self, score: float | None) -> str | None:
        """Label a 0-100 risk score."""
        return self.risk_bands.band_for(score)

    def validate_weights(self, weights: CategoryWeights) -> None:
        """Raise :class:`ConfigurationError` if the weights do not sum to the total."""
        if abs(weights.total() - self.weight_total) > self.weight_total_tolerance:
            raise ConfigurationError(
                f"Risk category weights must sum to {self.weight_total:g}%; "
                f"got {weights.total():g}%.",
                details={"weights": weights.as_dict(), "total": weights.total()},
            )


def load_supplier_risk_config(path: Path | str | None = None) -> SupplierRiskConfig:
    """Load and validate the supplier risk configuration from ``path``."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigurationError(
            f"Supplier risk configuration file is missing: {config_path.name}"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Supplier risk configuration is not valid JSON: {exc.msg} (line {exc.lineno})"
        ) from exc
    try:
        config = SupplierRiskConfig.model_validate(raw)
    except PydanticValidationError as exc:
        raise ConfigurationError(
            f"Supplier risk configuration failed validation: {exc.error_count()} problem(s).",
            details={"errors": exc.errors(include_url=False)[:10]},
        ) from exc

    logger.info(
        "Loaded supplier risk configuration v%s (%d categories, base currency %s)",
        config.config_version,
        len(config.categories),
        config.base_currency,
    )
    return config


@lru_cache(maxsize=1)
def get_supplier_risk_config() -> SupplierRiskConfig:
    """Return the cached default configuration."""
    return load_supplier_risk_config()
