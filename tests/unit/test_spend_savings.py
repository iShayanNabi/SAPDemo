"""Unit tests for the six savings opportunity rules.

Each rule gets a case that must produce an opportunity and a case that must
stay silent. The silent case matters: a savings model that fires on healthy
spend produces numbers nobody can defend in a negotiation.
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ConfigurationError
from app.modules.spend.metrics import calculate_supplier_spend
from app.modules.spend.savings import (
    calculate_savings,
    contract_compliance,
    preferred_supplier_migration,
    price_harmonisation,
    price_variance_reduction,
    savings_rule_catalogue,
    supplier_consolidation,
    tail_spend_reduction,
)
from app.modules.spend.thresholds import load_spend_config
from tests.factories import make_spend_frame, make_spend_row


def rule(spend_config, rule_id):
    """Shorthand for one rule's settings."""
    return spend_config.savings_rule(rule_id)


# ---------------------------------------------------------------------------
# SAV-01 price harmonisation
# ---------------------------------------------------------------------------
def test_price_harmonisation_detects_a_wide_spread(spend_config):
    rows = [
        make_spend_row(po_number=f"low{i}", quantity=100, unit_price=100.0) for i in range(3)
    ]
    rows += [
        make_spend_row(po_number=f"high{i}", quantity=100, unit_price=160.0) for i in range(3)
    ]
    frame = make_spend_frame(rows, spend_config)
    opportunities = price_harmonisation(frame, spend_config, rule(spend_config, "SAV-01"))

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.rule_id == "SAV-01"
    assert opportunity.scope == "material"
    assert opportunity.gross_saving_base > 0
    assert opportunity.estimated_saving_base == pytest.approx(
        opportunity.gross_saving_base * opportunity.realization_factor
    )
    assert opportunity.is_estimate is True
    assert "percentile" in opportunity.method


def test_price_harmonisation_ignores_consistent_prices(spend_config):
    rows = [
        make_spend_row(po_number=str(i), quantity=100, unit_price=100.0 + i) for i in range(6)
    ]
    frame = make_spend_frame(rows, spend_config)
    assert price_harmonisation(frame, spend_config, rule(spend_config, "SAV-01")) == []


def test_price_harmonisation_needs_enough_observations(spend_config):
    rows = [
        make_spend_row(po_number="1", quantity=100, unit_price=100.0),
        make_spend_row(po_number="2", quantity=100, unit_price=200.0),
    ]
    frame = make_spend_frame(rows, spend_config)
    assert price_harmonisation(frame, spend_config, rule(spend_config, "SAV-01")) == []


def test_price_harmonisation_needs_material_spend(spend_config):
    """A cheap material with a wide spread is not worth an opportunity."""
    rows = [
        make_spend_row(po_number=f"a{i}", quantity=1, unit_price=1.0) for i in range(4)
    ]
    rows += [make_spend_row(po_number=f"b{i}", quantity=1, unit_price=5.0) for i in range(4)]
    frame = make_spend_frame(rows, spend_config)
    assert price_harmonisation(frame, spend_config, rule(spend_config, "SAV-01")) == []


# ---------------------------------------------------------------------------
# SAV-02 contract compliance
# ---------------------------------------------------------------------------
def test_contract_compliance_detects_non_contracted_spend(spend_config):
    rows = [
        make_spend_row(po_number="1", quantity=100, unit_price=200.0),
        make_spend_row(po_number="2", quantity=200, unit_price=200.0,
                       contract_status="Not contracted", contract_number=None),
    ]
    frame = make_spend_frame(rows, spend_config)
    opportunities = contract_compliance(frame, spend_config, rule(spend_config, "SAV-02"))

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.addressable_spend_base == pytest.approx(40000.0)
    assert opportunity.gross_saving_base == pytest.approx(40000.0 * 0.08)
    assert opportunity.evidence["supplier_holds_contract_elsewhere"] is True
    assert "leakage" in opportunity.description


def test_contract_compliance_ignores_fully_contracted_suppliers(spend_config):
    frame = make_spend_frame(
        [make_spend_row(po_number=str(i), quantity=100, unit_price=200.0) for i in range(3)],
        spend_config,
    )
    assert contract_compliance(frame, spend_config, rule(spend_config, "SAV-02")) == []


def test_contract_compliance_ignores_small_suppliers(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number="1", quantity=1, unit_price=100.0,
                           contract_status="Not contracted", contract_number=None)
        ],
        spend_config,
    )
    assert contract_compliance(frame, spend_config, rule(spend_config, "SAV-02")) == []


