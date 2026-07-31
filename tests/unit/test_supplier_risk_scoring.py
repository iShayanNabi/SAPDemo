"""Unit tests for the Supplier Risk Copilot scoring model.

These tests drive the pure engine directly - no database, no HTTP - so each
one reads as a statement about the risk maths: what a metric normalises to,
how weights combine, what happens when data is missing, and how a score is
categorised.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.core.exceptions import ConfigurationError
from app.modules.supplier_risk.engine import compute_trend, find_alternatives
from app.modules.supplier_risk.scoring import (
    normalize_metric,
    score_category,
    score_supplier,
)
from app.modules.supplier_risk.thresholds import (
    RISK_CATEGORIES,
    CategoryWeights,
    load_supplier_risk_config,
)
from tests.factories import (
    RISK_AS_OF,
    make_risk_event,
    make_risk_profile,
    run_risk_assessment_for,
)

# ---------------------------------------------------------------------------
# Metric normalisation
# ---------------------------------------------------------------------------


def test_higher_is_better_metric_maps_best_value_to_zero_risk(supplier_risk_config):
    """A supplier at the configured best on-time rate carries no delivery risk."""
    spec = supplier_risk_config.category("delivery").metrics["on_time_delivery_rate"]
    score, basis, note = normalize_metric(spec, spec.best_value, supplier_risk_config)

    assert score == 0.0
    assert note is None
    assert "best" in basis


def test_higher_is_better_metric_maps_worst_value_to_full_risk(supplier_risk_config):
    spec = supplier_risk_config.category("delivery").metrics["on_time_delivery_rate"]
    score, _, _ = normalize_metric(spec, spec.worst_value, supplier_risk_config)

    assert score == 100.0


def test_metric_normalisation_is_linear_between_the_anchors(supplier_risk_config):
    """Halfway between best and worst is halfway up the risk scale."""
    spec = supplier_risk_config.category("delivery").metrics["on_time_delivery_rate"]
    midpoint = (spec.best_value + spec.worst_value) / 2

    score, _, _ = normalize_metric(spec, midpoint, supplier_risk_config)

    assert score == pytest.approx(50.0, abs=0.01)


def test_metric_normalisation_clamps_beyond_the_anchors(supplier_risk_config):
    """A supplier better than 'best' is not rewarded with a negative risk."""
    spec = supplier_risk_config.category("delivery").metrics["on_time_delivery_rate"]

    better_than_best, _, _ = normalize_metric(spec, 100.0, supplier_risk_config)
    worse_than_worst, _, _ = normalize_metric(spec, 0.0, supplier_risk_config)

    assert better_than_best == 0.0
    assert worse_than_worst == 100.0


def test_higher_is_worse_metric_runs_the_other_way(supplier_risk_config):
    """A defect rate is inverted relative to a quality score."""
    spec = supplier_risk_config.category("quality").metrics["defect_rate"]

    low_defects, _, _ = normalize_metric(spec, spec.best_value, supplier_risk_config)
    high_defects, _, _ = normalize_metric(spec, spec.worst_value, supplier_risk_config)

    assert low_defects == 0.0
    assert high_defects == 100.0


def test_categorical_metric_uses_the_configured_score_map(supplier_risk_config):
    spec = supplier_risk_config.category("contract").metrics["contract_status"]

    active, _, _ = normalize_metric(spec, "Active", supplier_risk_config)
    none, _, _ = normalize_metric(spec, "No contract", supplier_risk_config)

    assert active == 0.0
    assert none == 100.0


def test_unrecognised_categorical_value_falls_back_and_says_so(supplier_risk_config):
    """An unknown status uses the documented default and is flagged, not hidden."""
    spec = supplier_risk_config.category("contract").metrics["contract_status"]

    score, basis, note = normalize_metric(spec, "Pending legal review", supplier_risk_config)

    assert score == supplier_risk_config.score_map("contract_status").default
    assert note is not None
    assert "not in" in basis


def test_flag_metric_scores_true_and_false(supplier_risk_config):
    spec = supplier_risk_config.category("financial").metrics["financial_distress_flag"]

    flagged, _, _ = normalize_metric(spec, True, supplier_risk_config)
    clear, _, _ = normalize_metric(spec, False, supplier_risk_config)

    assert flagged == spec.flag_true_score
    assert clear == spec.flag_false_score


def test_missing_metric_returns_no_score(supplier_risk_config):
    spec = supplier_risk_config.category("delivery").metrics["on_time_delivery_rate"]

    score, basis, _ = normalize_metric(spec, None, supplier_risk_config)

    assert score is None
    assert "no value" in basis


def test_non_numeric_metric_is_reported_not_raised(supplier_risk_config):
    spec = supplier_risk_config.category("delivery").metrics["on_time_delivery_rate"]

    score, _, note = normalize_metric(spec, "not a number", supplier_risk_config)

    assert score is None
    assert note is not None


# ---------------------------------------------------------------------------
# Category scoring and weighting
# ---------------------------------------------------------------------------


def test_category_score_is_the_weighted_blend_of_its_metrics(supplier_risk_config):
    """The category score equals sum(normalised_weight * normalised_score)."""
    profile = make_risk_profile()
    spec = supplier_risk_config.category("delivery")

    result = score_category("delivery", spec, profile, 15.0, supplier_risk_config, RISK_AS_OF)

    expected = sum(
        metric.normalized_weight * metric.normalized_score
        for metric in result.metrics
        if metric.available
    )
    assert result.score == pytest.approx(expected, abs=0.01)


def test_every_metric_reports_its_own_contribution(supplier_risk_config):
    """Transparency requirement: each metric shows value, weight, score, contribution."""
    profile = make_risk_profile()
    spec = supplier_risk_config.category("quality")

    result = score_category("quality", spec, profile, 15.0, supplier_risk_config, RISK_AS_OF)

    assert len(result.metrics) == len(spec.metrics)
    for metric in result.metrics:
        assert metric.label
        assert metric.basis
        if metric.available:
            assert metric.contribution == pytest.approx(
                metric.normalized_weight * metric.normalized_score, abs=0.01
            )


def test_metric_weights_are_renormalised_when_one_input_is_missing(supplier_risk_config):
    """A missing metric must not be scored as if it were zero risk."""
    complete = make_risk_profile(defect_rate=8.0, quality_score=65.0, quality_incident_count=10)
    partial = make_risk_profile(defect_rate=8.0, quality_score=65.0, quality_incident_count=None)
    spec = supplier_risk_config.category("quality")

    full = score_category("quality", spec, complete, 15.0, supplier_risk_config, RISK_AS_OF)
    reduced = score_category("quality", spec, partial, 15.0, supplier_risk_config, RISK_AS_OF)

    available_weights = [m.normalized_weight for m in reduced.metrics if m.available]
    assert sum(available_weights) == pytest.approx(1.0, abs=0.001)
    assert "quality_incident_count" in reduced.missing_metrics
    # Both are worst-case on the remaining metrics, so both stay at maximum risk.
    assert full.score == pytest.approx(100.0, abs=0.01)
    assert reduced.score == pytest.approx(100.0, abs=0.01)


def test_category_with_no_data_is_reported_as_unavailable(supplier_risk_config):
    profile = make_risk_profile(
        compliance_finding_count=None, certification_status=None, audit_status=None
    )
    spec = supplier_risk_config.category("compliance")

    result = score_category("compliance", spec, profile, 10.0, supplier_risk_config, RISK_AS_OF)

    assert result.data_available is False
    assert result.score is None
    assert len(result.missing_metrics) == len(spec.metrics)


def test_overall_score_is_the_weighted_blend_of_the_categories(supplier_risk_config):
    profile = make_risk_profile()

    score = score_supplier(profile, supplier_risk_config.default_weights, supplier_risk_config, RISK_AS_OF)

    expected = sum(
        category.normalized_weight * category.score
        for category in score.categories.values()
        if category.data_available
    )
    assert score.overall_score == pytest.approx(expected, abs=0.01)
    assert score.overall_score == pytest.approx(
        sum(c.contribution for c in score.categories.values() if c.data_available), abs=0.01
    )


def test_all_ten_categories_are_scored_for_a_complete_supplier(supplier_risk_config):
    profile = make_risk_profile()

    score = score_supplier(profile, supplier_risk_config.default_weights, supplier_risk_config, RISK_AS_OF)

    assert set(score.scored_categories) == set(RISK_CATEGORIES)
    assert score.unscored_categories == []
    assert score.data_completeness_pct == pytest.approx(100.0, abs=0.01)


def test_worst_case_supplier_approaches_maximum_risk(supplier_risk_config):
    """Every metric pinned at its configured worst anchor scores near 100."""
    profile = make_risk_profile(
        on_time_delivery_rate=70.0, delivery_count=100, late_delivery_count=30,
        average_delay_days=14.0, quality_score=65.0, defect_rate=8.0, quality_incident_count=10,
        credit_score=35.0, payment_default_count=4, financial_distress_flag=True,
        category_spend_share=70.0, single_source_material_count=6, alternative_supplier_count=0,
        contract_status="No contract", contract_expiration=RISK_AS_OF - timedelta(days=10),
        invoice_count=100, invoice_exception_count=25, disputed_invoice_count=8,
        compliance_finding_count=5, certification_status="Missing", audit_status="Failed",
        esg_score=30.0, country="RU", regions_served=["EU"],
        capacity_utilization=98.0, lead_time_variability_days=15.0, lead_time_days=60,
    )

    score = score_supplier(profile, supplier_risk_config.default_weights, supplier_risk_config, RISK_AS_OF)

    assert score.overall_score is not None
    assert score.overall_score > 90.0
    assert score.overall_band == "critical"


def test_best_case_supplier_approaches_zero_risk(supplier_risk_config):
    profile = make_risk_profile(
        on_time_delivery_rate=99.0, delivery_count=100, late_delivery_count=0,
        average_delay_days=0.0, quality_score=98.0, defect_rate=0.2, quality_incident_count=0,
        credit_score=90.0, payment_default_count=0, financial_distress_flag=False,
        category_spend_share=10.0, single_source_material_count=0, alternative_supplier_count=4,
        contract_status="Active", contract_expiration=RISK_AS_OF + timedelta(days=365),
        invoice_count=100, invoice_exception_count=0, disputed_invoice_count=0,
        compliance_finding_count=0, certification_status="Valid", audit_status="Passed",
        esg_score=85.0, country="DE", regions_served=["EU", "NA", "APAC"],
        capacity_utilization=60.0, lead_time_variability_days=1.0, lead_time_days=7,
    )

    score = score_supplier(profile, supplier_risk_config.default_weights, supplier_risk_config, RISK_AS_OF)

    assert score.overall_score is not None
    assert score.overall_score < 5.0
    assert score.overall_band == "low"


def test_weights_change_the_outcome(supplier_risk_config):
    """Re-weighting toward a supplier's weak category raises its overall risk."""
    profile = make_risk_profile(
        on_time_delivery_rate=72.0, delivery_count=100, late_delivery_count=28,
        average_delay_days=12.0,
    )
    delivery_heavy = CategoryWeights(
        delivery=91.0, quality=1.0, financial=1.0, spend_concentration=1.0, contract=1.0,
        invoice=1.0, compliance=1.0, esg=1.0, geographic=1.0, operational=1.0,
    )

    balanced = score_supplier(
        profile, supplier_risk_config.default_weights, supplier_risk_config, RISK_AS_OF
    )
    weighted = score_supplier(profile, delivery_heavy, supplier_risk_config, RISK_AS_OF)

    assert weighted.overall_score > balanced.overall_score


