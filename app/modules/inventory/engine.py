"""Run the whole prediction for every series in an uploaded history.

The engine is pure: no database, no HTTP, no AI. It takes normalised series and
returns a complete forecast run - per material/plant the chosen model, the
demand forecast with its confidence range, the projected stock path, the
shortage and reorder dates, the recommended quantities, the stock
classification, the accuracy figures and the data-quality warnings.

**One broken series never costs the others.** Every series is forecast inside
its own ``try``/``except``: a series that raises lands in ``series_errors`` with
its key and the failure type, and the rest of the run completes. That is the
same isolation modules 1 and 4 apply to individual rules, applied here to
individual materials - a warehouse extract has thousands of them and one
pathological history must not empty the report.

**A series that cannot be forecast still produces output.** Too little history
is a legitimate answer, not an error: the item is returned with status
``insufficient_data``, its history, its stock position and a warning that says
how many periods it has and how many it needs. Silently dropping it would let a
planner believe a material was fine when it was simply never looked at.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.logging import get_logger
from app.core.rounding import decimal_mean, round_half_up
from app.modules.inventory.accuracy import AccuracyMetrics, compute_metrics, naive_scale
from app.modules.inventory.normalizer import InventorySeries
from app.modules.inventory.projection import (
    ForecastPoint,
    ProjectionResult,
    build_forecast_points,
    project_inventory,
)
from app.modules.inventory.selection import SelectionResult, refit_selected, select_model
from app.modules.inventory.thresholds import InventoryConfig

logger = get_logger(__name__)

__all__ = [
    "ENGINE_VERSION",
    "ForecastRunResult",
    "SeriesForecast",
    "SeriesWarning",
    "run_forecast",
]

#: Bumped whenever the engine's arithmetic changes. Stored on every run.
ENGINE_VERSION = "1.0.0"

#: Statuses an item can end a run in.
STATUS_FORECAST = "forecast"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_NO_MODEL = "no_model"


@dataclass
class SeriesWarning:
    """One data-quality warning about a single series."""

    code: str
    message: str
    severity: str = "warning"

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "severity": self.severity}


@dataclass
class SeriesForecast:
    """Everything the engine produced for one material / plant / storage location."""

    series_key: str
    material: str
    plant: str
    storage_location: str | None = None
    material_description: str | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None

    status: str = STATUS_FORECAST
    frequency: str = "monthly"
    season_length: int = 12
    history_period_count: int = 0
    observed_period_count: int = 0
    missing_period_count: int = 0
    history_start: date | None = None
    history_end: date | None = None

    model: str | None = None
    model_label: str | None = None
    model_parameters: dict[str, Any] = field(default_factory=dict)
    model_assumptions: list[str] = field(default_factory=list)
    model_notes: list[str] = field(default_factory=list)
    selection: SelectionResult | None = None

    horizon_periods: int = 0
    horizon_end_date: date | None = None
    confidence_level: float = 0.95
    forecast_points: list[ForecastPoint] = field(default_factory=list)
    total_forecast_demand: float | None = None

    accuracy_in_sample: AccuracyMetrics | None = None
    accuracy_backtest: AccuracyMetrics | None = None

    projection: ProjectionResult = field(default_factory=ProjectionResult)
    history: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[SeriesWarning] = field(default_factory=list)

    # -- shortcuts the API and the persistence layer index on ------------
    @property
    def predicted_shortage_date(self) -> date | None:
        return self.projection.predicted_shortage_date

    @property
    def recommended_reorder_date(self) -> date | None:
        return self.projection.reorder.recommended_reorder_date

    @property
    def recommended_reorder_quantity(self) -> float | None:
        return self.projection.reorder.recommended_reorder_quantity

    @property
    def recommended_safety_stock(self) -> float | None:
        return self.projection.reorder.recommended_safety_stock

    @property
    def movement_class(self) -> str:
        return self.projection.health.movement_class

    @property
    def is_dead_stock(self) -> bool:
        return self.projection.health.is_dead_stock

    @property
    def is_slow_moving(self) -> bool:
        return self.projection.health.is_slow_moving

    @property
    def overstock_risk(self) -> str:
        return self.projection.health.overstock_risk

    @property
    def label(self) -> str:
        location = f" / {self.storage_location}" if self.storage_location else ""
        return f"{self.material} @ {self.plant}{location}"

    def accuracy_headline(self) -> AccuracyMetrics | None:
        """The accuracy a reader should trust: backtest first, in-sample second."""
        return self.accuracy_backtest or self.accuracy_in_sample

    def to_dict(self) -> dict[str, Any]:
        headline = self.accuracy_headline()
        return {
            "series_key": self.series_key,
            "material": self.material,
            "material_description": self.material_description,
            "plant": self.plant,
            "storage_location": self.storage_location,
            "supplier_id": self.supplier_id,
            "supplier_name": self.supplier_name,
            "status": self.status,
            "frequency": self.frequency,
            "season_length": self.season_length,
            "history_period_count": self.history_period_count,
            "observed_period_count": self.observed_period_count,
            "missing_period_count": self.missing_period_count,
            "history_start": self.history_start.isoformat() if self.history_start else None,
            "history_end": self.history_end.isoformat() if self.history_end else None,
            "model": self.model,
            "model_label": self.model_label,
            "model_parameters": dict(self.model_parameters),
            "model_assumptions": list(self.model_assumptions),
            "model_notes": list(self.model_notes),
            "selection": self.selection.to_dict() if self.selection else None,
            "horizon_periods": self.horizon_periods,
            "horizon_end_date": (
                self.horizon_end_date.isoformat() if self.horizon_end_date else None
            ),
            "confidence_level": self.confidence_level,
            "forecast": [point.to_dict() for point in self.forecast_points],
            "total_forecast_demand": self.total_forecast_demand,
            "accuracy_in_sample": (
                self.accuracy_in_sample.to_dict() if self.accuracy_in_sample else None
            ),
            "accuracy_backtest": (
                self.accuracy_backtest.to_dict() if self.accuracy_backtest else None
            ),
            "accuracy_headline": headline.to_dict() if headline else None,
            "projection": self.projection.to_dict(),
            "history": list(self.history),
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


@dataclass
class ForecastRunResult:
    """One complete forecast run over an uploaded history."""

    items: list[SeriesForecast] = field(default_factory=list)
    as_of_date: date | None = None
    horizon_periods: int = 0
    confidence_level: float = 0.95
    requested_model: str | None = None
    engine_version: str = ENGINE_VERSION

    series_count: int = 0
    forecast_count: int = 0
    insufficient_data_count: int = 0
    shortage_count: int = 0
    reorder_now_count: int = 0
    overstock_count: int = 0
    slow_moving_count: int = 0
    dead_stock_count: int = 0
    total_forecast_demand: float | None = None
    model_usage: dict[str, int] = field(default_factory=dict)
    accuracy_summary: dict[str, float | None] = field(default_factory=dict)
    frequency_counts: dict[str, int] = field(default_factory=dict)
    warning_counts: dict[str, int] = field(default_factory=dict)
    series_errors: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0

    def summary_payload(self) -> dict[str, Any]:
        return {
            "series_count": self.series_count,
            "forecast_count": self.forecast_count,
            "insufficient_data_count": self.insufficient_data_count,
            "shortage_count": self.shortage_count,
            "reorder_now_count": self.reorder_now_count,
            "overstock_count": self.overstock_count,
            "slow_moving_count": self.slow_moving_count,
            "dead_stock_count": self.dead_stock_count,
            "total_forecast_demand": self.total_forecast_demand,
            "model_usage": dict(self.model_usage),
            "accuracy_summary": dict(self.accuracy_summary),
            "frequency_counts": dict(self.frequency_counts),
            "warning_counts": dict(self.warning_counts),
        }


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def run_forecast(
    series_list: list[InventorySeries],
    config: InventoryConfig,
    *,
    as_of: date | None = None,
    horizon_periods: int | None = None,
    confidence_level: float | None = None,
    requested_model: str | None = None,
) -> ForecastRunResult:
    """Forecast every series and project its stock forward."""
    started = time.perf_counter()

    horizon = int(horizon_periods or config.forecast.default_horizon_periods)
    horizon = max(1, min(horizon, config.forecast.max_horizon_periods))
    level = float(confidence_level or config.forecast.confidence_level)
    # Fail fast on an unusable confidence level rather than per series.
    config.forecast.z_for(level)

    result = ForecastRunResult(
        as_of_date=as_of,
        horizon_periods=horizon,
        confidence_level=level,
        requested_model=requested_model,
    )

    for series in series_list:
        try:
            reference = as_of or (series.grid.end_date_at(series.periods[-1].index))
            item = _forecast_one(
                series, config, reference, horizon, level, requested_model
            )
            result.items.append(item)
        except Exception as exc:  # noqa: BLE001 - one series never costs the rest
            logger.exception("Forecast failed for series %s", series.series_key)
            result.series_errors.append(
                {
                    "series_key": series.series_key,
                    "material": series.material,
                    "plant": series.plant,
                    "error_type": type(exc).__name__,
                    "message": (
                        "This material could not be forecast. The rest of the run completed."
                    ),
                }
            )

    _summarise(result, config)
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "Forecast run: %d series, %d forecast, %d insufficient data, %d projected shortages, "
        "%d errors in %d ms",
        result.series_count,
        result.forecast_count,
        result.insufficient_data_count,
        result.shortage_count,
        len(result.series_errors),
        result.duration_ms,
    )
    return result


def _forecast_one(
    series: InventorySeries,
    config: InventoryConfig,
    as_of: date,
    horizon: int,
    confidence_level: float,
    requested_model: str | None,
) -> SeriesForecast:
    """Forecast and project one series."""
    season_length = config.season_length_for(series.frequency)
    item = SeriesForecast(
        series_key=series.series_key,
        material=series.material,
        plant=series.plant,
        storage_location=series.storage_location,
        material_description=series.material_description,
        supplier_id=series.supplier_id,
        supplier_name=series.supplier_name,
        frequency=series.frequency,
        season_length=season_length,
        history_period_count=series.observation_count,
        observed_period_count=series.observed_period_count,
        missing_period_count=len(series.missing_period_indexes),
        history_start=series.first_period_date,
        history_end=series.last_period_date,
        horizon_periods=horizon,
        confidence_level=confidence_level,
        history=[period.to_dict() for period in series.periods],
    )
    item.warnings = _series_warnings(series, config)

    values = series.demand_values
    if len(values) < config.forecast.minimum_observations:
        item.status = STATUS_INSUFFICIENT_DATA
        item.warnings.append(
            SeriesWarning(
                code="insufficient_history",
                message=(
                    f"This material has {len(values)} period(s) of history and at least "
                    f"{config.forecast.minimum_observations} are needed to forecast. No demand "
                    "forecast, shortage date or reorder recommendation is produced for it."
                ),
                severity="high",
            )
        )
        item.projection = ProjectionResult(
            opening_inventory=series.closing_inventory,
            opening_inventory_date=series.closing_inventory_date,
            available=False,
            unavailable_reason="Too little history to forecast demand.",
            unscheduled_open_quantity=series.unscheduled_open_quantity,
        )
        return item

    selection = select_model(
        values,
        config,
        season_length,
        requested_model=requested_model,
        observed=[period.observed for period in series.periods],
    )
    item.selection = selection

    if not selection.selected_model:
        item.status = STATUS_NO_MODEL
        item.warnings.append(
            SeriesWarning(
                code="no_eligible_model",
                message=(
                    "No configured forecasting method can be applied to this material. The "
                    "reason for each method is listed against the candidates."
                ),
                severity="high",
            )
        )
        item.projection = ProjectionResult(
            opening_inventory=series.closing_inventory,
            opening_inventory_date=series.closing_inventory_date,
            available=False,
            unavailable_reason="No forecasting method is eligible for this material.",
            unscheduled_open_quantity=series.unscheduled_open_quantity,
        )
        return item

    fitted = refit_selected(selection, values, horizon, config, season_length)
    if fitted is None:  # pragma: no cover - guarded by the check above
        raise RuntimeError("The selected model could not be refitted.")

    item.model = fitted.model
    item.model_label = fitted.label
    item.model_parameters = dict(fitted.parameters)
    item.model_assumptions = list(fitted.assumptions)
    item.model_notes = list(fitted.notes)

    sigma = fitted.residual_std
    item.forecast_points = build_forecast_points(
        series,
        fitted.point_forecast,
        fitted.interval_factors,
        sigma,
        config,
        confidence_level,
    )
    item.total_forecast_demand = round_half_up(
        sum(point.demand for point in item.forecast_points), config.forecast.decimals
    )
    item.horizon_end_date = (
        item.forecast_points[-1].period_end_date if item.forecast_points else None
    )

    scale = naive_scale(values)
    in_sample_indexes = fitted.in_sample_actual_indexes
    item.accuracy_in_sample = compute_metrics(
        [values[index] for index in in_sample_indexes],
        [float(fitted.fitted[index]) for index in in_sample_indexes],
        scale=scale,
        basis="in_sample: one-step-ahead errors on the history the model was fitted to",
    )
    selected_evaluation = selection.selected_evaluation
    if selected_evaluation and selected_evaluation.metrics:
        item.accuracy_backtest = selected_evaluation.metrics
    else:
        item.warnings.append(
            SeriesWarning(
                code="no_backtest",
                message=(
                    "There was not enough history to hold periods back, so the accuracy shown is "
                    "in-sample only. In-sample accuracy is measured on the same periods the "
                    "model was fitted to and is always optimistic."
                ),
                severity="info",
            )
        )

    item.projection = project_inventory(series, item.forecast_points, sigma, config, as_of)

    if sigma == 0 and item.forecast_points:
        item.warnings.append(
            SeriesWarning(
                code="zero_forecast_error",
                message=(
                    "The selected model reproduced the history exactly, so its residual spread is "
                    "zero and the confidence range has no width. Treat the interval as unknown "
                    "rather than as certainty."
                ),
                severity="info",
            )
        )
    return item


def _series_warnings(series: InventorySeries, config: InventoryConfig) -> list[SeriesWarning]:
    """Data-quality warnings that are about a whole series rather than one row."""
    settings = config.data_quality
    warnings: list[SeriesWarning] = []

    missing = series.missing_period_indexes
    if missing:
        dates = ", ".join(item.isoformat() for item in series.missing_period_dates[:5])
        suffix = "" if len(missing) <= 5 else f" and {len(missing) - 5} more"
        severity = (
            "high"
            if series.missing_period_pct > config.period.max_missing_period_pct
            else "warning"
        )
        warnings.append(
            SeriesWarning(
                code="missing_periods",
                message=(
                    f"{len(missing)} of {series.observation_count} period(s) had no row in the "
                    f"file ({series.missing_period_pct:g}% of the history): {dates}{suffix}. They "
                    f"were treated as {config.period.missing_period_fill} demand so the periods "
                    "either side keep their real positions on the time axis."
                ),
                severity=severity,
            )
        )

    if settings.warn_on_missing_ending_inventory and series.closing_inventory is None:
        warnings.append(
            SeriesWarning(
                code="no_ending_inventory",
                message=(
                    "No ending inventory was supplied for this material, so no future stock "
                    "level, shortage date or reorder recommendation can be produced. The demand "
                    "forecast is still reported."
                ),
                severity="high",
            )
        )

    if settings.warn_on_missing_lead_time and series.lead_time_days is None:
        warnings.append(
            SeriesWarning(
                code="no_lead_time",
                message=(
                    "No lead time was supplied for this material. The configured default of "
                    f"{config.reorder.default_lead_time_days} days was used for the reorder "
                    "point and the safety stock; both change if the real lead time differs."
                ),
                severity="warning",
            )
        )

    if settings.warn_on_duplicate_period and series.duplicate_period_count:
        warnings.append(
            SeriesWarning(
                code="duplicate_periods",
                message=(
                    f"{series.duplicate_period_count} row(s) fall into a period that already had "
                    "one. Their quantities were added together and the later stock levels kept."
                ),
                severity="warning",
            )
        )

    if series.unscheduled_open_quantity > 0:
        warnings.append(
            SeriesWarning(
                code="unscheduled_open_quantity",
                message=(
                    f"{series.unscheduled_open_quantity:g} unit(s) are on order without a usable "
                    "expected date. They are excluded from the projected stock, because there is "
                    "no honest date to place them on."
                ),
                severity="warning",
            )
        )

    if not series.frequency_inferred:
        warnings.append(
            SeriesWarning(
                code="assumed_frequency",
                message=(
                    "This material has a single dated row, so the period granularity could not "
                    f"be measured and the configured default ({config.period.default_frequency}) "
                    "was assumed."
                ),
                severity="warning",
            )
        )

    return warnings


def _summarise(result: ForecastRunResult, config: InventoryConfig) -> None:
    """Roll the per-series results up into the run-level figures."""
    result.series_count = len(result.items)

    mae_values: list[float] = []
    rmse_values: list[float] = []
    smape_values: list[float] = []
    mape_values: list[float] = []
    mase_values: list[float] = []
    total_demand = 0.0
    has_demand = False

    for item in result.items:
        result.frequency_counts[item.frequency] = (
            result.frequency_counts.get(item.frequency, 0) + 1
        )
        for warning in item.warnings:
            result.warning_counts[warning.code] = result.warning_counts.get(warning.code, 0) + 1

        if item.status == STATUS_INSUFFICIENT_DATA:
            result.insufficient_data_count += 1
        if item.status == STATUS_FORECAST and item.model:
            result.forecast_count += 1
            result.model_usage[item.model] = result.model_usage.get(item.model, 0) + 1

        if item.total_forecast_demand is not None:
            total_demand += item.total_forecast_demand
            has_demand = True

        if item.projection.predicted_shortage_date is not None:
            result.shortage_count += 1
        if item.projection.reorder.order_urgency == "immediate":
            result.reorder_now_count += 1
        if item.projection.health.overstock_risk != "none":
            result.overstock_count += 1
        if item.projection.health.is_slow_moving:
            result.slow_moving_count += 1
        if item.projection.health.is_dead_stock:
            result.dead_stock_count += 1

        headline = item.accuracy_headline()
        if headline:
            if headline.mae is not None:
                mae_values.append(headline.mae)
            if headline.rmse is not None:
                rmse_values.append(headline.rmse)
            if headline.smape is not None:
                smape_values.append(headline.smape)
            if headline.mape is not None:
                mape_values.append(headline.mape)
            if headline.mase is not None:
                mase_values.append(headline.mase)

    result.total_forecast_demand = (
        round_half_up(total_demand, config.forecast.decimals) if has_demand else None
    )
    result.accuracy_summary = {
        "mean_mae": decimal_mean(mae_values),
        "mean_rmse": decimal_mean(rmse_values),
        "mean_smape": decimal_mean(smape_values),
        "mean_mape": decimal_mean(mape_values),
        "mean_mase": decimal_mean(mase_values),
        "series_with_mape": float(len(mape_values)),
        "series_with_backtest": float(
            sum(1 for item in result.items if item.accuracy_backtest is not None)
        ),
    }
