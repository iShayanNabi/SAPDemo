"""Typed, validated access to the Inventory Predictor configuration.

Every smoothing constant, grid, window, holdout length, service level, turnover
threshold and tolerance lives in ``config/inventory_rules.json`` and is
validated here at load time. The forecasting models, the model selector and the
reorder calculations read their numbers through this object, so retuning the
predictor - a different service level, a longer holdout, a wider overstock
threshold - is a JSON edit with no code change.

Two validations are worth calling out because they are the ones that catch a
bad edit before it can produce a wrong answer:

* a weighted moving average whose weights do not sum to 1 is **normalised**
  rather than rejected, and the normalisation is reported in the model's
  parameters, so a planner can see what was actually applied;
* a confidence or service level that has no matching z-score raises a
  :class:`ConfigurationError` instead of silently falling back to 1.96.
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

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "inventory_rules.json"

#: The five forecasting methods, in the order the UI should offer them.
MODEL_NAMES: tuple[str, ...] = (
    "simple_moving_average",
    "weighted_moving_average",
    "simple_exponential_smoothing",
    "holt_linear_trend",
    "holt_winters_seasonal",
)

#: Error metrics a model can be selected on.
SELECTION_METRICS: tuple[str, ...] = ("rmse", "mae", "mape", "smape", "mase")

#: How many smoothing constants each method estimates. Used by the selector to
#: charge a more complex model for its extra freedom before it can win.
MODEL_COMPLEXITY: dict[str, int] = {
    "simple_moving_average": 0,
    "weighted_moving_average": 0,
    "simple_exponential_smoothing": 1,
    "holt_linear_trend": 2,
    "holt_winters_seasonal": 3,
}


class FrequencySpec(BaseModel):
    """One supported period granularity."""

    label: str
    days: int = Field(gt=0)
    periods_per_year: int = Field(gt=0)
    season_length: int = Field(gt=1)


class PeriodSettings(BaseModel):
    """How dated rows become evenly spaced periods."""

    description: str = ""
    frequencies: dict[str, FrequencySpec]
    default_frequency: str = "monthly"
    missing_period_fill: str = "zero"
    max_missing_period_pct: float = Field(default=25.0, ge=0.0, le=100.0)
    max_gap_multiplier: float = Field(default=1.5, gt=1.0)

    def model_post_init(self, _context: object) -> None:
        if self.default_frequency not in self.frequencies:
            raise ValueError(
                f"default_frequency '{self.default_frequency}' is not one of "
                f"{sorted(self.frequencies)}"
            )
        allowed_fill = {"zero", "interpolate", "none"}
        if self.missing_period_fill not in allowed_fill:
            raise ValueError(
                f"missing_period_fill must be one of {sorted(allowed_fill)}, "
                f"got '{self.missing_period_fill}'"
            )

    def spec(self, frequency: str) -> FrequencySpec:
        """Return one frequency specification."""
        if frequency not in self.frequencies:
            raise ConfigurationError(f"Unknown period frequency: {frequency}")
        return self.frequencies[frequency]


class ForecastSettings(BaseModel):
    """Horizon and prediction-interval settings."""

    description: str = ""
    default_horizon_periods: int = Field(default=6, ge=1)
    max_horizon_periods: int = Field(default=36, ge=1)
    minimum_observations: int = Field(default=4, ge=2)
    confidence_level: float = Field(default=0.95, gt=0.0, lt=1.0)
    confidence_z_scores: dict[str, float] = Field(default_factory=dict)
    clip_negative_forecast: bool = True
    clip_negative_interval: bool = True
    decimals: int = Field(default=2, ge=0, le=6)

    def model_post_init(self, _context: object) -> None:
        if self.default_horizon_periods > self.max_horizon_periods:
            raise ValueError(
                "default_horizon_periods must not exceed max_horizon_periods "
                f"({self.default_horizon_periods} > {self.max_horizon_periods})"
            )

    def z_for(self, confidence_level: float | None = None) -> float:
        """Return the two-sided z-score for a confidence level.

        Raises:
            ConfigurationError: the level has no configured z-score. Guessing one
                would silently change the width of every interval in the report.
        """
        level = self.confidence_level if confidence_level is None else float(confidence_level)
        for key, value in self.confidence_z_scores.items():
            if abs(float(key) - level) < 1e-9:
                return float(value)
        raise ConfigurationError(
            f"No z-score is configured for confidence level {level:g}.",
            details={"available_levels": sorted(self.confidence_z_scores)},
        )

    @property
    def available_confidence_levels(self) -> list[float]:
        return sorted(float(key) for key in self.confidence_z_scores)


class ModelSpec(BaseModel):
    """Shared shape of one forecasting method's configuration."""

    enabled: bool = True
    label: str
    min_observations: int = Field(default=4, ge=2)
    assumptions: list[str] = Field(default_factory=list)

    # Moving averages
    window: int | None = Field(default=None, ge=1)
    weights: list[float] | None = None

    # Exponential smoothing family
    alpha: float | None = Field(default=None, ge=0.0, le=1.0)
    beta: float | None = Field(default=None, ge=0.0, le=1.0)
    gamma: float | None = Field(default=None, ge=0.0, le=1.0)
    damping: float = Field(default=1.0, gt=0.0, le=1.0)
    optimize: bool = False
    alpha_grid: list[float] = Field(default_factory=list)
    beta_grid: list[float] = Field(default_factory=list)
    gamma_grid: list[float] = Field(default_factory=list)

    # Seasonal
    min_seasons: int = Field(default=2, ge=2)
    season_length: int | None = Field(default=None, ge=2)
    #: Adjusted share of the variation the season must explain before a seasonal
    #: model is offered at all. Guards against fitting a season to noise.
    min_seasonal_strength: float = Field(default=0.25, ge=0.0, le=1.0)

    def model_post_init(self, _context: object) -> None:
        if self.weights is not None:
            if not self.weights:
                raise ValueError(f"model '{self.label}' has an empty weights list")
            if any(weight < 0 for weight in self.weights):
                raise ValueError(f"model '{self.label}' has a negative weight")
            if sum(self.weights) <= 0:
                raise ValueError(f"model '{self.label}' has weights that sum to zero")

    @property
    def normalized_weights(self) -> list[float]:
        """Weights scaled to sum to exactly 1, most-recent-first."""
        if not self.weights:
            return []
        total = float(sum(self.weights))
        return [float(weight) / total for weight in self.weights]

    @property
    def weights_were_normalized(self) -> bool:
        """True when the configured weights did not already sum to 1."""
        return bool(self.weights) and abs(float(sum(self.weights)) - 1.0) > 1e-9


