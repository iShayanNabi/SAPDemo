"""Unit tests for the Inventory Predictor's planning layer.

The forecast says what will be demanded; these tests cover what is done about
it - the projected stock path, the shortage date, the reorder point, the safety
stock, the order quantity and the stock classification.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

from app.core.exceptions import ConfigurationError, ValidationError
from app.modules.inventory.engine import run_forecast
from app.modules.inventory.field_definitions import REGISTRY
from app.modules.inventory.normalizer import (
    build_series,
    normalize_inventory_dataframe,
)
from app.modules.inventory.projection import build_forecast_points, project_inventory
from app.modules.inventory.thresholds import load_inventory_config
from app.services.tabular.mapping import suggest_mapping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_rows(
    demands: list[float],
    *,
    material: str = "M1",
    plant: str = "1000",
    ending: list[float] | None = None,
    lead_time: int | None = 30,
    reorder_point: float | None = None,
    safety_stock: float | None = None,
    open_po: tuple[float, str] | None = None,
    start: date = date(2024, 1, 1),
    skip: tuple[int, ...] = (),
) -> pd.DataFrame:
    """Build a raw inventory frame the loader can read, in canonical columns."""
    rows = []
    stock = ending[0] if ending else 1000.0
    for index, demand in enumerate(demands):
        if index in skip:
            continue
        month = date(
            start.year + (start.month - 1 + index) // 12,
            (start.month - 1 + index) % 12 + 1,
            1,
        )
        closing = ending[index] if ending else max(0.0, stock - demand + demand)
        row = {
            "material": material,
            "plant": plant,
            "period_date": month.isoformat(),
            "demand": demand,
            "starting_inventory": None,
            "ending_inventory": closing,
            "receipts": None,
            "issues": demand,
            "lead_time_days": lead_time,
            "reorder_point": reorder_point,
            "safety_stock": safety_stock,
            "supplier_id": "V1",
            "open_po_quantity": None,
            "po_expected_date": None,
        }
        if open_po and index == len(demands) - 1:
            row["open_po_quantity"] = open_po[0]
            row["po_expected_date"] = open_po[1]
        rows.append(row)
    return pd.DataFrame(rows)


def load(frame: pd.DataFrame, config, as_of: date | None = None):
    """Run a frame through the real mapper and normaliser."""
    mapping = suggest_mapping([str(column) for column in frame.columns], REGISTRY)
    dataset = normalize_inventory_dataframe(frame, mapping.mapping, config)
    return dataset, build_series(dataset.records, config, as_of=as_of)


# ---------------------------------------------------------------------------
# Stock projection and shortage date
# ---------------------------------------------------------------------------


def test_shortage_date_is_a_real_day_inside_the_period(inventory_config):
    # 300 a month against 150 on hand: the stock runs out halfway through July.
    frame = build_rows([300.0] * 12, ending=[150.0] * 12)
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    result = run_forecast(
        series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=3
    )
    item = result.items[0]

    shortage = item.projection.predicted_shortage_date
    assert shortage is not None
    # Consuming ~9.7 a day from 150 units runs out on about the 16th.
    assert shortage.month == 1
    assert 13 <= shortage.day <= 19
    assert item.projection.days_to_shortage is not None
    assert item.projection.shortage_within_horizon is True


def test_no_shortage_is_reported_when_stock_covers_the_horizon(inventory_config):
    frame = build_rows([100.0] * 12, ending=[9000.0] * 12)
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    assert item.projection.predicted_shortage_date is None
    assert item.projection.ending_projected_inventory > 0


def test_an_open_purchase_order_pushes_the_shortage_out(inventory_config):
    without = build_rows([300.0] * 12, ending=[400.0] * 12)
    with_order = build_rows(
        [300.0] * 12, ending=[400.0] * 12, open_po=(2000.0, "2025-02-10")
    )

    _d1, series_without = load(without, inventory_config, as_of=date(2025, 1, 1))
    _d2, series_with = load(with_order, inventory_config, as_of=date(2025, 1, 1))

    plain = run_forecast(
        series_without, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]
    supplied = run_forecast(
        series_with, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    assert plain.projection.predicted_shortage_date is not None
    assert supplied.projection.scheduled_receipt_total == pytest.approx(2000.0)
    assert (
        supplied.projection.predicted_shortage_date is None
        or supplied.projection.predicted_shortage_date
        > plain.projection.predicted_shortage_date
    )


def test_an_open_order_expected_too_late_is_flagged_for_expediting(inventory_config):
    frame = build_rows([300.0] * 12, ending=[150.0] * 12, open_po=(3000.0, "2025-06-01"))
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    assert item.projection.predicted_shortage_date is not None
    # The quantity on order keeps the inventory position above the reorder
    # point, so no new order is triggered - the existing one is simply late.
    assert item.projection.reorder.expedite_recommended is True
    assert "expected" in item.projection.reorder.expedite_reason


def test_an_open_quantity_with_no_expected_date_is_reported_not_placed(inventory_config):
    frame = build_rows([300.0] * 12, ending=[150.0] * 12)
    frame.loc[frame.index[-1], "open_po_quantity"] = 5000.0
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    assert item.projection.unscheduled_open_quantity == pytest.approx(5000.0)
    assert item.projection.scheduled_receipt_total == 0.0
    # It never silently rescues the projection.
    assert item.projection.predicted_shortage_date is not None
    assert any(w.code == "unscheduled_open_quantity" for w in item.warnings)


def test_a_repeated_open_quantity_is_counted_once_not_summed(inventory_config):
    # The other common extract shape: the same open PO restated on every row.
    frame = build_rows([300.0] * 12, ending=[400.0] * 12)
    frame["open_po_quantity"] = 500.0
    frame["po_expected_date"] = "2025-02-10"
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))

    assert series[0].open_po_quantity_total == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Safety stock and reorder point
# ---------------------------------------------------------------------------


def test_safety_stock_follows_the_documented_formula(inventory_config):
    frame = build_rows([300.0, 320.0, 280.0, 310.0, 290.0, 305.0] * 2, ending=[2000.0] * 12)
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    reorder = item.projection.reorder
    z_score = inventory_config.reorder.z_for()
    sigma = reorder.demand_sigma_per_period
    lead_time_periods = reorder.lead_time_days / series[0].grid.days

    expected = z_score * sigma * math.sqrt(lead_time_periods)
    assert reorder.recommended_safety_stock == pytest.approx(expected, abs=0.02)
    assert reorder.service_level_z == pytest.approx(z_score)


def test_reorder_point_is_lead_time_demand_plus_safety_stock(inventory_config):
    frame = build_rows([300.0] * 12, ending=[2000.0] * 12)
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    reorder = item.projection.reorder
    assert reorder.calculated_reorder_point == pytest.approx(
        reorder.expected_lead_time_demand + reorder.recommended_safety_stock, abs=0.02
    )
    # 30 days of lead time at ~300 a month is about one period of demand.
    assert reorder.expected_lead_time_demand == pytest.approx(300.0, rel=0.15)


def test_a_longer_lead_time_raises_both_the_reorder_point_and_the_safety_stock(
    inventory_config,
):
    demands = [300.0, 340.0, 260.0, 320.0, 280.0, 310.0] * 2
    short = build_rows(demands, ending=[2000.0] * 12, lead_time=7)
    long = build_rows(demands, ending=[2000.0] * 12, lead_time=90)

    _d1, series_short = load(short, inventory_config, as_of=date(2025, 1, 1))
    _d2, series_long = load(long, inventory_config, as_of=date(2025, 1, 1))

    quick = run_forecast(
        series_short, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]
    slow = run_forecast(
        series_long, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    assert (
        slow.projection.reorder.recommended_safety_stock
        > quick.projection.reorder.recommended_safety_stock
    )
    assert (
        slow.projection.reorder.calculated_reorder_point
        > quick.projection.reorder.calculated_reorder_point
    )


def test_a_missing_lead_time_uses_the_configured_default_and_warns(inventory_config):
    frame = build_rows([300.0] * 12, ending=[2000.0] * 12, lead_time=None)
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    assert item.projection.reorder.lead_time_days == (
        inventory_config.reorder.default_lead_time_days
    )
    assert item.projection.reorder.lead_time_source != "file"
    assert any(warning.code == "no_lead_time" for warning in item.warnings)


def test_reorder_quantity_covers_the_lead_time_plus_the_review_period(inventory_config):
    frame = build_rows([300.0] * 12, ending=[400.0] * 12)
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    reorder = item.projection.reorder
    assert reorder.recommended_reorder_date is not None
    assert reorder.recommended_reorder_quantity > 0
    # Order-up-to level minus the position at the trigger.
    assert reorder.recommended_reorder_quantity == pytest.approx(
        reorder.target_stock_level - reorder.inventory_position_at_reorder, abs=1.0
    )
    assert reorder.rationale


def test_the_reorder_date_leaves_enough_time_for_a_seasonal_material(inventory_config):
    """The trigger must use the demand expected *from the reorder date*.

    Found by driving the real API: a material whose demand peaks in November had
    its reorder point calculated from July's quiet demand, so the order was
    recommended for a date that left less than the lead time before the shortage
    the same engine had predicted. The recommendation contradicted itself.
    """
    # Quiet for half the year, then a sharp peak.
    season = [100.0, 100.0, 110.0, 105.0, 100.0, 110.0, 400.0, 420.0, 430.0, 410.0, 120.0, 105.0]
    # Stocked so the reorder point is genuinely reached inside the horizon.
    frame = build_rows(season * 3, ending=[900.0] * 36, lead_time=30)
    _dataset, series = load(frame, inventory_config, as_of=date(2027, 1, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2027, 1, 1), horizon_periods=12
    ).items[0]

    reorder = item.projection.reorder
    shortage = item.projection.predicted_shortage_date
    if shortage is not None and reorder.recommended_reorder_date is not None:
        lead_time_available = (shortage - reorder.recommended_reorder_date).days
        assert lead_time_available >= reorder.lead_time_days, (
            "the recommended order cannot arrive before the shortage it is meant to prevent"
        )
    # The forward-looking trigger is reported next to the static policy figure.
    assert reorder.reorder_point_at_trigger is not None
    assert reorder.calculated_reorder_point is not None


def test_no_order_is_recommended_when_stock_stays_above_the_reorder_point(inventory_config):
    frame = build_rows([100.0] * 12, ending=[50000.0] * 12)
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    assert item.projection.reorder.order_urgency == "not_required"
    assert item.projection.reorder.recommended_reorder_quantity == 0.0


def test_the_master_safety_stock_is_compared_against_the_recommendation(inventory_config):
    frame = build_rows(
        [300.0, 320.0, 280.0] * 4, ending=[2000.0] * 12, safety_stock=25.0, reorder_point=90.0
    )
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    reorder = item.projection.reorder
    assert reorder.master_safety_stock == pytest.approx(25.0)
    assert reorder.master_reorder_point == pytest.approx(90.0)
    assert reorder.safety_stock_gap == pytest.approx(
        reorder.recommended_safety_stock - 25.0, abs=0.02
    )
    assert reorder.reorder_point_gap == pytest.approx(
        reorder.calculated_reorder_point - 90.0, abs=0.02
    )


# ---------------------------------------------------------------------------
# Confidence intervals
# ---------------------------------------------------------------------------


def test_the_confidence_interval_brackets_the_forecast_and_widens_with_the_level(
    inventory_config,
):
    demands = [300.0, 340.0, 260.0, 320.0, 280.0, 310.0] * 3
    frame = build_rows(demands, ending=[5000.0] * 18)
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 7, 1))

    narrow = run_forecast(
        series,
        inventory_config,
        as_of=date(2025, 7, 1),
        horizon_periods=4,
        confidence_level=0.8,
    ).items[0]
    wide = run_forecast(
        series,
        inventory_config,
        as_of=date(2025, 7, 1),
        horizon_periods=4,
        confidence_level=0.99,
    ).items[0]

    for point in narrow.forecast_points:
        assert point.lower <= point.demand <= point.upper

    narrow_width = narrow.forecast_points[0].upper - narrow.forecast_points[0].lower
    wide_width = wide.forecast_points[0].upper - wide.forecast_points[0].lower
    assert wide_width > narrow_width


def test_an_unconfigured_confidence_level_is_refused_rather_than_guessed(inventory_config):
    with pytest.raises(ConfigurationError):
        inventory_config.forecast.z_for(0.87)


def test_the_interval_lower_bound_is_never_negative(inventory_config):
    # A small, volatile demand would otherwise produce a negative lower bound.
    demands = [5.0, 40.0, 2.0, 60.0, 8.0, 35.0] * 3
    frame = build_rows(demands, ending=[500.0] * 18)
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 7, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2025, 7, 1), horizon_periods=6
    ).items[0]

    assert all(point.lower >= 0 for point in item.forecast_points)
    assert all(point.demand >= 0 for point in item.forecast_points)


# ---------------------------------------------------------------------------
# Stock classification
# ---------------------------------------------------------------------------


def test_overstock_is_flagged_and_the_excess_quantified(inventory_config):
    frame = build_rows([30.0] * 12, ending=[20000.0] * 12)
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    health = item.projection.health
    assert health.overstock_risk == "high"
    assert health.days_of_cover > inventory_config.stock_health.overstock_days_of_cover
    assert health.overstock_excess_quantity > 0
    assert health.classification_basis


def test_dead_stock_needs_both_no_demand_and_stock_on_hand(inventory_config):
    dead = build_rows([50.0] * 12 + [0.0] * 14, ending=[900.0] * 26)
    consumed = build_rows([50.0] * 12 + [0.0] * 14, ending=[0.0] * 26)

    _d1, series_dead = load(dead, inventory_config, as_of=date(2026, 3, 1))
    _d2, series_consumed = load(consumed, inventory_config, as_of=date(2026, 3, 1))

    stuck = run_forecast(
        series_dead, inventory_config, as_of=date(2026, 3, 1), horizon_periods=6
    ).items[0]
    empty = run_forecast(
        series_consumed, inventory_config, as_of=date(2026, 3, 1), horizon_periods=6
    ).items[0]

    assert stuck.projection.health.is_dead_stock is True
    assert stuck.projection.health.trailing_zero_demand_periods >= 12
    # No stock left is not dead stock - there is nothing sitting on the shelf.
    assert empty.projection.health.is_dead_stock is False


def test_slow_moving_is_driven_by_turnover(inventory_config):
    slow = build_rows([10.0] * 24, ending=[3000.0] * 24)
    fast = build_rows([500.0] * 24, ending=[300.0] * 24)

    _d1, series_slow = load(slow, inventory_config, as_of=date(2026, 1, 1))
    _d2, series_fast = load(fast, inventory_config, as_of=date(2026, 1, 1))

    crawling = run_forecast(
        series_slow, inventory_config, as_of=date(2026, 1, 1), horizon_periods=6
    ).items[0]
    moving = run_forecast(
        series_fast, inventory_config, as_of=date(2026, 1, 1), horizon_periods=6
    ).items[0]

    assert crawling.projection.health.is_slow_moving is True
    assert crawling.projection.health.movement_class in {"slow_moving", "very_slow_moving"}
    assert moving.projection.health.movement_class == "fast_moving"
    assert moving.projection.health.is_slow_moving is False


# ---------------------------------------------------------------------------
# Missing periods and insufficient data
# ---------------------------------------------------------------------------


def test_missing_periods_are_detected_filled_and_reported(inventory_config):
    frame = build_rows([200.0] * 24, ending=[3000.0] * 24, skip=(5, 6, 17))
    dataset, series = load(frame, inventory_config, as_of=date(2026, 1, 1))

    assert len(dataset.records) == 21
    # The gaps are filled so the periods either side keep their real positions.
    assert series[0].observation_count == 24
    assert series[0].observed_period_count == 21
    assert series[0].missing_period_indexes == [5, 6, 17]

    item = run_forecast(
        series, inventory_config, as_of=date(2026, 1, 1), horizon_periods=6
    ).items[0]
    assert item.missing_period_count == 3
    warning = next(w for w in item.warnings if w.code == "missing_periods")
    assert "2024-06-01" in warning.message


def test_a_gap_does_not_shift_the_periods_after_it(inventory_config):
    without_gap = build_rows([100.0] * 12, ending=[1000.0] * 12)
    with_gap = build_rows([100.0] * 12, ending=[1000.0] * 12, skip=(3,))

    _d1, plain = load(without_gap, inventory_config)
    _d2, gapped = load(with_gap, inventory_config)

    # The last period must still be December, not November.
    assert plain[0].last_period_date == gapped[0].last_period_date == date(2024, 12, 1)


def test_too_little_history_is_reported_not_forecast(inventory_config):
    frame = build_rows([100.0, 120.0], ending=[500.0, 480.0])
    _dataset, series = load(frame, inventory_config, as_of=date(2024, 3, 1))
    result = run_forecast(series, inventory_config, as_of=date(2024, 3, 1))
    item = result.items[0]

    assert item.status == "insufficient_data"
    assert item.model is None
    assert item.forecast_points == []
    # It is reported rather than dropped: a planner must see it exists.
    assert result.series_count == 1
    assert result.insufficient_data_count == 1
    assert item.projection.available is False
    assert any(w.code == "insufficient_history" for w in item.warnings)


def test_a_series_with_no_ending_inventory_still_forecasts_demand(inventory_config):
    frame = build_rows([200.0] * 12)
    frame["ending_inventory"] = None
    _dataset, series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    item = run_forecast(
        series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    assert item.status == "forecast"
    assert item.forecast_points
    assert item.projection.available is False
    assert "ending inventory" in item.projection.unavailable_reason
    # No shortage date or order quantity is invented out of nothing.
    assert item.projection.predicted_shortage_date is None
    assert item.projection.reorder.recommended_reorder_quantity is None


# ---------------------------------------------------------------------------
# Data quality and isolation
# ---------------------------------------------------------------------------


def test_a_period_that_does_not_balance_is_reported(inventory_config):
    frame = build_rows([100.0] * 12, ending=[500.0] * 12)
    frame["starting_inventory"] = 500.0
    frame["receipts"] = 100.0
    frame.loc[frame.index[4], "ending_inventory"] = 999.0

    dataset, _series = load(frame, inventory_config)
    issue_types = {issue.issue_type for issue in dataset.issues}
    assert "balance_mismatch" in issue_types


def test_demand_that_exceeds_what_was_issued_is_reported(inventory_config):
    frame = build_rows([100.0] * 12, ending=[500.0] * 12)
    frame.loc[frame.index[3], "issues"] = 20.0

    dataset, _series = load(frame, inventory_config)
    assert "unfilled_demand" in {issue.issue_type for issue in dataset.issues}


def test_duplicate_periods_are_added_together_and_reported(inventory_config):
    frame = build_rows([100.0] * 12, ending=[500.0] * 12)
    duplicate = frame.iloc[[2]].copy()
    frame = pd.concat([frame, duplicate], ignore_index=True)

    _dataset, series = load(frame, inventory_config)
    assert series[0].duplicate_period_count == 1
    assert series[0].periods[2].demand == pytest.approx(200.0)

    item = run_forecast(series, inventory_config, horizon_periods=3).items[0]
    assert any(warning.code == "duplicate_periods" for warning in item.warnings)


def test_one_broken_series_does_not_stop_the_others(inventory_config, monkeypatch):
    good = build_rows([200.0] * 12, material="GOOD", ending=[2000.0] * 12)
    bad = build_rows([200.0] * 12, material="BAD", ending=[2000.0] * 12)
    _dataset, series = load(pd.concat([good, bad], ignore_index=True), inventory_config)

    from app.modules.inventory import engine as engine_module

    original = engine_module.select_model

    def explode(values, config, season_length, **kwargs):
        # Fail only for the second series, by length of its own demand list.
        if kwargs.get("observed") is not None and values and values[0] == 200.0:
            explode.calls += 1
            if explode.calls == 2:
                raise RuntimeError("deliberate failure")
        return original(values, config, season_length, **kwargs)

    explode.calls = 0
    monkeypatch.setattr(engine_module, "select_model", explode)

    result = run_forecast(series, inventory_config, horizon_periods=3)

    assert len(result.series_errors) == 1
    assert result.series_errors[0]["error_type"] == "RuntimeError"
    # The surviving series still produced a full result.
    assert len(result.items) == 1
    assert result.items[0].status == "forecast"


def test_a_file_with_no_usable_row_is_refused_clearly(inventory_config):
    frame = pd.DataFrame(
        [{"material": None, "plant": None, "period_date": None, "demand": 5.0}]
    )
    mapping = suggest_mapping([str(column) for column in frame.columns], REGISTRY)
    with pytest.raises(ValidationError):
        normalize_inventory_dataframe(frame, mapping.mapping, inventory_config)


# ---------------------------------------------------------------------------
# Configuration drives the behaviour
# ---------------------------------------------------------------------------


def test_changing_the_service_level_in_json_changes_the_safety_stock(tmp_path, inventory_config):
    """Proof the thresholds are configuration, not code."""
    import json

    from app.modules.inventory.thresholds import DEFAULT_CONFIG_PATH

    raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["reorder"]["service_level"] = 0.99
    edited_path = tmp_path / "inventory_rules.json"
    edited_path.write_text(json.dumps(raw), encoding="utf-8")
    edited = load_inventory_config(edited_path)

    demands = [300.0, 340.0, 260.0, 320.0, 280.0, 310.0] * 2
    frame = build_rows(demands, ending=[2000.0] * 12)

    _d1, base_series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    _d2, edited_series = load(frame, edited, as_of=date(2025, 1, 1))

    base = run_forecast(
        base_series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]
    stricter = run_forecast(
        edited_series, edited, as_of=date(2025, 1, 1), horizon_periods=6
    ).items[0]

    assert (
        stricter.projection.reorder.recommended_safety_stock
        > base.projection.reorder.recommended_safety_stock
    )
    assert stricter.projection.reorder.service_level == 0.99


def test_changing_the_overstock_threshold_in_json_changes_the_classification(
    tmp_path, inventory_config
):
    import json

    from app.modules.inventory.thresholds import DEFAULT_CONFIG_PATH

    raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["stock_health"]["overstock_days_of_cover"] = 10.0
    raw["stock_health"]["critical_overstock_days_of_cover"] = 20.0
    edited_path = tmp_path / "inventory_rules.json"
    edited_path.write_text(json.dumps(raw), encoding="utf-8")
    edited = load_inventory_config(edited_path)

    frame = build_rows([100.0] * 12, ending=[300.0] * 12)
    _d1, base_series = load(frame, inventory_config, as_of=date(2025, 1, 1))
    _d2, edited_series = load(frame, edited, as_of=date(2025, 1, 1))

    base = run_forecast(
        base_series, inventory_config, as_of=date(2025, 1, 1), horizon_periods=3
    ).items[0]
    strict = run_forecast(
        edited_series, edited, as_of=date(2025, 1, 1), horizon_periods=3
    ).items[0]

    assert base.projection.health.overstock_risk == "none"
    assert strict.projection.health.overstock_risk != "none"


def test_a_configuration_with_an_unknown_model_is_refused(tmp_path):
    import json

    from app.modules.inventory.thresholds import DEFAULT_CONFIG_PATH

    raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["models"]["neural_net"] = {"label": "Not a real method", "enabled": True}
    path = tmp_path / "inventory_rules.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ConfigurationError):
        load_inventory_config(path)
