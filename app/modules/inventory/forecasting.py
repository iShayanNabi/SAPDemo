"""The five explainable forecasting methods.

Every function here is pure: it takes a list of demand values and returns a
:class:`ForecastResult`. No database, no configuration lookup, no AI, no
randomness - the same input always produces the same output, and a planner can
reproduce any of these five methods in a spreadsheet.

**Why these five.** Each one encodes a different, statable belief about how
demand behaves, and the belief is what a planner has to agree or disagree with:

===============================  ====================================================
Method                           What it assumes
===============================  ====================================================
Simple moving average            A flat level; the last *w* periods are equally
                                 informative.
Weighted moving average          A flat level; recent periods are more informative.
Simple exponential smoothing     A level that drifts; older periods fade
                                 geometrically.
Holt linear trend                A level *and* a trend, both drifting.
Holt-Winters additive seasonal   A level, a trend and a repeating seasonal shape.
===============================  ====================================================

**Warm-up.** Each method needs a few periods before it can produce a fitted
value at all: three for a three-period moving average, one for exponential
smoothing, a whole season for Holt-Winters. Those early periods carry no
residual, so they are excluded from the error statistics rather than scored
against a value that was partly built from themselves. That exclusion is why the
accuracy figures in this module are comparable across the five methods.

**Prediction intervals.** ``interval_factors`` is the per-step multiplier that
turns the residual standard deviation into the standard error of an *h*-step
forecast. The moving averages assume a stationary level, so their interval does
not widen with the horizon. The exponential-smoothing family accumulates error,
so theirs does, following the standard formulae for each model.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.modules.inventory.thresholds import InventoryConfig, ModelSpec

__all__ = [
    "ForecastResult",
    "MODEL_FUNCTIONS",
    "fit_model",
    "holt_linear_trend",
    "holt_winters_seasonal",
    "simple_exponential_smoothing",
    "simple_moving_average",
    "weighted_moving_average",
]


@dataclass
class ForecastResult:
    """A fitted model, its in-sample behaviour and its forecast."""

    model: str
    label: str
    horizon: int
    parameters: dict[str, Any] = field(default_factory=dict)
    fitted: list[float | None] = field(default_factory=list)
    residuals: list[float] = field(default_factory=list)
    point_forecast: list[float] = field(default_factory=list)
    interval_factors: list[float] = field(default_factory=list)
    warmup: int = 0
    estimated_parameter_count: int = 0
    assumptions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def sse(self) -> float:
        """Sum of squared one-step-ahead in-sample errors."""
        return float(sum(value * value for value in self.residuals))

    @property
    def residual_std(self) -> float:
        """Residual standard deviation, corrected for the parameters estimated.

        Returns ``0.0`` when there are not enough residuals to measure spread -
        a series that fits perfectly and a series with two observations both
        legitimately have no measurable error, and pretending otherwise would
        invent an interval width.
        """
        count = len(self.residuals)
        if count == 0:
            return 0.0
        degrees_of_freedom = count - self.estimated_parameter_count
        if degrees_of_freedom <= 0:
            degrees_of_freedom = count
        return math.sqrt(self.sse / degrees_of_freedom)

    @property
    def in_sample_actual_indexes(self) -> list[int]:
        """Positions of the observations that carry a residual."""
        return [index for index, value in enumerate(self.fitted) if value is not None]


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------


def simple_moving_average(values: list[float], horizon: int, window: int) -> ForecastResult:
    """Average of the last ``window`` periods, held flat across the horizon."""
    window = max(1, min(int(window), len(values)))
    fitted: list[float | None] = [None] * len(values)
    for position in range(window, len(values)):
        fitted[position] = sum(values[position - window : position]) / window

    level = sum(values[-window:]) / window
    return ForecastResult(
        model="simple_moving_average",
        label="Simple moving average",
        horizon=horizon,
        parameters={"window": window},
        fitted=fitted,
        residuals=_residuals(values, fitted),
        point_forecast=[level] * horizon,
        interval_factors=[1.0] * horizon,
        warmup=window,
        estimated_parameter_count=0,
    )


def weighted_moving_average(
    values: list[float], horizon: int, weights: list[float]
) -> ForecastResult:
    """Weighted average of the last periods, most-recent-first, held flat."""
    weights = [float(weight) for weight in weights if weight >= 0] or [1.0]
    span = min(len(weights), len(values))
    applied = weights[:span]
    total = sum(applied)
    applied = [weight / total for weight in applied] if total else [1.0 / span] * span

    fitted: list[float | None] = [None] * len(values)
    for position in range(span, len(values)):
        window = values[position - span : position][::-1]  # most recent first
        fitted[position] = sum(weight * value for weight, value in zip(applied, window))

    recent = values[-span:][::-1]
    level = sum(weight * value for weight, value in zip(applied, recent))
    return ForecastResult(
        model="weighted_moving_average",
        label="Weighted moving average",
        horizon=horizon,
        parameters={"weights": [round(weight, 6) for weight in applied], "window": span},
        fitted=fitted,
        residuals=_residuals(values, fitted),
        point_forecast=[level] * horizon,
        interval_factors=[1.0] * horizon,
        warmup=span,
        estimated_parameter_count=0,
    )


# ---------------------------------------------------------------------------
# Exponential smoothing family
# ---------------------------------------------------------------------------


def simple_exponential_smoothing(
    values: list[float], horizon: int, alpha: float
) -> ForecastResult:
    """Exponentially weighted level, held flat across the horizon."""
    alpha = _clamp(alpha, 0.0, 1.0)
    level = values[0]
    fitted: list[float | None] = [None]
    for value in values[1:]:
        fitted.append(level)
        level = alpha * value + (1.0 - alpha) * level

    factors = [math.sqrt(1.0 + max(0, step - 1) * alpha * alpha) for step in range(1, horizon + 1)]
    return ForecastResult(
        model="simple_exponential_smoothing",
        label="Simple exponential smoothing",
        horizon=horizon,
        parameters={"alpha": round(alpha, 6)},
        fitted=fitted,
        residuals=_residuals(values, fitted),
        point_forecast=[level] * horizon,
        interval_factors=factors,
        warmup=1,
        estimated_parameter_count=1,
    )


def holt_linear_trend(
    values: list[float], horizon: int, alpha: float, beta: float, damping: float = 1.0
) -> ForecastResult:
    """Holt's method: a smoothed level plus a smoothed trend."""
    alpha = _clamp(alpha, 0.0, 1.0)
    beta = _clamp(beta, 0.0, 1.0)
    phi = _clamp(damping, 0.0, 1.0)

    level = values[0]
    trend = values[1] - values[0]
    fitted: list[float | None] = [None, None]
    for value in values[2:]:
        forecast = level + phi * trend
        fitted.append(forecast)
        previous_level = level
        level = alpha * value + (1.0 - alpha) * forecast
        trend = beta * (level - previous_level) + (1.0 - beta) * phi * trend

    point = []
    for step in range(1, horizon + 1):
        damped = sum(phi**power for power in range(1, step + 1)) if phi < 1.0 else float(step)
        point.append(level + damped * trend)

    return ForecastResult(
        model="holt_linear_trend",
        label="Holt linear trend",
        horizon=horizon,
        parameters={"alpha": round(alpha, 6), "beta": round(beta, 6), "damping": round(phi, 6)},
        fitted=fitted,
        residuals=_residuals(values, fitted),
        point_forecast=point,
        interval_factors=_holt_interval_factors(horizon, alpha, beta, phi),
        warmup=2,
        estimated_parameter_count=2,
    )


