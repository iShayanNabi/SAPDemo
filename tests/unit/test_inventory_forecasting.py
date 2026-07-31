"""Unit tests for the Inventory Predictor's forecasting layer.

These tests are deliberately arithmetic: a moving average of a known series has
one right answer, and asserting it by hand is what stops a refactor from
silently changing every forecast in the lab.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from app.modules.inventory.accuracy import compute_metrics, naive_scale
from app.modules.inventory.forecasting import (
    fit_model,
    holt_linear_trend,
    holt_winters_seasonal,
    simple_exponential_smoothing,
    simple_moving_average,
    weighted_moving_average,
)
from app.modules.inventory.periods import PeriodGrid, infer_frequency
from app.modules.inventory.selection import (
    profile_demand,
    seasonal_strength,
    select_model,
)


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------


def test_simple_moving_average_is_the_mean_of_the_window():
    result = simple_moving_average([10.0, 20.0, 30.0, 40.0, 50.0], horizon=3, window=3)

    # The forecast is the mean of the last three periods: (30 + 40 + 50) / 3.
    assert result.point_forecast == [40.0, 40.0, 40.0]
    # Warm-up: no fitted value until the window is full.
    assert result.fitted[:3] == [None, None, None]
    assert result.fitted[3] == pytest.approx(20.0)  # (10 + 20 + 30) / 3
    assert result.fitted[4] == pytest.approx(30.0)  # (20 + 30 + 40) / 3
    assert result.residuals == pytest.approx([20.0, 20.0])


def test_simple_moving_average_interval_does_not_widen_with_the_horizon():
    result = simple_moving_average([10.0, 12.0, 11.0, 13.0, 12.0], horizon=6, window=3)

    # A moving average assumes a stationary level, so its interval is flat.
    assert result.interval_factors == [1.0] * 6


def test_weighted_moving_average_applies_weights_most_recent_first():
    result = weighted_moving_average(
        [100.0, 200.0, 300.0], horizon=1, weights=[0.5, 0.3, 0.2]
    )

    # 0.5 * 300 + 0.3 * 200 + 0.2 * 100 = 230
    assert result.point_forecast[0] == pytest.approx(230.0)


def test_weighted_moving_average_normalises_weights_that_do_not_sum_to_one():
    result = weighted_moving_average([100.0, 200.0, 300.0], horizon=1, weights=[5.0, 3.0, 2.0])

    assert sum(result.parameters["weights"]) == pytest.approx(1.0)
    assert result.point_forecast[0] == pytest.approx(230.0)


# ---------------------------------------------------------------------------
# Exponential smoothing family
# ---------------------------------------------------------------------------


def test_simple_exponential_smoothing_matches_the_recursion_by_hand():
    values = [100.0, 110.0, 105.0]
    alpha = 0.4
    result = simple_exponential_smoothing(values, horizon=2, alpha=alpha)

    # level0 = 100; level1 = .4*110 + .6*100 = 104; level2 = .4*105 + .6*104 = 104.4
    assert result.point_forecast == pytest.approx([104.4, 104.4])
    assert result.fitted == [None, pytest.approx(100.0), pytest.approx(104.0)]


def test_simple_exponential_smoothing_interval_widens_with_the_horizon():
    result = simple_exponential_smoothing([10.0, 12.0, 11.0, 13.0], horizon=3, alpha=0.5)

    # The textbook rule: sqrt(1 + (h-1) * alpha^2).
    assert result.interval_factors[0] == pytest.approx(1.0)
    assert result.interval_factors[1] == pytest.approx(math.sqrt(1 + 0.25))
    assert result.interval_factors[2] == pytest.approx(math.sqrt(1 + 2 * 0.25))


def test_holt_projects_a_trend_forward_instead_of_flattening():
    values = [float(100 + 10 * index) for index in range(12)]
    result = holt_linear_trend(values, horizon=3, alpha=0.6, beta=0.3)

    # A perfectly linear series must keep rising by ~10 a period.
    assert result.point_forecast[0] == pytest.approx(220.0, abs=1.0)
    assert result.point_forecast[1] == pytest.approx(230.0, abs=1.0)
    assert result.point_forecast[2] == pytest.approx(240.0, abs=1.0)
    assert result.point_forecast[2] > result.point_forecast[0]


def test_holt_winters_reproduces_a_clean_seasonal_shape():
    season = [100.0, 120.0, 160.0, 120.0]
    values = season * 4
    result = holt_winters_seasonal(
        values, horizon=4, alpha=0.3, beta=0.05, gamma=0.3, season_length=4
    )

    # The next four periods must repeat the season, starting where it left off.
    assert result.point_forecast == pytest.approx(season, abs=6.0)
    # The first season is never scored: its fitted values come from itself.
    assert result.fitted[:4] == [None, None, None, None]
    assert result.warmup == 4


def test_holt_winters_handles_a_zero_demand_period():
    # An additive season is used precisely so a zero period is not a division.
    values = [50.0, 0.0, 80.0, 30.0] * 3
    result = holt_winters_seasonal(
        values, horizon=4, alpha=0.3, beta=0.1, gamma=0.3, season_length=4
    )

    assert len(result.point_forecast) == 4
    assert all(math.isfinite(value) for value in result.point_forecast)


def test_fit_model_optimises_the_smoothing_constant_from_the_grid(inventory_config):
    # A series that jumps and stays put is fitted best by a responsive alpha.
    values = [10.0] * 8 + [90.0] * 8
    result = fit_model("simple_exponential_smoothing", values, 3, inventory_config)

    assert result.parameters["alpha"] >= 0.5
    assert any("grid" in note for note in result.notes)


# ---------------------------------------------------------------------------
# Accuracy metrics
# ---------------------------------------------------------------------------


def test_mae_and_rmse_are_computed_by_hand():
    metrics = compute_metrics([10.0, 20.0, 30.0], [12.0, 18.0, 33.0])

    # errors: -2, +2, -3 -> MAE = 7/3, RMSE = sqrt(17/3)
    assert metrics.mae == pytest.approx(2.33, abs=0.01)
    assert metrics.rmse == pytest.approx(math.sqrt(17 / 3), abs=0.01)
    assert metrics.observations == 3


def test_mape_is_reported_when_no_period_has_zero_demand():
    metrics = compute_metrics([100.0, 200.0], [110.0, 180.0])

    # |10|/100 = 10%, |20|/200 = 10% -> MAPE = 10%
    assert metrics.mape_available is True
    assert metrics.mape == pytest.approx(10.0)


def test_mape_is_refused_rather_than_computed_over_the_non_zero_periods():
    metrics = compute_metrics([100.0, 0.0, 50.0], [90.0, 10.0, 55.0])

    # Dropping the zero period would report a flattering 10% and hide the
    # period the forecast got most wrong.
    assert metrics.mape is None
    assert metrics.mape_available is False
    assert metrics.zero_demand_periods == 1
    assert "zero demand" in metrics.mape_unavailable_reason
    # The safe alternatives are always there.
    assert metrics.smape is not None


def test_smape_treats_a_correctly_predicted_zero_as_no_error():
    metrics = compute_metrics([0.0, 100.0], [0.0, 100.0])

    assert metrics.smape == pytest.approx(0.0)


def test_mase_compares_against_a_naive_forecast():
    history = [10.0, 20.0, 10.0, 20.0]  # mean absolute change = 10
    scale = naive_scale(history)
    assert scale == pytest.approx(10.0)

    beats_naive = compute_metrics([20.0, 20.0], [18.0, 22.0], scale=scale)
    assert beats_naive.mase == pytest.approx(0.2)
    assert beats_naive.mase < 1

    loses_to_naive = compute_metrics([20.0, 20.0], [0.0, 40.0], scale=scale)
    assert loses_to_naive.mase == pytest.approx(2.0)


def test_naive_scale_is_none_for_a_flat_history():
    # Dividing by zero would report an infinite error for an exact forecast.
    assert naive_scale([5.0, 5.0, 5.0]) is None
    assert naive_scale([5.0]) is None


# ---------------------------------------------------------------------------
# Period handling
# ---------------------------------------------------------------------------


def test_frequency_is_inferred_from_month_end_dates(inventory_config):
    # 28, 31 and 30 day gaps are still monthly data.
    dates = [date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31), date(2025, 4, 30)]
    frequency, median_gap = infer_frequency(dates, inventory_config)

    assert frequency == "monthly"
    assert median_gap == pytest.approx(30.0, abs=1.5)


def test_weekly_and_daily_frequencies_are_recognised(inventory_config):
    weekly = [date(2025, 1, 6), date(2025, 1, 13), date(2025, 1, 20)]
    daily = [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)]

    assert infer_frequency(weekly, inventory_config)[0] == "weekly"
    assert infer_frequency(daily, inventory_config)[0] == "daily"


def test_monthly_grid_uses_calendar_months_not_thirty_day_blocks(inventory_config):
    grid = PeriodGrid.build("monthly", date(2025, 1, 15), inventory_config)

    assert grid.origin == date(2025, 1, 1)
    assert grid.index_of(date(2025, 3, 31)) == 2
    assert grid.date_at(13) == date(2026, 2, 1)
    # February is 28 days, not 30 - a shortage date inside it depends on this.
    assert grid.length_days(1) == 28
    assert grid.length_days(0) == 31


# ---------------------------------------------------------------------------
# Seasonality detection and model selection
# ---------------------------------------------------------------------------


def test_seasonal_strength_is_high_for_a_real_season():
    season = [50.0, 80.0, 140.0, 90.0]
    strength = seasonal_strength(season * 6, 4)

    assert strength is not None
    assert strength > 0.8


def test_seasonal_strength_is_near_zero_for_noise_around_a_level():
    # 12 seasonal factors fitted to 30 observations explain ~40% of the variance
    # by chance. The degrees-of-freedom correction is what removes that.
    values = [100.0 + (index * 37 % 11) - 5 for index in range(30)]
    strength = seasonal_strength(values, 12)

    assert strength is not None
    assert strength < 0.5


def test_seasonal_strength_ignores_periods_that_were_never_observed():
    # Two Augusts missing from the file, filled with zeros, look like a perfect
    # seasonal dip. They must not count as evidence of a season.
    values = [100.0] * 24
    observed = [True] * 24
    for index in (7, 19):
        values[index] = 0.0
        observed[index] = False

    with_gaps = seasonal_strength(values, 12)
    without_gaps = seasonal_strength(values, 12, observed)

    assert with_gaps is not None and with_gaps > 0.5
    assert without_gaps is None or without_gaps < 0.5


def test_seasonal_model_is_not_offered_without_two_full_seasons(inventory_config):
    values = [100.0, 120.0, 160.0, 120.0] * 3  # 12 monthly periods
    result = select_model(values, inventory_config, season_length=12)

    seasonal = next(
        item for item in result.evaluations if item.model == "holt_winters_seasonal"
    )
    assert seasonal.eligible is False
    assert "seasons" in seasonal.ineligible_reason
    assert result.selected_model != "holt_winters_seasonal"


def test_seasonal_model_wins_on_a_clearly_seasonal_series(inventory_config):
    season = [60.0, 90.0, 200.0, 120.0, 70.0, 65.0, 80.0, 110.0, 190.0, 130.0, 75.0, 62.0]
    values = (season * 3)[:30]
    result = select_model(values, inventory_config, season_length=12)

    assert result.selected_model == "holt_winters_seasonal"
    assert result.selection_basis == "backtest"
    assert result.profile.has_seasonality is True


def test_level_only_model_wins_on_a_stable_series(inventory_config):
    values = [300.0 + ((index * 53) % 17) - 8 for index in range(30)]
    result = select_model(values, inventory_config, season_length=12)

    assert result.selected_model in {
        "simple_moving_average",
        "weighted_moving_average",
        "simple_exponential_smoothing",
    }


def test_every_candidate_is_scored_on_the_same_held_out_periods(inventory_config):
    values = [float(200 + (index % 7) * 13) for index in range(30)]
    result = select_model(values, inventory_config, season_length=12)

    evaluated = [item for item in result.evaluations if item.evaluated]
    assert len(evaluated) >= 2
    # Comparing RMSE across different holdout windows would make the winner an
    # artefact of the split rather than a measurement.
    assert len({item.folds for item in evaluated}) == 1
    assert len({item.holdout_periods for item in evaluated}) == 1


def test_a_more_complex_model_must_beat_the_simpler_one_by_the_margin(inventory_config):
    values = [300.0 + ((index * 53) % 17) - 8 for index in range(30)]
    result = select_model(values, inventory_config, season_length=12)

    winner = next(item for item in result.evaluations if item.selected)
    from app.modules.inventory.thresholds import MODEL_COMPLEXITY

    better_but_complex = [
        item
        for item in result.evaluations
        if item.score is not None
        and winner.score is not None
        and item.score < winner.score
        and MODEL_COMPLEXITY[item.model] > MODEL_COMPLEXITY[winner.model]
    ]
    for candidate in better_but_complex:
        # It scored better, but not by enough to justify its extra parameters.
        margin = inventory_config.selection.complexity_margin_pct / 100.0
        assert candidate.score >= winner.score * (1 - margin)


def test_intermittent_demand_rules_out_trend_and_seasonal_models(inventory_config):
    values = [0.0, 0.0, 40.0, 0.0, 0.0, 0.0, 55.0, 0.0] * 4
    profile = profile_demand(values, inventory_config, season_length=12)

    assert profile.is_intermittent is True
    assert profile.pattern in {"intermittent", "lumpy"}

    result = select_model(values, inventory_config, season_length=12)
    for name in ("holt_linear_trend", "holt_winters_seasonal"):
        candidate = next(item for item in result.evaluations if item.model == name)
        assert candidate.eligible is False
        assert "zeros" in candidate.ineligible_reason
    assert result.selected_model in inventory_config.intermittent.allowed_models


def test_a_requested_model_that_cannot_be_used_falls_back_and_says_so(inventory_config):
    values = [100.0, 105.0, 98.0, 102.0, 99.0, 101.0]  # far too short for seasonal
    result = select_model(
        values, inventory_config, season_length=12, requested_model="holt_winters_seasonal"
    )

    assert result.selected_model != "holt_winters_seasonal"
    assert any("requested model" in note.lower() for note in result.notes)


def test_a_requested_model_that_can_be_used_is_honoured(inventory_config):
    values = [float(200 + index * 4) for index in range(24)]
    result = select_model(
        values, inventory_config, season_length=12, requested_model="simple_moving_average"
    )

    assert result.selected_model == "simple_moving_average"
    assert result.selection_basis == "requested"


def test_too_little_history_to_backtest_falls_back_to_the_configured_model(inventory_config):
    values = [100.0, 110.0, 105.0, 108.0]
    result = select_model(values, inventory_config, season_length=12)

    assert result.selection_basis == "fallback"
    assert result.selected_model == inventory_config.selection.fallback_model
    assert any("not enough history" in note for note in result.notes)
