"""Choosing a forecasting model, and saying why.

Two decisions live here, and they are kept apart on purpose:

**Eligibility** - can this method be applied to this series at all? That is a
question about the *shape* of the data: Holt-Winters needs two complete seasons,
Holt needs enough periods to see a trend, and none of the trend or seasonal
models are offered for intermittent demand, where a run of zeros makes both of
them fit noise and forecast confidently wrong.

**Selection** - of the methods that are eligible, which one actually works? That
is answered by *backtesting*, never by in-sample fit. The last few periods are
held back, each eligible method is refitted on the shortened history, and the
methods are scored on periods they never saw. In-sample fit would always crown
the most flexible model, which is exactly the model most likely to be
over-fitted.

Everything about the decision is reported: every candidate, its parameters, its
error on the held-out periods, and - for the ones that were never tried - the
reason they were not eligible. A planner disagreeing with the chosen model can
see what the alternatives scored.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.core.rounding import decimal_mean, round_half_up
from app.modules.inventory.accuracy import AccuracyMetrics, compute_metrics, naive_scale
from app.modules.inventory.forecasting import ForecastResult, fit_model
from app.modules.inventory.thresholds import MODEL_COMPLEXITY, InventoryConfig

logger = get_logger(__name__)

__all__ = [
    "DemandProfile",
    "ModelEvaluation",
    "SelectionResult",
    "eligibility",
    "profile_demand",
    "seasonal_strength",
    "select_model",
]


@dataclass
class DemandProfile:
    """What kind of demand this series has.

    The classification follows Syntetos and Boylan: the average interval between
    non-zero demands (ADI) says how *sparse* demand is, and the squared
    coefficient of variation of the non-zero demands (CV squared) says how
    *variable* it is when it does occur.
    """

    observation_count: int = 0
    zero_period_count: int = 0
    zero_period_pct: float = 0.0
    mean_demand: float | None = None
    std_demand: float | None = None
    coefficient_of_variation: float | None = None
    cv_squared: float | None = None
    average_demand_interval: float | None = None
    pattern: str = "unknown"
    is_intermittent: bool = False
    total_demand: float = 0.0
    seasonal_strength: float | None = None
    has_seasonality: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_count": self.observation_count,
            "zero_period_count": self.zero_period_count,
            "zero_period_pct": self.zero_period_pct,
            "mean_demand": self.mean_demand,
            "std_demand": self.std_demand,
            "coefficient_of_variation": self.coefficient_of_variation,
            "cv_squared": self.cv_squared,
            "average_demand_interval": self.average_demand_interval,
            "pattern": self.pattern,
            "is_intermittent": self.is_intermittent,
            "total_demand": self.total_demand,
            "seasonal_strength": self.seasonal_strength,
            "has_seasonality": self.has_seasonality,
        }


@dataclass
class ModelEvaluation:
    """One candidate method and how it did."""

    model: str
    label: str
    eligible: bool = True
    ineligible_reason: str | None = None
    evaluated: bool = False
    folds: int = 0
    holdout_periods: int = 0
    score: float | None = None
    metrics: AccuracyMetrics | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    selected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "label": self.label,
            "eligible": self.eligible,
            "ineligible_reason": self.ineligible_reason,
            "evaluated": self.evaluated,
            "folds": self.folds,
            "holdout_periods": self.holdout_periods,
            "score": self.score,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "parameters": dict(self.parameters),
            "selected": self.selected,
        }


@dataclass
class SelectionResult:
    """The chosen model, the runners-up and the reasoning."""

    selected_model: str | None = None
    selection_basis: str = "backtest"
    metric: str = "rmse"
    metric_label: str = ""
    evaluations: list[ModelEvaluation] = field(default_factory=list)
    profile: DemandProfile = field(default_factory=DemandProfile)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_model": self.selected_model,
            "selection_basis": self.selection_basis,
            "metric": self.metric,
            "metric_label": self.metric_label,
            "candidates": [item.to_dict() for item in self.evaluations],
            "demand_profile": self.profile.to_dict(),
            "notes": list(self.notes),
        }

    @property
    def selected_evaluation(self) -> ModelEvaluation | None:
        for evaluation in self.evaluations:
            if evaluation.selected:
                return evaluation
        return None


# ---------------------------------------------------------------------------
# Demand profiling
# ---------------------------------------------------------------------------


def seasonal_strength(
    values: list[float], season_length: int, observed: list[bool] | None = None
) -> float | None:
    """How much of the variation in demand the season of the year explains.

    This is an **adjusted** R-squared of grouping the detrended history by
    position in the season, and the adjustment is the whole point. A plain R
    squared is useless here: fitting 12 monthly factors to 30 observations
    explains about 12/30 of the variance *by chance alone*, so a completely
    seasonless series scores around 0.4 and looks convincingly seasonal.

    The standard degrees-of-freedom correction

        1 - (1 - R^2) * (n - 1) / (n - k)

    charges the seasonal model for every factor it fits. Random noise then
    scores near zero while a real repeating shape still scores near one, which
    is exactly the distinction the model selector needs.

    Periods that had no row in the file are excluded from the measurement when
    ``observed`` is supplied. A gap filled with a zero is not evidence of a
    season - if August is missing two years running, the filled zeros look like a
    perfect August dip, and a seasonal model would go on forecasting a dip that
    only ever existed in the gaps.

    Returns ``None`` when the history is too short to measure, or when demand is
    completely flat and there is no variation to explain.
    """
    observations = len(values)
    if observations < 2 * season_length or observations - season_length < 2:
        return None

    # Detrend with a centred moving average of one season, so a rising series is
    # not read as seasonal just because its later slots sit higher.
    half = season_length // 2
    detrended: list[tuple[int, float]] = []
    for index in range(observations):
        if observed is not None and index < len(observed) and not observed[index]:
            continue
        start = max(0, index - half)
        end = min(observations, index + half + 1)
        window = values[start:end]
        detrended.append((index % season_length, values[index] - sum(window) / len(window)))

    observations = len(detrended)
    if observations < 2 * season_length or observations - season_length < 2:
        return None

    overall = sum(value for _slot, value in detrended) / observations
    total_variance = sum((value - overall) ** 2 for _slot, value in detrended)
    if total_variance <= 0:
        return None

    groups: dict[int, list[float]] = {}
    for slot, value in detrended:
        groups.setdefault(slot, []).append(value)

    explained = sum(
        len(group) * ((sum(group) / len(group)) - overall) ** 2 for group in groups.values()
    )
    r_squared = explained / total_variance

    parameters = len(groups)
    if observations - parameters <= 0:
        return None
    adjusted = 1.0 - (1.0 - r_squared) * (observations - 1) / (observations - parameters)
    return round_half_up(max(0.0, adjusted), 4)


def profile_demand(
    values: list[float],
    config: InventoryConfig,
    season_length: int | None = None,
    observed: list[bool] | None = None,
) -> DemandProfile:
    """Classify the demand pattern of one series."""
    profile = DemandProfile(observation_count=len(values))
    if not values:
        profile.pattern = "no_data"
        return profile

    if season_length:
        profile.seasonal_strength = seasonal_strength(values, season_length, observed)
        threshold = config.model("holt_winters_seasonal").min_seasonal_strength
        profile.has_seasonality = bool(
            profile.seasonal_strength is not None and profile.seasonal_strength >= threshold
        )

    non_zero = [value for value in values if value != 0]
    profile.total_demand = round_half_up(sum(values))
    profile.zero_period_count = len(values) - len(non_zero)
    profile.zero_period_pct = round_half_up(profile.zero_period_count / len(values) * 100.0)
    profile.mean_demand = decimal_mean(values)

    if len(values) >= 2 and profile.mean_demand is not None:
        mean = float(profile.mean_demand)
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        profile.std_demand = round_half_up(math.sqrt(variance))

    if not non_zero:
        profile.pattern = "no_demand"
        profile.is_intermittent = True
        return profile

    # ADI: how many periods pass, on average, between two demands.
    profile.average_demand_interval = round_half_up(len(values) / len(non_zero))

    non_zero_mean = decimal_mean(non_zero)
    if non_zero_mean and non_zero_mean > 0:
        if len(non_zero) >= 2:
            mean = float(non_zero_mean)
            variance = sum((value - mean) ** 2 for value in non_zero) / (len(non_zero) - 1)
            cv = math.sqrt(variance) / mean
        else:
            cv = 0.0
        profile.coefficient_of_variation = round_half_up(cv, 4)
        profile.cv_squared = round_half_up(cv * cv, 4)

    settings = config.intermittent
    adi = profile.average_demand_interval or 1.0
    cv_squared = profile.cv_squared or 0.0
    sparse = (
        adi >= settings.adi_threshold
        and profile.zero_period_pct >= settings.min_zero_period_pct
    )
    erratic = cv_squared >= settings.cv_squared_threshold

    if sparse and erratic:
        profile.pattern = "lumpy"
    elif sparse:
        profile.pattern = "intermittent"
    elif erratic:
        profile.pattern = "erratic"
    else:
        profile.pattern = "smooth"

    profile.is_intermittent = bool(settings.enabled and sparse)
    return profile


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def eligibility(
    values: list[float],
    config: InventoryConfig,
    season_length: int,
    profile: DemandProfile,
) -> dict[str, str | None]:
    """Return ``{model_name: reason_it_cannot_be_used_or_None}``.

    A ``None`` reason means the method is eligible. Every other entry carries a
    sentence the user can read, because "the seasonal model was not used" is
    only useful next to "there are 14 periods and it needs 24".
    """
    observations = len(values)
    reasons: dict[str, str | None] = {}

    for name in config.enabled_models:
        spec = config.model(name)
        reason: str | None = None

        if observations < spec.min_observations:
            reason = (
                f"needs at least {spec.min_observations} periods of history and this series "
                f"has {observations}"
            )
        elif name == "holt_winters_seasonal":
            required = spec.min_seasons * season_length
            if observations < required:
                reason = (
                    f"needs {spec.min_seasons} complete seasons of {season_length} periods "
                    f"({required} periods) and this series has {observations}"
                )
            elif profile.seasonal_strength is None:
                reason = (
                    "seasonal strength could not be measured on this history, so a seasonal "
                    "model cannot be justified"
                )
            elif not profile.has_seasonality:
                reason = (
                    f"shows no repeating seasonal shape: the position in the season explains "
                    f"{profile.seasonal_strength:.0%} of the variation in demand once the "
                    f"{season_length} seasonal factors it fits are paid for, below the "
                    f"{spec.min_seasonal_strength:.0%} required. Fitting a season here would "
                    "memorise noise"
                )
        elif name == "simple_moving_average" and spec.window and observations <= spec.window:
            reason = (
                f"a {spec.window}-period moving average needs more than {spec.window} periods "
                "to produce a single fitted value"
            )

        if (
            reason is None
            and profile.is_intermittent
            and config.intermittent.enabled
            and name not in config.intermittent.allowed_models
        ):
            reason = (
                f"demand is {profile.pattern} (demand occurs about every "
                f"{profile.average_demand_interval} periods), and trend and seasonal models fit "
                "the runs of zeros rather than the demand"
            )

        reasons[name] = reason

    return reasons


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def select_model(
    values: list[float],
    config: InventoryConfig,
    season_length: int,
    *,
    requested_model: str | None = None,
    observed: list[bool] | None = None,
) -> SelectionResult:
    """Backtest every eligible method and pick the winner.

    Args:
        values: The demand history, one entry per period, gaps already filled.
        config: The validated inventory configuration.
        season_length: Periods in one season for this frequency.
        requested_model: A method the caller asked for. It is honoured when it is
            eligible for this series; when it is not, the series falls back to
            automatic selection and the reason is recorded rather than hidden.
        observed: Which periods came from a real row. Used so filled gaps cannot
            be mistaken for a seasonal pattern.
    """
    profile = profile_demand(values, config, season_length, observed)
    reasons = eligibility(values, config, season_length, profile)
    metric = config.selection.metric

    result = SelectionResult(
        metric=metric,
        metric_label=metric.upper(),
        profile=profile,
    )

    evaluations: dict[str, ModelEvaluation] = {}
    for name in config.enabled_models:
        spec = config.model(name)
        evaluations[name] = ModelEvaluation(
            model=name,
            label=spec.label,
            eligible=reasons[name] is None,
            ineligible_reason=reasons[name],
        )

    eligible_names = [name for name in config.enabled_models if reasons[name] is None]
    if not eligible_names:
        result.evaluations = [evaluations[name] for name in config.enabled_models]
        result.selection_basis = "no_eligible_model"
        result.notes.append(
            "No forecasting method can be applied to this series. The reasons are listed "
            "against each candidate."
        )
        return result

    scale = naive_scale(values)
    plan = _plan_backtest(values, config, season_length, eligible_names)
    if plan is not None:
        folds, holdout = plan
        for name in eligible_names:
            _backtest(
                name, values, config, season_length, scale, evaluations[name], folds, holdout
            )

    scored = [
        evaluation
        for evaluation in evaluations.values()
        if evaluation.evaluated and evaluation.score is not None
    ]

    # If the configured metric could not be computed for any candidate - which
    # is exactly what happens when MAPE meets a series with a zero period - fall
    # back to RMSE and say so, rather than picking arbitrarily.
    if not scored and metric != "rmse":
        for name in eligible_names:
            evaluation = evaluations[name]
            if evaluation.metrics is not None:
                evaluation.score = evaluation.metrics.value_for("rmse")
        scored = [item for item in evaluations.values() if item.score is not None]
        if scored:
            result.metric = "rmse"
            result.metric_label = "RMSE"
            result.notes.append(
                f"{metric.upper()} could not be computed for any candidate on this series, so "
                "the models were compared on RMSE instead."
            )

    if scored:
        winner = _pick_winner(scored, config, result)
        winner.selected = True
        result.selected_model = winner.model
        result.selection_basis = "backtest"
    else:
        # Nothing could be backtested: too little history to hold anything back.
        preferred = sorted(
            eligible_names, key=lambda name: (config.selection.rank(name), name)
        )
        fallback = (
            config.selection.fallback_model
            if config.selection.fallback_model in eligible_names
            else preferred[0]
        )
        evaluations[fallback].selected = True
        result.selected_model = fallback
        result.selection_basis = "fallback"
        result.notes.append(
            "There is not enough history to hold periods back for a backtest, so the "
            f"configured fallback method ({config.model(fallback).label}) was used. Its accuracy "
            "is reported in-sample only and will be optimistic."
        )

    if requested_model:
        requested_reason = reasons.get(requested_model)
        if requested_model not in evaluations:
            result.notes.append(
                f"The requested model '{requested_model}' is not configured, so the model was "
                "selected automatically."
            )
        elif requested_reason is not None:
            result.notes.append(
                f"The requested model ({config.model(requested_model).label}) cannot be used "
                f"for this series: it {requested_reason}. The model was selected automatically "
                "instead."
            )
        else:
            for evaluation in evaluations.values():
                evaluation.selected = evaluation.model == requested_model
            result.selected_model = requested_model
            result.selection_basis = "requested"
            result.notes.append(
                "The model was chosen by the user, not by backtesting. The scores of the other "
                "candidates are still reported for comparison."
            )

    result.evaluations = [evaluations[name] for name in config.enabled_models]
    return result


def _pick_winner(
    scored: list[ModelEvaluation], config: InventoryConfig, result: SelectionResult
) -> ModelEvaluation:
    """Choose the winner, charging a more complex model for its extra freedom.

    A backtest on a handful of held-out periods is a noisy measurement, and the
    model with the most parameters wins those coin flips more often than it
    deserves. So the candidates are walked from simplest to most complex, and a
    more complex one only takes the lead when it beats the incumbent by more
    than the configured margin. Ties, and near-ties, go to the simpler model -
    which is also the one a planner can explain.
    """
    margin = config.selection.complexity_margin_pct / 100.0
    ordered = sorted(
        scored,
        key=lambda item: (
            MODEL_COMPLEXITY.get(item.model, 0),
            item.score,
            config.selection.rank(item.model),
            item.model,
        ),
    )

    incumbent = ordered[0]
    for candidate in ordered[1:]:
        same_complexity = MODEL_COMPLEXITY.get(candidate.model, 0) == MODEL_COMPLEXITY.get(
            incumbent.model, 0
        )
        threshold = incumbent.score if same_complexity else incumbent.score * (1.0 - margin)
        if candidate.score < threshold:
            incumbent = candidate
        elif not same_complexity and candidate.score < incumbent.score:
            result.notes.append(
                f"{candidate.label} scored slightly better ({candidate.score:g} against "
                f"{incumbent.score:g}) but not by the {config.selection.complexity_margin_pct:g}% "
                f"required to justify its extra parameters, so the simpler {incumbent.label} was "
                "kept."
            )
    return incumbent


def _minimum_train(model_name: str, config: InventoryConfig, season_length: int) -> int:
    """Shortest history this method can be fitted to."""
    spec = config.model(model_name)
    minimum = max(config.selection.minimum_train_observations, spec.min_observations)
    if model_name == "holt_winters_seasonal":
        minimum = max(minimum, spec.min_seasons * season_length)
    return minimum


def _plan_backtest(
    values: list[float],
    config: InventoryConfig,
    season_length: int,
    eligible_names: list[str],
) -> tuple[int, int] | None:
    """Decide the held-out periods **once**, for every candidate together.

    Two models scored on different holdout windows cannot be compared: a method
    that happened to be tested on three easy periods would beat one tested on
    six hard ones, and the winner would be an artefact of the split. The fold
    count is therefore driven by the most demanding eligible model - in practice
    Holt-Winters, which needs two whole seasons to train on - and every candidate
    is then scored on exactly the same periods.

    Returns ``None`` when even one fold would leave too little history to fit
    the most demanding model, in which case nothing is backtested and the caller
    falls back to a configured method.
    """
    observations = len(values)
    minimum_train = max(
        _minimum_train(name, config, season_length) for name in eligible_names
    )
    holdout = config.selection.holdout_periods
    folds = config.selection.folds
    while folds >= 1 and observations - holdout * folds < minimum_train:
        folds -= 1
    return (folds, holdout) if folds >= 1 else None


def _backtest(
    model_name: str,
    values: list[float],
    config: InventoryConfig,
    season_length: int,
    scale: float | None,
    evaluation: ModelEvaluation,
    folds: int,
    holdout: int,
) -> None:
    """Score one method on periods it was not fitted to."""
    observations = len(values)

    actuals: list[float] = []
    predictions: list[float] = []
    parameters: dict[str, Any] = {}
    for fold in range(folds):
        train_end = observations - holdout * (folds - fold)
        train = values[:train_end]
        test = values[train_end : train_end + holdout]
        if not test:
            continue
        fitted = fit_model(model_name, train, len(test), config, season_length)
        parameters = dict(fitted.parameters)
        actuals.extend(test)
        predictions.extend(fitted.point_forecast[: len(test)])

    if not actuals:
        return

    evaluation.evaluated = True
    evaluation.folds = folds
    evaluation.holdout_periods = holdout
    evaluation.parameters = parameters
    evaluation.metrics = compute_metrics(
        actuals,
        predictions,
        scale=scale,
        basis=f"backtest: {folds} fold(s) of {holdout} held-out period(s)",
    )
    evaluation.score = evaluation.metrics.value_for(config.selection.metric)


def refit_selected(
    result: SelectionResult,
    values: list[float],
    horizon: int,
    config: InventoryConfig,
    season_length: int,
) -> ForecastResult | None:
    """Refit the selected method on the **full** history and forecast forward.

    The backtest deliberately fitted on shortened histories; the forecast a user
    acts on must use every period available.
    """
    if not result.selected_model:
        return None
    return fit_model(result.selected_model, values, horizon, config, season_length)