def holt_winters_seasonal(
    values: list[float],
    horizon: int,
    alpha: float,
    beta: float,
    gamma: float,
    season_length: int,
    damping: float = 1.0,
) -> ForecastResult:
    """Holt-Winters with an **additive** season.

    Additive rather than multiplicative on purpose: a multiplicative season is
    undefined when a period's demand is zero, and inventory demand hits zero
    regularly. The seasonal effect here adds or subtracts a quantity.
    """
    alpha = _clamp(alpha, 0.0, 1.0)
    beta = _clamp(beta, 0.0, 1.0)
    gamma = _clamp(gamma, 0.0, 1.0)
    phi = _clamp(damping, 0.0, 1.0)
    season_length = max(2, int(season_length))

    first_season = values[:season_length]
    second_season = values[season_length : 2 * season_length]
    level = sum(first_season) / len(first_season)
    trend = (sum(second_season) / len(second_season) - level) / season_length
    seasonals = [value - level for value in first_season]

    fitted: list[float | None] = []
    for position, value in enumerate(values):
        slot = position % season_length
        forecast = level + phi * trend + seasonals[slot]
        # The first season is fitted with seasonal indexes derived from itself,
        # so those periods are shown but never scored.
        fitted.append(None if position < season_length else forecast)
        previous_level = level
        level = alpha * (value - seasonals[slot]) + (1.0 - alpha) * (level + phi * trend)
        trend = beta * (level - previous_level) + (1.0 - beta) * phi * trend
        seasonals[slot] = gamma * (value - level) + (1.0 - gamma) * seasonals[slot]

    observations = len(values)
    point = []
    for step in range(1, horizon + 1):
        damped = sum(phi**power for power in range(1, step + 1)) if phi < 1.0 else float(step)
        slot = (observations + step - 1) % season_length
        point.append(level + damped * trend + seasonals[slot])

    result = ForecastResult(
        model="holt_winters_seasonal",
        label="Holt-Winters additive seasonal",
        horizon=horizon,
        parameters={
            "alpha": round(alpha, 6),
            "beta": round(beta, 6),
            "gamma": round(gamma, 6),
            "damping": round(phi, 6),
            "season_length": season_length,
        },
        fitted=fitted,
        residuals=_residuals(values, fitted),
        point_forecast=point,
        interval_factors=_holt_interval_factors(horizon, alpha, beta, phi),
        warmup=season_length,
        estimated_parameter_count=3,
    )
    result.notes.append(
        "The prediction interval uses the Holt trend formula. It is an approximation for a "
        "seasonal model: it accounts for level and trend error accumulating, not for the "
        "seasonal indexes being estimated."
    )
    return result


