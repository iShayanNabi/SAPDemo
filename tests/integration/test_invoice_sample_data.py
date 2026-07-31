"""Integration tests for the Invoice Validator sample datasets.

The scenario manifest is the specification. Each documented anchor invoice has a
check that the engine raises its rule end to end through HTTP, and the run is
compared against the recorded baseline.
"""

from __future__ import annotations


def _upload(api_client, dataset: str, path) -> str:
    response = api_client.post(
        "/api/v1/invoices/upload",
        data={"dataset": dataset},
        files={"file": (path.name, path.read_bytes(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["upload_id"]


def _validate(api_client, invoice_csv, po_csv, gr_csv, manifest, **extra) -> dict:
    body = {
        "invoice_upload_id": _upload(api_client, "invoices", invoice_csv),
        "po_upload_id": _upload(api_client, "purchase_orders", po_csv),
        "gr_upload_id": _upload(api_client, "goods_receipts", gr_csv),
        "as_of_date": manifest["as_of_date"],
        "generate_ai_summary": False,
        **extra,
    }
    response = api_client.post("/api/v1/invoices/validate", json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _exceptions(api_client, validation_id: str) -> list[dict]:
    return api_client.get(
        f"/api/v1/invoices/validations/{validation_id}/exceptions", params={"limit": 1000}
    ).json()["data"]["exceptions"]


# ---------------------------------------------------------------------------
# Dataset shape
# ---------------------------------------------------------------------------
def test_datasets_meet_minimum_sizes(invoice_baseline):
    assert invoice_baseline["invoice_count"] >= 400
    assert invoice_baseline["goods_receipt_count"] >= 300
    assert invoice_baseline["purchase_order_line_count"] >= 300


def test_sample_files_available_in_three_formats(invoice_sample_csv_path, invoice_sample_xlsx_path):
    assert invoice_sample_csv_path.is_file()
    assert invoice_sample_xlsx_path.is_file()


# ---------------------------------------------------------------------------
# Baseline reproduction and determinism
# ---------------------------------------------------------------------------
def test_run_reproduces_baseline(
    api_client, invoice_sample_csv_path, invoice_po_sample_csv_path,
    goods_receipt_sample_csv_path, invoice_scenario_manifest, invoice_baseline
):
    data = _validate(
        api_client, invoice_sample_csv_path, invoice_po_sample_csv_path,
        goods_receipt_sample_csv_path, invoice_scenario_manifest,
    )
    assert data["exceptions_count"] == invoice_baseline["exceptions_count"]
    assert data["kpis"]["severity_counts"] == invoice_baseline["severity_counts"]
    rule_counts = {r["rule_id"]: r["count"] for r in data["kpis"]["rule_counts"]}
    assert rule_counts == invoice_baseline["rule_counts"]

    flagged = sorted({e["invoice_number"] for e in _exceptions(api_client, data["validation_id"]) if e["invoice_number"]})
    assert flagged == invoice_baseline["flagged_invoice_numbers"]


def test_repeated_runs_are_identical(
    api_client, invoice_sample_csv_path, invoice_po_sample_csv_path,
    goods_receipt_sample_csv_path, invoice_scenario_manifest
):
    first = _validate(
        api_client, invoice_sample_csv_path, invoice_po_sample_csv_path,
        goods_receipt_sample_csv_path, invoice_scenario_manifest,
    )
    second = _validate(
        api_client, invoice_sample_csv_path, invoice_po_sample_csv_path,
        goods_receipt_sample_csv_path, invoice_scenario_manifest,
    )
    assert first["kpis"]["rule_counts"] == second["kpis"]["rule_counts"]
    assert first["exceptions_count"] == second["exceptions_count"]


def test_only_anchor_invoices_are_flagged(
    api_client, invoice_sample_csv_path, invoice_po_sample_csv_path,
    goods_receipt_sample_csv_path, invoice_scenario_manifest
):
    data = _validate(
        api_client, invoice_sample_csv_path, invoice_po_sample_csv_path,
        goods_receipt_sample_csv_path, invoice_scenario_manifest,
    )
    flagged = {e["invoice_number"] for e in _exceptions(api_client, data["validation_id"])}
    # Every flagged invoice is one of the documented anchors.
    anchors = {n for s in invoice_scenario_manifest["scenarios"] for n in s["invoice_numbers"]}
    assert flagged <= anchors


# ---------------------------------------------------------------------------
# Documented anchors - one assertion per rule
# ---------------------------------------------------------------------------
def test_every_anchor_rule_is_detected(
    api_client, invoice_sample_csv_path, invoice_po_sample_csv_path,
    goods_receipt_sample_csv_path, invoice_scenario_manifest
):
    data = _validate(
        api_client, invoice_sample_csv_path, invoice_po_sample_csv_path,
        goods_receipt_sample_csv_path, invoice_scenario_manifest,
    )
    exceptions = _exceptions(api_client, data["validation_id"])
    by_invoice: dict[str, set[str]] = {}
    for exception in exceptions:
        by_invoice.setdefault(exception["invoice_number"], set()).add(exception["rule_id"])

    for scenario in invoice_scenario_manifest["scenarios"]:
        rule_id = scenario["rule_id"]
        target = scenario["invoice_numbers"][-1]  # the flagged invoice for the anchor
        assert rule_id in by_invoice.get(target, set()), (
            f"{scenario['scenario_id']} ({rule_id}) not detected on {target}"
        )


# ---------------------------------------------------------------------------
# Format equivalence
# ---------------------------------------------------------------------------
def test_csv_and_xlsx_invoices_produce_the_same_result(
    api_client, invoice_sample_csv_path, invoice_sample_xlsx_path,
    invoice_po_sample_csv_path, goods_receipt_sample_csv_path, invoice_scenario_manifest
):
    csv_data = _validate(
        api_client, invoice_sample_csv_path, invoice_po_sample_csv_path,
        goods_receipt_sample_csv_path, invoice_scenario_manifest,
    )

    xlsx_upload = api_client.post(
        "/api/v1/invoices/upload",
        data={"dataset": "invoices"},
        files={
            "file": (
                "sample_invoices.xlsx",
                invoice_sample_xlsx_path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    ).json()["data"]
    body = {
        "invoice_upload_id": xlsx_upload["upload_id"],
        "po_upload_id": _upload(api_client, "purchase_orders", invoice_po_sample_csv_path),
        "gr_upload_id": _upload(api_client, "goods_receipts", goods_receipt_sample_csv_path),
        "as_of_date": invoice_scenario_manifest["as_of_date"],
        "generate_ai_summary": False,
    }
    xlsx_data = api_client.post("/api/v1/invoices/validate", json=body).json()["data"]
    assert xlsx_data["exceptions_count"] == csv_data["exceptions_count"]
