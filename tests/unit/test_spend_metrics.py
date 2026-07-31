"""Unit tests for spend classification, filtering, metrics and analytics.

Every calculation the dashboard shows is exercised here against small datasets
where the expected answer can be worked out by hand.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.modules.spend.analytics import (
    build_analytics,
    contract_leakage,
    maverick_spend_breakdown,
    monthly_spend,
    purchase_price_variance,
    supplier_concentration,
    tail_spend_suppliers,
    top_materials,
)
from app.modules.spend.filters import (
    SpendFilter,
    apply_filter,
    available_filter_values,
    date_bounds,
)
from app.modules.spend.metrics import (
    calculate_metrics,
    calculate_price_variance,
    calculate_supplier_spend,
    concentration_level,
    herfindahl_index,
    methodology,
    purchase_order_totals,
    spend_by_currency,
)
from app.modules.spend.normalizer import classify_contract_status, classify_preferred_supplier
from tests.factories import SPEND_BASE_DATE, make_spend_frame, make_spend_row


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status", ["Contracted", "under contract", "YES", "framework"])
def test_contracted_status_values_are_recognised(spend_config, status):
    assert classify_contract_status(status, None, spend_config) is True


@pytest.mark.parametrize("status", ["Not contracted", "no contract", "spot", "FALSE"])
def test_non_contracted_status_values_are_recognised(spend_config, status):
    assert classify_contract_status(status, "4600001", spend_config) is False


def test_contract_status_falls_back_to_contract_number(spend_config):
    """A plain PO extract has no status column but does have a contract number."""
    assert classify_contract_status(None, "4600000123", spend_config) is True
    assert classify_contract_status(None, None, spend_config) is False


@pytest.mark.parametrize("status", ["Preferred", "strategic", "core", "partner"])
def test_preferred_status_values_are_recognised(spend_config, status):
    assert classify_preferred_supplier(status, spend_config) is True


@pytest.mark.parametrize("status", ["Non-preferred", "tail", "one-time", None, "", "unknown"])
def test_unknown_supplier_status_is_not_preferred(spend_config, status):
    """Assuming preferred status without evidence would understate maverick spend."""
    assert classify_preferred_supplier(status, spend_config) is False


def test_maverick_requires_both_conditions(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", contract_status="Not contracted",
                           preferred_supplier_status="Non-preferred"),
            make_spend_row(po_number="2", contract_status="Not contracted",
                           preferred_supplier_status="Preferred"),
            make_spend_row(po_number="3", contract_status="Contracted",
                           preferred_supplier_status="Non-preferred"),
            make_spend_row(po_number="4"),
        ],
        spend_config,
    )
    assert frame["is_maverick"].tolist() == [True, False, False, False]


def test_spend_under_management_covers_contracted_or_preferred(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", contract_status="Not contracted",
                           preferred_supplier_status="Non-preferred"),
            make_spend_row(po_number="2", contract_status="Not contracted",
                           preferred_supplier_status="Preferred"),
            make_spend_row(po_number="3", contract_status="Contracted",
                           preferred_supplier_status="Non-preferred"),
        ],
        spend_config,
    )
    assert frame["is_under_management"].tolist() == [False, True, True]


# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------
def test_spend_is_converted_to_base_currency(spend_config):
    frame = make_spend_frame(
        [make_spend_row(currency="USD", quantity=10, unit_price=100.0)], spend_config
    )
    expected = 1000.0 * spend_config.conversion_rate("USD")
    assert frame["spend_base"].iloc[0] == pytest.approx(expected)


def test_transaction_date_falls_back_to_order_date(spend_config):
    order_date = date(2025, 6, 4)
    frame = make_spend_frame(
        [make_spend_row(transaction_date=None, order_date=order_date)], spend_config
    )
    assert frame["effective_date"].iloc[0] == order_date
    assert frame["spend_month"].iloc[0] == "2025-06"


def test_total_value_is_derived_from_quantity_and_price(spend_config):
    frame = make_spend_frame(
        [make_spend_row(quantity=12, unit_price=25.0, total_value=None)], spend_config
    )
    assert frame["total_value"].iloc[0] == 300.0


def test_current_price_defaults_to_unit_price(spend_config):
    frame = make_spend_frame(
        [make_spend_row(unit_price=42.0, current_price=None)], spend_config
    )
    assert frame["current_price_base"].iloc[0] == pytest.approx(42.0)


def test_price_variance_columns(spend_config):
    frame = make_spend_frame(
        [make_spend_row(quantity=10, unit_price=120.0, current_price=120.0, baseline_price=100.0)],
        spend_config,
    )
    assert frame["price_variance_base"].iloc[0] == pytest.approx(200.0)
    assert frame["price_variance_pct"].iloc[0] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def test_total_spend_and_counts(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", po_item="00010", quantity=10, unit_price=100.0),
            make_spend_row(po_number="1", po_item="00020", quantity=5, unit_price=100.0),
            make_spend_row(po_number="2", supplier_id="0000200002", quantity=20, unit_price=50.0),
        ],
        spend_config,
    )
    metrics = calculate_metrics(frame, spend_config)

    assert metrics.total_spend == pytest.approx(2500.0)
    assert metrics.line_item_count == 3
    assert metrics.purchase_order_count == 2
    assert metrics.supplier_count == 2


def test_average_and_median_use_order_totals_not_line_totals(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", po_item="00010", quantity=10, unit_price=100.0),
            make_spend_row(po_number="1", po_item="00020", quantity=10, unit_price=100.0),
            make_spend_row(po_number="2", quantity=10, unit_price=100.0),
            make_spend_row(po_number="3", quantity=10, unit_price=100.0),
        ],
        spend_config,
    )
    totals = purchase_order_totals(frame)
    assert sorted(totals.tolist()) == [1000.0, 1000.0, 2000.0]

    metrics = calculate_metrics(frame, spend_config)
    assert metrics.average_po_value == pytest.approx(4000.0 / 3, rel=1e-3)
    assert metrics.median_po_value == pytest.approx(1000.0)


def test_contracted_versus_non_contracted_split(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", quantity=10, unit_price=100.0),
            make_spend_row(po_number="2", quantity=30, unit_price=100.0,
                           contract_status="Not contracted", contract_number=None),
        ],
        spend_config,
    )
    metrics = calculate_metrics(frame, spend_config)

    assert metrics.contracted_spend == pytest.approx(1000.0)
    assert metrics.non_contracted_spend == pytest.approx(3000.0)
    assert metrics.contracted_spend_pct == pytest.approx(25.0)


def test_maverick_spend_calculation(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", quantity=10, unit_price=100.0),
            make_spend_row(po_number="2", quantity=20, unit_price=100.0,
                           contract_status="Not contracted", contract_number=None,
                           preferred_supplier_status="Non-preferred"),
        ],
        spend_config,
    )
    metrics = calculate_metrics(frame, spend_config)

    assert metrics.maverick_spend == pytest.approx(2000.0)
    assert metrics.maverick_spend_pct == pytest.approx(66.67, abs=0.01)
    assert metrics.spend_under_management == pytest.approx(1000.0)
    assert metrics.spend_under_management_pct == pytest.approx(33.33, abs=0.01)


def test_spend_by_currency(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", currency="EUR", quantity=10, unit_price=100.0),
            make_spend_row(po_number="2", currency="USD", quantity=10, unit_price=100.0),
        ],
        spend_config,
    )
    rows = {row["currency"]: row for row in spend_by_currency(frame, spend_config)}

    assert rows["EUR"]["spend_base"] == pytest.approx(1000.0)
    assert rows["USD"]["spend_base"] == pytest.approx(1000.0 * spend_config.conversion_rate("USD"))
    assert rows["USD"]["spend_document_currency"] == pytest.approx(1000.0)


def test_empty_frame_produces_zero_metrics(spend_config):
    frame = make_spend_frame([make_spend_row()], spend_config)
    empty = frame[frame["supplier_id"] == "nobody"]
    metrics = calculate_metrics(empty, spend_config)

    assert metrics.total_spend == 0.0
    assert metrics.supplier_count == 0
    assert metrics.spend_by_currency == []


# ---------------------------------------------------------------------------
# Concentration
# ---------------------------------------------------------------------------
def test_herfindahl_index_of_a_monopoly_is_ten_thousand(spend_config):
    frame = make_spend_frame(
        [make_spend_row(po_number=str(i), quantity=10, unit_price=100.0) for i in range(4)],
        spend_config,
    )
    suppliers = calculate_supplier_spend(frame, spend_config)
    assert herfindahl_index(suppliers) == pytest.approx(10000.0)


def test_herfindahl_index_of_four_equal_suppliers(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number=str(i), supplier_id=f"000020000{i}",
                           quantity=10, unit_price=100.0)
            for i in range(4)
        ],
        spend_config,
    )
    suppliers = calculate_supplier_spend(frame, spend_config)
    # Four suppliers at 25% each -> 4 * 625 = 2500
    assert herfindahl_index(suppliers) == pytest.approx(2500.0)


@pytest.mark.parametrize(
    ("hhi", "expected"), [(500.0, "low"), (1800.0, "moderate"), (3000.0, "high")]
)
def test_concentration_level_thresholds(spend_config, hhi, expected):
    assert concentration_level(hhi, spend_config) == expected


def test_top_supplier_and_top_five_share(spend_config):
    rows = [
        make_spend_row(po_number="1", supplier_id="A", quantity=50, unit_price=100.0),
        *[
            make_spend_row(po_number=str(i + 2), supplier_id=f"S{i}", quantity=10, unit_price=100.0)
            for i in range(5)
        ],
    ]
    frame = make_spend_frame(rows, spend_config)
    metrics = calculate_metrics(frame, spend_config)

    assert metrics.top_supplier_id == "A"
    assert metrics.top_supplier_share_pct == pytest.approx(50.0)
    assert metrics.top_five_supplier_share_pct == pytest.approx(90.0)


def test_supplier_concentration_breakdown_flags_single_source(spend_config):
    rows = [
        make_spend_row(po_number=str(i), supplier_id="MONO", material_group="MG90",
                       quantity=100, unit_price=900.0)
        for i in range(6)
    ]
    frame = make_spend_frame(rows, spend_config)
    concentrated = supplier_concentration(frame, spend_config)

    assert concentrated
    entry = concentrated[0]
    assert entry["value"] == "MG90"
    assert entry["top_supplier_share_pct"] == pytest.approx(100.0)
    assert entry["exceeds_warning_threshold"] is True


def test_small_categories_are_not_reported_as_concentrated(spend_config):
    """A tiny single-supplier category would otherwise generate noise."""
    frame = make_spend_frame(
        [make_spend_row(material_group="MG99", quantity=1, unit_price=100.0)], spend_config
    )
    assert supplier_concentration(frame, spend_config) == []


# ---------------------------------------------------------------------------
# Tail spend
# ---------------------------------------------------------------------------
def test_tail_classification_follows_pareto(spend_config):
    rows = [make_spend_row(po_number="big", supplier_id="BIG", quantity=100, unit_price=100.0)]
    for index in range(6):
        rows.append(
            make_spend_row(po_number=f"s{index}", supplier_id=f"SMALL{index}",
                           quantity=1, unit_price=100.0)
        )
    frame = make_spend_frame(rows, spend_config)
    suppliers = {row.supplier_id: row for row in calculate_supplier_spend(frame, spend_config)}

    assert suppliers["BIG"].is_tail is False
    assert all(suppliers[f"SMALL{i}"].is_tail for i in range(6))


def test_tail_metrics_and_breakdown(spend_config):
    rows = [make_spend_row(po_number="big", supplier_id="BIG", quantity=100, unit_price=100.0)]
    rows += [
        make_spend_row(po_number=f"s{i}", supplier_id=f"SMALL{i}", quantity=2, unit_price=100.0)
        for i in range(5)
    ]
    frame = make_spend_frame(rows, spend_config)
    suppliers = calculate_supplier_spend(frame, spend_config)
    metrics = calculate_metrics(frame, spend_config, suppliers)

    assert metrics.tail_supplier_count == 5
    assert metrics.tail_spend == pytest.approx(1000.0)
    assert metrics.tail_spend_pct == pytest.approx(9.09, abs=0.01)
    assert len(tail_spend_suppliers(suppliers)) == 5


def test_tail_classification_skipped_for_tiny_supplier_base(spend_config):
    """With fewer suppliers than the configured minimum, nothing is tail."""
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", supplier_id="A", quantity=100, unit_price=100.0),
            make_spend_row(po_number="2", supplier_id="B", quantity=1, unit_price=100.0),
        ],
        spend_config,
    )
    suppliers = calculate_supplier_spend(frame, spend_config)
    assert not any(row.is_tail for row in suppliers)


# ---------------------------------------------------------------------------
# Price variance
# ---------------------------------------------------------------------------
def test_price_variance_against_baseline(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", quantity=10, unit_price=120.0,
                           current_price=120.0, baseline_price=100.0),
            make_spend_row(po_number="2", quantity=10, unit_price=100.0,
                           current_price=100.0, baseline_price=100.0),
        ],
        spend_config,
    )
    variance, variance_pct, lines = calculate_price_variance(frame, spend_config)

    assert variance == pytest.approx(200.0)
    assert lines == 1
    assert variance_pct == pytest.approx(200.0 / 2200.0 * 100.0, abs=0.01)


def test_price_variance_ignores_small_lines(spend_config):
    """Lines below the configured minimum value are excluded as noise."""
    frame = make_spend_frame(
        [make_spend_row(quantity=1, unit_price=120.0, current_price=120.0, baseline_price=100.0)],
        spend_config,
    )
    variance, _pct, lines = calculate_price_variance(frame, spend_config)
    assert variance == 0.0
    assert lines == 0


def test_price_variance_falls_back_to_material_median(spend_config):
    rows = [
        make_spend_row(po_number=str(i), quantity=10, unit_price=100.0,
                       current_price=100.0, baseline_price=None)
        for i in range(4)
    ]
    rows.append(
        make_spend_row(po_number="odd", quantity=10, unit_price=150.0,
                       current_price=150.0, baseline_price=None)
    )
    frame = make_spend_frame(rows, spend_config)
    variance, _pct, lines = calculate_price_variance(frame, spend_config)

    assert variance == pytest.approx(500.0)
    assert lines == 1


def test_price_variance_breakdown_reports_spread(spend_config):
    rows = [
        make_spend_row(po_number=str(i), quantity=10, unit_price=100.0, current_price=100.0,
                       baseline_price=100.0)
        for i in range(4)
    ]
    rows.append(
        make_spend_row(po_number="high", quantity=10, unit_price=150.0, current_price=150.0,
                       baseline_price=100.0)
    )
    frame = make_spend_frame(rows, spend_config)
    breakdown = purchase_price_variance(frame, spend_config)

    assert breakdown
    entry = breakdown[0]
    assert entry["comparison_basis"] == "baseline_price"
    assert entry["price_spread_pct"] == pytest.approx(50.0)
    assert entry["exceeds_alert_threshold"] is True


# ---------------------------------------------------------------------------
# Analytics breakdowns
# ---------------------------------------------------------------------------
def test_monthly_spend_is_ordered_with_deltas(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", transaction_date=date(2025, 1, 15),
                           quantity=10, unit_price=100.0),
            make_spend_row(po_number="2", transaction_date=date(2025, 2, 15),
                           quantity=20, unit_price=100.0),
        ],
        spend_config,
    )
    rows = monthly_spend(frame)

    assert [row["value"] for row in rows] == ["2025-01", "2025-02"]
    assert rows[0]["change_vs_previous_pct"] is None
    assert rows[1]["change_vs_previous_pct"] == pytest.approx(100.0)


def test_contract_leakage_only_reports_suppliers_with_a_contract(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", supplier_id="MIXED", quantity=10, unit_price=100.0),
            make_spend_row(po_number="2", supplier_id="MIXED", quantity=5, unit_price=100.0,
                           contract_status="Not contracted", contract_number=None),
            make_spend_row(po_number="3", supplier_id="NEVER", quantity=5, unit_price=100.0,
                           contract_status="Not contracted", contract_number=None),
        ],
        spend_config,
    )
    rows = contract_leakage(frame)

    assert [row["value"] for row in rows] == ["MIXED"]
    assert rows[0]["leaked_spend_base"] == pytest.approx(500.0)
    assert rows[0]["leakage_share_pct"] == pytest.approx(33.33, abs=0.01)


def test_maverick_breakdown_reports_share_of_supplier(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", supplier_id="S1", quantity=10, unit_price=100.0),
            make_spend_row(po_number="2", supplier_id="S1", quantity=10, unit_price=100.0,
                           contract_status="Not contracted", contract_number=None,
                           preferred_supplier_status="Non-preferred"),
        ],
        spend_config,
    )
    rows = maverick_spend_breakdown(frame)

    assert rows[0]["maverick_spend_base"] == pytest.approx(1000.0)
    assert rows[0]["maverick_share_of_supplier_pct"] == pytest.approx(50.0)


def test_top_materials_are_ranked_by_spend(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", material="A", quantity=10, unit_price=100.0),
            make_spend_row(po_number="2", material="B", quantity=50, unit_price=100.0),
        ],
        spend_config,
    )
    rows = top_materials(frame, top_n=5)
    assert [row["value"] for row in rows] == ["B", "A"]


def test_build_analytics_returns_every_breakdown(spend_config):
    frame = make_spend_frame(
        [make_spend_row(po_number=str(i), supplier_id=f"S{i}") for i in range(6)], spend_config
    )
    suppliers = calculate_supplier_spend(frame, spend_config)
    analytics = build_analytics(frame, spend_config, suppliers)

    for key in (
        "monthly_spend", "spend_by_supplier", "spend_by_category", "spend_by_material_group",
        "spend_by_plant", "spend_by_company_code", "top_materials", "tail_spend_suppliers",
        "supplier_concentration", "contract_leakage", "maverick_spend",
        "purchase_price_variance",
    ):
        assert key in analytics, key


def test_breakdown_rows_carry_drilldown_keys(spend_config):
    """The UI sends dimension+value back to the transactions endpoint."""
    frame = make_spend_frame([make_spend_row()], spend_config)
    suppliers = calculate_supplier_spend(frame, spend_config)
    analytics = build_analytics(frame, spend_config, suppliers)

    for row in analytics["spend_by_category"]:
        assert row["dimension"] == "category"
        assert row["value"]


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def test_empty_filter_returns_everything(spend_config):
    frame = make_spend_frame([make_spend_row(po_number=str(i)) for i in range(3)], spend_config)
    assert len(apply_filter(frame, SpendFilter())) == 3
    assert SpendFilter().is_empty is True


def test_date_range_filter(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", transaction_date=date(2025, 1, 10)),
            make_spend_row(po_number="2", transaction_date=date(2025, 6, 10)),
            make_spend_row(po_number="3", transaction_date=date(2025, 12, 10)),
        ],
        spend_config,
    )
    filtered = apply_filter(
        frame, SpendFilter(date_from=date(2025, 5, 1), date_to=date(2025, 7, 1))
    )
    assert filtered["po_number"].tolist() == ["2"]


def test_undated_rows_are_dropped_when_a_date_range_is_requested(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", transaction_date=date(2025, 6, 10)),
            make_spend_row(po_number="2", transaction_date=None, order_date=None),
        ],
        spend_config,
    )
    assert len(apply_filter(frame, SpendFilter(date_from=date(2025, 1, 1)))) == 1
    assert len(apply_filter(frame, SpendFilter())) == 2


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("supplier_id", "0000200002"),
        ("category", "Logistics"),
        ("material_group", "MG20"),
        ("plant", "2010"),
        ("company_code", "2000"),
        ("currency", "USD"),
    ],
)
def test_categorical_filters(spend_config, field_name, value):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1"),
            make_spend_row(po_number="2", **{field_name: value}),
        ],
        spend_config,
    )
    filtered = apply_filter(frame, SpendFilter(values={field_name: [value]}))
    assert filtered["po_number"].tolist() == ["2"]


def test_filters_combine_with_and_logic(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", category="Logistics", plant="1010"),
            make_spend_row(po_number="2", category="Logistics", plant="2010"),
            make_spend_row(po_number="3", category="Packaging", plant="2010"),
        ],
        spend_config,
    )
    filtered = apply_filter(
        frame, SpendFilter(values={"category": ["Logistics"], "plant": ["2010"]})
    )
    assert filtered["po_number"].tolist() == ["2"]


def test_multiple_values_in_one_filter_are_or_logic(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", category="Logistics"),
            make_spend_row(po_number="2", category="Packaging"),
            make_spend_row(po_number="3", category="Laboratory"),
        ],
        spend_config,
    )
    filtered = apply_filter(
        frame, SpendFilter(values={"category": ["Logistics", "Packaging"]})
    )
    assert filtered["po_number"].tolist() == ["1", "2"]


def test_metrics_reflect_the_filter(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", category="Logistics", quantity=10, unit_price=100.0),
            make_spend_row(po_number="2", category="Packaging", quantity=90, unit_price=100.0),
        ],
        spend_config,
    )
    filtered = apply_filter(frame, SpendFilter(values={"category": ["Logistics"]}))
    metrics = calculate_metrics(filtered, spend_config)

    assert metrics.total_spend == pytest.approx(1000.0)
    assert metrics.line_item_count == 1


def test_available_filter_values_come_from_the_data(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", category="Logistics"),
            make_spend_row(po_number="2", category="Packaging"),
        ],
        spend_config,
    )
    options = available_filter_values(frame)
    assert options["category"] == ["Logistics", "Packaging"]
    assert "supplier_id" in options


def test_date_bounds(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", transaction_date=date(2025, 1, 10)),
            make_spend_row(po_number="2", transaction_date=date(2025, 9, 10)),
        ],
        spend_config,
    )
    assert date_bounds(frame) == (date(2025, 1, 10), date(2025, 9, 10))


def test_filter_round_trips_through_its_dict(spend_config):
    spend_filter = SpendFilter.from_request(
        date_from=SPEND_BASE_DATE,
        date_to=SPEND_BASE_DATE + timedelta(days=30),
        values={"category": ["Logistics"], "plant": []},
    )
    payload = spend_filter.to_dict()

    assert payload["values"] == {"category": ["Logistics"]}
    assert payload["date_from"] == SPEND_BASE_DATE.isoformat()
    assert spend_filter.active_filters()["category"] == ["Logistics"]


def test_unknown_filter_fields_are_ignored():
    spend_filter = SpendFilter.from_request(values={"not_a_field": ["x"]})
    assert spend_filter.is_empty


# ---------------------------------------------------------------------------
# Methodology
# ---------------------------------------------------------------------------
def test_methodology_states_the_calculation_basis(spend_config):
    document = methodology(spend_config)
    assert "deterministic" in document["calculation_basis"]
    assert "not connected to any SAP system" in document["data_disclaimer"]
    assert document["savings_disclaimer"]
    assert document["base_currency"] == spend_config.base_currency


def test_metrics_are_labelled_rule_based(spend_config):
    frame = make_spend_frame([make_spend_row()], spend_config)
    metrics = calculate_metrics(frame, spend_config)
    assert metrics.metrics_version
    assert metrics.base_currency == spend_config.base_currency