def test_weights_that_do_not_sum_to_the_total_are_rejected(supplier_risk_config):
    broken = CategoryWeights(
        delivery=50.0, quality=50.0, financial=50.0, spend_concentration=0.0, contract=0.0,
        invoice=0.0, compliance=0.0, esg=0.0, geographic=0.0, operational=0.0,
    )

    with pytest.raises(ConfigurationError):
        supplier_risk_config.validate_weights(broken)


# ---------------------------------------------------------------------------
# Missing data handling
# ---------------------------------------------------------------------------


def test_category_weights_are_renormalised_over_available_categories(supplier_risk_config):
    """With a category missing, the remaining weights still represent 100%."""
    profile = make_risk_profile(
        compliance_finding_count=None, certification_status=None, audit_status=None
    )

    score = score_supplier(profile, supplier_risk_config.default_weights, supplier_risk_config, RISK_AS_OF)

    assert "compliance" in score.unscored_categories
    available = [c for c in score.categories.values() if c.data_available]
    assert sum(c.normalized_weight for c in available) == pytest.approx(1.0, abs=0.001)


def test_overall_score_is_withheld_when_too_few_categories_have_data(supplier_risk_config):
    """The lab withholds an overall figure rather than computing it from a fragment."""
    sparse = make_risk_profile(
        **{
            name: None
            for name in (
                "quality_score", "defect_rate", "quality_incident_count", "credit_score",
                "payment_default_count", "financial_distress_flag", "category_spend_share",
                "single_source_material_count", "alternative_supplier_count", "contract_status",
                "contract_expiration", "invoice_count", "invoice_exception_count",
                "disputed_invoice_count", "compliance_finding_count", "certification_status",
                "audit_status", "esg_score", "country", "capacity_utilization",
                "lead_time_variability_days", "lead_time_days",
            )
        },
        regions_served=[],
    )

    score = score_supplier(sparse, supplier_risk_config.default_weights, supplier_risk_config, RISK_AS_OF)

    assert score.overall_score is None
    assert score.overall_band is None
    assert score.limited_data is True


