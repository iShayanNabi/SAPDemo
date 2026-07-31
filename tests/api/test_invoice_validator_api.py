"""API tests for the Invoice Validator endpoints."""

from __future__ import annotations

import pytest

from tests.factories import invoice_rows_to_csv


def _upload(api_client, dataset: str, filename: str, content: bytes, content_type: str = "text/csv") -> dict:
    response = api_client.post(
        "/api/v1/invoices/upload",
        data={"dataset": dataset},
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _upload_samples(api_client, invoice_csv, po_csv, gr_csv) -> dict[str, str]:
    return {
        "invoice": _upload(api_client, "invoices", "sample_invoices.csv", invoice_csv.read_bytes())["upload_id"],
        "po": _upload(api_client, "purchase_orders", "sample_pos.csv", po_csv.read_bytes())["upload_id"],
        "gr": _upload(api_client, "goods_receipts", "sample_gr.csv", gr_csv.read_bytes())["upload_id"],
    }


def _validate(api_client, uploads: dict[str, str], **extra) -> dict:
    body = {
        "invoice_upload_id": uploads["invoice"],
        "po_upload_id": uploads["po"],
        "gr_upload_id": uploads["gr"],
        "as_of_date": "2026-06-30",
        "generate_ai_summary": False,
        **extra,
    }
    response = api_client.post("/api/v1/invoices/validate", json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def test_upload_invoices_maps_sap_headers(api_client, invoice_sample_csv_path):
    data = _upload(api_client, "invoices", "sample_invoices.csv", invoice_sample_csv_path.read_bytes())
    assert data["dataset"] == "invoices"
    assert data["row_count"] > 400
    assert data["missing_required_fields"] == []
    assert data["suggested_mapping"]  # something mapped
    assert data["is_mappable"] is True


def test_upload_rejects_empty_file(api_client):
    response = api_client.post(
        "/api/v1/invoices/upload",
        data={"dataset": "invoices"},
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert response.status_code == 400


def test_upload_requires_dataset(api_client, invoice_sample_csv_path):
    response = api_client.post(
        "/api/v1/invoices/upload",
        files={"file": ("sample_invoices.csv", invoice_sample_csv_path.read_bytes(), "text/csv")},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------
def test_validate_end_to_end(
    api_client, invoice_sample_csv_path, invoice_po_sample_csv_path, goods_receipt_sample_csv_path
):
    uploads = _upload_samples(
        api_client, invoice_sample_csv_path, invoice_po_sample_csv_path, goods_receipt_sample_csv_path
    )
    data = _validate(api_client, uploads)
    assert data["invoice_count"] > 400
    assert data["exceptions_count"] == 17
    assert data["three_way_matches"]
    rules_hit = {r["rule_id"] for r in data["kpis"]["rule_counts"]}
    assert len(rules_hit) == 17
    assert data["disclaimer"]


def test_validate_missing_invoice_upload_is_404(api_client):
    response = api_client.post(
        "/api/v1/invoices/validate",
        json={"invoice_upload_id": "does-not-exist", "generate_ai_summary": False},
    )
    assert response.status_code == 404


def test_validate_unknown_rule_is_422(api_client, invoice_sample_csv_path):
    upload_id = _upload(api_client, "invoices", "sample_invoices.csv", invoice_sample_csv_path.read_bytes())["upload_id"]
    response = api_client.post(
        "/api/v1/invoices/validate",
        json={"invoice_upload_id": upload_id, "enabled_rules": ["IV-R999"], "generate_ai_summary": False},
    )
    assert response.status_code == 422


def test_validate_without_po_and_gr_skips_dependent_rules(api_client, invoice_sample_csv_path):
    upload_id = _upload(api_client, "invoices", "sample_invoices.csv", invoice_sample_csv_path.read_bytes())["upload_id"]
    response = api_client.post(
        "/api/v1/invoices/validate",
        json={"invoice_upload_id": upload_id, "as_of_date": "2026-06-30", "generate_ai_summary": False},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    skipped = {e["rule_id"] for e in data["rule_executions"] if e.get("skipped_reason") not in (None, "disabled")}
    assert "IV-R003" in skipped and "IV-R004" in skipped


def test_tolerance_override_reduces_exceptions(
    api_client, invoice_sample_csv_path, invoice_po_sample_csv_path, goods_receipt_sample_csv_path
):
    uploads = _upload_samples(
        api_client, invoice_sample_csv_path, invoice_po_sample_csv_path, goods_receipt_sample_csv_path
    )
    strict = _validate(api_client, uploads)
    wide = _validate(
        api_client, uploads,
        tolerances={"price": {"pct": 1000.0, "abs": 100000.0}, "quantity": {"pct": 1000.0, "abs": 100000.0}},
    )
    assert wide["exceptions_count"] < strict["exceptions_count"]


# ---------------------------------------------------------------------------
# Retrieval, exceptions, export
# ---------------------------------------------------------------------------
def test_get_validation_and_filtered_exceptions(
    api_client, invoice_sample_csv_path, invoice_po_sample_csv_path, goods_receipt_sample_csv_path
):
    uploads = _upload_samples(
        api_client, invoice_sample_csv_path, invoice_po_sample_csv_path, goods_receipt_sample_csv_path
    )
    validation_id = _validate(api_client, uploads)["validation_id"]

    detail = api_client.get(f"/api/v1/invoices/validations/{validation_id}").json()["data"]
    assert detail["validation_id"] == validation_id

    all_exc = api_client.get(f"/api/v1/invoices/validations/{validation_id}/exceptions").json()["data"]
    assert all_exc["total"] == 17

    critical = api_client.get(
        f"/api/v1/invoices/validations/{validation_id}/exceptions", params={"severity": "critical"}
    ).json()["data"]
    assert critical["total"] == 1
    assert critical["exceptions"][0]["rule_id"] == "IV-R013"

    by_rule = api_client.get(
        f"/api/v1/invoices/validations/{validation_id}/exceptions", params={"rule_id": "IV-R005"}
    ).json()["data"]
    assert by_rule["total"] == 1


@pytest.mark.parametrize(
    "fmt,media",
    [
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("csv", "text/csv"),
        ("json", "application/json"),
    ],
)
def test_export_formats(
    api_client, invoice_sample_csv_path, invoice_po_sample_csv_path, goods_receipt_sample_csv_path, fmt, media
):
    uploads = _upload_samples(
        api_client, invoice_sample_csv_path, invoice_po_sample_csv_path, goods_receipt_sample_csv_path
    )
    validation_id = _validate(api_client, uploads)["validation_id"]
    response = api_client.get(
        f"/api/v1/invoices/validations/{validation_id}/export", params={"format": fmt}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media.split(";")[0])
    assert len(response.content) > 100


def test_validation_not_found_is_404(api_client):
    assert api_client.get("/api/v1/invoices/validations/nope").status_code == 404
    assert api_client.get("/api/v1/invoices/validations/nope/exceptions").status_code == 404


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
def test_fields_catalogue_has_three_datasets(api_client):
    data = api_client.get("/api/v1/invoices/fields").json()["data"]
    assert len(data["invoices"]) == 16
    assert len(data["goods_receipts"]) == 7
    assert any(f["name"] == "po_status" for f in data["purchase_orders"])


def test_rules_catalogue_lists_seventeen_rules(api_client):
    data = api_client.get("/api/v1/invoices/rules").json()["data"]
    assert len(data["rules"]) == 17
    assert set(data["tolerances"]) == {"price", "quantity", "tax", "freight"}
    assert data["expected_tax_rate"] == pytest.approx(0.19)


def test_sample_info_and_download(api_client, invoice_sample_csv_path):
    info = api_client.get("/api/v1/invoices/sample/info").json()["data"]
    assert info["available"] is True
    assert info["invoice_count"] and info["invoice_count"] > 400

    download = api_client.get("/api/v1/invoices/sample", params={"dataset": "goods_receipts", "format": "csv"})
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/csv")


# ---------------------------------------------------------------------------
# Mapping with hand-built files
# ---------------------------------------------------------------------------
def test_upload_and_validate_minimal_built_files(api_client):
    invoices = [{
        "invoice_number": "INV-100", "supplier_id": "S1", "supplier_name": "Acme",
        "po_number": "PO-100", "po_item": "10", "invoice_date": "2026-03-20", "posting_date": "2026-03-21",
        "quantity": 5, "unit_price": 200.0, "subtotal": 1000.0, "tax": 190.0, "freight": 10.0,
        "currency": "EUR", "total_amount": 1200.0, "payment_terms": "NT30", "gr_reference": "GR-1",
    }]
    pos = [{
        "po_number": "PO-100", "po_item": "10", "supplier_id": "S1", "supplier_name": "Acme",
        "material": "M1", "quantity": 5, "unit_price": 150.0, "currency": "EUR",
        "payment_terms": "NT30", "order_date": "2026-03-01", "po_status": "Open",
    }]
    grs = [{
        "gr_number": "GR-1", "po_number": "PO-100", "po_item": "10", "receipt_date": "2026-03-10",
        "received_quantity": 5, "accepted_quantity": 5, "rejected_quantity": 0,
    }]
    uploads = {
        "invoice": _upload(api_client, "invoices", "inv.csv", invoice_rows_to_csv(invoices, "invoices"))["upload_id"],
        "po": _upload(api_client, "purchase_orders", "po.csv", invoice_rows_to_csv(pos, "purchase_orders"))["upload_id"],
        "gr": _upload(api_client, "goods_receipts", "gr.csv", invoice_rows_to_csv(grs, "goods_receipts"))["upload_id"],
    }
    data = _validate(api_client, uploads)
    # Invoiced 200 vs PO 150 -> price mismatch.
    assert "IV-R005" in {r["rule_id"] for r in data["kpis"]["rule_counts"]}
