"""API tests for the Spend Analytics Dashboard endpoints.

Run against a real FastAPI test client backed by a temporary SQLite database,
so routing, validation, the service layer, persistence and the export builders
are exercised together.
"""

from __future__ import annotations

import io
import json
from datetime import date

import pytest
from openpyxl import load_workbook

from tests.factories import make_spend_row, spend_rows_to_csv, spend_rows_to_xlsx

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

TECHNICAL_HEADERS = {
    "po_number": "EBELN", "supplier_id": "LIFNR", "material": "MATNR",
    "material_group": "MATKL", "quantity": "MENGE", "unit_price": "NETPR",
    "currency": "WAERS", "transaction_date": "POSTING_DATE", "category": "SPEND_CATEGORY",
    "contract_status": "CONTRACT_STATUS", "preferred_supplier_status": "PREFERRED_SUPPLIER",
    "baseline_price": "BASELINE_PRICE", "current_price": "ACTUAL_PRICE",
}


def spend_dataset() -> list[dict]:
    """A small dataset with a known answer for every headline metric."""
    rows = []
    # Contracted, preferred spend with two suppliers.
    for index in range(4):
        rows.append(
            make_spend_row(
                po_number=f"55000{index:03d}", supplier_id="0000200001",
                material="SPM-100000", category="Components",
                transaction_date=date(2025, 1 + index, 12),
                quantity=100, unit_price=100.0,
            )
        )
    # A second supplier, non-contracted and non-preferred: maverick spend.
    for index in range(3):
        rows.append(
            make_spend_row(
                po_number=f"55001{index:03d}", supplier_id="0000200002",
                supplier_name="Bluepeak Supply Ltd", material="SPM-100003",
                category="Logistics", material_group="MG50",
                transaction_date=date(2025, 6 + index, 8),
                quantity=50, unit_price=200.0,
                contract_status="Not contracted", contract_number=None,
                preferred_supplier_status="Non-preferred",
            )
        )
    # A line priced well above its baseline: price variance.
    rows.append(
        make_spend_row(
            po_number="5500999", supplier_id="0000200003", material="SPM-100006",
            category="Laboratory", transaction_date=date(2025, 9, 3),
            quantity=100, unit_price=150.0, current_price=150.0, baseline_price=100.0,
        )
    )
    return rows