def test_limited_data_is_flagged_below_the_configured_completeness(supplier_risk_config):
    profile = make_risk_profile(
        quality_score=None, defect_rate=None, quality_incident_count=None,
        credit_score=None, payment_default_count=None, financial_distress_flag=None,
        compliance_finding_count=None, certification_status=None, audit_status=None,
        esg_score=None,
    )

    score = score_supplier(profile, supplier_risk_config.default_weights, supplier_risk_config, RISK_AS_OF)

    assert score.data_completeness_pct < supplier_risk_config.missing_data.flag_below_completeness_pct
    assert score.limited_data is True


def test_a_missing_metric_never_silently_scores_as_zero_risk(supplier_risk_config):
    """The bug this guards: treating 'no data' as 'no problem'."""
    unknown_quality = make_risk_profile(
        quality_score=None, defect_rate=None, quality_incident_count=None
    )

    score = score_supplier(
        unknown_quality, supplier_risk_config.default_weights, supplier_risk_config, RISK_AS_OF
    )

    quality = score.categories["quality"]
    assert quality.data_available is False
    assert quality.score is None
    assert quality.contribution == 0.0
    assert "quality" not in score.scored_categories


# ---------------------------------------------------------------------------
# Risk categorisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, "low"),
        (24.99, "low"),
        (25.0, "medium"),
        (49.99, "medium"),
        (50.0, "high"),
        (74.99, "high"),
        (75.0, "critical"),
        (100.0, "critical"),
    ],
)
def test_risk_bands_classify_the_whole_scale(supplier_risk_config, score, expected):
    assert supplier_risk_config.band_for(score) == expected


