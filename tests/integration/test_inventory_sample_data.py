"""Integration tests for the bundled inventory sample data.

These read ``inventory_scenario_manifest.json`` and assert that every documented
anchor actually behaves the way the manifest says it does, through the real
reader, mapper, normaliser and engine - the same path the API takes.

The point of driving the assertions from the manifest is that the documentation
and the tests cannot drift apart: adding a scenario to the manifest without
making it true fails the suite.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.inventory.engine import run_forecast
from app.modules.inventory.field_definitions import REGISTRY
from app.modules.inventory.normalizer import build_series, normalize_inventory_dataframe
from app.services.files.readers import read_tabular
from app.services.tabular.mapping import suggest_mapping


@pytest.fixture(scope="module")
def loaded(inventory_sample_csv_path, inventory_scenario_manifest):
    """The demo history, loaded and forecast exactly as the API would."""
    from app.modules.inventory.thresholds import get_inventory_config

    config = get_inventory_config()
    as_of = date.fromisoformat(inventory_scenario_manifest["as_of_date"])
    horizon = inventory_scenario_manifest["baseline_horizon_periods"]

    read_result = read_tabular(inventory_sample_csv_path.read_bytes(), ".csv")
    mapping = suggest_mapping(read_result.source_columns, REGISTRY)
    dataset = normalize_inventory_dataframe(read_result.dataframe, mapping.mapping, config)
    series = build_series(dataset.records, config, as_of=as_of)
    result = run_forecast(series, config, as_of=as_of, horizon_periods=horizon)
    return dataset, series, result


def _item(result, material: str, plant: str):
    for item in result.items:
        if item.material == material and item.plant == plant:
            return item
    raise AssertionError(f"{material} @ {plant} is not in the forecast run")


# ---------------------------------------------------------------------------
# The dataset itself
# ---------------------------------------------------------------------------


def test_the_file_matches_what_the_manifest_claims(loaded, inventory_scenario_manifest):
    dataset, series, _result = loaded

    assert dataset.record_count == inventory_scenario_manifest["row_count"]
    assert len(series) == inventory_scenario_manifest["series_count"]
    assert {item.frequency for item in series} == {"monthly"}


def test_every_series_has_at_least_two_years_of_history(loaded):
    _dataset, series, _result = loaded

    # Anything shorter and the seasonal anchor could not exist. The deliberate
    # short-history anchor is the documented exception.
    long_enough = [item for item in series if item.observation_count >= 24]
    assert len(long_enough) == len(series) - 1


def test_the_run_completes_without_a_single_series_failing(loaded):
    _dataset, _series, result = loaded

    assert result.series_errors == []
    assert result.forecast_count + result.insufficient_data_count == result.series_count


# ---------------------------------------------------------------------------
# The documented anchors
# ---------------------------------------------------------------------------


def test_every_documented_scenario_holds(loaded, inventory_scenario_manifest):
    """Walk the manifest and assert each anchor's documented expectation."""
    dataset, series, result = loaded

    for scenario in inventory_scenario_manifest["scenarios"]:
        material = scenario["material"]
        plant = scenario["plant"]
        expected = scenario["assert"]
        item = _item(result, material, plant)
        context = f"{scenario['scenario_id']} ({material} @ {plant})"

        if "status" in expected:
            assert item.status == expected["status"], context
        if "model" in expected:
            assert item.model == expected["model"], f"{context}: model is {item.model}"
        if "model_in" in expected:
            assert item.model in expected["model_in"], f"{context}: model is {item.model}"
        if "model_not" in expected:
            assert item.model != expected["model_not"], context
        if expected.get("forecast_rising"):
            demands = [point.demand for point in item.forecast_points]
            assert demands[-1] > demands[0], context
        if "is_intermittent" in expected:
            assert item.selection is not None, context
            assert item.selection.profile.is_intermittent == expected["is_intermittent"], context
        if expected.get("seasonal_model_ineligible"):
            seasonal = next(
                candidate
                for candidate in item.selection.evaluations
                if candidate.model == "holt_winters_seasonal"
            )
            assert seasonal.eligible is False, context
            assert seasonal.ineligible_reason, context
        if "has_shortage" in expected:
            has_shortage = item.projection.predicted_shortage_date is not None
            assert has_shortage == expected["has_shortage"], context
        if expected.get("shortage_within_horizon"):
            assert item.projection.shortage_within_horizon is True, context
        if "order_urgency" in expected:
            assert item.projection.reorder.order_urgency == expected["order_urgency"], context
        if "overstock_risk" in expected:
            assert item.projection.health.overstock_risk == expected["overstock_risk"], context
        if expected.get("has_excess_quantity"):
            assert item.projection.health.overstock_excess_quantity, context
        if "is_slow_moving" in expected:
            assert item.projection.health.is_slow_moving == expected["is_slow_moving"], context
        if "is_dead_stock" in expected:
            assert item.projection.health.is_dead_stock == expected["is_dead_stock"], context
        if "min_trailing_zero_periods" in expected:
            assert (
                item.projection.health.trailing_zero_demand_periods
                >= expected["min_trailing_zero_periods"]
            ), context
        if "missing_period_count" in expected:
            assert item.missing_period_count == expected["missing_period_count"], context
        if "warning_code" in expected:
            codes = {warning.code for warning in item.warnings}
            assert expected["warning_code"] in codes, f"{context}: warnings are {codes}"
        if "expedite_recommended" in expected:
            assert (
                item.projection.reorder.expedite_recommended
                == expected["expedite_recommended"]
            ), context
        if "projection_available" in expected:
            assert item.projection.available == expected["projection_available"], context
        if "file_issue_type" in expected:
            issue_types = {issue.issue_type for issue in dataset.issues}
            assert expected["file_issue_type"] in issue_types, context
        if expected.get("separate_series"):
            same_material = [entry for entry in series if entry.material == material]
            assert len(same_material) >= 2, context
            assert len({entry.plant for entry in same_material}) >= 2, context