def upload_spend(api_client, content: bytes, filename: str, mime: str) -> dict:
    """Upload helper returning the ``data`` block."""
    response = api_client.post(
        "/api/v1/spend/upload", files={"file": (filename, content, mime)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    return body["data"]


# ---------------------------------------------------------------------------
# Catalogues
# ---------------------------------------------------------------------------
def test_index_lists_the_spend_module(api_client):
    body = api_client.get("/").json()
    modules = {module["id"]: module for module in body["modules"]}
    assert modules["spend_analytics"]["status"] == "available"


def test_field_catalogue_includes_spend_specific_fields(api_client):
    fields = api_client.get("/api/v1/spend/fields").json()["data"]
    by_name = {field["name"]: field for field in fields}

    for name in (
        "transaction_date", "category", "subcategory", "contract_status",
        "preferred_supplier_status", "baseline_price", "current_price", "payment_status",
    ):
        assert by_name[name]["is_spend_specific"] is True

    # Purchase order fields are reused, not redefined.
    assert "EBELN" in by_name["po_number"]["aliases"]
    assert by_name["po_number"]["is_spend_specific"] is False


def test_category_alias_resolves_to_category_not_material_group(api_client):
    """In a spend cube CATEGORY means the procurement category."""
    fields = api_client.get("/api/v1/spend/fields").json()["data"]
    by_name = {field["name"]: field for field in fields}
    assert "CATEGORY" in by_name["category"]["aliases"]
    assert "CATEGORY" not in by_name["material_group"]["aliases"]


def test_savings_rule_catalogue(api_client):
    rules = api_client.get("/api/v1/spend/savings-rules").json()["data"]
    assert len(rules) == 6
    assert {rule["rule_id"] for rule in rules} == {f"SAV-0{i}" for i in range(1, 7)}
    assert all(0.0 <= rule["realization_factor"] <= 1.0 for rule in rules)


def test_methodology_endpoint_states_the_disclaimers(api_client):
    body = api_client.get("/api/v1/spend/methodology").json()["data"]
    assert "deterministic" in body["calculation_basis"]
    assert "not connected to any SAP system" in body["data_disclaimer"]
    assert "not guaranteed" in body["savings_disclaimer"]


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def test_upload_csv_with_technical_headers(api_client):
    data = upload_spend(
        api_client, spend_rows_to_csv(spend_dataset(), TECHNICAL_HEADERS), "spend.csv", "text/csv"
    )
    assert data["row_count"] == 8
    assert data["is_analyzable"] is True
    assert data["suggested_mapping"]["POSTING_DATE"] == "transaction_date"
    assert data["suggested_mapping"]["SPEND_CATEGORY"] == "category"
    assert data["missing_required_fields"] == []


def test_upload_xlsx(api_client):
    data = upload_spend(api_client, spend_rows_to_xlsx(spend_dataset()), "spend.xlsx", XLSX_MIME)
    assert data["row_count"] == 8
    assert data["is_analyzable"] is True


@pytest.mark.parametrize(
    ("filename", "content", "mime"),
    [
        ("spend.exe", b"MZ\x90\x00binary", "application/octet-stream"),
        ("spend.txt", b"a,b\n1,2\n", "text/plain"),
        ("spend.csv", b"", "text/csv"),
        ("spend.json", b"{not json", "application/json"),
    ],
)
def test_invalid_uploads_are_rejected(api_client, filename, content, mime):
    response = api_client.post(
        "/api/v1/spend/upload", files={"file": (filename, content, mime)}
    )
    assert response.status_code in (400, 422)
    body = response.json()
    assert body["success"] is False
    assert "/home/" not in body["error"]["message"]


def test_upload_without_any_date_column_is_not_analyzable(api_client):
    """No date column at all - spend cannot be placed on a timeline."""
    content = b"EBELN,LIFNR,MENGE,NETPR\n5500001,0000200001,10,100\n"
    data = upload_spend(api_client, content, "spend.csv", "text/csv")

    assert data["is_analyzable"] is False
    assert "transaction_date" in data["missing_required_fields"]


def test_upload_without_a_value_basis_is_not_analyzable(api_client):
    """Neither a total nor quantity x price means there is no spend to sum."""
    content = b"EBELN,LIFNR,POSTING_DATE\n5500001,0000200001,2025-01-05\n"
    data = upload_spend(api_client, content, "spend.csv", "text/csv")

    assert data["is_analyzable"] is False
    assert "total_value" in data["missing_required_fields"]


def test_total_value_alone_is_enough(api_client):
    """A spend cube often has an amount but no quantity or unit price."""
    content = (
        b"EBELN,LIFNR,POSTING_DATE,NETWR,WAERS\n"
        b"5500001,0000200001,2025-01-05,1500,EUR\n"
        b"5500002,0000200002,2025-02-05,2500,EUR\n"
    )
    data = upload_spend(api_client, content, "spend.csv", "text/csv")
    assert data["is_analyzable"] is True

    response = api_client.post(
        "/api/v1/spend/analyze",
        json={"upload_id": data["upload_id"], "generate_ai_summary": False},
    )
    assert response.status_code == 200
    assert response.json()["data"]["metrics"]["total_spend"] == pytest.approx(4000.0)


def test_empty_date_values_are_reported_as_a_data_quality_issue(api_client):
    """The column exists but is blank: analysable, with a warning."""
    rows = [dict(row) for row in spend_dataset()]
    for row in rows:
        row["transaction_date"] = None
        row["order_date"] = None
    data = upload_spend(api_client, spend_rows_to_csv(rows), "spend.csv", "text/csv")
    assert data["is_analyzable"] is True

    response = api_client.post(
        "/api/v1/spend/analyze",
        json={"upload_id": data["upload_id"], "generate_ai_summary": False},
    )
    analysis = response.json()["data"]
    issue_types = {issue["issue_type"] for issue in analysis["data_quality_issues"]}
    assert "missing_date" in issue_types
    assert analysis["analytics"]["monthly_spend"] == []


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def analysis(api_client) -> dict:
    """Upload and analyse the known dataset once."""
    upload = upload_spend(
        api_client, spend_rows_to_csv(spend_dataset(), TECHNICAL_HEADERS), "spend.csv", "text/csv"
    )
    response = api_client.post(
        "/api/v1/spend/analyze",
        json={"upload_id": upload["upload_id"], "generate_ai_summary": True},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_analysis_headline_metrics(analysis):
    metrics = analysis["metrics"]
    # 4 x 10,000 contracted + 3 x 10,000 maverick + 1 x 15,000 variance line
    assert metrics["total_spend"] == pytest.approx(85000.0)
    assert metrics["line_item_count"] == 8
    assert metrics["purchase_order_count"] == 8
    assert metrics["supplier_count"] == 3
    assert metrics["base_currency"] == "EUR"


def test_analysis_contract_and_maverick_split(analysis):
    metrics = analysis["metrics"]
    assert metrics["contracted_spend"] == pytest.approx(55000.0)
    assert metrics["non_contracted_spend"] == pytest.approx(30000.0)
    assert metrics["maverick_spend"] == pytest.approx(30000.0)
    assert metrics["maverick_spend_pct"] == pytest.approx(35.29, abs=0.01)


def test_analysis_reports_concentration_and_tail(analysis):
    metrics = analysis["metrics"]
    assert metrics["supplier_concentration_hhi"] > 0
    assert metrics["supplier_concentration_level"] in {"low", "moderate", "high"}
    assert metrics["top_supplier_share_pct"] > 0
    assert metrics["top_five_supplier_share_pct"] >= metrics["top_supplier_share_pct"]


def test_analysis_reports_price_variance(analysis):
    assert analysis["metrics"]["price_variance_base"] == pytest.approx(5000.0)


def test_analysis_returns_every_breakdown(analysis):
    analytics = analysis["analytics"]
    for key in (
        "monthly_spend", "spend_by_supplier", "spend_by_category", "spend_by_material_group",
        "spend_by_plant", "spend_by_company_code", "top_materials", "tail_spend_suppliers",
        "supplier_concentration", "contract_leakage", "maverick_spend",
        "purchase_price_variance",
    ):
        assert key in analytics, key
    assert len(analytics["monthly_spend"]) >= 6


def test_analysis_includes_labelled_mock_narrative(analysis):
    narrative = analysis["ai_narrative"]
    assert narrative["available"] is True
    assert narrative["origin"] == "mock_ai"
    assert narrative["prompt_version"].startswith("spend_narrative_v")
    assert narrative["summary"]


def test_analysis_exposes_methodology_and_filter_options(analysis):
    assert analysis["methodology"]["calculation_basis"]
    assert "category" in analysis["filter_options"]
    assert analysis["filter_options"]["category"]


def test_analysis_with_unknown_upload_returns_404(api_client):
    response = api_client.post("/api/v1/spend/analyze", json={"upload_id": "does-not-exist"})
    assert response.status_code == 404


def test_analysis_rejects_unknown_savings_rule(api_client):
    upload = upload_spend(
        api_client, spend_rows_to_csv(spend_dataset(), TECHNICAL_HEADERS), "spend.csv", "text/csv"
    )
    response = api_client.post(
        "/api/v1/spend/analyze",
        json={"upload_id": upload["upload_id"], "enabled_savings_rules": ["SAV-99"]},
    )
    assert response.status_code == 422
    assert "SAV-99" in response.json()["error"]["details"]["unknown_rules"]


def test_analysis_rejects_unknown_body_fields(api_client):
    response = api_client.post(
        "/api/v1/spend/analyze", json={"upload_id": "x", "surprise": True}
    )
    assert response.status_code == 422


def test_analysis_with_mapping_override(api_client):
    """A user correction must win over the automatic suggestion."""
    headers = dict(TECHNICAL_HEADERS)
    headers["category"] = "ZZ_SEGMENT"
    upload = upload_spend(
        api_client, spend_rows_to_csv(spend_dataset(), headers), "spend.csv", "text/csv"
    )
    response = api_client.post(
        "/api/v1/spend/analyze",
        json={
            "upload_id": upload["upload_id"],
            "column_mapping_overrides": {"ZZ_SEGMENT": "category"},
            "generate_ai_summary": False,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["applied_mapping"]["ZZ_SEGMENT"] == "category"
    assert data["ai_narrative"]["available"] is False


# ---------------------------------------------------------------------------
# Filtering through the API
# ---------------------------------------------------------------------------
def test_date_filter_narrows_the_analysis(api_client):
    upload = upload_spend(
        api_client, spend_rows_to_csv(spend_dataset(), TECHNICAL_HEADERS), "spend.csv", "text/csv"
    )
    response = api_client.post(
        "/api/v1/spend/analyze",
        json={
            "upload_id": upload["upload_id"],
            "filters": {"date_from": "2025-06-01", "date_to": "2025-08-31"},
            "generate_ai_summary": False,
        },
    )
    data = response.json()["data"]

    assert data["filtered_record_count"] == 3
    assert data["record_count"] == 8
    assert data["metrics"]["total_spend"] == pytest.approx(30000.0)
    assert data["applied_filter"]["date_from"] == "2025-06-01"


def test_category_filter_narrows_the_analysis(api_client):
    upload = upload_spend(
        api_client, spend_rows_to_csv(spend_dataset(), TECHNICAL_HEADERS), "spend.csv", "text/csv"
    )
    response = api_client.post(
        "/api/v1/spend/analyze",
        json={
            "upload_id": upload["upload_id"],
            "filters": {"category": ["Logistics"]},
            "generate_ai_summary": False,
        },
    )
    data = response.json()["data"]

    assert data["filtered_record_count"] == 3
    assert data["metrics"]["maverick_spend_pct"] == pytest.approx(100.0)
    assert [row["value"] for row in data["analytics"]["spend_by_category"]] == ["Logistics"]


def test_filter_rejects_unknown_fields(api_client):
    upload = upload_spend(
        api_client, spend_rows_to_csv(spend_dataset(), TECHNICAL_HEADERS), "spend.csv", "text/csv"
    )
    response = api_client.post(
        "/api/v1/spend/analyze",
        json={"upload_id": upload["upload_id"], "filters": {"not_a_field": ["x"]}},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Retrieval and drill-down
# ---------------------------------------------------------------------------
def test_list_analyses(api_client, analysis):
    body = api_client.get("/api/v1/spend/analyses", params={"limit": 5}).json()["data"]
    assert body["total"] >= 1
    assert all("analysis_id" in item for item in body["analyses"])


def test_get_single_analysis(api_client, analysis):
    body = api_client.get(f"/api/v1/spend/analyses/{analysis['analysis_id']}").json()["data"]
    assert body["analysis_id"] == analysis["analysis_id"]
    assert body["metrics"]["total_spend"] == analysis["metrics"]["total_spend"]


def test_get_unknown_analysis_returns_404(api_client):
    assert api_client.get("/api/v1/spend/analyses/nope").status_code == 404


def test_drilldown_by_supplier_reconciles_with_the_rollup(api_client, analysis):
    supplier = analysis["supplier_spend"][0]
    body = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/transactions",
        params={"dimension": "supplier", "value": supplier["supplier_id"], "limit": 500},
    ).json()["data"]

    assert body["total"] == supplier["transaction_count"]
    assert body["total_spend_base"] == pytest.approx(supplier["spend_base"])
    assert all(t["supplier_id"] == supplier["supplier_id"] for t in body["transactions"])


def test_drilldown_by_category_reconciles_with_the_breakdown(api_client, analysis):
    category = analysis["analytics"]["spend_by_category"][0]
    body = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/transactions",
        params={"dimension": "category", "value": category["value"], "limit": 500},
    ).json()["data"]

    assert body["total"] == category["transaction_count"]
    assert body["total_spend_base"] == pytest.approx(category["spend_base"])


def test_drilldown_by_month(api_client, analysis):
    month = analysis["analytics"]["monthly_spend"][0]
    body = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/transactions",
        params={"dimension": "spend_month", "value": month["value"]},
    ).json()["data"]
    assert body["total_spend_base"] == pytest.approx(month["spend_base"])


def test_drilldown_boolean_filters(api_client, analysis):
    body = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/transactions",
        params={"maverick": True, "limit": 100},
    ).json()["data"]

    assert body["total"] == 3
    assert body["total_spend_base"] == pytest.approx(30000.0)
    assert all(t["is_maverick"] for t in body["transactions"])


def test_drilldown_rejects_an_unknown_dimension(api_client, analysis):
    response = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/transactions",
        params={"dimension": "not_a_dimension", "value": "x"},
    )
    assert response.status_code == 422
    assert "allowed_dimensions" in response.json()["error"]["details"]


def test_drilldown_pagination(api_client, analysis):
    first = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/transactions",
        params={"limit": 1, "offset": 0},
    ).json()["data"]
    second = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/transactions",
        params={"limit": 1, "offset": 1},
    ).json()["data"]

    assert first["total"] == 8
    assert first["transactions"][0] != second["transactions"][0]