class SelectionSettings(BaseModel):
    """How the winning model is chosen."""

    description: str = ""
    method: str = "backtest"
    metric: str = "rmse"
    holdout_periods: int = Field(default=3, ge=1)
    folds: int = Field(default=2, ge=1)
    minimum_train_observations: int = Field(default=4, ge=2)
    fallback_model: str = "simple_moving_average"
    preference_order: list[str] = Field(default_factory=list)
    #: A model that estimates more parameters must beat the best simpler model by
    #: at least this share of its error before it is chosen.
    complexity_margin_pct: float = Field(default=5.0, ge=0.0, le=100.0)

    def model_post_init(self, _context: object) -> None:
        if self.method not in {"backtest", "fixed"}:
            raise ValueError(f"selection.method must be 'backtest' or 'fixed', got '{self.method}'")
        if self.metric not in SELECTION_METRICS:
            raise ValueError(
                f"selection.metric must be one of {list(SELECTION_METRICS)}, got '{self.metric}'"
            )
        if self.fallback_model not in MODEL_NAMES:
            raise ValueError(f"selection.fallback_model is unknown: '{self.fallback_model}'")
        unknown = [name for name in self.preference_order if name not in MODEL_NAMES]
        if unknown:
            raise ValueError(f"selection.preference_order references unknown models: {unknown}")

    def rank(self, model_name: str) -> int:
        """Tie-break position of a model (lower wins). Unlisted models come last."""
        if model_name in self.preference_order:
            return self.preference_order.index(model_name)
        return len(self.preference_order)