def test_the_seasonal_anchor_forecast_repeats_its_shape(loaded):
    _dataset, _series, result = loaded
    item = _item(result, "100001", "1000")

    assert item.model == "holt_winters_seasonal"
    demands = [point.demand for point in item.forecast_points]
    # The season peaks in November: a six-period forecast from July must rise.
    assert max(demands) > min(demands) * 1.2
    assert item.model_parameters["season_length"] == 12


def test_the_shortage_anchor_reports_a_real_date_and_a_quantity(loaded):
    _dataset, _series, result = loaded
    item = _item(result, "100005", "1000")

    shortage = item.projection.predicted_shortage_date
    assert shortage is not None
    assert shortage.year == 2026
    assert item.projection.days_to_shortage is not None
    assert item.projection.reorder.recommended_reorder_quantity > 0
    assert item.projection.reorder.calculated_reorder_point > 0


def test_the_intermittent_anchor_cannot_report_mape(loaded):
    _dataset, _series, result = loaded
    item = _item(result, "100004", "1000")

    accuracy = item.accuracy_headline()
    assert accuracy is not None
    assert accuracy.mape is None
    assert accuracy.mape_available is False
    assert accuracy.zero_demand_periods > 0
    # The safe alternative is always there.
    assert accuracy.smape is not None


def test_the_insufficient_data_anchor_is_reported_not_dropped(loaded):
    _dataset, _series, result = loaded
    item = _item(result, "100010", "2000")

    assert item.status == "insufficient_data"
    assert item.history  # its history is still returned
    assert item.forecast_points == []
    assert item.projection.reorder.recommended_reorder_quantity is None


# ---------------------------------------------------------------------------
# Reproducibility and the recorded baseline
# ---------------------------------------------------------------------------


