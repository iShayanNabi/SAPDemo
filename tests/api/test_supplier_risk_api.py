"""API tests for the Supplier Risk Copilot endpoints.

These drive the real FastAPI app through ``TestClient``, so they cover the
response envelope, status codes, validation and the four routes the module is
specified around.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.factories import (
    DEFAULT_RISK_PROFILE,
    RISK_AS_OF,
    risk_event_rows_to_csv,
    risk_profile_rows_to_csv,
)

CSV_MIME = "text/csv"


def _profile_row(**overrides):
    """A demo profile row in canonical column names."""
    row = {**DEFAULT_RISK_PROFILE, **overrides}
    return row


def _upload_profiles(client, rows, filename="risk_profiles.csv"):
    content = risk_profile_rows_to_csv(rows)
    response = client.post(
        "/api/v1/supplier-risk/upload",
        files={"file": (filename, content, CSV_MIME)},
        data={"dataset": "profiles"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    return body["data"]


def _upload_events(client, rows, dataset_id, filename="risk_events.csv"):
    content = risk_event_rows_to_csv(rows)
    response = client.post(
        "/api/v1/supplier-risk/upload",
        files={"file": (filename, content, CSV_MIME)},
        data={"dataset": "events", "dataset_id": dataset_id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    return body["data"]


def _calculate(client, dataset_id, **payload):
    body = {"dataset_id": dataset_id, "as_of_date": RISK_AS_OF.isoformat(), **payload}
    response = client.post("/api/v1/supplier-risk/calculate", json=body)
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["success"] is True
    return envelope["data"]


@pytest.fixture
def loaded(api_client):
    """A dataset with three suppliers and an assessment over it."""
    rows = [
        _profile_row(
            supplier_id="0000390001",
            supplier_name="Ravenna Frontier Trading BV",
            spend_category="Components",
            on_time_delivery_rate=72.0,
            delivery_count=100,
            late_delivery_count=28,
            average_delay_days=12.0,
            quality_score=68.0,
            defect_rate=7.0,
            quality_incident_count=8,
            contract_status="No contract",
            contract_expiration=None,
            invoice_count=100,
            invoice_exception_count=22,
            disputed_invoice_count=6,
            compliance_finding_count=4,
            certification_status="Expired",
            audit_status="Failed",
            esg_score=35.0,
            country="TR",
        ),
        _profile_row(
            supplier_id="0000390002",
            supplier_name="Kestrel Specialities SA",
            spend_category="Components",
        ),
        _profile_row(
            supplier_id="0000390003",
            supplier_name="Fairmont Legacy Trading BV",
            spend_category="Components",
            contract_expiration=RISK_AS_OF + timedelta(days=20),
        ),
    ]
    dataset = _upload_profiles(api_client, rows)
    events = [
        {
            "event_id": f"EVT-{index:03d}",
            "supplier_id": "0000390001",
            "event_type": "late_delivery",
            "event_date": RISK_AS_OF - timedelta(days=20),
            "reference": "4500000123",
            "severity": "high",
            "description": "Delivery arrived late",
            "amount": None,
            "currency": "EUR",
        }
        for index in range(3)
    ]
    _upload_events(api_client, events, dataset["dataset_id"])
    assessment = _calculate(api_client, dataset["dataset_id"])
    return {"dataset": dataset, "assessment": assessment}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_upload_profiles_maps_the_sap_columns(api_client):
    data = _upload_profiles(api_client, [_profile_row(supplier_id="0000391001")])

    assert data["is_analyzable"] is True
    assert data["supplier_count"] == 1
    assert data["dataset_id"]
    assert data["missing_required_fields"] == []


def test_upload_rejects_an_empty_file(api_client):
    response = api_client.post(
        "/api/v1/supplier-risk/upload",
        files={"file": ("empty.csv", b"", CSV_MIME)},
        data={"dataset": "profiles"},
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


def test_upload_without_the_supplier_id_is_not_analyzable(api_client):
    content = b"NAME1,OTD\nAcme,95\n"
    response = api_client.post(
        "/api/v1/supplier-risk/upload",
        files={"file": ("bad.csv", content, CSV_MIME)},
        data={"dataset": "profiles"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_analyzable"] is False
    assert "supplier_id" in data["missing_required_fields"]
    assert data["dataset_id"] is None


def test_upload_events_attaches_to_the_dataset(api_client):
    dataset = _upload_profiles(api_client, [_profile_row(supplier_id="0000392001")])
    events = [
        {
            "event_id": "EVT-1",
            "supplier_id": "0000392001",
            "event_type": "late_delivery",
            "event_date": RISK_AS_OF - timedelta(days=10),
            "reference": "4500000001",
            "severity": "high",
            "description": "Late",
            "amount": None,
            "currency": "EUR",
        }
    ]

    data = _upload_events(api_client, events, dataset["dataset_id"])

    assert data["event_count"] == 1
    assert data["dataset_id"] == dataset["dataset_id"]


def test_datasets_endpoint_lists_uploads(api_client, loaded):
    response = api_client.get("/api/v1/supplier-risk/datasets")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["total"] >= 1
    assert any(item["id"] == loaded["dataset"]["dataset_id"] for item in body["datasets"])


# ---------------------------------------------------------------------------
# Calculate
# ---------------------------------------------------------------------------


def test_calculate_scores_every_supplier(api_client, loaded):
    assessment = loaded["assessment"]

    assert assessment["status"] == "completed"
    assert assessment["summary"]["supplier_count"] == 3
    assert assessment["summary"]["scored_count"] == 3
    assert assessment["rule_errors"] == []
    assert len(assessment["suppliers"]) == 3


def test_calculate_ranks_the_riskiest_supplier_first(api_client, loaded):
    suppliers = loaded["assessment"]["suppliers"]

    assert suppliers[0]["supplier_id"] == "0000390001"
    assert suppliers[0]["rank"] == 1
    scores = [item["overall_score"] for item in suppliers]
    assert scores == sorted(scores, reverse=True)


def test_calculate_reports_all_ten_categories(api_client, loaded):
    supplier = loaded["assessment"]["suppliers"][0]

    expected = {
        "delivery", "quality", "financial", "spend_concentration", "contract",
        "invoice", "compliance", "esg", "geographic", "operational",
    }
    assert set(supplier["category_scores"]) == expected


def test_calculate_counts_expiring_contracts(api_client, loaded):
    assert loaded["assessment"]["summary"]["contracts_expiring_count"] == 1


def test_calculate_rejects_weights_that_do_not_sum_to_100(api_client, loaded):
    response = api_client.post(
        "/api/v1/supplier-risk/calculate",
        json={
            "dataset_id": loaded["dataset"]["dataset_id"],
            "weights": {
                "delivery": 50.0, "quality": 50.0, "financial": 50.0,
                "spend_concentration": 0.0, "contract": 0.0, "invoice": 0.0,
                "compliance": 0.0, "esg": 0.0, "geographic": 0.0, "operational": 0.0,
            },
        },
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "configuration_error"


def test_calculate_rejects_an_unknown_field(api_client, loaded):
    response = api_client.post(
        "/api/v1/supplier-risk/calculate",
        json={"dataset_id": loaded["dataset"]["dataset_id"], "not_a_field": 1},
    )

    assert response.status_code == 422


def test_calculate_on_an_unknown_dataset_is_a_404(api_client):
    response = api_client.post(
        "/api/v1/supplier-risk/calculate", json={"dataset_id": "does-not-exist"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_custom_weights_change_the_scores(api_client, loaded):
    dataset_id = loaded["dataset"]["dataset_id"]
    delivery_heavy = _calculate(
        api_client,
        dataset_id,
        weights={
            "delivery": 91.0, "quality": 1.0, "financial": 1.0, "spend_concentration": 1.0,
            "contract": 1.0, "invoice": 1.0, "compliance": 1.0, "esg": 1.0,
            "geographic": 1.0, "operational": 1.0,
        },
    )

    default_top = loaded["assessment"]["suppliers"][0]["overall_score"]
    weighted_top = delivery_heavy["suppliers"][0]["overall_score"]
    assert weighted_top != default_top


def test_ai_summary_is_labelled_and_separate(api_client, loaded):
    assessment = _calculate(
        api_client, loaded["dataset"]["dataset_id"], generate_ai_summary=True
    )

    narrative = assessment["ai_narrative"]
    assert narrative["available"] is True
    assert narrative["origin"] == "mock_ai"
    assert narrative["summary"]
    # The narrative never replaces a computed figure.
    assert assessment["suppliers"][0]["overall_score"] is not None


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------


def test_list_suppliers_returns_the_assessed_portfolio(api_client, loaded):
    response = api_client.get("/api/v1/supplier-risk/suppliers")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 3
    assert data["assessment_id"]


def test_list_suppliers_filters_by_band(api_client, loaded):
    band = loaded["assessment"]["suppliers"][0]["overall_band"]
    response = api_client.get("/api/v1/supplier-risk/suppliers", params={"band": band})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] >= 1
    assert all(item["overall_band"] == band for item in data["suppliers"])


def test_list_suppliers_filters_expiring_contracts(api_client, loaded):
    response = api_client.get(
        "/api/v1/supplier-risk/suppliers", params={"expiring_only": True}
    )

    data = response.json()["data"]
    assert data["total"] == 1
    assert data["suppliers"][0]["supplier_id"] == "0000390003"


def test_get_supplier_returns_the_full_profile(api_client, loaded):
    response = api_client.get("/api/v1/supplier-risk/suppliers/0000390001")

    assert response.status_code == 200
    profile = response.json()["data"]
    assert profile["supplier_id"] == "0000390001"
    assert len(profile["categories"]) == 10
    assert profile["trend"] is not None
    assert profile["actions"]
    assert profile["output_origin"] == "rule_based"


def test_supplier_profile_exposes_the_full_scoring_breakdown(api_client, loaded):
    """The transparency requirement: metric, weight, normalised score, contribution."""
    profile = api_client.get("/api/v1/supplier-risk/suppliers/0000390001").json()["data"]

    delivery = next(item for item in profile["categories"] if item["category"] == "delivery")
    assert delivery["metrics"]
    for metric in delivery["metrics"]:
        assert {"metric", "label", "raw_value", "weight", "normalized_weight",
                "normalized_score", "contribution", "available", "basis"} <= set(metric)


def test_supplier_profile_lists_the_supporting_records(api_client, loaded):
    profile = api_client.get("/api/v1/supplier-risk/suppliers/0000390001").json()["data"]

    assert len(profile["delivery_issues"]) == 3
    assert profile["delivery_issues"][0]["event_id"].startswith("EVT-")


def test_get_unknown_supplier_is_a_404(api_client, loaded):
    response = api_client.get("/api/v1/supplier-risk/suppliers/0000999999")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


def test_chat_answers_a_supplier_risk_question(api_client, loaded):
    response = api_client.post(
        "/api/v1/supplier-risk/chat",
        json={"question": "Show supplier Ravenna Frontier Trading BV's risk."},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["intent"] == "supplier_risk"
    assert data["data_available"] is True
    assert data["citations"]
    assert "0000390001" in data["suppliers_referenced"]


def test_chat_answer_cites_internal_records(api_client, loaded):
    data = api_client.post(
        "/api/v1/supplier-risk/chat",
        json={"question": "Why is this supplier high risk?", "supplier_id": "0000390001"},
    ).json()["data"]

    assert data["citations"]
    for citation in data["citations"]:
        assert citation["source"] in {"supplier_risk_profiles", "supplier_risk_events"}
        assert citation["record_id"]


@pytest.mark.parametrize(
    ("question", "expected_intent"),
    [
        ("Which suppliers have the most delivery issues?", "delivery_issues"),
        ("Which suppliers have contracts expiring soon?", "contracts_expiring"),
        ("What action should procurement take?", "recommended_action"),
        ("Which suppliers are the highest risk?", "highest_risk"),
    ],
)
def test_chat_handles_the_documented_questions(api_client, loaded, question, expected_intent):
    data = api_client.post(
        "/api/v1/supplier-risk/chat", json={"question": question}
    ).json()["data"]

    assert data["intent"] == expected_intent
    assert data["data_available"] is True


def test_chat_finds_a_lower_risk_alternative(api_client, loaded):
    data = api_client.post(
        "/api/v1/supplier-risk/chat",
        json={
            "question": "Which alternative supplier has lower risk?",
            "supplier_id": "0000390001",
        },
    ).json()["data"]

    assert data["intent"] == "alternatives"
    assert data["data_available"] is True
    assert "0000390002" in data["suppliers_referenced"]


def test_chat_states_when_a_supplier_is_not_in_the_records(api_client, loaded):
    data = api_client.post(
        "/api/v1/supplier-risk/chat",
        json={"question": "Show supplier Northwind Traders risk."},
    ).json()["data"]

    assert data["data_available"] is False
    assert data["unavailable_reason"] == "supplier_not_found"
    assert data["citations"] == []


def test_chat_states_when_the_question_is_unsupported(api_client, loaded):
    data = api_client.post(
        "/api/v1/supplier-risk/chat", json={"question": "What is the weather in Berlin?"}
    ).json()["data"]

    assert data["data_available"] is False
    assert data["unavailable_reason"] == "unsupported_question"


def test_chat_rejects_an_empty_question(api_client, loaded):
    response = api_client.post("/api/v1/supplier-risk/chat", json={"question": ""})

    assert response.status_code == 422


def test_chat_rejects_an_unknown_field(api_client, loaded):
    response = api_client.post(
        "/api/v1/supplier-risk/chat", json={"question": "Hello", "rogue": True}
    )

    assert response.status_code == 422


def test_chat_on_an_unknown_assessment_is_a_404(api_client, loaded):
    response = api_client.post(
        "/api/v1/supplier-risk/chat",
        json={"question": "Which suppliers are the highest risk?", "assessment_id": "nope"},
    )

    assert response.status_code == 404


def test_chat_carries_the_disclaimer(api_client, loaded):
    data = api_client.post(
        "/api/v1/supplier-risk/chat", json={"question": "Which suppliers are the highest risk?"}
    ).json()["data"]

    assert data["disclaimer"]
    assert data["output_origin"] == "rule_based"


# ---------------------------------------------------------------------------
# Documentation endpoints
# ---------------------------------------------------------------------------


def test_fields_endpoint_documents_the_contract(api_client):
    response = api_client.get("/api/v1/supplier-risk/fields")

    assert response.status_code == 200
    fields = response.json()["data"]
    names = {item["name"] for item in fields}
    assert "supplier_id" in names
    assert "credit_score" in names
    assert any(item["inherited_from_supplier_master"] for item in fields)


def test_scoring_endpoint_documents_the_model(api_client):
    response = api_client.get("/api/v1/supplier-risk/scoring")

    assert response.status_code == 200
    info = response.json()["data"]
    assert len(info["categories"]) == 10
    assert sum(info["default_weights"].values()) == pytest.approx(info["weight_total"])
    assert info["risk_bands"]
    assert info["disclaimer"]
    for category in info["categories"]:
        assert category["metrics"]


def test_ai_status_never_leaks_a_key(api_client):
    response = api_client.get("/api/v1/supplier-risk/ai-status")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["resolved_provider"] == "mock"
    assert not any("key" in str(key).lower() for key in body)


def test_sample_info_reports_the_demo_dataset(api_client):
    response = api_client.get("/api/v1/supplier-risk/sample/info")

    assert response.status_code == 200
    info = response.json()["data"]
    assert info["data_origin"] == "demo_data"


def test_assessments_can_be_listed_and_fetched(api_client, loaded):
    listing = api_client.get("/api/v1/supplier-risk/assessments").json()["data"]
    assert listing["total"] >= 1

    assessment_id = loaded["assessment"]["assessment_id"]
    detail = api_client.get(f"/api/v1/supplier-risk/assessments/{assessment_id}").json()["data"]
    assert detail["assessment_id"] == assessment_id
    assert len(detail["suppliers"]) == 3


def test_unknown_assessment_is_a_404(api_client):
    response = api_client.get("/api/v1/supplier-risk/assessments/does-not-exist")

    assert response.status_code == 404


def test_response_envelope_is_consistent(api_client, loaded):
    response = api_client.get("/api/v1/supplier-risk/suppliers")
    body = response.json()

    assert set(body) == {"success", "data", "error", "meta"}
    assert body["meta"]["api_version"] == "v1"