# ---------------------------------------------------------------------------
# SAV-03 supplier consolidation
# ---------------------------------------------------------------------------
def test_supplier_consolidation_detects_a_fragmented_group(spend_config):
    rows = [
        make_spend_row(po_number=str(i), supplier_id=f"S{i}", material=f"M{i}",
                       material_group="MG15", quantity=100, unit_price=200.0)
        for i in range(5)
    ]
    frame = make_spend_frame(rows, spend_config)
    opportunities = supplier_consolidation(frame, spend_config, rule(spend_config, "SAV-03"))

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.scope == "material_group"
    assert opportunity.supplier_count == 5
    assert opportunity.addressable_spend_base == pytest.approx(100000.0 * 0.60)


def test_supplier_consolidation_ignores_a_focused_group(spend_config):
    rows = [
        make_spend_row(po_number=str(i), supplier_id=f"S{i % 2}", material_group="MG15",
                       quantity=100, unit_price=200.0)
        for i in range(5)
    ]
    frame = make_spend_frame(rows, spend_config)
    assert supplier_consolidation(frame, spend_config, rule(spend_config, "SAV-03")) == []


def test_supplier_consolidation_ignores_small_groups(spend_config):
    rows = [
        make_spend_row(po_number=str(i), supplier_id=f"S{i}", material_group="MG15",
                       quantity=1, unit_price=10.0)
        for i in range(5)
    ]
    frame = make_spend_frame(rows, spend_config)
    assert supplier_consolidation(frame, spend_config, rule(spend_config, "SAV-03")) == []


# ---------------------------------------------------------------------------
# SAV-04 tail spend reduction
# ---------------------------------------------------------------------------
def test_tail_spend_reduction_combines_price_and_process(spend_config):
    rows = [make_spend_row(po_number="big", supplier_id="BIG", quantity=1000, unit_price=500.0)]
    rows += [
        make_spend_row(po_number=f"t{i}", supplier_id=f"TAIL{i}", quantity=50, unit_price=200.0)
        for i in range(8)
    ]
    frame = make_spend_frame(rows, spend_config)
    suppliers = calculate_supplier_spend(frame, spend_config)
    opportunities = tail_spend_reduction(
        frame, spend_config, rule(spend_config, "SAV-04"), suppliers
    )

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.scope == "portfolio"
    assert opportunity.supplier_count == 8
    evidence = opportunity.evidence
    assert evidence["price_component_base"] > 0
    assert evidence["process_component_base"] == pytest.approx(8 * 45.0)
    assert opportunity.gross_saving_base == pytest.approx(
        evidence["price_component_base"] + evidence["process_component_base"]
    )


def test_tail_spend_reduction_needs_material_tail_spend(spend_config):
    rows = [make_spend_row(po_number="big", supplier_id="BIG", quantity=1000, unit_price=500.0)]
    rows += [
        make_spend_row(po_number=f"t{i}", supplier_id=f"TAIL{i}", quantity=1, unit_price=1.0)
        for i in range(6)
    ]
    frame = make_spend_frame(rows, spend_config)
    suppliers = calculate_supplier_spend(frame, spend_config)
    assert tail_spend_reduction(frame, spend_config, rule(spend_config, "SAV-04"), suppliers) == []


def test_tail_spend_reduction_with_no_tail_suppliers(spend_config):
    frame = make_spend_frame(
        [make_spend_row(po_number="1", quantity=100, unit_price=100.0)], spend_config
    )
    suppliers = calculate_supplier_spend(frame, spend_config)
    assert tail_spend_reduction(frame, spend_config, rule(spend_config, "SAV-04"), suppliers) == []


# ---------------------------------------------------------------------------
# SAV-05 move to preferred suppliers
# ---------------------------------------------------------------------------
def test_preferred_migration_detects_a_price_gap(spend_config):
    rows = [
        make_spend_row(po_number=f"p{i}", supplier_id="PREF", quantity=50, unit_price=100.0)
        for i in range(3)
    ]
    rows += [
        make_spend_row(po_number=f"n{i}", supplier_id="OTHER", quantity=50, unit_price=140.0,
                       preferred_supplier_status="Non-preferred")
        for i in range(3)
    ]
    frame = make_spend_frame(rows, spend_config)
    opportunities = preferred_supplier_migration(
        frame, spend_config, rule(spend_config, "SAV-05")
    )

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.evidence["preferred_price_base"] == pytest.approx(100.0)
    assert opportunity.evidence["price_gap_pct"] == pytest.approx(40.0)
    assert opportunity.gross_saving_base == pytest.approx(3 * 50 * 40.0)


