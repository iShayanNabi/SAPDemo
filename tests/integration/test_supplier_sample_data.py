"""Integration tests for the Supplier Recommendation Engine sample catalogue.

The scenario manifest is the specification. Each documented anchor supplier has a
test that reads the manifest and checks the engine behaves as documented, end to
end through HTTP, and the ranking is compared against the recorded baseline.
"""

from __future__ import annotations

import copy

import pytest


def _upload_catalog(api_client, csv_path) -> str:
    content = csv_path.read_bytes()
    response = api_client.post(
        "/api/v1/suppliers/upload",
        files={"file": ("sample_suppliers.csv", content, "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["catalog_id"]


def _recommend(api_client, catalog_id, requirement, *, weights=None, generate_ai=False) -> dict:
    body = {"catalog_id": catalog_id, "requirement": requirement, "generate_ai_summary": generate_ai}
    if weights is not None:
        body["weights"] = weights
    response = api_client.post("/api/v1/supplier-recommendations/recommend", json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _anchor(manifest: dict, scenario_id: str) -> dict:
    return next(s for s in manifest["scenarios"] if s["scenario_id"] == scenario_id)


# ---------------------------------------------------------------------------
# Dataset shape
# ---------------------------------------------------------------------------
def test_catalogue_has_at_least_fifty_varied_suppliers(api_client, supplier_sample_csv_path):
    catalog_id = _upload_catalog(api_client, supplier_sample_csv_path)
    listing = api_client.get(
        "/api/v1/suppliers", params={"catalog_id": catalog_id, "limit": 1000}
    ).json()["data"]
    assert listing["total"] >= 50
    suppliers = listing["suppliers"]
    # Variety: more than a handful of distinct prices, lead times and regions.
    assert len({s["unit_price"] for s in suppliers}) > 20
    assert len({s["lead_time_days"] for s in suppliers}) > 5
    regions = {r for s in suppliers for r in s["regions_served"]}
    assert len(regions) >= 3
    currencies = {s["currency"] for s in suppliers}
    assert len(currencies) >= 2


def test_sample_files_are_available_in_three_formats(
    supplier_sample_csv_path, supplier_sample_xlsx_path, supplier_sample_json_path
):
    assert supplier_sample_csv_path.is_file()
    assert supplier_sample_xlsx_path.is_file()
    assert supplier_sample_json_path.is_file()


# ---------------------------------------------------------------------------
# Baseline reproduction and determinism
# ---------------------------------------------------------------------------
def test_canonical_ranking_matches_baseline(
    api_client, supplier_sample_csv_path, supplier_scenario_manifest, supplier_baseline
):
    catalog_id = _upload_catalog(api_client, supplier_sample_csv_path)
    requirement = supplier_scenario_manifest["canonical_requirement"]
    data = _recommend(api_client, catalog_id, requirement)

    assert data["eligible_count"] == supplier_baseline["eligible_count"]
    assert data["ineligible_count"] == supplier_baseline["ineligible_count"]
    assert data["top_supplier_id"] == supplier_baseline["top_supplier_id"]

    eligible = [e for e in data["results"] if e["is_eligible"]]
    top_five = [
        {"rank": e["rank"], "supplier_id": e["supplier_id"], "overall_score": e["overall_score"]}
        for e in eligible[:5]
    ]
    assert top_five == supplier_baseline["top_five"]


def test_repeated_recommendations_are_identical(
    api_client, supplier_sample_csv_path, supplier_scenario_manifest
):
    catalog_id = _upload_catalog(api_client, supplier_sample_csv_path)
    requirement = supplier_scenario_manifest["canonical_requirement"]
    first = _recommend(api_client, catalog_id, requirement)
    second = _recommend(api_client, catalog_id, requirement)
    assert [(e["supplier_id"], e["rank"], e["overall_score"]) for e in first["results"]] == \
           [(e["supplier_id"], e["rank"], e["overall_score"]) for e in second["results"]]


# ---------------------------------------------------------------------------
# Documented anchor scenarios
# ---------------------------------------------------------------------------
def test_sr01_lowest_cost_wins_on_all_cost_weights(
    api_client, supplier_sample_csv_path, supplier_scenario_manifest
):
    catalog_id = _upload_catalog(api_client, supplier_sample_csv_path)
    anchor = _anchor(supplier_scenario_manifest, "SR-01")
    weights = {
        "cost": 100, "delivery": 0, "quality": 0, "capacity": 0, "risk": 0,
        "esg": 0, "contract": 0, "geographic": 0, "past_performance": 0,
    }
    data = _recommend(
        api_client, catalog_id, supplier_scenario_manifest["canonical_requirement"], weights=weights
    )
    winner = next(e for e in data["results"] if e["rank"] == 1)
    assert winner["supplier_id"] == anchor["supplier_id"]
    assert winner["cost_score"] == 100.0


def test_sr02_high_risk_toggles_with_tolerance(
    api_client, supplier_sample_csv_path, supplier_scenario_manifest
):
    catalog_id = _upload_catalog(api_client, supplier_sample_csv_path)
    anchor_id = _anchor(supplier_scenario_manifest, "SR-02")["supplier_id"]
    base_requirement = supplier_scenario_manifest["canonical_requirement"]

    at_medium = _recommend(api_client, catalog_id, base_requirement)
    by_id = {e["supplier_id"]: e for e in at_medium["results"]}
    assert by_id[anchor_id]["eligibility_status"] == "ineligible"

    high = copy.deepcopy(base_requirement)
    high["risk_tolerance"] = "high"
    at_high = _recommend(api_client, catalog_id, high)
    by_id_high = {e["supplier_id"]: e for e in at_high["results"]}
    assert by_id_high[anchor_id]["eligibility_status"] == "eligible"


def test_sr03_wrong_material_is_ineligible(
    api_client, supplier_sample_csv_path, supplier_scenario_manifest
):
    catalog_id = _upload_catalog(api_client, supplier_sample_csv_path)
    anchor_id = _anchor(supplier_scenario_manifest, "SR-03")["supplier_id"]
    data = _recommend(api_client, catalog_id, supplier_scenario_manifest["canonical_requirement"])
    entry = {e["supplier_id"]: e for e in data["results"]}[anchor_id]
    assert entry["eligibility_status"] == "ineligible"
    assert any("material" in r.lower() for r in entry["ineligibility_reasons"])


def test_sr04_weak_esg_toggles_with_sustainability(
    api_client, supplier_sample_csv_path, supplier_scenario_manifest
):
    catalog_id = _upload_catalog(api_client, supplier_sample_csv_path)
    anchor_id = _anchor(supplier_scenario_manifest, "SR-04")["supplier_id"]
    base_requirement = supplier_scenario_manifest["canonical_requirement"]

    canonical = _recommend(api_client, catalog_id, base_requirement)
    assert {e["supplier_id"]: e for e in canonical["results"]}[anchor_id]["eligibility_status"] == "eligible"

    strict = copy.deepcopy(base_requirement)
    strict["sustainability_requirement"] = 70
    with_floor = _recommend(api_client, catalog_id, strict)
    entry = {e["supplier_id"]: e for e in with_floor["results"]}[anchor_id]
    assert entry["eligibility_status"] == "ineligible"
    assert any("esg" in r.lower() for r in entry["ineligibility_reasons"])


def test_sr05_no_contract_toggles_with_contract_requirement(
    api_client, supplier_sample_csv_path, supplier_scenario_manifest
):
    catalog_id = _upload_catalog(api_client, supplier_sample_csv_path)
    anchor_id = _anchor(supplier_scenario_manifest, "SR-05")["supplier_id"]
    base_requirement = supplier_scenario_manifest["canonical_requirement"]

    canonical = _recommend(api_client, catalog_id, base_requirement)
    assert {e["supplier_id"]: e for e in canonical["results"]}[anchor_id]["eligibility_status"] == "eligible"

    strict = copy.deepcopy(base_requirement)
    strict["contract_requirement"] = True
    required = _recommend(api_client, catalog_id, strict)
    entry = {e["supplier_id"]: e for e in required["results"]}[anchor_id]
    assert entry["eligibility_status"] == "ineligible"
    assert any("contract" in r.lower() for r in entry["ineligibility_reasons"])


def test_sr06_low_capacity_is_ineligible_for_canonical(
    api_client, supplier_sample_csv_path, supplier_scenario_manifest
):
    catalog_id = _upload_catalog(api_client, supplier_sample_csv_path)
    anchor_id = _anchor(supplier_scenario_manifest, "SR-06")["supplier_id"]
    data = _recommend(api_client, catalog_id, supplier_scenario_manifest["canonical_requirement"])
    entry = {e["supplier_id"]: e for e in data["results"]}[anchor_id]
    assert entry["eligibility_status"] == "ineligible"
    assert any("capacity" in r.lower() for r in entry["ineligibility_reasons"])


def test_sr07_expiring_contract_is_penalised(
    api_client, supplier_sample_csv_path, supplier_scenario_manifest
):
    catalog_id = _upload_catalog(api_client, supplier_sample_csv_path)
    anchor_id = _anchor(supplier_scenario_manifest, "SR-07")["supplier_id"]
    data = _recommend(api_client, catalog_id, supplier_scenario_manifest["canonical_requirement"])
    entry = {e["supplier_id"]: e for e in data["results"]}[anchor_id]
    assert entry["eligibility_status"] == "eligible"
    # Its contract lapses before the required delivery date -> classified expiring.
    assert entry["contract_classification"] == "expiring"


# ---------------------------------------------------------------------------
# Cross-cutting checks
# ---------------------------------------------------------------------------
def test_every_eligible_supplier_has_a_unique_rank(
    api_client, supplier_sample_csv_path, supplier_scenario_manifest
):
    catalog_id = _upload_catalog(api_client, supplier_sample_csv_path)
    data = _recommend(api_client, catalog_id, supplier_scenario_manifest["canonical_requirement"])
    ranks = sorted(e["rank"] for e in data["results"] if e["is_eligible"])
    assert ranks == list(range(1, len(ranks) + 1))


def test_eligible_scores_are_bounded(
    api_client, supplier_sample_csv_path, supplier_scenario_manifest
):
    catalog_id = _upload_catalog(api_client, supplier_sample_csv_path)
    data = _recommend(api_client, catalog_id, supplier_scenario_manifest["canonical_requirement"])
    for entry in data["results"]:
        if not entry["is_eligible"]:
            continue
        assert 0.0 <= entry["overall_score"] <= 100.0
        for key in (
            "cost_score", "delivery_score", "quality_score", "capacity_score", "risk_score",
            "esg_score", "contract_score", "geographic_score", "past_performance_score",
        ):
            assert 0.0 <= entry[key] <= 100.0


def test_format_equivalence_csv_and_xlsx(
    api_client, supplier_sample_csv_path, supplier_sample_xlsx_path, supplier_scenario_manifest
):
    """The CSV (technical headers) and XLSX (business labels) rank identically."""
    requirement = supplier_scenario_manifest["canonical_requirement"]

    csv_catalog = _upload_catalog(api_client, supplier_sample_csv_path)
    csv_data = _recommend(api_client, csv_catalog, requirement)

    xlsx_content = supplier_sample_xlsx_path.read_bytes()
    xlsx_upload = api_client.post(
        "/api/v1/suppliers/upload",
        files={
            "file": (
                "sample_suppliers.xlsx",
                xlsx_content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    ).json()["data"]
    xlsx_data = _recommend(api_client, xlsx_upload["catalog_id"], requirement)

    assert csv_data["eligible_count"] == xlsx_data["eligible_count"]
    assert csv_data["top_supplier_id"] == xlsx_data["top_supplier_id"]
    csv_top = [e["supplier_id"] for e in csv_data["results"] if e["is_eligible"]][:5]
    xlsx_top = [e["supplier_id"] for e in xlsx_data["results"] if e["is_eligible"]][:5]
    assert csv_top == xlsx_top