class IntermittentSettings(BaseModel):
    """Classification of sparse demand, and which models it allows."""

    description: str = ""
    enabled: bool = True
    min_zero_period_pct: float = Field(default=30.0, ge=0.0, le=100.0)
    adi_threshold: float = Field(default=1.32, gt=0.0)
    cv_squared_threshold: float = Field(default=0.49, ge=0.0)
    allowed_models: list[str] = Field(default_factory=list)

    def model_post_init(self, _context: object) -> None:
        unknown = [name for name in self.allowed_models if name not in MODEL_NAMES]
        if unknown:
            raise ValueError(f"intermittent.allowed_models references unknown models: {unknown}")


class ReorderSettings(BaseModel):
    """Reorder point, safety stock and order quantity policy."""

    description: str = ""
    service_level: float = Field(default=0.95, gt=0.0, lt=1.0)
    service_level_z_scores: dict[str, float] = Field(default_factory=dict)
    safety_stock_basis: str = "forecast_error"
    default_lead_time_days: int = Field(default=14, ge=0)
    review_period_days: int = Field(default=30, ge=0)
    minimum_order_quantity: float = Field(default=0.0, ge=0.0)
    rounding_multiple: float = Field(default=1.0, gt=0.0)
    respect_master_safety_stock: bool = True

    def model_post_init(self, _context: object) -> None:
        allowed = {"forecast_error", "demand_variation"}
        if self.safety_stock_basis not in allowed:
            raise ValueError(
                f"reorder.safety_stock_basis must be one of {sorted(allowed)}, "
                f"got '{self.safety_stock_basis}'"
            )
        # Fail at load time, not halfway through a run.
        self.z_for(self.service_level)

    def z_for(self, service_level: float | None = None) -> float:
        """Return the one-sided z-score for a service level."""
        level = self.service_level if service_level is None else float(service_level)
        for key, value in self.service_level_z_scores.items():
            if abs(float(key) - level) < 1e-9:
                return float(value)
        raise ConfigurationError(
            f"No z-score is configured for service level {level:g}.",
            details={"available_levels": sorted(self.service_level_z_scores)},
        )

    @property
    def available_service_levels(self) -> list[float]:
        return sorted(float(key) for key in self.service_level_z_scores)


class StockHealthSettings(BaseModel):
    """Overstock, slow-moving and dead-stock thresholds."""

    description: str = ""
    overstock_days_of_cover: float = Field(default=180.0, gt=0.0)
    critical_overstock_days_of_cover: float = Field(default=365.0, gt=0.0)
    excess_cover_days: float = Field(default=90.0, gt=0.0)
    fast_moving_turnover: float = Field(default=4.0, gt=0.0)
    slow_moving_turnover: float = Field(default=2.0, gt=0.0)
    very_slow_turnover: float = Field(default=1.0, gt=0.0)
    slow_moving_zero_demand_pct: float = Field(default=50.0, ge=0.0, le=100.0)
    dead_stock_zero_demand_periods: int = Field(default=12, ge=1)
    dead_stock_requires_stock_on_hand: bool = True
    shortage_horizon_days: int = Field(default=90, ge=1)

    def model_post_init(self, _context: object) -> None:
        if self.critical_overstock_days_of_cover < self.overstock_days_of_cover:
            raise ValueError(
                "critical_overstock_days_of_cover must not be below overstock_days_of_cover"
            )
        if not self.fast_moving_turnover > self.slow_moving_turnover > self.very_slow_turnover:
            raise ValueError(
                "turnover thresholds must decrease: fast > slow > very slow, got "
                f"{self.fast_moving_turnover} / {self.slow_moving_turnover} / "
                f"{self.very_slow_turnover}"
            )