def test_the_run_reproduces_the_recorded_baseline(loaded, inventory_baseline):
    _dataset, _series, result = loaded
    summary = result.summary_payload()
    expected = inventory_baseline["summary"]

    for key in (
        "series_count",
        "forecast_count",
        "insufficient_data_count",
        "shortage_count",
        "reorder_now_count",
        "overstock_count",
        "slow_moving_count",
        "dead_stock_count",
    ):
        assert summary[key] == expected[key], key

    assert summary["model_usage"] == expected["model_usage"]
    assert summary["total_forecast_demand"] == pytest.approx(
        expected["total_forecast_demand"]
    )


def test_every_series_reproduces_its_recorded_result(loaded, inventory_baseline):
    _dataset, _series, result = loaded
    recorded = {
        (entry["material"], entry["plant"]): entry for entry in inventory_baseline["series"]
    }

    assert len(recorded) == len(result.items)
    for item in result.items:
        expected = recorded[(item.material, item.plant)]
        key = f"{item.material}@{item.plant}"
        assert item.status == expected["status"], key
        assert item.model == expected["model"], key
        assert item.movement_class == expected["movement_class"], key
        assert item.is_dead_stock == expected["is_dead_stock"], key
        assert item.overstock_risk == expected["overstock_risk"], key
        shortage = (
            item.predicted_shortage_date.isoformat()
            if item.predicted_shortage_date
            else None
        )
        assert shortage == expected["predicted_shortage_date"], key
        if expected["total_forecast_demand"] is not None:
            assert item.total_forecast_demand == pytest.approx(
                expected["total_forecast_demand"]
            ), key


def test_forecasting_the_same_file_twice_gives_the_same_answer(
    inventory_sample_csv_path, inventory_scenario_manifest
):
    """No randomness, no dictionary-ordering luck, no wall-clock dependency."""
    from app.modules.inventory.thresholds import get_inventory_config

    config = get_inventory_config()
    as_of = date.fromisoformat(inventory_scenario_manifest["as_of_date"])

    def run_once():
        read_result = read_tabular(inventory_sample_csv_path.read_bytes(), ".csv")
        mapping = suggest_mapping(read_result.source_columns, REGISTRY)
        dataset = normalize_inventory_dataframe(read_result.dataframe, mapping.mapping, config)
        series = build_series(dataset.records, config, as_of=as_of)
        return run_forecast(series, config, as_of=as_of, horizon_periods=6)

    first, second = run_once(), run_once()

    assert first.summary_payload() == second.summary_payload()
    assert [item.to_dict() for item in first.items] == [
        item.to_dict() for item in second.items
    ]


def test_the_three_file_formats_produce_the_same_forecast(
    inventory_sample_csv_path,
    inventory_sample_xlsx_path,
    inventory_sample_json_path,
    inventory_scenario_manifest,
):
    """CSV carries SAP headers, XLSX business labels, JSON canonical names -
    and all three must map onto the same contract and give the same answer."""
    from app.modules.inventory.thresholds import get_inventory_config

    config = get_inventory_config()
    as_of = date.fromisoformat(inventory_scenario_manifest["as_of_date"])

    summaries = []
    for path, extension in (
        (inventory_sample_csv_path, ".csv"),
        (inventory_sample_xlsx_path, ".xlsx"),
        (inventory_sample_json_path, ".json"),
    ):
        read_result = read_tabular(path.read_bytes(), extension)
        mapping = suggest_mapping(read_result.source_columns, REGISTRY)
        assert not mapping.missing_required_fields, path.name
        dataset = normalize_inventory_dataframe(read_result.dataframe, mapping.mapping, config)
        series = build_series(dataset.records, config, as_of=as_of)
        result = run_forecast(series, config, as_of=as_of, horizon_periods=6)
        summaries.append(result.summary_payload())

    assert summaries[0] == summaries[1] == summaries[2]