def test_band_is_none_when_there_is_no_score(supplier_risk_config):
    assert supplier_risk_config.band_for(None) is None


def test_every_category_carries_its_own_band(supplier_risk_config):
    profile = make_risk_profile()

    score = score_supplier(profile, supplier_risk_config.default_weights, supplier_risk_config, RISK_AS_OF)

    for category in score.categories.values():
        if category.data_available:
            assert category.band in supplier_risk_config.risk_bands.labels


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


def test_trend_is_unknown_without_enough_dated_records(supplier_risk_config):
    trend = compute_trend([make_risk_event()], supplier_risk_config, RISK_AS_OF)

    assert trend.direction == "unknown"
    assert trend.data_available is False


def test_trend_deteriorates_when_recent_records_outweigh_earlier_ones(supplier_risk_config):
    window = supplier_risk_config.trend.window_days
    events = [
        make_risk_event(event_id=f"R-{i}", severity="high", event_date=RISK_AS_OF - timedelta(days=10))
        for i in range(4)
    ] + [
        make_risk_event(
            event_id="P-1", severity="low", event_date=RISK_AS_OF - timedelta(days=window + 10)
        )
    ]

    trend = compute_trend(events, supplier_risk_config, RISK_AS_OF)

    assert trend.direction == "deteriorating"
    assert trend.data_available is True
    assert trend.delta > 0


def test_trend_improves_when_earlier_records_outweigh_recent_ones(supplier_risk_config):
    window = supplier_risk_config.trend.window_days
    events = [
        make_risk_event(
            event_id=f"P-{i}", severity="critical",
            event_date=RISK_AS_OF - timedelta(days=window + 10),
        )
        for i in range(4)
    ] + [make_risk_event(event_id="R-1", severity="low", event_date=RISK_AS_OF - timedelta(days=5))]

    trend = compute_trend(events, supplier_risk_config, RISK_AS_OF)

    assert trend.direction == "improving"
    assert trend.delta < 0