class DataQualitySettings(BaseModel):
    """What the loader and the engine warn about."""

    description: str = ""
    balance_tolerance: float = Field(default=0.01, ge=0.0)
    warn_on_balance_mismatch: bool = True
    warn_on_negative_demand: bool = True
    warn_on_negative_inventory: bool = True
    warn_on_demand_issue_gap: bool = True
    demand_issue_gap_tolerance_pct: float = Field(default=5.0, ge=0.0, le=100.0)
    warn_on_missing_lead_time: bool = True
    warn_on_missing_ending_inventory: bool = True
    warn_on_past_po_expected_date: bool = True
    warn_on_duplicate_period: bool = True
    max_missing_period_warnings: int = Field(default=10, ge=0)


class ReportingSettings(BaseModel):
    """Presentation defaults and the standing forecast disclaimer."""

    top_n_default: int = Field(default=20, ge=1)
    max_series_per_dataset: int = Field(default=2000, ge=1)
    max_rows_per_dataset: int = Field(default=200_000, ge=1)
    forecast_disclaimer: str = ""


class InventoryConfig(BaseModel):
    """The complete, validated Inventory Predictor configuration."""

    config_version: str
    description: str = ""
    period: PeriodSettings
    forecast: ForecastSettings
    models: dict[str, ModelSpec]
    selection: SelectionSettings
    intermittent: IntermittentSettings = Field(default_factory=IntermittentSettings)
    reorder: ReorderSettings
    stock_health: StockHealthSettings
    data_quality: DataQualitySettings = Field(default_factory=DataQualitySettings)
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)

    def model_post_init(self, _context: object) -> None:
        missing = [name for name in MODEL_NAMES if name not in self.models]
        if missing:
            raise ValueError(f"configuration is missing forecasting models: {missing}")
        unknown = [name for name in self.models if name not in MODEL_NAMES]
        if unknown:
            raise ValueError(f"configuration defines unknown forecasting models: {unknown}")
        if not self.models[self.selection.fallback_model].enabled:
            raise ValueError(
                f"selection.fallback_model '{self.selection.fallback_model}' is disabled; "
                "the fallback must always be available"
            )
        # Fail at load time, not on the first forecast.
        self.forecast.z_for()

    # -- helpers ---------------------------------------------------------
    def model(self, name: str) -> ModelSpec:
        """Return one model specification."""
        if name not in self.models:
            raise ConfigurationError(f"Unknown forecasting model: {name}")
        return self.models[name]

    @property
    def enabled_models(self) -> list[str]:
        """The configured methods that are switched on, in canonical order."""
        return [name for name in MODEL_NAMES if self.models[name].enabled]

    def season_length_for(self, frequency: str) -> int:
        """Season length used by Holt-Winters for a frequency.

        The seasonal model's own ``season_length`` wins when it is set, so a
        weekly file can be forced onto a 13-period season without touching the
        frequency table.
        """
        override = self.models["holt_winters_seasonal"].season_length
        if override:
            return int(override)
        return self.period.spec(frequency).season_length

    def periods_per_year(self, frequency: str) -> int:
        return self.period.spec(frequency).periods_per_year

    def period_days(self, frequency: str) -> int:
        return self.period.spec(frequency).days


def load_inventory_config(path: Path | str | None = None) -> InventoryConfig:
    """Load and validate the inventory configuration from ``path``."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigurationError(
            f"Inventory configuration file is missing: {config_path.name}"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Inventory configuration is not valid JSON: {exc.msg} (line {exc.lineno})"
        ) from exc
    try:
        config = InventoryConfig.model_validate(raw)
    except PydanticValidationError as exc:
        raise ConfigurationError(
            f"Inventory configuration failed validation: {exc.error_count()} problem(s).",
            details={"errors": exc.errors(include_url=False)[:10]},
        ) from exc

    logger.info(
        "Loaded inventory configuration v%s (%d models enabled, selection on %s)",
        config.config_version,
        len(config.enabled_models),
        config.selection.metric.upper(),
    )
    return config


@lru_cache(maxsize=1)
def get_inventory_config() -> InventoryConfig:
    """Return the cached default configuration."""
    return load_inventory_config()
