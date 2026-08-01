"""Unit tests for the Supplier Risk Copilot's question answering.

The copilot must do three things reliably: understand the questions the module
promises to answer, cite the internal records behind every answer, and say
plainly when the information is not in the loaded data. Each is tested here
against the pure engine, with no database and no AI provider involved.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.modules.supplier_risk.copilot import (
    CopilotIntent,
    answer_question,
    detect_intent,
    resolve_supplier,
)
from tests.factories import (
    RISK_AS_OF,
    make_risk_event,
    make_risk_profile,
    run_risk_assessment_for,
)


@pytest.fixture
def assessment(supplier_risk_config):
    """A small portfolio: one risky supplier, two healthy ones, one sparse."""
    risky = make_risk_profile(
        supplier_id="0000300002",
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
    )
    healthy = make_risk_profile(
        supplier_id="0000300003",
        supplier_name="Kestrel Specialities SA",
        spend_category="Components",
    )
    expiring = make_risk_profile(
        supplier_id="0000300007",
        supplier_name="Fairmont Legacy Trading BV",
        spend_category="Components",
        contract_expiration=RISK_AS_OF + timedelta(days=20),
        contract_number="4600000007",
    )
    events = [
        make_risk_event(
            event_id=f"EVT-{index:03d}",
            supplier_id="0000300002",
            event_type="late_delivery",
            severity="high",
            reference="4500000123",
            event_date=RISK_AS_OF - timedelta(days=20),
            description="Delivery 12 days late",
        )
        for index in range(3)
    ] + [
        make_risk_event(
            event_id="EVT-900",
            supplier_id="0000300002",
            event_type="invoice_exception",
            severity="critical",
            reference="5100000999",
            event_date=RISK_AS_OF - timedelta(days=15),
            description="Billed above the purchase order price",
        )
    ]
    return run_risk_assessment_for([risky, healthy, expiring], events)


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Show supplier ABC's risk.", CopilotIntent.SUPPLIER_RISK),
        ("Why is this supplier high risk?", CopilotIntent.WHY_RISK),
        ("Which suppliers have the most delivery issues?", CopilotIntent.DELIVERY_ISSUES),
        ("Which suppliers have contracts expiring soon?", CopilotIntent.CONTRACTS_EXPIRING),
        ("Which alternative supplier has lower risk?", CopilotIntent.ALTERNATIVES),
        ("What action should procurement take?", CopilotIntent.RECOMMENDED_ACTION),
        ("Which suppliers are the highest risk?", CopilotIntent.HIGHEST_RISK),
        ("What is the weather in Berlin?", CopilotIntent.UNKNOWN),
    ],
)
def test_detect_intent_covers_the_documented_questions(question, expected):
    assert detect_intent(question) is expected


def test_empty_question_is_unknown():
    assert detect_intent("") is CopilotIntent.UNKNOWN


# ---------------------------------------------------------------------------
# Supplier resolution
# ---------------------------------------------------------------------------


def test_supplier_is_resolved_by_id(assessment, supplier_risk_config):
    profile, _ = resolve_supplier(
        "Show 0000300002 risk", assessment, supplier_risk_config
    )

    assert profile is not None
    assert profile.supplier_id == "0000300002"


def test_supplier_is_resolved_by_full_name(assessment, supplier_risk_config):
    profile, _ = resolve_supplier(
        "Show supplier Ravenna Frontier Trading BV's risk", assessment, supplier_risk_config
    )

    assert profile is not None
    assert profile.supplier_id == "0000300002"


def test_supplier_is_resolved_by_a_distinctive_short_name(assessment, supplier_risk_config):
    profile, _ = resolve_supplier("Show supplier Kestrel risk", assessment, supplier_risk_config)

    assert profile is not None
    assert profile.supplier_id == "0000300003"


def test_explicit_supplier_id_context_wins(assessment, supplier_risk_config):
    """Follow-ups like 'why is this supplier high risk?' carry the id separately."""
    profile, _ = resolve_supplier(
        "Why is this supplier high risk?",
        assessment,
        supplier_risk_config,
        supplier_id="0000300007",
    )

    assert profile is not None
    assert profile.supplier_id == "0000300007"


def test_unknown_supplier_is_not_resolved_and_is_quoted_back(assessment, supplier_risk_config):
    profile, mentioned = resolve_supplier(
        "Show supplier Northwind Traders risk.", assessment, supplier_risk_config
    )

    assert profile is None
    assert mentioned == "Northwind Traders"


# ---------------------------------------------------------------------------
# The six documented questions
# ---------------------------------------------------------------------------


def test_supplier_risk_question_reports_the_computed_score(assessment, supplier_risk_config):
    answer = answer_question(
        "Show supplier Ravenna Frontier Trading BV's risk.", assessment, supplier_risk_config
    )
    profile = assessment.by_id("0000300002")

    assert answer.intent is CopilotIntent.SUPPLIER_RISK
    assert answer.data_available is True
    assert f"{profile.overall_score:g}" in answer.answer
    assert profile.overall_band in answer.answer
    assert "0000300002" in answer.suppliers_referenced


def test_why_question_lists_the_driving_categories(assessment, supplier_risk_config):
    answer = answer_question(
        "Why is this supplier high risk?",
        assessment,
        supplier_risk_config,
        supplier_id="0000300002",
    )

    assert answer.intent is CopilotIntent.WHY_RISK
    drivers = assessment.by_id("0000300002").score.top_drivers(
        supplier_risk_config.copilot.top_drivers_in_answer
    )
    for driver in drivers:
        assert driver.label in answer.answer


def test_delivery_issue_question_ranks_by_delivery_risk(assessment, supplier_risk_config):
    answer = answer_question(
        "Which suppliers have the most delivery issues?", assessment, supplier_risk_config
    )

    assert answer.intent is CopilotIntent.DELIVERY_ISSUES
    assert answer.suppliers_referenced[0] == "0000300002"


def test_contract_expiry_question_lists_only_the_expiring_contract(
    assessment, supplier_risk_config
):
    answer = answer_question(
        "Which suppliers have contracts expiring soon?", assessment, supplier_risk_config
    )

    assert answer.intent is CopilotIntent.CONTRACTS_EXPIRING
    assert answer.suppliers_referenced == ["0000300007"]


def test_alternatives_question_proposes_a_lower_risk_supplier(assessment, supplier_risk_config):
    answer = answer_question(
        "Which alternative supplier has lower risk?",
        assessment,
        supplier_risk_config,
        supplier_id="0000300002",
    )

    assert answer.intent is CopilotIntent.ALTERNATIVES
    assert answer.data_available is True
    assert "0000300003" in answer.suppliers_referenced
    target = assessment.by_id("0000300002")
    alternative = assessment.by_id("0000300003")
    assert alternative.overall_score < target.overall_score


def test_action_question_returns_the_rule_based_actions(assessment, supplier_risk_config):
    answer = answer_question(
        "What action should procurement take?",
        assessment,
        supplier_risk_config,
        supplier_id="0000300002",
    )

    assert answer.intent is CopilotIntent.RECOMMENDED_ACTION
    actions = assessment.by_id("0000300002").actions
    assert actions
    assert actions[0].action in answer.answer


# ---------------------------------------------------------------------------
# Source citation generation
# ---------------------------------------------------------------------------


def test_every_answer_cites_internal_records(assessment, supplier_risk_config):
    questions = [
        ("Show supplier Ravenna Frontier Trading BV's risk.", None),
        ("Why is this supplier high risk?", "0000300002"),
        ("Which suppliers have the most delivery issues?", None),
        ("Which suppliers have contracts expiring soon?", None),
        ("Which alternative supplier has lower risk?", "0000300002"),
        ("What action should procurement take?", "0000300002"),
    ]
    for question, supplier_id in questions:
        answer = answer_question(
            question, assessment, supplier_risk_config, supplier_id=supplier_id
        )
        assert answer.citations, f"no citations for: {question}"
        for citation in answer.citations:
            assert citation.source in {"supplier_risk_profiles", "supplier_risk_events"}
            assert citation.record_id


def test_citations_point_at_the_supplier_being_discussed(assessment, supplier_risk_config):
    answer = answer_question(
        "Show supplier Ravenna Frontier Trading BV's risk.", assessment, supplier_risk_config
    )

    profile_citations = [
        citation for citation in answer.citations if citation.source == "supplier_risk_profiles"
    ]
    assert profile_citations
    assert all(citation.record_id == "0000300002" for citation in profile_citations)


def test_why_answer_cites_the_individual_event_records(assessment, supplier_risk_config):
    """The delivery events behind a delivery-driven score must be citable."""
    answer = answer_question(
        "Why is this supplier high risk?",
        assessment,
        supplier_risk_config,
        supplier_id="0000300002",
    )

    event_citations = [
        citation for citation in answer.citations if citation.source == "supplier_risk_events"
    ]
    assert event_citations
    assert all(citation.record_id.startswith("EVT-") for citation in event_citations)


def test_citation_carries_the_field_and_value_it_backs(assessment, supplier_risk_config):
    answer = answer_question(
        "Show supplier Ravenna Frontier Trading BV's risk.", assessment, supplier_risk_config
    )

    overall = next(
        citation for citation in answer.citations if citation.field_name == "overall_score"
    )
    assert overall.value == assessment.by_id("0000300002").overall_score


# ---------------------------------------------------------------------------
# Unavailable-information responses
# ---------------------------------------------------------------------------


def test_no_loaded_data_is_reported_plainly(supplier_risk_config):
    answer = answer_question("Show supplier ABC's risk.", None, supplier_risk_config)

    assert answer.data_available is False
    assert answer.unavailable_reason == "no_assessment_loaded"
    assert answer.citations == []
    assert supplier_risk_config.copilot.no_data_message in answer.answer


def test_unknown_supplier_produces_an_unavailable_answer(assessment, supplier_risk_config):
    answer = answer_question(
        "Show supplier Northwind Traders risk.", assessment, supplier_risk_config
    )

    assert answer.data_available is False
    assert answer.unavailable_reason == "supplier_not_found"
    assert "Northwind Traders" in answer.answer
    assert answer.citations == []


def test_unsupported_question_says_what_the_copilot_can_answer(
    assessment, supplier_risk_config
):
    answer = answer_question("What is the weather in Berlin?", assessment, supplier_risk_config)

    assert answer.data_available is False
    assert answer.unavailable_reason == "unsupported_question"
    assert supplier_risk_config.copilot.unavailable_message in answer.answer
    assert answer.follow_up_suggestions


def test_empty_question_is_handled(assessment, supplier_risk_config):
    answer = answer_question("   ", assessment, supplier_risk_config)

    assert answer.data_available is False
    assert answer.unavailable_reason == "empty_question"


def test_supplier_without_a_score_reports_missing_data_not_a_number(supplier_risk_config):
    """A sparse supplier must not be given an invented risk score."""
    sparse = make_risk_profile(
        supplier_id="0000300099",
        supplier_name="Thin Data Ltd",
        **dict.fromkeys(("quality_score", "defect_rate", "quality_incident_count", "credit_score", "payment_default_count", "financial_distress_flag", "category_spend_share", "single_source_material_count", "alternative_supplier_count", "contract_status", "contract_expiration", "invoice_count", "invoice_exception_count", "disputed_invoice_count", "compliance_finding_count", "certification_status", "audit_status", "esg_score", "country", "capacity_utilization", "lead_time_variability_days", "lead_time_days")),
        regions_served=[],
    )
    result = run_risk_assessment_for([sparse])

    answer = answer_question(
        "Why is supplier Thin Data Ltd high risk?", result, supplier_risk_config
    )

    assert answer.data_available is False
    assert answer.unavailable_reason == "insufficient_data_for_score"


def test_no_contract_dates_reports_unavailable(supplier_risk_config):
    result = run_risk_assessment_for(
        [make_risk_profile(contract_expiration=None, contract_status="Active")]
    )

    answer = answer_question(
        "Which suppliers have contracts expiring soon?", result, supplier_risk_config
    )

    assert answer.data_available is False
    assert answer.unavailable_reason == "no_contract_dates"


def test_no_lower_risk_alternative_is_reported_honestly(supplier_risk_config):
    first = make_risk_profile(supplier_id="0000300002", spend_category="Components")
    second = make_risk_profile(supplier_id="0000300003", spend_category="Components")
    result = run_risk_assessment_for([first, second])

    answer = answer_question(
        "Which alternative supplier has lower risk?",
        result,
        supplier_risk_config,
        supplier_id="0000300002",
    )

    assert answer.data_available is False
    assert answer.unavailable_reason == "no_alternative_found"


def test_the_copilot_never_invents_a_supplier(assessment, supplier_risk_config):
    """Answers may only mention suppliers that are actually loaded."""
    loaded = {profile.supplier_id for profile in assessment.profiles}

    for question in (
        "Which suppliers are the highest risk?",
        "Which suppliers have the most delivery issues?",
        "What action should procurement take?",
    ):
        answer = answer_question(question, assessment, supplier_risk_config)
        assert set(answer.suppliers_referenced) <= loaded


def test_answers_are_deterministic(assessment, supplier_risk_config):
    question = "Which suppliers are the highest risk?"

    first = answer_question(question, assessment, supplier_risk_config)
    second = answer_question(question, assessment, supplier_risk_config)

    assert first.answer == second.answer
    assert [c.record_id for c in first.citations] == [c.record_id for c in second.citations]