def test_preferred_migration_needs_a_preferred_supplier(spend_config):
    rows = [
        make_spend_row(po_number=str(i), supplier_id=f"S{i}", quantity=50, unit_price=140.0,
                       preferred_supplier_status="Non-preferred")
        for i in range(4)
    ]
    frame = make_spend_frame(rows, spend_config)
    assert preferred_supplier_migration(frame, spend_config, rule(spend_config, "SAV-05")) == []


def test_preferred_migration_ignores_a_small_gap(spend_config):
    rows = [
        make_spend_row(po_number=f"p{i}", supplier_id="PREF", quantity=50, unit_price=100.0)
        for i in range(3)
    ]
    rows += [
        make_spend_row(po_number=f"n{i}", supplier_id="OTHER", quantity=50, unit_price=101.0,
                       preferred_supplier_status="Non-preferred")
        for i in range(3)
    ]
    frame = make_spend_frame(rows, spend_config)
    assert preferred_supplier_migration(frame, spend_config, rule(spend_config, "SAV-05")) == []


# ---------------------------------------------------------------------------
# SAV-06 reduce high price variance
# ---------------------------------------------------------------------------
def test_price_variance_reduction_detects_lines_above_baseline(spend_config):
    rows = [
        make_spend_row(po_number=str(i), quantity=100, unit_price=130.0,
                       current_price=130.0, baseline_price=100.0)
        for i in range(3)
    ]
    frame = make_spend_frame(rows, spend_config)
    opportunities = price_variance_reduction(frame, spend_config, rule(spend_config, "SAV-06"))

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.gross_saving_base == pytest.approx(3 * 100 * 30.0)
    assert opportunity.evidence["worst_variance_pct"] == pytest.approx(30.0)


def test_price_variance_reduction_ignores_lines_at_baseline(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number=str(i), quantity=100, unit_price=100.0,
                           current_price=100.0, baseline_price=100.0)
            for i in range(3)
        ],
        spend_config,
    )
    assert price_variance_reduction(frame, spend_config, rule(spend_config, "SAV-06")) == []


def test_price_variance_reduction_ignores_a_small_variance(spend_config):
    frame = make_spend_frame(
        [
            make_spend_row(po_number=str(i), quantity=100, unit_price=105.0,
                           current_price=105.0, baseline_price=100.0)
            for i in range(3)
        ],
        spend_config,
    )
    assert price_variance_reduction(frame, spend_config, rule(spend_config, "SAV-06")) == []


# ---------------------------------------------------------------------------
# Engine behaviour
# ---------------------------------------------------------------------------
def test_engine_runs_every_enabled_rule(spend_config):
    frame = make_spend_frame([make_spend_row()], spend_config)
    suppliers = calculate_supplier_spend(frame, spend_config)
    result = calculate_savings(frame, spend_config, suppliers)

    executed = {entry["rule_id"] for entry in result.rule_executions}
    assert executed == set(spend_config.savings_rules)
    assert result.rule_errors == []


def test_engine_can_run_a_subset(spend_config):
    rows = [
        make_spend_row(po_number=str(i), quantity=100, unit_price=130.0,
                       current_price=130.0, baseline_price=100.0)
        for i in range(3)
    ]
    frame = make_spend_frame(rows, spend_config)
    suppliers = calculate_supplier_spend(frame, spend_config)
    result = calculate_savings(frame, spend_config, suppliers, enabled_rules=["SAV-06"])

    assert {o.rule_id for o in result.opportunities} == {"SAV-06"}


def test_engine_isolates_a_failing_rule(spend_config, monkeypatch):
    """One broken model must not lose the other five."""
    import app.modules.spend.savings as savings_module

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(savings_module, "price_harmonisation", explode)

    rows = [
        make_spend_row(po_number=str(i), quantity=100, unit_price=130.0,
                       current_price=130.0, baseline_price=100.0)
        for i in range(3)
    ]
    frame = make_spend_frame(rows, spend_config)
    suppliers = calculate_supplier_spend(frame, spend_config)
    result = savings_module.calculate_savings(frame, spend_config, suppliers)

    assert result.rule_errors and result.rule_errors[0]["rule_id"] == "SAV-01"
    assert any(o.rule_id == "SAV-06" for o in result.opportunities)


