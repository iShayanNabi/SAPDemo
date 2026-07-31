"""Unit tests for the Invoice Validator rules, tolerances and engine isolation.

Each rule test builds the smallest set of records that should trigger it and
isolates the rule with ``enabled_rules`` so the assertion is exact.
"""

from __future__ import annotations

from datetime import date

import pytest

from tests.factories import (
    invoice_rule_ids,
    make_goods_receipt,
    make_invoice,
    make_po_line,
    run_invoice_validation,
)


# ---------------------------------------------------------------------------
# Clean baseline
# ---------------------------------------------------------------------------
def test_clean_invoice_raises_no_exceptions():
    result = run_invoice_validation([make_invoice()], [make_po_line()], [make_goods_receipt()])
    assert result.exceptions == []
    assert result.summary["fully_three_way_matched"] == 1


# ---------------------------------------------------------------------------
# One rule per test
# ---------------------------------------------------------------------------
def test_r001_duplicate_invoices():
    a = make_invoice(invoice_number="INV-A", po_number="PO-1")
    b = make_invoice(invoice_number="INV-B", po_number="PO-2")
    result = run_invoice_validation([a, b], enabled_rules=["IV-R001"])
    assert [e.invoice_number for e in result.exceptions] == ["INV-B"]
    assert result.exceptions[0].rule_id == "IV-R001"


def test_r002_duplicate_invoice_number():
    a = make_invoice(invoice_number="DUP", po_number="PO-1", invoice_date=date(2026, 3, 1), unit_price=100.0)
    b = make_invoice(invoice_number="DUP", po_number="PO-2", invoice_date=date(2026, 3, 8), unit_price=120.0)
    result = run_invoice_validation([a, b], enabled_rules=["IV-R002"])
    assert invoice_rule_ids(result) == {"IV-R002"}
    assert len(result.exceptions) == 1


def test_r003_missing_purchase_order():
    invoice = make_invoice(po_number="9999999999")
    result = run_invoice_validation([invoice], [make_po_line(po_number="4500000001")], enabled_rules=["IV-R003"])
    assert invoice_rule_ids(result) == {"IV-R003"}


def test_r004_missing_goods_receipt():
    invoice = make_invoice(po_number="PO-1")
    po = make_po_line(po_number="PO-1")
    # A GR for another PO makes the dataset present without covering this line.
    other_gr = make_goods_receipt(po_number="PO-2")
    result = run_invoice_validation([invoice], [po], [other_gr], enabled_rules=["IV-R004"])
    assert invoice_rule_ids(result) == {"IV-R004"}


def test_r005_price_mismatch():
    invoice = make_invoice(unit_price=130.0)
    result = run_invoice_validation([invoice], [make_po_line(unit_price=100.0)], enabled_rules=["IV-R005"])
    assert invoice_rule_ids(result) == {"IV-R005"}
    assert result.exceptions[0].difference_amount == pytest.approx(300.0)  # 30 * 10 units


def test_r005_price_within_tolerance_passes():
    invoice = make_invoice(unit_price=100.5)  # 0.5% over, inside the 2% / 1.0 tolerance
    result = run_invoice_validation([invoice], [make_po_line(unit_price=100.0)], enabled_rules=["IV-R005"])
    assert result.exceptions == []


def test_r006_quantity_mismatch_versus_receipt():
    invoice = make_invoice(quantity=8.0)
    result = run_invoice_validation(
        [invoice], [make_po_line()], [make_goods_receipt(received_quantity=10.0)],
        enabled_rules=["IV-R006"],
    )
    assert invoice_rule_ids(result) == {"IV-R006"}


def test_r007_tax_mismatch():
    invoice = make_invoice(subtotal=1000.0, tax=250.0)  # expected 190
    result = run_invoice_validation([invoice], enabled_rules=["IV-R007"])
    assert invoice_rule_ids(result) == {"IV-R007"}


