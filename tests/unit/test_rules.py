"""Unit tests for the 20 deterministic risk rules.

Each rule gets at least two tests: one dataset that must produce a finding and
one that must stay clean. The clean case matters as much as the positive one -
a rule that fires on healthy data is worse than no rule at all.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.modules.po_risk.rules.approvals import ExcessiveChangesRule, HighValueWithoutApprovalRule
from app.modules.po_risk.rules.contracts import (
    MaverickSpendRule,
    MissingContractReferenceRule,
    OffContractPurchaseRule,
    UnusualPaymentTermsRule,
)
from app.modules.po_risk.rules.data_quality import (
    CurrencyAnomalyRule,
    MissingRequiredFieldsRule,
    QuantityAnomalyRule,
)
from app.modules.po_risk.rules.delivery import (
    DeliveryBeforeOrderRule,
    LateDeliveryRule,
    RequestedBeforeOrderRule,
)
from app.modules.po_risk.rules.duplication import DuplicateLineItemRule, DuplicatePurchaseOrderRule
from app.modules.po_risk.rules.pricing import MaterialPriceVarianceRule, UnitPriceIncreaseRule
from app.modules.po_risk.rules.splitting import ApprovalThresholdProximityRule, SplitPurchaseRule
from app.modules.po_risk.rules.supplier import HighRiskSupplierRule, SupplierConcentrationRule
from app.schemas.common import Severity
from tests.factories import BASE_DATE, make_context, make_row


# ---------------------------------------------------------------------------
# PO-R001 duplicate purchase orders
# ---------------------------------------------------------------------------
def test_duplicate_purchase_order_detected(rule_config):
    rows = [
        make_row(po_number="4500000001", quantity=50, unit_price=200.0),
        make_row(po_number="4500000002", quantity=50, unit_price=200.0,
                 order_date=BASE_DATE + timedelta(days=3)),
    ]
    findings = DuplicatePurchaseOrderRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.po_number == "4500000002"
    assert finding.evidence["original_po_number"] == "4500000001"
    assert finding.evidence["days_apart"] == 3
    assert finding.severity.rank >= Severity.HIGH.rank


def test_duplicate_purchase_order_outside_date_window(rule_config):
    rows = [
        make_row(po_number="4500000001", quantity=50, unit_price=200.0),
        make_row(po_number="4500000002", quantity=50, unit_price=200.0,
                 order_date=BASE_DATE + timedelta(days=40)),
    ]
    assert DuplicatePurchaseOrderRule(rule_config).evaluate(make_context(rows)) == []


def test_duplicate_purchase_order_ignores_different_values(rule_config):
    rows = [
        make_row(po_number="4500000001", quantity=50, unit_price=200.0),
        make_row(po_number="4500000002", quantity=80, unit_price=200.0,
                 order_date=BASE_DATE + timedelta(days=2)),
    ]
    assert DuplicatePurchaseOrderRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R002 duplicate line items
# ---------------------------------------------------------------------------
def test_duplicate_line_item_detected(rule_config):
    rows = [
        make_row(po_item="00010"),
        make_row(po_item="00020"),
    ]
    findings = DuplicateLineItemRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].po_item == "00020"
    assert findings[0].evidence["original_item"] == "00010"


def test_duplicate_line_item_not_raised_for_different_quantity(rule_config):
    rows = [make_row(po_item="00010", quantity=10), make_row(po_item="00020", quantity=11)]
    assert DuplicateLineItemRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R003 split purchases
# ---------------------------------------------------------------------------
def test_split_purchase_detected(rule_config):
    rows = [
        make_row(po_number=str(4500000001 + index), quantity=100, unit_price=90.0,
                 order_date=BASE_DATE + timedelta(days=index * 2))
        for index in range(4)
    ]
    findings = SplitPurchaseRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    evidence = findings[0].evidence
    assert evidence["order_count"] == 4
    assert evidence["combined_value_base"] == pytest.approx(36000.0)
    # 25,000 is the bundling threshold; the *approval* level the cluster crosses is 10,000.
    assert 10000.0 in evidence["crossed_approval_thresholds"]


def test_split_purchase_needs_minimum_order_count(rule_config):
    rows = [
        make_row(po_number=str(4500000001 + index), quantity=100, unit_price=90.0,
                 order_date=BASE_DATE + timedelta(days=index * 2))
        for index in range(2)
    ]
    assert SplitPurchaseRule(rule_config).evaluate(make_context(rows)) == []


def test_split_purchase_ignores_orders_spread_over_time(rule_config):
    rows = [
        make_row(po_number=str(4500000001 + index), quantity=100, unit_price=90.0,
                 order_date=BASE_DATE + timedelta(days=index * 30))
        for index in range(4)
    ]
    assert SplitPurchaseRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R004 approval threshold proximity
# ---------------------------------------------------------------------------
def test_order_just_below_threshold_detected(rule_config):
    rows = [make_row(quantity=1, unit_price=9850.0)]
    findings = ApprovalThresholdProximityRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].evidence["approval_threshold_base"] == 10000.0
    assert findings[0].evidence["gap_pct"] == pytest.approx(1.5)


def test_order_comfortably_below_threshold_is_clean(rule_config):
    rows = [make_row(quantity=1, unit_price=7000.0)]
    assert ApprovalThresholdProximityRule(rule_config).evaluate(make_context(rows)) == []


def test_order_above_threshold_is_not_proximity(rule_config):
    rows = [make_row(quantity=1, unit_price=10500.0)]
    assert ApprovalThresholdProximityRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R005 unit price increase
# ---------------------------------------------------------------------------
def test_unit_price_increase_detected(rule_config):
    rows = [
        make_row(po_number="4500000001", unit_price=100.0),
        make_row(po_number="4500000002", unit_price=150.0,
                 order_date=BASE_DATE + timedelta(days=30)),
    ]
    findings = UnitPriceIncreaseRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].evidence["increase_pct"] == pytest.approx(50.0)
    assert findings[0].po_number == "4500000002"


def test_small_price_increase_is_clean(rule_config):
    rows = [
        make_row(po_number="4500000001", unit_price=100.0),
        make_row(po_number="4500000002", unit_price=110.0,
                 order_date=BASE_DATE + timedelta(days=30)),
    ]
    assert UnitPriceIncreaseRule(rule_config).evaluate(make_context(rows)) == []


def test_price_decrease_is_never_flagged(rule_config):
    rows = [
        make_row(po_number="4500000001", unit_price=200.0),
        make_row(po_number="4500000002", unit_price=100.0,
                 order_date=BASE_DATE + timedelta(days=10)),
    ]
    assert UnitPriceIncreaseRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R006 material price variance
# ---------------------------------------------------------------------------
def test_price_variance_against_material_median(rule_config):
    rows = [
        make_row(po_number=str(4500000001 + index), supplier_id=f"000010000{index + 1}",
                 unit_price=100.0)
        for index in range(4)
    ]
    rows.append(make_row(po_number="4500000099", supplier_id="0000100009", unit_price=180.0))
    findings = MaterialPriceVarianceRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].po_number == "4500000099"
    assert findings[0].evidence["variance_pct"] == pytest.approx(80.0)


def test_price_variance_needs_enough_observations(rule_config):
    rows = [
        make_row(po_number="4500000001", unit_price=100.0),
        make_row(po_number="4500000002", unit_price=180.0),
    ]
    assert MaterialPriceVarianceRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R007 off-contract purchase
# ---------------------------------------------------------------------------
def test_off_contract_purchase_detected(rule_config):
    rows = [
        make_row(po_number="4500000001", contract_number="4600000123", quantity=40, unit_price=100.0),
        make_row(po_number="4500000002", contract_number="4600000123", quantity=40, unit_price=100.0),
        make_row(po_number="4500000003", contract_number=None, quantity=40, unit_price=100.0),
    ]
    findings = OffContractPurchaseRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].po_number == "4500000003"
    assert findings[0].evidence["contracted_lines_for_pair"] == 2


def test_off_contract_not_raised_without_contract_history(rule_config):
    rows = [make_row(po_number="4500000003", contract_number=None, quantity=40, unit_price=100.0)]
    assert OffContractPurchaseRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R008 missing contract reference
# ---------------------------------------------------------------------------
def test_missing_contract_on_high_value_line(rule_config):
    rows = [make_row(quantity=100, unit_price=400.0, contract_number=None)]
    findings = MissingContractReferenceRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].evidence["line_value_base"] == pytest.approx(40000.0)


def test_missing_contract_below_threshold_is_clean(rule_config):
    rows = [make_row(quantity=10, unit_price=400.0, contract_number=None)]
    assert MissingContractReferenceRule(rule_config).evaluate(make_context(rows)) == []


def test_contract_reference_present_is_clean(rule_config):
    rows = [make_row(quantity=100, unit_price=400.0, contract_number="4600000123")]
    assert MissingContractReferenceRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R009 high value without approval
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status", ["Not Approved", "Pending", "Blocked", None])
def test_high_value_without_approval_detected(rule_config, status):
    rows = [make_row(quantity=100, unit_price=250.0, approval_status=status)]
    findings = HighValueWithoutApprovalRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].severity is Severity.CRITICAL


@pytest.mark.parametrize("status", ["Approved", "approved", "Released"])
def test_released_high_value_order_is_clean(rule_config, status):
    rows = [make_row(quantity=100, unit_price=250.0, approval_status=status)]
    assert HighValueWithoutApprovalRule(rule_config).evaluate(make_context(rows)) == []


def test_low_value_without_approval_is_clean(rule_config):
    rows = [make_row(quantity=5, unit_price=100.0, approval_status="Open")]
    assert HighValueWithoutApprovalRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R010 late delivery
# ---------------------------------------------------------------------------
def test_late_delivery_detected(rule_config):
    rows = [
        make_row(
            requested_delivery_date=BASE_DATE + timedelta(days=14),
            actual_delivery_date=BASE_DATE + timedelta(days=34),
        )
    ]
    findings = LateDeliveryRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].evidence["delay_days"] == 20


def test_delivery_inside_grace_period_is_clean(rule_config):
    rows = [
        make_row(
            requested_delivery_date=BASE_DATE + timedelta(days=14),
            actual_delivery_date=BASE_DATE + timedelta(days=16),
        )
    ]
    assert LateDeliveryRule(rule_config).evaluate(make_context(rows)) == []


@pytest.mark.parametrize(
    ("delay_days", "expected"),
    [(10, Severity.LOW), (35, Severity.HIGH), (70, Severity.CRITICAL)],
)
def test_late_delivery_severity_scales_with_delay(rule_config, delay_days, expected):
    rows = [
        make_row(
            requested_delivery_date=BASE_DATE + timedelta(days=14),
            actual_delivery_date=BASE_DATE + timedelta(days=14 + delay_days),
        )
    ]
    findings = LateDeliveryRule(rule_config).evaluate(make_context(rows))
    assert findings[0].severity is expected


# ---------------------------------------------------------------------------
# PO-R011 / PO-R012 date consistency
# ---------------------------------------------------------------------------
def test_requested_delivery_before_order_detected(rule_config):
    rows = [make_row(requested_delivery_date=BASE_DATE - timedelta(days=5))]
    findings = RequestedBeforeOrderRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].evidence["days_before_order"] == 5
    assert findings[0].confidence_score == 1.0


def test_requested_delivery_after_order_is_clean(rule_config):
    assert RequestedBeforeOrderRule(rule_config).evaluate(make_context([make_row()])) == []


def test_actual_delivery_before_order_detected(rule_config):
    rows = [make_row(actual_delivery_date=BASE_DATE - timedelta(days=3))]
    findings = DeliveryBeforeOrderRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].evidence["pattern"] == "after-the-fact purchase order"


def test_actual_delivery_after_order_is_clean(rule_config):
    assert DeliveryBeforeOrderRule(rule_config).evaluate(make_context([make_row()])) == []


# ---------------------------------------------------------------------------
# PO-R013 quantity anomalies
# ---------------------------------------------------------------------------
def test_zero_quantity_detected(rule_config):
    findings = QuantityAnomalyRule(rule_config).evaluate(make_context([make_row(quantity=0)]))

    assert len(findings) == 1
    assert findings[0].evidence["anomaly_type"] == "non_positive_quantity"
    assert findings[0].severity.rank >= Severity.HIGH.rank


def test_quantity_outlier_against_material_median(rule_config):
    rows = [make_row(po_number=str(4500000001 + index), quantity=10) for index in range(5)]
    rows.append(make_row(po_number="4500000099", quantity=400))
    findings = QuantityAnomalyRule(rule_config).evaluate(make_context(rows))

    outliers = [f for f in findings if f.evidence.get("anomaly_type") == "quantity_outlier"]
    assert len(outliers) == 1
    assert outliers[0].evidence["multiple_of_median"] == pytest.approx(40.0)


def test_normal_quantities_are_clean(rule_config):
    rows = [make_row(po_number=str(4500000001 + index), quantity=10 + index) for index in range(6)]
    assert QuantityAnomalyRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R014 currency anomaly
# ---------------------------------------------------------------------------
def test_currency_anomaly_detected(rule_config):
    rows = [make_row(po_number=str(4500000001 + index)) for index in range(5)]
    rows.append(make_row(po_number="4500000099", currency="USD"))
    findings = CurrencyAnomalyRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].evidence["document_currency"] == "USD"
    assert findings[0].evidence["expected_currency"] == "EUR"


def test_consistent_currency_is_clean(rule_config):
    rows = [make_row(po_number=str(4500000001 + index)) for index in range(6)]
    assert CurrencyAnomalyRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R015 missing fields
# ---------------------------------------------------------------------------
def test_missing_watch_field_detected(rule_config):
    findings = MissingRequiredFieldsRule(rule_config).evaluate(
        make_context([make_row(material_group=None)])
    )

    assert len(findings) == 1
    assert findings[0].evidence["missing_watch_fields"] == ["material_group"]


def test_complete_row_is_clean(rule_config):
    assert MissingRequiredFieldsRule(rule_config).evaluate(make_context([make_row()])) == []


# ---------------------------------------------------------------------------
# PO-R016 unusual payment terms
# ---------------------------------------------------------------------------
def test_unusual_payment_terms_detected(rule_config):
    rows = [make_row(quantity=100, unit_price=100.0, payment_terms="NT120")]
    findings = UnusualPaymentTermsRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].evidence["payment_terms"] == "NT120"


def test_standard_payment_terms_are_clean(rule_config):
    rows = [make_row(quantity=100, unit_price=100.0, payment_terms="NT30")]
    assert UnusualPaymentTermsRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R017 excessive changes
# ---------------------------------------------------------------------------
def test_excessive_changes_detected(rule_config):
    findings = ExcessiveChangesRule(rule_config).evaluate(make_context([make_row(change_count=9)]))

    assert len(findings) == 1
    assert findings[0].evidence["change_count"] == 9


def test_change_count_within_limit_is_clean(rule_config):
    assert ExcessiveChangesRule(rule_config).evaluate(make_context([make_row(change_count=4)])) == []


def test_change_count_above_critical_limit_raises_severity(rule_config):
    findings = ExcessiveChangesRule(rule_config).evaluate(make_context([make_row(change_count=15)]))
    assert findings[0].severity.rank >= Severity.HIGH.rank


# ---------------------------------------------------------------------------
# PO-R018 supplier concentration
# ---------------------------------------------------------------------------
def test_supplier_concentration_detected(rule_config):
    rows = [
        make_row(po_number=str(4500000001 + index), supplier_id="0000100001",
                 material_group="MG10", quantity=100, unit_price=250.0)
        for index in range(6)
    ]
    findings = SupplierConcentrationRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].evidence["share_pct"] == pytest.approx(100.0)
    assert findings[0].po_number is None


def test_balanced_material_group_is_clean(rule_config):
    rows = []
    for index in range(6):
        rows.append(
            make_row(po_number=str(4500000001 + index),
                     supplier_id=f"000010000{index % 3 + 1}",
                     material_group="MG10", quantity=100, unit_price=250.0)
        )
    assert SupplierConcentrationRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R019 maverick spend
# ---------------------------------------------------------------------------
def test_maverick_spend_detected(rule_config):
    rows = [
        make_row(po_number="4500000001", supplier_id="0000100001", contract_number="4600000123"),
        make_row(po_number="4500000002", supplier_id="0000100001", contract_number="4600000123"),
        make_row(po_number="4500000003", supplier_id="0000100055", contract_number=None,
                 quantity=50, unit_price=100.0),
    ]
    findings = MaverickSpendRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].supplier_id == "0000100055"
    assert findings[0].evidence["preferred_supplier"] == "0000100001"


def test_contracted_supplier_is_not_maverick(rule_config):
    rows = [
        make_row(po_number="4500000001", supplier_id="0000100001", contract_number="4600000123"),
        make_row(po_number="4500000002", supplier_id="0000100001", contract_number="4600000123"),
        make_row(po_number="4500000003", supplier_id="0000100001", contract_number=None,
                 quantity=50, unit_price=100.0),
    ]
    assert MaverickSpendRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# PO-R020 high risk supplier
# ---------------------------------------------------------------------------
def test_high_risk_supplier_detected(rule_config):
    watch_listed = rule_config.high_risk_suppliers[0].supplier_id
    rows = [make_row(supplier_id=watch_listed)]
    findings = HighRiskSupplierRule(rule_config).evaluate(make_context(rows))

    assert len(findings) == 1
    assert findings[0].supplier_id == watch_listed
    assert findings[0].evidence["watch_list_reason"]


def test_unlisted_supplier_is_clean(rule_config):
    rows = [make_row(supplier_id="0000199999")]
    assert HighRiskSupplierRule(rule_config).evaluate(make_context(rows)) == []


# ---------------------------------------------------------------------------
# Cross-cutting behaviour
# ---------------------------------------------------------------------------
def test_severity_escalates_with_value(rule_config):
    """A medium rule becomes critical once the exposed value crosses the band."""
    rows = [make_row(quantity=1, unit_price=260000.0, payment_terms="CASH")]
    findings = UnusualPaymentTermsRule(rule_config).evaluate(make_context(rows))
    assert findings[0].severity is Severity.CRITICAL


def test_every_finding_is_labelled_rule_based(rule_config):
    rows = [make_row(quantity=0, payment_terms="CASH", change_count=20)]
    context = make_context(rows)
    for rule_class in (QuantityAnomalyRule, UnusualPaymentTermsRule, ExcessiveChangesRule):
        for finding in rule_class(rule_config).evaluate(context):
            assert finding.output_origin.value == "rule_based"
            assert finding.explanation
            assert finding.recommended_action
            assert 0.0 <= finding.confidence_score <= 1.0
            assert finding.estimated_financial_exposure >= 0.0
