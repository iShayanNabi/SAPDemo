"""Integration tests for the Supplier Risk Copilot against the demo dataset.

The scenario manifest is the specification. These tests upload the real
generated files through the HTTP API and assert that every documented anchor
behaves exactly as the manifest claims, that the recorded baseline still
reproduces, and that the copilot answers from the same figures the API returns.

If the engine, the configuration or the generator drifts, one of these fails.
"""

from __future__ import annotations

from datetime import date

import pytest

CSV_MIME = "text/csv"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _anchor(manifest: dict, scenario_id: str) -> dict:
    return next(item for item in manifest["scenarios"] if item["scenario_id"] == scenario_id)


def _upload(api_client, path, dataset, mime=CSV_MIME, dataset_id=None):
    payload = {"dataset": dataset}
    if dataset_id:
        payload["dataset_id"] = dataset_id
    response = api_client.post(
        "/api/v1/supplier-risk/upload",
        files={"file": (path.name, path.read_bytes(), mime)},
        data=payload,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    return body["data"]


@pytest.fixture(scope="module")
def sample_assessment(
    api_client,
    supplier_risk_sample_csv_path,
    supplier_risk_event_sample_csv_path,
    supplier_risk_scenario_manifest,
):
    """Upload the real demo files and run the documented assessment."""
    profiles = _upload(api_client, supplier_risk_sample_csv_path, "profiles")
    _upload(
        api_client,
        supplier_risk_event_sample_csv_path,
        "events",
        dataset_id=profiles["dataset_id"],
    )
    response = api_client.post(
        "/api/v1/supplier-risk/calculate",
        json={
            "dataset_id": profiles["dataset_id"],
            "as_of_date": supplier_risk_scenario_manifest["as_of_date"],
        },
    )
    assert response.status_code == 200, response.text
    return {"dataset": profiles, "assessment": response.json()["data"]}


def _supplier(api_client, sample_assessment, supplier_id):
    assessment_id = sample_assessment["assessment"]["assessment_id"]
    response = api_client.get(
        f"/api/v1/supplier-risk/suppliers/{supplier_id}",
        params={"assessment_id": assessment_id},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _category(profile: dict, name: str) -> dict:
    return next(item for item in profile["categories"] if item["category"] == name)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_demo_files_map_without_manual_correction(sample_assessment):
    """SAP technical headers must map with no user intervention."""
    dataset = sample_assessment["dataset"]

    assert dataset["is_analyzable"] is True
    assert dataset["missing_required_fields"] == []
    assert dataset["unmapped_columns"] == []


def test_demo_dataset_loads_without_data_quality_issues(sample_assessment):
    assert sample_assessment["dataset"]["data_quality_issues"] == []


def test_manifest_counts_match_the_loaded_data(
    sample_assessment, supplier_risk_scenario_manifest
):
    summary = sample_assessment["assessment"]["summary"]

    assert summary["supplier_count"] == supplier_risk_scenario_manifest["supplier_count"]
    assert summary["event_count"] == supplier_risk_scenario_manifest["event_count"]


def test_no_rule_errors_on_the_demo_dataset(sample_assessment):
    assert sample_assessment["assessment"]["rule_errors"] == []


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


def test_assessment_reproduces_the_recorded_baseline(
    sample_assessment, supplier_risk_baseline
):
    summary = sample_assessment["assessment"]["summary"]

    assert summary["supplier_count"] == supplier_risk_baseline["supplier_count"]
    assert summary["scored_count"] == supplier_risk_baseline["scored_count"]
    assert summary["event_count"] == supplier_risk_baseline["event_count"]
    assert summary["band_counts"] == supplier_risk_baseline["band_counts"]
    assert summary["average_overall_score"] == supplier_risk_baseline["average_overall_score"]
    assert summary["highest_risk_supplier_id"] == supplier_risk_baseline[
        "highest_risk_supplier_id"
    ]
    assert summary["highest_risk_score"] == supplier_risk_baseline["highest_risk_score"]
    assert summary["contracts_expiring_count"] == supplier_risk_baseline[
        "contracts_expiring_count"
    ]
    assert summary["limited_data_count"] == supplier_risk_baseline["limited_data_count"]


def test_category_averages_reproduce_the_baseline(sample_assessment, supplier_risk_baseline):
    assert (
        sample_assessment["assessment"]["summary"]["category_averages"]
        == supplier_risk_baseline["category_averages"]
    )


def test_top_five_ranking_reproduces_the_baseline(sample_assessment, supplier_risk_baseline):
    suppliers = sample_assessment["assessment"]["suppliers"][:5]

    for expected, actual in zip(supplier_risk_baseline["top_five"], suppliers, strict=True):
        assert actual["rank"] == expected["rank"]
        assert actual["supplier_id"] == expected["supplier_id"]
        assert actual["overall_score"] == expected["overall_score"]
        assert actual["overall_band"] == expected["overall_band"]


def test_engine_and_config_versions_match_the_baseline(
    sample_assessment, supplier_risk_baseline
):
    assessment = sample_assessment["assessment"]

    assert assessment["config_version"] == supplier_risk_baseline["config_version"]
    assert assessment["engine_version"] == supplier_risk_baseline["engine_version"]


# ---------------------------------------------------------------------------
# Documented anchors
# ---------------------------------------------------------------------------


def test_srk01_is_the_highest_overall_risk_supplier(
    api_client, sample_assessment, supplier_risk_scenario_manifest
):
    anchor = _anchor(supplier_risk_scenario_manifest, "SRK-01")
    summary = sample_assessment["assessment"]["summary"]

    assert summary["highest_risk_supplier_id"] == anchor["supplier_id"]
    profile = _supplier(api_client, sample_assessment, anchor["supplier_id"])
    assert profile["overall_band"] == "critical"


@pytest.mark.parametrize(
    ("scenario_id", "category"),
    [
        ("SRK-02", "delivery"),
        ("SRK-03", "quality"),
        ("SRK-04", "financial"),
        ("SRK-05", "spend_concentration"),
        ("SRK-07", "invoice"),
        ("SRK-08", "compliance"),
    ],
)
def test_each_category_anchor_tops_its_own_category(
    api_client, sample_assessment, supplier_risk_scenario_manifest, scenario_id, category
):
    """Each anchor must genuinely be the worst supplier in the category it anchors."""
    anchor = _anchor(supplier_risk_scenario_manifest, scenario_id)
    assessment_id = sample_assessment["assessment"]["assessment_id"]

    listing = api_client.get(
        "/api/v1/supplier-risk/suppliers",
        params={"assessment_id": assessment_id, "limit": 1000},
    ).json()["data"]["suppliers"]

    scored = [
        item for item in listing if item["category_scores"].get(category) is not None
    ]
    worst = max(scored, key=lambda item: item["category_scores"][category])
    assert worst["supplier_id"] == anchor["supplier_id"]


def test_srk06_contract_expires_inside_the_critical_window(
    api_client, sample_assessment, supplier_risk_scenario_manifest, supplier_risk_config
):
    anchor = _anchor(supplier_risk_scenario_manifest, "SRK-06")
    profile = _supplier(api_client, sample_assessment, anchor["supplier_id"])

    assert profile["contract_expiring_soon"] is True
    assert profile["days_to_contract_expiry"] is not None
    assert (
        profile["days_to_contract_expiry"]
        <= supplier_risk_config.contract_expiry.critical_within_days
    )


def test_srk06_appears_in_the_expiring_contracts_filter(
    api_client, sample_assessment, supplier_risk_scenario_manifest
):
    anchor = _anchor(supplier_risk_scenario_manifest, "SRK-06")
    assessment_id = sample_assessment["assessment"]["assessment_id"]

    listing = api_client.get(
        "/api/v1/supplier-risk/suppliers",
        params={"assessment_id": assessment_id, "expiring_only": True, "limit": 1000},
    ).json()["data"]

    assert anchor["supplier_id"] in {item["supplier_id"] for item in listing["suppliers"]}


def test_srk09_has_no_overall_score_because_data_is_missing(
    api_client, sample_assessment, supplier_risk_scenario_manifest
):
    """The missing-data anchor must be withheld, not guessed."""
    anchor = _anchor(supplier_risk_scenario_manifest, "SRK-09")
    profile = _supplier(api_client, sample_assessment, anchor["supplier_id"])

    assert profile["overall_score"] is None
    assert profile["overall_band"] is None
    assert profile["limited_data"] is True
    assert len(profile["scored_categories"]) < 3


def test_srk09_is_the_only_unscored_supplier(sample_assessment, supplier_risk_scenario_manifest):
    anchor = _anchor(supplier_risk_scenario_manifest, "SRK-09")
    unscored = [
        item
        for item in sample_assessment["assessment"]["suppliers"]
        if item["overall_score"] is None
    ]

    assert [item["supplier_id"] for item in unscored] == [anchor["supplier_id"]]


def test_every_anchor_is_present_in_the_assessment(
    sample_assessment, supplier_risk_scenario_manifest
):
    loaded = {item["supplier_id"] for item in sample_assessment["assessment"]["suppliers"]}

    for scenario in supplier_risk_scenario_manifest["scenarios"]:
        assert scenario["supplier_id"] in loaded, scenario["scenario_id"]


# ---------------------------------------------------------------------------
# Transparency
# ---------------------------------------------------------------------------


def test_contributions_sum_to_the_overall_score(api_client, sample_assessment):
    """The audit trail must add up: contributions reconstruct the score."""
    profile = _supplier(api_client, sample_assessment, "0000300001")

    total = sum(
        item["contribution"] for item in profile["categories"] if item["data_available"]
    )
    assert total == pytest.approx(profile["overall_score"], abs=0.05)


def test_metric_contributions_sum_to_their_category_score(api_client, sample_assessment):
    profile = _supplier(api_client, sample_assessment, "0000300001")

    for category in profile["categories"]:
        if not category["data_available"]:
            continue
        total = sum(item["contribution"] for item in category["metrics"] if item["available"])
        assert total == pytest.approx(category["score"], abs=0.05), category["category"]


def test_every_metric_explains_how_it_was_scored(api_client, sample_assessment):
    profile = _supplier(api_client, sample_assessment, "0000300001")

    for category in profile["categories"]:
        for metric in category["metrics"]:
            assert metric["basis"], f"{category['category']}.{metric['metric']}"


# ---------------------------------------------------------------------------
# Copilot over the demo dataset
# ---------------------------------------------------------------------------


def _ask(api_client, sample_assessment, question, supplier_id=None):
    payload = {
        "question": question,
        "assessment_id": sample_assessment["assessment"]["assessment_id"],
    }
    if supplier_id:
        payload["supplier_id"] = supplier_id
    response = api_client.post("/api/v1/supplier-risk/chat", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_copilot_reports_the_same_score_the_api_returns(api_client, sample_assessment):
    """The copilot and the supplier page must never disagree."""
    profile = _supplier(api_client, sample_assessment, "0000300001")
    answer = _ask(api_client, sample_assessment, "Show supplier 0000300001 risk.")

    assert f"{profile['overall_score']:g}" in answer["answer"]
    cited = next(
        item for item in answer["citations"] if item["field_name"] == "overall_score"
    )
    assert cited["value"] == profile["overall_score"]


def test_copilot_delivery_ranking_matches_the_delivery_anchor(
    api_client, sample_assessment, supplier_risk_scenario_manifest
):
    anchor = _anchor(supplier_risk_scenario_manifest, "SRK-02")
    answer = _ask(
        api_client, sample_assessment, "Which suppliers have the most delivery issues?"
    )

    assert answer["suppliers_referenced"][0] == anchor["supplier_id"]


def test_copilot_lists_the_expiring_contract_anchor(
    api_client, sample_assessment, supplier_risk_scenario_manifest
):
    anchor = _anchor(supplier_risk_scenario_manifest, "SRK-06")
    answer = _ask(
        api_client, sample_assessment, "Which suppliers have contracts expiring soon?"
    )

    assert anchor["supplier_id"] in answer["suppliers_referenced"]


def test_copilot_explains_the_highest_risk_supplier(api_client, sample_assessment):
    answer = _ask(
        api_client,
        sample_assessment,
        "Why is this supplier high risk?",
        supplier_id="0000300001",
    )

    assert answer["data_available"] is True
    assert answer["citations"]
    assert answer["intent"] == "why_risk"


def test_copilot_refuses_to_score_the_missing_data_anchor(
    api_client, sample_assessment, supplier_risk_scenario_manifest
):
    anchor = _anchor(supplier_risk_scenario_manifest, "SRK-09")
    answer = _ask(
        api_client,
        sample_assessment,
        "Why is this supplier high risk?",
        supplier_id=anchor["supplier_id"],
    )

    assert answer["data_available"] is False
    assert answer["unavailable_reason"] == "insufficient_data_for_score"


def test_copilot_cites_only_loaded_suppliers(api_client, sample_assessment):
    loaded = {item["supplier_id"] for item in sample_assessment["assessment"]["suppliers"]}

    for question in (
        "Which suppliers are the highest risk?",
        "Which suppliers have the most delivery issues?",
        "What action should procurement take?",
        "Which suppliers have contracts expiring soon?",
    ):
        answer = _ask(api_client, sample_assessment, question)
        assert set(answer["suppliers_referenced"]) <= loaded


# ---------------------------------------------------------------------------
# Determinism and format equivalence
# ---------------------------------------------------------------------------


def test_repeated_assessments_are_identical(
    api_client, sample_assessment, supplier_risk_scenario_manifest
):
    response = api_client.post(
        "/api/v1/supplier-risk/calculate",
        json={
            "dataset_id": sample_assessment["dataset"]["dataset_id"],
            "as_of_date": supplier_risk_scenario_manifest["as_of_date"],
        },
    )
    repeat = response.json()["data"]

    first = sample_assessment["assessment"]
    assert repeat["summary"]["band_counts"] == first["summary"]["band_counts"]
    assert repeat["summary"]["average_overall_score"] == first["summary"][
        "average_overall_score"
    ]
    assert [item["supplier_id"] for item in repeat["suppliers"]] == [
        item["supplier_id"] for item in first["suppliers"]
    ]
    assert [item["overall_score"] for item in repeat["suppliers"]] == [
        item["overall_score"] for item in first["suppliers"]
    ]


def test_xlsx_business_labels_produce_the_same_scores(
    api_client,
    sample_assessment,
    supplier_risk_sample_xlsx_path,
    supplier_risk_scenario_manifest,
):
    """The XLSX uses business labels, the CSV SAP codes; both must score alike."""
    uploaded = _upload(api_client, supplier_risk_sample_xlsx_path, "profiles", XLSX_MIME)
    assert uploaded["is_analyzable"] is True

    response = api_client.post(
        "/api/v1/supplier-risk/calculate",
        json={
            "dataset_id": uploaded["dataset_id"],
            "as_of_date": supplier_risk_scenario_manifest["as_of_date"],
        },
    )
    xlsx_assessment = response.json()["data"]

    csv_scores = {
        item["supplier_id"]: item["overall_score"]
        for item in sample_assessment["assessment"]["suppliers"]
    }
    xlsx_scores = {
        item["supplier_id"]: item["overall_score"] for item in xlsx_assessment["suppliers"]
    }
    assert xlsx_scores == csv_scores


def test_as_of_date_changes_contract_expiry_reporting(
    api_client, sample_assessment, supplier_risk_scenario_manifest
):
    """Moving the reference date forward brings more contracts into the window."""
    manifest_date = date.fromisoformat(supplier_risk_scenario_manifest["as_of_date"])
    later = manifest_date.replace(year=manifest_date.year + 1)

    response = api_client.post(
        "/api/v1/supplier-risk/calculate",
        json={
            "dataset_id": sample_assessment["dataset"]["dataset_id"],
            "as_of_date": later.isoformat(),
        },
    )
    later_assessment = response.json()["data"]

    assert (
        later_assessment["summary"]["contracts_expiring_count"]
        >= sample_assessment["assessment"]["summary"]["contracts_expiring_count"]
    )


# ---------------------------------------------------------------------------
# Aggregate stability
#
# The invoice category average over this dataset is exactly 20.195 - a value
# that sits precisely on a two-decimal rounding tie. Summing the 54 supplier
# scores in binary floating point drifts by ~1e-15, which was enough to report
# 20.19 on one interpreter and 20.20 on another from identical inputs. These
# assert that the aggregate no longer depends on anything but the data.
# ---------------------------------------------------------------------------


def test_the_invoice_average_sits_on_a_rounding_tie(
    supplier_risk_sample_csv_path,
    supplier_risk_event_sample_csv_path,
    supplier_risk_scenario_manifest,
    supplier_risk_config,
):
    """Pin the condition itself, so a data change that removes it is visible."""
    from decimal import Decimal

    result = _run_engine_directly(
        supplier_risk_sample_csv_path,
        supplier_risk_event_sample_csv_path,
        supplier_risk_scenario_manifest,
        supplier_risk_config,
    )
    scores = [
        profile.score.categories["invoice"].score
        for profile in result.profiles
        if "invoice" in profile.score.categories
        and profile.score.categories["invoice"].score is not None
    ]

    exact_mean = sum(Decimal(str(score)) for score in scores) / len(scores)
    assert exact_mean == Decimal("20.195"), (
        "the regression this guards depends on the mean landing on a tie; "
        f"it is now {exact_mean}"
    )
    assert result.category_averages["invoice"] == 20.2


def test_repeated_runs_produce_identical_aggregates(
    supplier_risk_sample_csv_path,
    supplier_risk_event_sample_csv_path,
    supplier_risk_scenario_manifest,
    supplier_risk_config,
):
    """The same files must produce the same figures on every run."""
    runs = [
        _run_engine_directly(
            supplier_risk_sample_csv_path,
            supplier_risk_event_sample_csv_path,
            supplier_risk_scenario_manifest,
            supplier_risk_config,
        )
        for _ in range(5)
    ]

    first = runs[0]
    for other in runs[1:]:
        assert other.category_averages == first.category_averages
        assert other.average_overall_score == first.average_overall_score
        assert other.band_counts == first.band_counts


def test_aggregates_do_not_depend_on_supplier_order(
    supplier_risk_sample_csv_path,
    supplier_risk_event_sample_csv_path,
    supplier_risk_scenario_manifest,
    supplier_risk_config,
):
    """Reordering the input rows must not move an average.

    This is the defect in its purest form: binary accumulation error depends on
    the order values are added in, so a mean on a tie moved when the rows did.
    """
    import random

    from app.modules.supplier_risk.engine import run_risk_assessment

    profiles, events, as_of = _load_records(
        supplier_risk_sample_csv_path,
        supplier_risk_event_sample_csv_path,
        supplier_risk_scenario_manifest,
        supplier_risk_config,
    )
    baseline = run_risk_assessment(
        profiles, events, supplier_risk_config.default_weights, supplier_risk_config, as_of
    )

    for seed in range(4):
        shuffled = list(profiles)
        random.Random(seed).shuffle(shuffled)
        result = run_risk_assessment(
            shuffled, events, supplier_risk_config.default_weights, supplier_risk_config, as_of
        )

        assert result.category_averages == baseline.category_averages, f"seed {seed}"
        assert result.average_overall_score == baseline.average_overall_score, f"seed {seed}"


def test_the_generator_and_the_api_share_one_calculation_path(
    sample_assessment, supplier_risk_sample_csv_path,
    supplier_risk_event_sample_csv_path, supplier_risk_scenario_manifest,
    supplier_risk_config,
):
    """The baseline generator must not have its own copy of the arithmetic.

    ``scripts/generate_supplier_risk_sample_data.py`` and
    ``app/modules/supplier_risk/service.py`` both call ``run_risk_assessment``.
    Calling the engine directly here and comparing against the figures the HTTP
    API returned proves the two agree, so a baseline recorded by the generator
    is a statement about what the API will actually serve.
    """
    import scripts.generate_supplier_risk_sample_data as generator
    from app.modules.supplier_risk import service
    from app.modules.supplier_risk.engine import run_risk_assessment

    # Neither has its own copy: both hold the identical function object.
    assert generator.run_risk_assessment is run_risk_assessment
    assert service.run_risk_assessment is run_risk_assessment

    direct = _run_engine_directly(
        supplier_risk_sample_csv_path,
        supplier_risk_event_sample_csv_path,
        supplier_risk_scenario_manifest,
        supplier_risk_config,
    )
    served = sample_assessment["assessment"]["summary"]

    assert direct.category_averages == served["category_averages"]
    assert direct.average_overall_score == served["average_overall_score"]


def _load_records(profiles_path, events_path, manifest, config):
    """Load the sample files through the real reader, mapper and normaliser."""
    from app.modules.supplier_risk.field_definitions import EVENT_REGISTRY, REGISTRY
    from app.modules.supplier_risk.normalizer import (
        normalize_risk_event_dataframe,
        normalize_supplier_risk_dataframe,
    )
    from app.services.files.readers import read_tabular
    from app.services.tabular.mapping import suggest_mapping

    def _load(path, registry, normalise):
        read_result = read_tabular(path.read_bytes(), ".csv")
        mapping = suggest_mapping(read_result.source_columns, registry).mapping
        return normalise(read_result.dataframe, mapping, config)

    profiles = _load(profiles_path, REGISTRY, normalize_supplier_risk_dataframe).profiles
    events = _load(events_path, EVENT_REGISTRY, normalize_risk_event_dataframe).events
    return profiles, events, date.fromisoformat(manifest["as_of_date"])


def _run_engine_directly(profiles_path, events_path, manifest, config):
    """Run the engine over the sample files, bypassing HTTP and the database."""
    from app.modules.supplier_risk.engine import run_risk_assessment

    profiles, events, as_of = _load_records(profiles_path, events_path, manifest, config)
    return run_risk_assessment(profiles, events, config.default_weights, config, as_of)