def test_r008_currency_mismatch():
    invoice = make_invoice(currency="USD")
    result = run_invoice_validation([invoice], [make_po_line(currency="EUR")], enabled_rules=["IV-R008"])
    assert invoice_rule_ids(result) == {"IV-R008"}


def test_r009_supplier_mismatch():
    invoice = make_invoice(supplier_id="0000700099")
    result = run_invoice_validation(
        [invoice], [make_po_line(supplier_id="0000700001")], enabled_rules=["IV-R009"]
    )
    assert invoice_rule_ids(result) == {"IV-R009"}


def test_r010_freight_mismatch():
    invoice = make_invoice(freight=900.0)  # cap is max(250, 10% of 1000) = 250
    result = run_invoice_validation([invoice], enabled_rules=["IV-R010"])
    assert invoice_rule_ids(result) == {"IV-R010"}


def test_r011_payment_term_mismatch():
    invoice = make_invoice(payment_terms="NT60")
    result = run_invoice_validation([invoice], [make_po_line(payment_terms="NT30")], enabled_rules=["IV-R011"])
    assert invoice_rule_ids(result) == {"IV-R011"}


def test_r012_three_way_match_exception():
    invoice = make_invoice(quantity=10.0)
    gr = make_goods_receipt(received_quantity=10.0, accepted_quantity=7.0, rejected_quantity=3.0)
    result = run_invoice_validation([invoice], [make_po_line()], [gr], enabled_rules=["IV-R012"])
    assert invoice_rule_ids(result) == {"IV-R012"}


def test_r013_overbilling():
    a = make_invoice(invoice_number="INV-A", po_number="PO-1", quantity=10.0, invoice_date=date(2026, 3, 1))
    b = make_invoice(invoice_number="INV-B", po_number="PO-1", quantity=10.0, invoice_date=date(2026, 3, 15))
    result = run_invoice_validation([a, b], [make_po_line(po_number="PO-1", quantity=10.0)], enabled_rules=["IV-R013"])
    assert invoice_rule_ids(result) == {"IV-R013"}
    assert result.exceptions[0].severity.value == "critical"


def test_r014_invoice_before_purchase_order():
    invoice = make_invoice(invoice_date=date(2026, 3, 1))
    po = make_po_line(order_date=date(2026, 3, 10))
    result = run_invoice_validation([invoice], [po], enabled_rules=["IV-R014"])
    assert invoice_rule_ids(result) == {"IV-R014"}


def test_r015_invoice_before_receipt():
    invoice = make_invoice(invoice_date=date(2026, 3, 1))
    gr = make_goods_receipt(receipt_date=date(2026, 3, 10))
    result = run_invoice_validation([invoice], [make_po_line()], [gr], enabled_rules=["IV-R015"])
    assert invoice_rule_ids(result) == {"IV-R015"}


def test_r016_future_invoice_date():
    invoice = make_invoice(invoice_date=date(2026, 9, 15))
    result = run_invoice_validation([invoice], as_of_date=date(2026, 6, 30), enabled_rules=["IV-R016"])
    assert invoice_rule_ids(result) == {"IV-R016"}


def test_r017_closed_po_invoicing():
    result = run_invoice_validation(
        [make_invoice()], [make_po_line(po_status="Closed")], enabled_rules=["IV-R017"]
    )
    assert invoice_rule_ids(result) == {"IV-R017"}


# ---------------------------------------------------------------------------
# Tolerance calculation
# ---------------------------------------------------------------------------
def test_tolerance_exceeds_needs_both_absolute_and_percentage():
    from app.modules.invoice_validator.thresholds import Tolerance

    tol = Tolerance(pct=2.0, abs=1.0)
    assert tol.exceeds(100.0, 105.0) is True          # 5 > 1 and 5 > 2
    assert tol.exceeds(100.0, 100.9) is False         # 0.9 < 1 absolute guard
    assert tol.exceeds(1000.0, 1015.0) is False       # 15 < 20 (2%) percentage guard
    assert tol.exceeds(None, 105.0) is False
    assert tol.exceeds(100.0, None) is False


