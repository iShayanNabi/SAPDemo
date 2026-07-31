"""Unit tests for the supplier scoring, weighting and ranking.

Small, hand-checkable supplier pools where the expected score can be reasoned
about directly. Every figure here is produced by the deterministic engine.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.exceptions import ConfigurationError
from app.modules.supplier_reco.engine import run_recommendation
from app.modules.supplier_reco.scoring import (
    SCORING_ENGINE_VERSION,
    classify_contract,
    score_suppliers,
)
from app.modules.supplier_reco.thresholds import Weights
from tests.factories import make_requirement, make_supplier


# ---------------------------------------------------------------------------
# Weight validation
# ---------------------------------------------------------------------------
def test_default_weights_sum_to_one_hundred(supplier_reco_config):
    assert supplier_reco_config.default_weights.total() == pytest.approx(100.0)
    supplier_reco_config.validate_weights(supplier_reco_config.default_weights)


def test_weights_not_summing_to_one_hundred_are_rejected(supplier_reco_config):
    bad = Weights(
        cost=50, delivery=10, quality=10, capacity=5, risk=5, esg=5,
        contract=5, geographic=5, past_performance=10,  # sums to 105
    )
    assert bad.total() == pytest.approx(105.0)
    with pytest.raises(ConfigurationError):
        supplier_reco_config.validate_weights(bad)


# ---------------------------------------------------------------------------
# Score normalisation
# ---------------------------------------------------------------------------
def test_cost_score_is_minmax_inverse_of_price(supplier_reco_config):
    suppliers = [
        make_supplier(supplier_id="A", unit_price=100.0),
        make_supplier(supplier_id="B", unit_price=200.0),
        make_supplier(supplier_id="C", unit_price=150.0),
    ]
    scores = score_suppliers(suppliers, make_requirement(), supplier_reco_config.default_weights, supplier_reco_config)
    assert scores["A"].cost == 100.0  # cheapest
    assert scores["B"].cost == 0.0    # priciest
    assert scores["C"].cost == 50.0   # midpoint


def test_single_supplier_scores_full_on_relative_dimensions(supplier_reco_config):
    suppliers = [make_supplier(supplier_id="A", unit_price=175.0)]
    scores = score_suppliers(suppliers, make_requirement(), supplier_reco_config.default_weights, supplier_reco_config)
    # With one supplier there is no spread, so min-max dimensions score full marks.
    assert scores["A"].cost == 100.0


def test_missing_price_scores_zero_on_cost(supplier_reco_config):
    suppliers = [
        make_supplier(supplier_id="A", unit_price=100.0),
        make_supplier(supplier_id="B", unit_price=None),
    ]
    scores = score_suppliers(suppliers, make_requirement(), supplier_reco_config.default_weights, supplier_reco_config)
    assert scores["B"].cost == 0.0


def test_risk_score_is_inverse_of_risk(supplier_reco_config):
    suppliers = [
        make_supplier(supplier_id="A", risk_score=10.0),
        make_supplier(supplier_id="B", risk_score=90.0, risk_tolerance="high"),
    ]
    scores = score_suppliers(suppliers, make_requirement(risk_tolerance="high"), supplier_reco_config.default_weights, supplier_reco_config)
    assert scores["A"].risk == 90.0
    assert scores["B"].risk == 10.0


def test_esg_score_used_directly(supplier_reco_config):
    supplier = make_supplier(supplier_id="A", esg_score=73.0)
    scores = score_suppliers([supplier], make_requirement(), supplier_reco_config.default_weights, supplier_reco_config)
    assert scores["A"].esg == 73.0


def test_capacity_score_rewards_coverage_over_quantity(supplier_reco_config):
    # target coverage ratio 1.5, quantity 100 -> full marks at 150 capacity.
    plenty = make_supplier(supplier_id="A", available_capacity=150.0)
    scores = score_suppliers([plenty], make_requirement(quantity=100), supplier_reco_config.default_weights, supplier_reco_config)
    assert scores["A"].capacity == 100.0

    tight = make_supplier(supplier_id="B", available_capacity=75.0)
    scores = score_suppliers([tight], make_requirement(quantity=100), supplier_reco_config.default_weights, supplier_reco_config)
    assert scores["B"].capacity == pytest.approx(50.0)  # 75 / 150 * 100


def test_geographic_score_shares_the_specified_criteria(supplier_reco_config):
    both = make_supplier(supplier_id="A", regions_served=["EU"], plants_served=["1010"])
    requirement = make_requirement(preferred_region="EU", plant="1010")
    scores = score_suppliers([both], requirement, supplier_reco_config.default_weights, supplier_reco_config)
    assert scores["A"].geographic == 100.0

    region_only = make_supplier(supplier_id="B", regions_served=["EU"], plants_served=["9999"])
    scores = score_suppliers([region_only], requirement, supplier_reco_config.default_weights, supplier_reco_config)
    # region (60) matched, plant (40) missed -> 60 / 100.
    assert scores["B"].geographic == pytest.approx(60.0)


def test_geographic_full_when_no_location_preference(supplier_reco_config):
    supplier = make_supplier(supplier_id="A")
    requirement = make_requirement(preferred_region=None, plant=None)
    scores = score_suppliers([supplier], requirement, supplier_reco_config.default_weights, supplier_reco_config)
    assert scores["A"].geographic == 100.0


# ---------------------------------------------------------------------------
# Contract classification
# ---------------------------------------------------------------------------
def test_contract_classification_active(supplier_reco_config):
    supplier = make_supplier(contract_status="Active", contract_expiration=date(2030, 1, 1))
    requirement = make_requirement(required_delivery_date=date(2026, 10, 1), order_date=date(2026, 8, 1))
    assert classify_contract(supplier, requirement, supplier_reco_config) == "active"


def test_contract_classification_expiring_before_delivery(supplier_reco_config):
    supplier = make_supplier(contract_status="Active", contract_expiration=date(2026, 9, 1))
    requirement = make_requirement(required_delivery_date=date(2026, 10, 1), order_date=date(2026, 8, 1))
    # Active, but the contract lapses before the goods are needed.
    assert classify_contract(supplier, requirement, supplier_reco_config) == "expiring"


def test_contract_classification_none_and_unknown(supplier_reco_config):
    requirement = make_requirement()
    none_supplier = make_supplier(contract_status="No contract", contract_expiration=None)
    assert classify_contract(none_supplier, requirement, supplier_reco_config) == "none"
    unknown_supplier = make_supplier(contract_status=None, contract_expiration=None)
    assert classify_contract(unknown_supplier, requirement, supplier_reco_config) == "unknown"


# ---------------------------------------------------------------------------
# Overall score, ranking, determinism
# ---------------------------------------------------------------------------
def test_overall_score_is_weighted_sum(supplier_reco_config):
    supplier = make_supplier(supplier_id="A")
    weights = supplier_reco_config.default_weights
    scores = score_suppliers([supplier], make_requirement(), weights, supplier_reco_config)
    s = scores["A"]
    expected = sum(
        weights.as_dict()[dim] / 100.0 * getattr(s, dim)
        for dim in weights.as_dict()
    )
    assert s.overall == pytest.approx(round(expected, 2))


def test_ranking_orders_by_overall_score_descending(supplier_reco_config):
    suppliers = [
        make_supplier(supplier_id="CHEAP", unit_price=60.0, quality_score=70.0, esg_score=60.0, risk_score=40.0),
        make_supplier(supplier_id="BALANCED", unit_price=110.0, quality_score=95.0, esg_score=90.0, risk_score=10.0),
        make_supplier(supplier_id="POOR", unit_price=200.0, quality_score=65.0, esg_score=50.0, risk_score=58.0),
    ]
    result = run_recommendation(suppliers, make_requirement(), supplier_reco_config.default_weights, supplier_reco_config)
    ranks = [(e.supplier_id, e.rank) for e in result.ranked]
    # Ranks are a strict 1..N sequence over the eligible set.
    eligible_ranks = sorted(e.rank for e in result.ranked if e.is_eligible)
    assert eligible_ranks == [1, 2, 3]
    # The engine's own overall order is non-increasing.
    eligible = [e for e in result.ranked if e.is_eligible]
    overalls = [e.overall_score for e in sorted(eligible, key=lambda e: e.rank)]
    assert overalls == sorted(overalls, reverse=True)


def test_all_cost_weight_ranks_cheapest_first(supplier_reco_config):
    weights = Weights(
        cost=100, delivery=0, quality=0, capacity=0, risk=0, esg=0,
        contract=0, geographic=0, past_performance=0,
    )
    suppliers = [
        make_supplier(supplier_id="A", unit_price=120.0),
        make_supplier(supplier_id="B", unit_price=70.0),
        make_supplier(supplier_id="C", unit_price=95.0),
    ]
    result = run_recommendation(suppliers, make_requirement(), weights, supplier_reco_config)
    winner = next(e for e in result.ranked if e.rank == 1)
    assert winner.supplier_id == "B"


def test_recommendation_is_deterministic(supplier_reco_config):
    suppliers = [
        make_supplier(supplier_id=f"{300001 + i:010d}", unit_price=90.0 + i * 7, risk_score=20.0 + i)
        for i in range(6)
    ]
    first = run_recommendation(suppliers, make_requirement(), supplier_reco_config.default_weights, supplier_reco_config)
    second = run_recommendation(suppliers, make_requirement(), supplier_reco_config.default_weights, supplier_reco_config)
    assert [(e.supplier_id, e.rank, e.overall_score) for e in first.ranked] == \
           [(e.supplier_id, e.rank, e.overall_score) for e in second.ranked]


def test_estimated_cost_and_delivery(supplier_reco_config):
    supplier = make_supplier(supplier_id="A", unit_price=100.0, currency="EUR", lead_time_days=10)
    requirement = make_requirement(quantity=250, order_date=date(2026, 8, 1))
    result = run_recommendation([supplier], requirement, supplier_reco_config.default_weights, supplier_reco_config)
    entry = result.ranked[0]
    assert entry.estimated_total_cost_base == pytest.approx(25000.0)  # 100 * 250
    assert entry.estimated_delivery_date == date(2026, 8, 11)  # order + 10 days


def test_engine_version_is_reported(supplier_reco_config):
    result = run_recommendation([make_supplier()], make_requirement(), supplier_reco_config.default_weights, supplier_reco_config)
    assert result.scoring_engine_version == SCORING_ENGINE_VERSION
