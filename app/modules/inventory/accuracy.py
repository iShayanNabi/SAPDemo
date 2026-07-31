"""Forecast accuracy metrics.

Four families, because no single number answers "is this forecast any good?":

``MAE``
    Mean absolute error, in units of the material. Easy to explain, easy to
    compare against a safety stock.
``RMSE``
    Root mean squared error, also in units. Punishes a few large misses more
    than many small ones, which is the behaviour a stockout-averse planner
    wants, and it is the standard deviation the prediction interval is built
    from.
``MAPE``
    Mean absolute percentage error. Scale-free, so it compares two materials -
    **but it divides by the actual value, so it is undefined the moment a period
    had zero demand.**
``sMAPE`` / ``MASE``
    The safe alternatives, always reported.

The MAPE trap is the reason this module exists as its own file. Computing MAPE
over "just the non-zero periods" is the usual workaround and it is dishonest:
for an intermittent material it silently drops exactly the periods the forecast
found hardest and reports a flattering number. Here, **MAPE is reported only
when every period in the comparison window has non-zero demand.** Otherwise it
is ``None``, the reason is stated, and sMAPE and MASE carry the answer.

MASE compares the forecast against a naive "next period equals this one"
forecast on the training history: below 1 means the model beats naive, above 1
means it does not. It is the one metric here that says whether the modelling was
worth doing at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.rounding import decimal_mean, round_half_up

__all__ = [
    "AccuracyMetrics",
    "METRIC_LABELS",
    "compute_metrics",
    "metric_value",
    "naive_scale",
]

#: Human labels for the metrics a model can be selected on.
METRIC_LABELS: dict[str, str] = {
    "mae": "Mean absolute error",
    "rmse": "Root mean squared error",
    "mape": "Mean absolute percentage error",
    "smape": "Symmetric mean absolute percentage error",
    "mase": "Mean absolute scaled error",
}


@dataclass
class AccuracyMetrics:
    """How far a set of forecasts fell from what actually happened."""

    observations: int = 0
    mae: float | None = None
    rmse: float | None = None
    mape: float | None = None
    mape_available: bool = False
    mape_unavailable_reason: str | None = None
    zero_demand_periods: int = 0
    smape: float | None = None
    mase: float | None = None
    bias: float | None = None
    bias_pct: float | None = None
    basis: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": self.observations,
            "mae": self.mae,
            "rmse": self.rmse,
            "mape": self.mape,
            "mape_available": self.mape_available,
            "mape_unavailable_reason": self.mape_unavailable_reason,
            "zero_demand_periods": self.zero_demand_periods,
            "smape": self.smape,
            "mase": self.mase,
            "bias": self.bias,
            "bias_pct": self.bias_pct,
            "basis": self.basis,
            "notes": list(self.notes),
        }

    def value_for(self, metric: str) -> float | None:
        """Return one metric by name, or ``None`` when it could not be computed."""
        return getattr(self, metric, None)


def naive_scale(history: list[float]) -> float | None:
    """Mean absolute change between consecutive periods - the MASE denominator.

    Returns ``None`` when the history is too short, and ``None`` rather than
    zero for a perfectly flat history: dividing by zero would report an infinite
    scaled error for a forecast that is in fact exactly right.
    """
    if len(history) < 2:
        return None
    changes = [abs(later - earlier) for earlier, later in zip(history, history[1:])]
    mean_change = decimal_mean(changes, decimals=6)
    if mean_change is None or mean_change <= 0:
        return None
    return mean_change


def compute_metrics(
    actuals: list[float],
    forecasts: list[float],
    *,
    scale: float | None = None,
    basis: str = "",
) -> AccuracyMetrics:
    """Compare ``forecasts`` against ``actuals`` position by position.

    Args:
        actuals: What demand turned out to be.
        forecasts: What the model said it would be.
        scale: The MASE denominator from :func:`naive_scale`. Omit it and MASE is
            reported as ``None`` rather than guessed.
        basis: Short label describing where the comparison came from
            (``"in_sample"``, ``"backtest"``), carried through to the API.
    """
    paired = [
        (float(actual), float(forecast))
        for actual, forecast in zip(actuals, forecasts)
    ]
    metrics = AccuracyMetrics(observations=len(paired), basis=basis)
    if not paired:
        metrics.mape_unavailable_reason = "There are no periods to compare."
        return metrics

    errors = [actual - forecast for actual, forecast in paired]
    absolute = [abs(error) for error in errors]

    metrics.mae = decimal_mean(absolute)
    squared_mean = decimal_mean([error * error for error in errors], decimals=8)
    metrics.rmse = round_half_up(squared_mean**0.5) if squared_mean is not None else None
    metrics.bias = decimal_mean(errors)

    zero_periods = [actual for actual, _ in paired if actual == 0]
    metrics.zero_demand_periods = len(zero_periods)

    if zero_periods:
        metrics.mape_available = False
        metrics.mape_unavailable_reason = (
            f"{len(zero_periods)} of {len(paired)} period(s) had zero demand. MAPE divides by "
            "the actual value, so it is undefined here. Computing it over the non-zero periods "
            "only would quietly drop the hardest periods, so sMAPE and MASE are reported instead."
        )
    else:
        percentage_errors = [
            abs(error) / abs(actual) * 100.0
            for error, (actual, _) in zip(errors, paired)
        ]
        metrics.mape = decimal_mean(percentage_errors)
        metrics.mape_available = True

    # sMAPE: a period where the actual and the forecast are both zero was
    # predicted exactly, so it contributes no error rather than a division.
    symmetric: list[float] = []
    for (actual, forecast), error in zip(paired, errors):
        denominator = abs(actual) + abs(forecast)
        symmetric.append(0.0 if denominator == 0 else 2.0 * abs(error) / denominator * 100.0)
    metrics.smape = decimal_mean(symmetric)

    if scale and scale > 0 and metrics.mae is not None:
        metrics.mase = round_half_up(metrics.mae / scale)
    elif metrics.mae is not None:
        metrics.notes.append(
            "MASE is not reported: the history is too short or completely flat, so there is no "
            "naive benchmark to scale against."
        )

    actual_total = sum(actual for actual, _ in paired)
    if actual_total:
        metrics.bias_pct = round_half_up(sum(errors) / actual_total * 100.0)

    return metrics


def metric_value(metrics: AccuracyMetrics, metric: str) -> float | None:
    """Return the value a model should be *selected* on.

    ``None`` means "this model cannot be compared on this metric", which the
    selector treats as ineligible rather than as a score of zero.
    """
    value = metrics.value_for(metric)
    return None if value is None else float(value)