def test_engine_totals_and_grouping(spend_config):
    rows = [
        make_spend_row(po_number=str(i), quantity=100, unit_price=130.0,
                       current_price=130.0, baseline_price=100.0)
        for i in range(3)
    ]
    frame = make_spend_frame(rows, spend_config)
    suppliers = calculate_supplier_spend(frame, spend_config)
    result = calculate_savings(frame, spend_config, suppliers)

    assert result.total_estimated_saving == pytest.approx(
        sum(o.estimated_saving_base for o in result.opportunities)
    )
    assert sum(result.by_rule().values()) == pytest.approx(result.total_estimated_saving)


def test_opportunities_are_sorted_by_value(spend_config):
    rows = [
        make_spend_row(po_number=f"a{i}", material="A", quantity=100, unit_price=130.0,
                       current_price=130.0, baseline_price=100.0)
        for i in range(3)
    ]
    rows += [
        make_spend_row(po_number=f"b{i}", material="B", quantity=500, unit_price=130.0,
                       current_price=130.0, baseline_price=100.0)
        for i in range(3)
    ]
    frame = make_spend_frame(rows, spend_config)
    suppliers = calculate_supplier_spend(frame, spend_config)
    result = calculate_savings(frame, spend_config, suppliers)

    values = [o.estimated_saving_base for o in result.opportunities]
    assert values == sorted(values, reverse=True)


def test_every_opportunity_shows_its_arithmetic(spend_config):
    """A user must be able to check a savings figure, not just trust it."""
    rows = [
        make_spend_row(po_number=str(i), quantity=100, unit_price=130.0,
                       current_price=130.0, baseline_price=100.0)
        for i in range(4)
    ]
    frame = make_spend_frame(rows, spend_config)
    suppliers = calculate_supplier_spend(frame, spend_config)
    result = calculate_savings(frame, spend_config, suppliers)

    assert result.opportunities
    for opportunity in result.opportunities:
        assert opportunity.method and len(opportunity.method) > 40
        assert opportunity.description
        assert opportunity.evidence
        assert opportunity.is_estimate is True
        assert 0.0 <= opportunity.confidence <= 1.0
        assert 0.0 <= opportunity.realization_factor <= 1.0
        assert opportunity.estimated_saving_base <= opportunity.gross_saving_base


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def test_savings_rule_catalogue_exposes_assumptions(spend_config):
    catalogue = savings_rule_catalogue(spend_config)
    assert len(catalogue) == 6
    assert all(entry["params"] for entry in catalogue)
    assert all("realization_factor" in entry for entry in catalogue)


def test_changing_an_assumption_changes_the_estimate(spend_config, tmp_path):
    """Retuning a savings model must be a JSON edit, not a code change."""
    import json

    rows = [
        make_spend_row(po_number="1", quantity=100, unit_price=200.0),
        make_spend_row(po_number="2", quantity=200, unit_price=200.0,
                       contract_status="Not contracted", contract_number=None),
    ]
    frame = make_spend_frame(rows, spend_config)
    before = contract_compliance(frame, spend_config, rule(spend_config, "SAV-02"))[0]

    config_path = tmp_path / "spend.json"
    raw = spend_config.model_dump(mode="json")
    raw["savings_rules"]["SAV-02"]["params"]["assumed_saving_pct"] = 16.0
    config_path.write_text(json.dumps(raw), encoding="utf-8")

    tuned = load_spend_config(config_path)
    after = contract_compliance(frame, tuned, tuned.savings_rule("SAV-02"))[0]

    assert after.gross_saving_base == pytest.approx(before.gross_saving_base * 2)


def test_disabling_a_rule_stops_it_producing_opportunities(spend_config, tmp_path):
    import json

    rows = [
        make_spend_row(po_number=str(i), quantity=100, unit_price=130.0,
                       current_price=130.0, baseline_price=100.0)
        for i in range(3)
    ]
    frame = make_spend_frame(rows, spend_config)
    suppliers = calculate_supplier_spend(frame, spend_config)

    config_path = tmp_path / "spend.json"
    raw = spend_config.model_dump(mode="json")
    raw["savings_rules"]["SAV-06"]["enabled"] = False
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    tuned = load_spend_config(config_path)

    result = calculate_savings(frame, tuned, suppliers)
    assert not any(o.rule_id == "SAV-06" for o in result.opportunities)
    assert tuned.is_savings_rule_enabled("SAV-06") is False


def test_unknown_savings_rule_is_reported(spend_config):
    with pytest.raises(ConfigurationError):
        spend_config.savings_rule("SAV-99")


def test_invalid_configuration_is_rejected(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"config_version": "1.0.0"}', encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_spend_config(path)


def test_missing_configuration_file_is_reported(tmp_path):
    with pytest.raises(ConfigurationError, match="missing"):
        load_spend_config(tmp_path / "nope.json")