def test_tolerance_override_changes_outcome(invoice_validator_config):
    from app.modules.invoice_validator.thresholds import Tolerance

    invoice = make_invoice(unit_price=130.0)
    po = make_po_line(unit_price=100.0)

    strict = run_invoice_validation([invoice], [po], enabled_rules=["IV-R005"])
    assert invoice_rule_ids(strict) == {"IV-R005"}

    loose = invoice_validator_config.with_tolerances(
        invoice_validator_config.tolerances.model_copy(
            update={"price": Tolerance(pct=100.0, abs=1000.0)}
        )
    )
    relaxed = run_invoice_validation([invoice], [po], config=loose, enabled_rules=["IV-R005"])
    assert relaxed.exceptions == []


def test_config_edit_changes_outcome(tmp_path):
    """Editing a value in the JSON config changes the outcome with no code change."""
    import json

    from app.modules.invoice_validator.thresholds import (
        DEFAULT_CONFIG_PATH,
        load_invoice_validator_config,
    )

    raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    invoice = make_invoice(freight=900.0)

    default_config = load_invoice_validator_config(DEFAULT_CONFIG_PATH)
    assert invoice_rule_ids(run_invoice_validation([invoice], config=default_config, enabled_rules=["IV-R010"])) == {"IV-R010"}

    raw["freight_policy"]["flat_cap"] = 100000.0
    edited_path = tmp_path / "edited_rules.json"
    edited_path.write_text(json.dumps(raw), encoding="utf-8")
    edited_config = load_invoice_validator_config(edited_path)
    assert run_invoice_validation([invoice], config=edited_config, enabled_rules=["IV-R010"]).exceptions == []


# ---------------------------------------------------------------------------
# Engine behaviour
# ---------------------------------------------------------------------------
def test_one_broken_rule_does_not_kill_the_run(monkeypatch):
    from app.modules.invoice_validator.rules.amounts import PriceMismatchRule

    def _boom(self, context):
        raise RuntimeError("intentional test failure")

    monkeypatch.setattr(PriceMismatchRule, "evaluate", _boom)

    invoice = make_invoice(unit_price=130.0, currency="USD")
    result = run_invoice_validation([invoice], [make_po_line(unit_price=100.0, currency="EUR")])
    assert any(err["rule_id"] == "IV-R005" for err in result.rule_errors)
    # The currency mismatch rule still ran despite the price rule failing.
    assert "IV-R008" in invoice_rule_ids(result)


def test_po_dependent_rules_skipped_without_po_dataset():
    result = run_invoice_validation([make_invoice()])
    skipped = {e.rule_id: e.skipped_reason for e in result.executions if e.skipped_reason}
    assert skipped.get("IV-R003") == "no_purchase_order_dataset"
    assert skipped.get("IV-R005") == "no_purchase_order_dataset"


def test_gr_dependent_rules_skipped_without_gr_dataset():
    result = run_invoice_validation([make_invoice()], [make_po_line()])
    skipped = {e.rule_id: e.skipped_reason for e in result.executions if e.skipped_reason}
    assert skipped.get("IV-R004") == "no_goods_receipt_dataset"
    assert skipped.get("IV-R012") == "no_goods_receipt_dataset"


def test_exception_output_carries_every_required_field():
    invoice = make_invoice(unit_price=130.0)
    result = run_invoice_validation([invoice], [make_po_line(unit_price=100.0)], enabled_rules=["IV-R005"])
    payload = result.exceptions[0].to_dict()
    for key in (
        "rule_id", "exception_type", "severity", "invoice_number", "supplier_id", "po_number",
        "po_item", "gr_number", "expected_value", "actual_value", "difference", "difference_amount",
        "currency", "explanation", "recommended_action",
    ):
        assert key in payload
    assert payload["output_origin"] == "rule_based"