# ---------------------------------------------------------------------------
# Fitting through the configuration
# ---------------------------------------------------------------------------

#: model name -> the function that fits it. Used by the selector and the engine.
MODEL_FUNCTIONS: dict[str, Callable[..., ForecastResult]] = {
    "simple_moving_average": simple_moving_average,
    "weighted_moving_average": weighted_moving_average,
    "simple_exponential_smoothing": simple_exponential_smoothing,
    "holt_linear_trend": holt_linear_trend,
    "holt_winters_seasonal": holt_winters_seasonal,
}


def fit_model(
    model_name: str,
    values: list[float],
    horizon: int,
    config: InventoryConfig,
    season_length: int | None = None,
) -> ForecastResult:
    """Fit one configured model to ``values``.

    Smoothing constants come from the configuration. When the model has
    ``optimize`` switched on, the constants are chosen by an exhaustive search of
    the configured grid, minimising the sum of squared one-step-ahead errors.
    The grid is coarse and fixed, which keeps the choice reproducible: the same
    history always produces the same constants.
    """
    spec = config.model(model_name)
    horizon = max(1, int(horizon))

    if model_name == "simple_moving_average":
        return _decorate(simple_moving_average(values, horizon, spec.window or 3), spec)

    if model_name == "weighted_moving_average":
        result = weighted_moving_average(values, horizon, spec.normalized_weights or [1.0])
        if spec.weights_were_normalized:
            result.notes.append(
                "The configured weights did not sum to 1 and were scaled proportionally. "
                "The scaled weights are the ones shown in the parameters."
            )
        return _decorate(result, spec)

    if model_name == "simple_exponential_smoothing":
        grid = [(alpha,) for alpha in (spec.alpha_grid if spec.optimize else [spec.alpha or 0.3])]
        best = _grid_search(
            grid, lambda params: simple_exponential_smoothing(values, horizon, params[0])
        )
        return _decorate(best, spec, optimized=spec.optimize and len(grid) > 1)

    if model_name == "holt_linear_trend":
        alphas = spec.alpha_grid if spec.optimize else [spec.alpha or 0.3]
        betas = spec.beta_grid if spec.optimize else [spec.beta or 0.1]
        grid = [(alpha, beta) for alpha in alphas for beta in betas]
        best = _grid_search(
            grid,
            lambda params: holt_linear_trend(values, horizon, params[0], params[1], spec.damping),
        )
        return _decorate(best, spec, optimized=spec.optimize and len(grid) > 1)

    if model_name == "holt_winters_seasonal":
        length = int(season_length or spec.season_length or 12)
        alphas = spec.alpha_grid if spec.optimize else [spec.alpha or 0.3]
        betas = spec.beta_grid if spec.optimize else [spec.beta or 0.1]
        gammas = spec.gamma_grid if spec.optimize else [spec.gamma or 0.2]
        grid = [(a, b, g) for a in alphas for b in betas for g in gammas]
        best = _grid_search(
            grid,
            lambda params: holt_winters_seasonal(
                values, horizon, params[0], params[1], params[2], length, spec.damping
            ),
        )
        return _decorate(best, spec, optimized=spec.optimize and len(grid) > 1)

    raise ValueError(f"Unknown forecasting model: {model_name}")


