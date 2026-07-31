"""Unit tests for the supplier eligibility filters.

Each hard constraint is exercised with a supplier that passes everything except
the one thing under test, so a failure points straight at the responsible rule.
"""

from __future__ import annotations

from app.modules.supplier_reco.eligibility import evaluate_eligibility
from tests.factories import make_requirement, make_supplier


def _reasons(supplier, requirement, config):
    return evaluate_eligibility(supplier, requirement, config).reasons


def test_healthy_supplier_is_eligible(supplier_reco_config):
    result = evaluate_eligibility(make_supplier(), make_requirement(), supplier_reco_config)
    assert result.is_eligible
    assert result.status == "eligible"
    assert result.reasons == []


def test_material_mismatch_is_ineligible(supplier_reco_config):
    supplier = make_supplier(materials_supplied=["MAT-9999"])
    result = evaluate_eligibility(supplier, make_requirement(material="MAT-1000"), supplier_reco_config)
    assert not result.is_eligible
    assert any("does not supply material" in r.lower() for r in result.reasons)


def test_plant_mismatch_is_ineligible(supplier_reco_config):
    supplier = make_supplier(plants_served=["2010"])
    result = evaluate_eligibility(supplier, make_requirement(plant="1010"), supplier_reco_config)
    assert not result.is_eligible
    assert any("plant" in r.lower() for r in result.reasons)


def test_capacity_below_minimum_is_ineligible(supplier_reco_config):
    supplier = make_supplier(available_capacity=50.0)
    requirement = make_requirement(minimum_available_capacity=100.0, quantity=10)
    result = evaluate_eligibility(supplier, requirement, supplier_reco_config)
    assert not result.is_eligible
    assert any("capacity" in r.lower() for r in result.reasons)


def test_capacity_cannot_cover_quantity_is_ineligible(supplier_reco_config):
    supplier = make_supplier(available_capacity=40.0)
    requirement = make_requirement(quantity=100, minimum_available_capacity=None)
    result = evaluate_eligibility(supplier, requirement, supplier_reco_config)
    assert not result.is_eligible
    assert any("cover" in r.lower() for r in result.reasons)


def test_quality_below_minimum_is_ineligible(supplier_reco_config):
    supplier = make_supplier(quality_score=70.0)
    requirement = make_requirement(minimum_quality_score=85.0)
    result = evaluate_eligibility(supplier, requirement, supplier_reco_config)
    assert not result.is_eligible
    assert any("quality" in r.lower() for r in result.reasons)


def test_risk_tolerance_low_excludes_medium_risk(supplier_reco_config):
    supplier = make_supplier(risk_score=45.0)  # above the 'low' ceiling of 30
    low = evaluate_eligibility(supplier, make_requirement(risk_tolerance="low"), supplier_reco_config)
    assert not low.is_eligible
    medium = evaluate_eligibility(supplier, make_requirement(risk_tolerance="medium"), supplier_reco_config)
    assert medium.is_eligible


def test_risk_tolerance_high_admits_high_risk(supplier_reco_config):
    supplier = make_supplier(risk_score=85.0)
    assert not evaluate_eligibility(supplier, make_requirement(risk_tolerance="medium"), supplier_reco_config).is_eligible
    assert evaluate_eligibility(supplier, make_requirement(risk_tolerance="high"), supplier_reco_config).is_eligible


def test_sustainability_requirement_excludes_low_esg(supplier_reco_config):
    supplier = make_supplier(esg_score=40.0)
    requirement = make_requirement(sustainability_requirement=70.0)
    result = evaluate_eligibility(supplier, requirement, supplier_reco_config)
    assert not result.is_eligible
    assert any("esg" in r.lower() for r in result.reasons)
    # No sustainability requirement -> eligible.
    assert evaluate_eligibility(supplier, make_requirement(), supplier_reco_config).is_eligible


def test_contract_requirement_excludes_uncontracted(supplier_reco_config):
    supplier = make_supplier(contract_status="No contract", contract_expiration=None)
    requirement = make_requirement(contract_requirement=True)
    result = evaluate_eligibility(supplier, requirement, supplier_reco_config)
    assert not result.is_eligible
    assert any("contract" in r.lower() for r in result.reasons)
    # Without the requirement the same supplier is eligible.
    assert evaluate_eligibility(supplier, make_requirement(), supplier_reco_config).is_eligible


def test_missing_data_is_ineligible_when_a_minimum_is_required(supplier_reco_config):
    supplier = make_supplier(quality_score=None)
    requirement = make_requirement(minimum_quality_score=80.0)
    result = evaluate_eligibility(supplier, requirement, supplier_reco_config)
    assert not result.is_eligible
    assert any("not known" in r.lower() for r in result.reasons)


def test_multiple_failures_all_reported(supplier_reco_config):
    supplier = make_supplier(
        materials_supplied=["MAT-9999"], risk_score=95.0, esg_score=10.0,
    )
    requirement = make_requirement(risk_tolerance="low", sustainability_requirement=70.0)
    reasons = _reasons(supplier, requirement, supplier_reco_config)
    # Material, risk and ESG should each contribute a reason.
    assert len(reasons) >= 3