def test_trend_ignores_undated_records(supplier_risk_config):
    events = [make_risk_event(event_id=f"U-{i}", event_date=None) for i in range(6)]

    trend = compute_trend(events, supplier_risk_config, RISK_AS_OF)

    assert trend.direction == "unknown"


# ---------------------------------------------------------------------------
# Recommended actions and alternatives
# ---------------------------------------------------------------------------


def test_high_category_risk_triggers_its_recommended_action(supplier_risk_config):
    profile = make_risk_profile(
        on_time_delivery_rate=70.0, delivery_count=100, late_delivery_count=30,
        average_delay_days=14.0,
    )

    result = run_risk_assessment_for([profile])
    actions = result.profiles[0].actions

    assert any(action.category == "delivery" for action in actions)
    triggered = next(action for action in actions if action.category == "delivery")
    assert triggered.trigger
    assert triggered.action


def test_a_healthy_supplier_triggers_no_actions():
    result = run_risk_assessment_for([make_risk_profile()])

    assert result.profiles[0].actions == []


def test_actions_are_capped_at_the_configured_maximum(supplier_risk_config):
    profile = make_risk_profile(
        on_time_delivery_rate=70.0, delivery_count=100, late_delivery_count=30,
        average_delay_days=14.0, quality_score=65.0, defect_rate=8.0, quality_incident_count=10,
        credit_score=35.0, payment_default_count=4, financial_distress_flag=True,
        category_spend_share=70.0, single_source_material_count=6, alternative_supplier_count=0,
        contract_status="No contract", contract_expiration=None,
        invoice_count=100, invoice_exception_count=25, disputed_invoice_count=8,
        compliance_finding_count=5, certification_status="Missing", audit_status="Failed",
        esg_score=30.0, country="RU", capacity_utilization=98.0,
        lead_time_variability_days=15.0, lead_time_days=60,
    )

    result = run_risk_assessment_for([profile])

    assert len(result.profiles[0].actions) <= supplier_risk_config.actions.max_actions


def test_alternatives_must_share_a_category_and_beat_the_margin(supplier_risk_config):
    risky = make_risk_profile(
        supplier_id="0000300002", supplier_name="Risky BV", spend_category="Components",
        on_time_delivery_rate=70.0, delivery_count=100, late_delivery_count=30,
        quality_score=65.0, defect_rate=8.0,
    )
    safe = make_risk_profile(
        supplier_id="0000300003", supplier_name="Safe SA", spend_category="Components"
    )
    unrelated = make_risk_profile(
        supplier_id="0000300004", supplier_name="Other GmbH", spend_category="Logistics",
        materials_supplied=["MAT-9999"],
    )

    result = run_risk_assessment_for([risky, safe, unrelated])
    target = result.by_id("0000300002")
    alternatives = find_alternatives(target, result.profiles, supplier_risk_config)

    ids = [item.supplier_id for item in alternatives]
    assert "0000300003" in ids
    assert "0000300004" not in ids


def test_no_alternative_is_offered_when_none_is_meaningfully_better(supplier_risk_config):
    first = make_risk_profile(supplier_id="0000300002", spend_category="Components")
    second = make_risk_profile(supplier_id="0000300003", spend_category="Components")

    result = run_risk_assessment_for([first, second])
    alternatives = find_alternatives(result.by_id("0000300002"), result.profiles, supplier_risk_config)

    assert alternatives == []


# ---------------------------------------------------------------------------
# Engine behaviour
# ---------------------------------------------------------------------------


def test_assessment_is_deterministic():
    """Two runs over the same records produce identical scores."""
    profiles = [
        make_risk_profile(supplier_id="0000300002", on_time_delivery_rate=80.0),
        make_risk_profile(supplier_id="0000300001"),
    ]

    first = run_risk_assessment_for(profiles)
    second = run_risk_assessment_for(list(reversed(profiles)))

    assert [p.supplier_id for p in first.profiles] == [p.supplier_id for p in second.profiles]
    assert [p.overall_score for p in first.profiles] == [p.overall_score for p in second.profiles]


