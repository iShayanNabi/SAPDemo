"""API tests for the Inventory Predictor.

These drive the real HTTP endpoints through the FastAPI test client, against the
real database and the real engine. They are the tests that would have caught a
route that works in a unit test and 500s over HTTP.
"""

from __future__ import annotations

import pytest

BASE = "/api/v1/inventory"


def _upload(api_client, path):
    with path.open("rb") as handle:
        response = api_client.post(
            f"{BASE}/upload",
            files={"file": (path.name, handle.read(), "text/csv")},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    return body["data"]


@pytest.fixture(scope="module")
def dataset(api_client, inventory_sample_csv_path):
    """A loaded dataset, shared by the read-only tests in this module."""
    return _upload(api_client, inventory_sample_csv_path)


@pytest.fixture(scope="module")
def forecast_run(api_client, dataset):
    """A completed forecast run over the demo dataset."""
    response = api_client.post(
        f"{BASE}/forecast",
        json={
            "dataset_id": dataset["dataset_id"],
            "horizon_periods": 6,
            "confidence_level": 0.95,
            "as_of_date": "2026-07-01",
            "generate_ai_summary": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_upload_loads_the_history_and_reports_the_series(dataset):
    assert dataset["is_analyzable"] is True
    assert dataset["dataset_id"]
    assert dataset["row_count"] > 400
    assert dataset["series_count"] >= 15
    assert dataset["plant_count"] == 3
    assert dataset["frequency"] == "monthly"
    assert dataset["history_start"] == "2024-01-01"
    assert dataset["series"]
    assert {"material", "plant", "period_count"} <= set(dataset["series"][0])


def test_upload_maps_sap_technical_headers(dataset):
    mapped = set(dataset["suggested_mapping"].values())
    assert {"material", "plant", "period_date", "demand"} <= mapped
    assert dataset["missing_required_fields"] == []
    # LGORT must land on the storage location, not on the plant.
    assert dataset["suggested_mapping"]["LGORT"] == "storage_location"
    assert dataset["suggested_mapping"]["WERKS"] == "plant"


def test_upload_reports_the_deliberate_balance_mismatch(dataset):
    issue_types = {issue["issue_type"] for issue in dataset["data_quality_issues"]}
    assert "balance_mismatch" in issue_types


def test_upload_rejects_an_empty_file(api_client):
    response = api_client.post(
        f"{BASE}/upload", files={"file": ("empty.csv", b"", "text/csv")}
    )
    assert response.status_code == 400
    assert response.json()["success"] is False


def test_upload_rejects_a_file_type_that_is_not_tabular(api_client):
    response = api_client.post(
        f"{BASE}/upload", files={"file": ("contract.pdf", b"%PDF-1.7 fake", "application/pdf")}
    )
    assert response.status_code == 400
    assert response.json()["success"] is False


def test_upload_without_the_required_columns_is_not_analyzable(api_client):
    content = b"SOME_COLUMN,ANOTHER\n1,2\n3,4\n"
    response = api_client.post(
        f"{BASE}/upload", files={"file": ("wrong.csv", content, "text/csv")}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_analyzable"] is False
    assert data["missing_required_fields"]
    assert data["dataset_id"] is None


def test_datasets_lists_the_upload(api_client, dataset):
    response = api_client.get(f"{BASE}/datasets")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["total"] >= 1
    assert any(item["id"] == dataset["dataset_id"] for item in body["datasets"])


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


def test_forecast_returns_a_complete_run(forecast_run):
    assert forecast_run["forecast_id"]
    assert forecast_run["horizon_periods"] == 6
    assert forecast_run["confidence_level"] == 0.95
    assert forecast_run["output_origin"] == "forecast"
    assert forecast_run["disclaimer"]

    summary = forecast_run["summary"]
    assert summary["series_count"] >= 15
    assert summary["forecast_count"] >= 14
    assert summary["insufficient_data_count"] >= 1
    assert summary["model_usage"]
    assert forecast_run["series_errors"] == []


def test_forecast_items_carry_the_planning_figures(forecast_run):
    items = forecast_run["items"]
    assert items
    shortage_items = [item for item in items if item["predicted_shortage_date"]]
    assert shortage_items
    for item in shortage_items:
        assert item["days_to_shortage"] is not None
        assert item["output_origin"] == "forecast"


def test_forecast_labels_its_narrative_as_ai_and_keeps_it_separate(forecast_run):
    narrative = forecast_run["ai_narrative"]
    assert narrative["available"] is True
    assert narrative["origin"] == "mock_ai"
    assert narrative["summary"]
    # The narrative lives in its own field: the computed figures are untouched.
    assert forecast_run["summary"]["shortage_count"] >= 0
    assert forecast_run["output_origin"] == "forecast"


def test_forecast_rejects_a_confidence_level_with_no_configured_z_score(api_client, dataset):
    response = api_client.post(
        f"{BASE}/forecast", json={"dataset_id": dataset["dataset_id"], "confidence_level": 0.87}
    )
    assert response.status_code >= 400
    assert response.json()["success"] is False


def test_forecast_rejects_an_unknown_dataset(api_client):
    response = api_client.post(f"{BASE}/forecast", json={"dataset_id": "does-not-exist"})
    assert response.status_code == 404
    assert response.json()["success"] is False


def test_forecast_rejects_an_unknown_model_name(api_client, dataset):
    response = api_client.post(
        f"{BASE}/forecast", json={"dataset_id": dataset["dataset_id"], "model": "arima"}
    )
    assert response.status_code == 422


def test_forecast_can_be_filtered_to_named_materials(api_client, dataset):
    response = api_client.post(
        f"{BASE}/forecast",
        json={
            "dataset_id": dataset["dataset_id"],
            "materials": ["100005"],
            "as_of_date": "2026-07-01",
            "horizon_periods": 3,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["summary"]["series_count"] == 1
    assert data["items"][0]["material"] == "100005"


def test_forcing_a_model_is_honoured_where_it_can_be_applied(api_client, dataset):
    response = api_client.post(
        f"{BASE}/forecast",
        json={
            "dataset_id": dataset["dataset_id"],
            "model": "simple_moving_average",
            "as_of_date": "2026-07-01",
            "horizon_periods": 3,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["requested_model"] == "simple_moving_average"
    forecast_items = [item for item in data["items"] if item["status"] == "forecast"]
    assert all(item["model"] == "simple_moving_average" for item in forecast_items)


def test_a_different_horizon_produces_a_different_run(api_client, dataset):
    response = api_client.post(
        f"{BASE}/forecast",
        json={
            "dataset_id": dataset["dataset_id"],
            "horizon_periods": 12,
            "as_of_date": "2026-07-01",
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["horizon_periods"] == 12
    # The same dataset is reusable: no re-upload was needed.
    assert data["dataset_id"] == dataset["dataset_id"]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def test_get_forecast_returns_the_persisted_run(api_client, forecast_run):
    response = api_client.get(f"{BASE}/forecasts/{forecast_run['forecast_id']}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["forecast_id"] == forecast_run["forecast_id"]
    assert data["summary"]["series_count"] == forecast_run["summary"]["series_count"]
    assert data["items"]


def test_get_forecast_404s_on_an_unknown_id(api_client):
    response = api_client.get(f"{BASE}/forecasts/nope")
    assert response.status_code == 404
    assert response.json()["success"] is False


def test_list_forecasts_is_paginated(api_client, forecast_run):
    response = api_client.get(f"{BASE}/forecasts", params={"limit": 2})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["limit"] == 2
    assert len(data["forecasts"]) <= 2
    assert data["total"] >= 1


def test_items_can_be_filtered_to_the_shortages(api_client, forecast_run):
    response = api_client.get(
        f"{BASE}/forecasts/{forecast_run['forecast_id']}/items",
        params={"shortage_only": True},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] >= 1
    assert all(item["predicted_shortage_date"] for item in data["items"])


def test_items_can_be_filtered_to_dead_stock(api_client, forecast_run):
    response = api_client.get(
        f"{BASE}/forecasts/{forecast_run['forecast_id']}/items",
        params={"dead_stock_only": True},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] >= 1
    assert all(item["is_dead_stock"] for item in data["items"])


def test_items_can_be_filtered_by_plant(api_client, forecast_run):
    response = api_client.get(
        f"{BASE}/forecasts/{forecast_run['forecast_id']}/items", params={"plant": "1000"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] >= 1
    assert all(item["plant"] == "1000" for item in data["items"])


def test_item_detail_carries_the_forecast_projection_and_reasoning(api_client, forecast_run):
    response = api_client.get(
        f"{BASE}/forecasts/{forecast_run['forecast_id']}/item",
        params={"material": "100001", "plant": "1000"},
    )
    assert response.status_code == 200
    detail = response.json()["data"]

    assert detail["material"] == "100001"
    assert len(detail["forecast"]) == 6
    assert detail["history"]
    assert detail["model_assumptions"]
    assert detail["selection"]["candidates"]
    assert detail["projection"]["periods"]
    assert detail["projection"]["reorder"]["rationale"]
    assert detail["accuracy_headline"] is not None
    for point in detail["forecast"]:
        assert point["lower"] <= point["demand"] <= point["upper"]


def test_item_detail_404s_for_a_material_not_in_the_run(api_client, forecast_run):
    response = api_client.get(
        f"{BASE}/forecasts/{forecast_run['forecast_id']}/item",
        params={"material": "999999", "plant": "1000"},
    )
    assert response.status_code == 404
    assert response.json()["success"] is False


def test_the_same_material_in_two_plants_is_two_separate_forecasts(api_client, forecast_run):
    first = api_client.get(
        f"{BASE}/forecasts/{forecast_run['forecast_id']}/item",
        params={"material": "100001", "plant": "1000"},
    ).json()["data"]
    second = api_client.get(
        f"{BASE}/forecasts/{forecast_run['forecast_id']}/item",
        params={"material": "100001", "plant": "3000"},
    ).json()["data"]

    assert first["series_key"] != second["series_key"]
    assert first["total_forecast_demand"] != second["total_forecast_demand"]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("file_format", "prefix"),
    [("xlsx", b"PK\x03\x04"), ("csv", b"\xef\xbb\xbf"), ("json", b"{")],
)
def test_export_returns_a_real_file(api_client, forecast_run, file_format, prefix):
    response = api_client.get(
        f"{BASE}/forecasts/{forecast_run['forecast_id']}/export",
        params={"format": file_format},
    )
    assert response.status_code == 200
    assert response.content.startswith(prefix)
    assert "attachment" in response.headers["content-disposition"]
    assert len(response.content) > 200


def test_the_json_export_carries_the_disclaimer_and_the_methodology(api_client, forecast_run):
    response = api_client.get(
        f"{BASE}/forecasts/{forecast_run['forecast_id']}/export", params={"format": "json"}
    )
    payload = response.json()
    assert "validated in a live SAP environment" in payload["disclaimer"]
    assert "not connected to a live SAP system" in payload["disclaimer"]
    assert payload["methodology"]["methods"]
    assert payload["items"]
    assert payload["report_type"] == "sap_inventory_forecast"


def test_export_404s_on_an_unknown_run(api_client):
    response = api_client.get(f"{BASE}/forecasts/nope/export")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Documentation endpoints
# ---------------------------------------------------------------------------


def test_fields_returns_the_documented_contract(api_client):
    response = api_client.get(f"{BASE}/fields")
    assert response.status_code == 200
    fields = response.json()["data"]
    by_name = {item["name"]: item for item in fields}

    assert {"material", "plant", "period_date", "demand"} <= set(by_name)
    assert by_name["material"]["required"] is True
    assert by_name["material"]["is_series_key"] is True
    assert "MATNR" in by_name["material"]["aliases"]
    assert "LGORT" in by_name["storage_location"]["aliases"]
    # Every one of the specified input fields is supported.
    for name in (
        "material_description", "starting_inventory", "ending_inventory", "receipts",
        "issues", "lead_time_days", "reorder_point", "safety_stock", "supplier_id",
        "open_po_quantity", "po_expected_date",
    ):
        assert name in by_name


def test_methods_documents_every_model_and_its_assumptions(api_client):
    response = api_client.get(f"{BASE}/methods")
    assert response.status_code == 200
    data = response.json()["data"]

    models = {item["model"] for item in data["methods"]}
    assert models == {
        "simple_moving_average",
        "weighted_moving_average",
        "simple_exponential_smoothing",
        "holt_linear_trend",
        "holt_winters_seasonal",
    }
    assert all(item["assumptions"] for item in data["methods"])
    assert data["selection"]["metric"]
    assert data["reorder"]["safety_stock_formula"]
    assert "mape" in data["accuracy_metrics"]
    assert data["disclaimer"]


def test_sample_endpoints_serve_the_demo_dataset(api_client):
    info = api_client.get(f"{BASE}/sample/info")
    assert info.status_code == 200
    data = info.json()["data"]
    assert data["available"] is True
    assert data["data_origin"] == "demo_data"
    assert data["scenario_count"] >= 10

    download = api_client.get(f"{BASE}/sample", params={"format": "csv"})
    assert download.status_code == 200
    assert download.content.startswith(b"MATNR")


def test_ai_status_never_leaks_a_key(api_client):
    response = api_client.get(f"{BASE}/ai-status")
    assert response.status_code == 200
    body = response.text.lower()
    assert "api_key" not in body
    assert "sk-" not in body