# ---------------------------------------------------------------------------
# Opportunities
# ---------------------------------------------------------------------------
def test_opportunities_endpoint_matches_the_metric(api_client, analysis):
    body = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/opportunities"
    ).json()["data"]

    assert body["total"] == len(analysis["opportunities"])
    assert body["total_estimated_saving_base"] == pytest.approx(
        analysis["metrics"]["estimated_savings_opportunity"]
    )


def test_opportunities_carry_the_disclaimer_and_estimate_flag(api_client, analysis):
    body = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/opportunities"
    ).json()["data"]

    assert "not guaranteed" in body["disclaimer"]
    for opportunity in body["opportunities"]:
        assert opportunity["is_estimate"] is True
        assert opportunity["method"]
        assert opportunity["output_origin"] == "rule_based"


def test_opportunities_can_be_filtered(api_client, analysis):
    if not analysis["opportunities"]:
        pytest.skip("No opportunity produced for this dataset")
    rule_id = analysis["opportunities"][0]["rule_id"]
    body = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/opportunities",
        params={"rule_id": rule_id},
    ).json()["data"]
    assert all(o["rule_id"] == rule_id for o in body["opportunities"])


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def test_export_xlsx(api_client, analysis):
    response = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/export", params={"format": "xlsx"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_MIME

    workbook = load_workbook(io.BytesIO(response.content))
    assert set(workbook.sheetnames) == {
        "Summary", "Spend Breakdowns", "Suppliers", "Savings Opportunities",
        "Transactions", "Methodology",
    }
    assert workbook["Transactions"].max_row == analysis["filtered_record_count"] + 1
    assert "not guaranteed" in str(workbook["Savings Opportunities"]["A1"].value)