def _decorate(result: ForecastResult, spec: ModelSpec, optimized: bool = False) -> ForecastResult:
    """Attach the configured label and assumptions to a fitted result."""
    result.label = spec.label
    result.assumptions = list(spec.assumptions)
    if optimized:
        result.notes.append(
            "The smoothing constants were chosen by searching the configured grid for the "
            "lowest sum of squared one-step-ahead errors on this material's own history."
        )
    return result


def _grid_search(
    grid: list[tuple[float, ...]], build: Callable[[tuple[float, ...]], ForecastResult]
) -> ForecastResult:
    """Return the fit with the lowest in-sample SSE.

    Ties are broken by the order of the grid, so the search is reproducible and
    prefers the smaller smoothing constant - the steadier model - when two
    settings fit the history equally well.
    """
    best: ForecastResult | None = None
    best_sse = math.inf
    for params in grid:
        candidate = build(params)
        sse = candidate.sse
        if sse < best_sse - 1e-12:
            best, best_sse = candidate, sse
    if best is None:  # pragma: no cover - a grid is never empty by construction
        raise ValueError("The parameter grid produced no candidate fit.")
    return best


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _residuals(values: list[float], fitted: list[float | None]) -> list[float]:
    """One-step-ahead errors for the periods that have a fitted value."""
    return [
        values[index] - fit
        for index, fit in enumerate(fitted)
        if fit is not None and index < len(values)
    ]


def _holt_interval_factors(horizon: int, alpha: float, beta: float, phi: float) -> list[float]:
    """Standard-error multipliers for the Holt family.

    For the undamped model the *h*-step variance is
    ``sigma^2 * (1 + sum_{j=1..h-1} (alpha*(1 + j*beta))^2)``; damping replaces
    ``j*beta`` with the geometric sum of the damping factors. Both are the
    textbook additive-error results, which is what makes the interval widths
    checkable rather than chosen.
    """
    factors: list[float] = []
    for step in range(1, horizon + 1):
        total = 1.0
        for offset in range(1, step):
            if phi >= 1.0:
                coefficient = alpha * (1.0 + offset * beta)
            else:
                geometric = phi * (1.0 - phi**offset) / (1.0 - phi)
                coefficient = alpha * (1.0 + beta * geometric)
            total += coefficient * coefficient
        factors.append(math.sqrt(total))
    return factors


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))