def test_contracts_expiring_are_counted_against_the_as_of_date(supplier_risk_config):
    window = supplier_risk_config.contract_expiry.expiring_within_days
    soon = make_risk_profile(
        supplier_id="0000300002", contract_expiration=RISK_AS_OF + timedelta(days=window - 10)
    )
    later = make_risk_profile(
        supplier_id="0000300003", contract_expiration=RISK_AS_OF + timedelta(days=window + 60)
    )

    result = run_risk_assessment_for([soon, later])

    assert result.contracts_expiring_count == 1
    assert result.by_id("0000300002").contract_expiring_soon is True
    assert result.by_id("0000300003").contract_expiring_soon is False


def test_one_broken_category_does_not_fail_the_whole_assessment(tmp_path):
    """Rule isolation: a broken category is reported, the rest still score."""
    from pathlib import Path

    source = Path("app/modules/supplier_risk/config/supplier_risk_rules.json")
    raw = json.loads(source.read_text(encoding="utf-8"))
    config = load_supplier_risk_config(_write_json(tmp_path / "rules.json", raw))

    # Break one category the way a bad edit would: the geographic category still
    # references the country score map, but the map is gone.
    del config.score_maps["country_risk_index"]

    errors: list[dict] = []
    score = score_supplier(
        make_risk_profile(), config.default_weights, config, RISK_AS_OF, errors=errors
    )

    assert errors
    assert errors[0]["category"] == "geographic"
    assert score.categories["geographic"].data_available is False
    assert score.overall_score is not None
    assert "delivery" in score.scored_categories


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Configuration drives the outcome
# ---------------------------------------------------------------------------


def test_config_edit_changes_outcome_with_no_code_change(tmp_path):
    """Editing the JSON thresholds must change the result on its own."""
    from pathlib import Path

    source = Path("app/modules/supplier_risk/config/supplier_risk_rules.json")
    raw = json.loads(source.read_text(encoding="utf-8"))

    default_config = load_supplier_risk_config(_write_json(tmp_path / "default.json", raw))
    profile = make_risk_profile(on_time_delivery_rate=90.0)
    before = run_risk_assessment_for([profile], config=default_config)

    # Tighten the on-time anchor: 90% is now much closer to the worst case.
    raw["categories"]["delivery"]["metrics"]["on_time_delivery_rate"]["worst_value"] = 89.0
    strict_config = load_supplier_risk_config(_write_json(tmp_path / "strict.json", raw))
    after = run_risk_assessment_for([profile], config=strict_config)

    assert after.profiles[0].category_score("delivery") > before.profiles[0].category_score("delivery")
    assert after.profiles[0].overall_score > before.profiles[0].overall_score


def test_config_edit_can_rebalance_the_risk_bands(tmp_path):
    from pathlib import Path

    source = Path("app/modules/supplier_risk/config/supplier_risk_rules.json")
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["risk_bands"]["bands"] = [
        {"label": "acceptable", "min_score": 0.0, "max_score": 60.0},
        {"label": "unacceptable", "min_score": 60.0, "max_score": 100.0},
    ]
    raw["actions"]["trigger_band"] = "unacceptable"

    config = load_supplier_risk_config(_write_json(tmp_path / "bands.json", raw))

    assert config.band_for(10.0) == "acceptable"
    assert config.band_for(80.0) == "unacceptable"


def test_country_risk_index_is_configurable(tmp_path, supplier_risk_config):
    from pathlib import Path

    source = Path("app/modules/supplier_risk/config/supplier_risk_rules.json")
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["score_maps"]["country_risk_index"]["values"]["DE"] = 95.0

    config = load_supplier_risk_config(_write_json(tmp_path / "country.json", raw))
    profile = make_risk_profile(country="DE")

    before = run_risk_assessment_for([profile], config=supplier_risk_config)
    after = run_risk_assessment_for([profile], config=config)

    assert after.profiles[0].category_score("geographic") > before.profiles[0].category_score(
        "geographic"
    )


def test_invalid_configuration_is_rejected_with_a_clear_error(tmp_path):
    raw = {"config_version": "1.0.0"}

    with pytest.raises(ConfigurationError):
        load_supplier_risk_config(_write_json(tmp_path / "broken.json", raw))


def test_missing_configuration_file_is_reported(tmp_path):
    with pytest.raises(ConfigurationError):
        load_supplier_risk_config(tmp_path / "does_not_exist.json")