def test_export_csv(api_client, analysis):
    response = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/export", params={"format": "csv"}
    )
    text = response.content.decode("utf-8-sig")
    lines = text.strip().splitlines()

    assert lines[0].startswith("PO Number,Item,Transaction Date")
    assert len(lines) == analysis["filtered_record_count"] + 1


def test_export_json(api_client, analysis):
    response = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/export", params={"format": "json"}
    )
    payload = json.loads(response.content)

    assert payload["report_type"] == "sap_spend_analysis"
    assert "not guaranteed" in payload["disclaimer"]
    assert len(payload["transactions"]) == analysis["filtered_record_count"]
    assert len(payload["savings_rule_catalogue"]) == 6
    assert payload["methodology"]["calculation_basis"]


def test_export_rejects_an_unknown_format(api_client, analysis):
    response = api_client.get(
        f"/api/v1/spend/analyses/{analysis['analysis_id']}/export", params={"format": "pdf"}
    )
    assert response.status_code == 422


def test_export_of_unknown_analysis_returns_404(api_client):
    assert api_client.get("/api/v1/spend/analyses/nope/export").status_code == 404


# ---------------------------------------------------------------------------
# Sample data endpoints
# ---------------------------------------------------------------------------
def test_sample_info(api_client, spend_sample_csv_path):
    body = api_client.get("/api/v1/spend/sample/info").json()["data"]
    assert body["available"] is True
    assert body["row_count"] > 1000
    assert body["months_covered"] >= 24
    assert body["data_origin"] == "demo_data"


@pytest.mark.parametrize("file_format", ["csv", "xlsx", "json"])
def test_sample_download(api_client, spend_sample_csv_path, file_format):
    response = api_client.get("/api/v1/spend/sample", params={"format": file_format})
    assert response.status_code == 200
    assert len(response.content) > 1000
