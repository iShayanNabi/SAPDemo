"""Unit tests for the deterministic half of the Test Case Generator.

Everything asserted here happens *before* a provider is ever contacted: the
allocation, the identifiers, the priorities and the coverage arithmetic. If any
of it started depending on a language model, these tests would be the ones to
fail.
"""

from __future__ import annotations

import json

import pytest

from app.core.exceptions import ConfigurationError
from app.modules.test_case_generator.engine import build_coverage, summarise_cases
from app.modules.test_case_generator.planning import (
    allocate,
    build_plan,
    next_identifier,
    read_signals,
)
from app.modules.test_case_generator.thresholds import (
    DEFAULT_CONFIG_PATH,
    load_test_case_config,
)
from app.schemas.common import OutputOrigin
from app.schemas.test_case_generator import (
    TEST_TYPE_ORDER,
    ExecutionResult,
    GenerateTestCasesRequest,
    ProcessContextSchema,
    TestCaseSchema,
    TestCaseSource,
    TestCaseStatus,
    TestPriority,
    TestStepSchema,
    TestType,
)

FINANCIAL_CONTEXT = ProcessContextSchema(
    sap_product="SAP S/4HANA 2023",
    sap_module="MM",
    business_process="Procure to Pay - standard purchase order",
    process_description=(
        "A requisition becomes a purchase order, the warehouse posts a goods receipt and "
        "accounts payable posts the supplier invoice before the payment run settles it."
    ),
    integrations=["Ariba", "Bank gateway", "Supplier portal"],
    user_roles=["Buyer", "Warehouse clerk", "AP clerk", "Approver"],
)

QUIET_CONTEXT = ProcessContextSchema(
    sap_product="SAP S/4HANA 2023",
    sap_module="PM",
    business_process="Raise a maintenance notification",
    process_description=(
        "A technician records a fault against a piece of equipment and a planner reviews it."
    ),
    user_roles=["Technician"],
)


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------


class TestAllocation:
    def test_an_even_count_is_shared_equally(self, test_case_config):
        allocation, uncovered = allocate(
            8, [TestType.SIT, TestType.UAT, TestType.NEGATIVE, TestType.INTEGRATION],
            test_case_config,
        )

        assert list(allocation.values()) == [2, 2, 2, 2]
        assert uncovered == []

    def test_the_remainder_follows_the_configured_weights(self, test_case_config):
        allocation, _ = allocate(
            10, [TestType.SIT, TestType.UAT, TestType.NEGATIVE, TestType.SECURITY],
            test_case_config,
        )

        assert sum(allocation.values()) == 10
        # sit (weight 5) and uat (4) outweigh security (2), so they take the two spare cases.
        assert allocation[TestType.SIT] > allocation[TestType.SECURITY]

    def test_fewer_cases_than_types_keeps_the_types_asked_for_first(self, test_case_config):
        requested = [TestType.DATA_MIGRATION, TestType.SIT, TestType.SECURITY, TestType.UAT]

        allocation, uncovered = allocate(2, requested, test_case_config)

        # data_migration carries the lightest configured weight and still survives,
        # because the caller listed it first.
        assert list(allocation) == [TestType.DATA_MIGRATION, TestType.SIT]
        assert uncovered == [TestType.SECURITY, TestType.UAT]

    def test_every_requested_type_is_accounted_for(self, test_case_config):
        requested = list(TEST_TYPE_ORDER)

        allocation, uncovered = allocate(3, requested, test_case_config)

        assert len(allocation) + len(uncovered) == len(requested)
        assert sum(allocation.values()) == 3

    def test_no_requested_type_produces_no_plan(self, test_case_config):
        assert allocate(5, [], test_case_config) == ({}, [])


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


class TestPlan:
    def test_identifiers_are_unique_typed_and_numbered_from_one(self, test_case_config):
        plan = build_plan(
            FINANCIAL_CONTEXT, [TestType.SIT, TestType.NEGATIVE], 5, test_case_config
        )

        identifiers = [slot.slot_id for slot in plan.slots]
        assert len(identifiers) == len(set(identifiers)) == 5
        assert identifiers[0] == "TC-SIT-001"
        assert any(item.startswith("TC-NEG-") for item in identifiers)
        for slot in plan.slots:
            assert test_case_config.spec(slot.test_type).id_code in slot.slot_id

    def test_the_suite_is_laid_out_in_the_requested_type_order(self, test_case_config):
        plan = build_plan(
            FINANCIAL_CONTEXT, [TestType.NEGATIVE, TestType.SIT], 4, test_case_config
        )

        assert [slot.test_type for slot in plan.slots[:2]] == [TestType.NEGATIVE] * 2
        assert [slot.sequence for slot in plan.slots] == [1, 2, 3, 4]

    def test_cases_of_one_type_rotate_through_the_configured_focus_areas(
        self, test_case_config
    ):
        plan = build_plan(QUIET_CONTEXT, [TestType.SIT], 4, test_case_config)

        focuses = [slot.focus for slot in plan.slots]
        assert len(set(focuses)) == 4, "four SIT cases must not test the same thing four times"
        assert focuses == test_case_config.spec(TestType.SIT).focus_areas[:4]

    def test_a_count_above_the_configured_maximum_is_capped_and_reported(
        self, test_case_config
    ):
        plan = build_plan(
            QUIET_CONTEXT,
            [TestType.SIT],
            test_case_config.generation.max_test_cases + 10,
            test_case_config,
        )

        assert plan.size == test_case_config.generation.max_test_cases
        assert any("maximum" in note for note in plan.notes)

    def test_uncovered_types_are_reported_not_swallowed(self, test_case_config):
        plan = build_plan(QUIET_CONTEXT, list(TEST_TYPE_ORDER), 3, test_case_config)

        assert len(plan.uncovered_types) == len(TEST_TYPE_ORDER) - 3
        assert plan.notes, "dropping a requested test type must produce a note"

    def test_the_plan_does_not_depend_on_an_ai_provider(self, test_case_config):
        first = build_plan(FINANCIAL_CONTEXT, list(TEST_TYPE_ORDER), 12, test_case_config)
        second = build_plan(FINANCIAL_CONTEXT, list(TEST_TYPE_ORDER), 12, test_case_config)

        assert [slot.slot_id for slot in first.slots] == [
            slot.slot_id for slot in second.slots
        ]
        assert [slot.priority for slot in first.slots] == [
            slot.priority for slot in second.slots
        ]


# ---------------------------------------------------------------------------
# Priority derivation
# ---------------------------------------------------------------------------


class TestPriority_:
    def test_a_quiet_process_keeps_every_base_priority(self, test_case_config):
        plan = build_plan(QUIET_CONTEXT, list(TEST_TYPE_ORDER), 8, test_case_config)

        for slot in plan.slots:
            assert slot.priority is test_case_config.spec(slot.test_type).default_priority
            assert slot.priority_reasons == ()

    def test_a_financial_process_escalates_the_types_the_rule_names(self, test_case_config):
        plan = build_plan(FINANCIAL_CONTEXT, [TestType.SIT, TestType.UAT], 4, test_case_config)

        sit = next(slot for slot in plan.slots if slot.test_type is TestType.SIT)
        uat = next(slot for slot in plan.slots if slot.test_type is TestType.UAT)

        assert sit.priority is TestPriority.CRITICAL
        assert sit.priority_reasons, "an escalation must say why it happened"
        # uat is not in escalate_keyword_types, so a financial keyword must not touch it.
        assert uat.priority is test_case_config.spec(TestType.UAT).default_priority

    def test_many_roles_escalate_only_the_access_test_types(self, test_case_config):
        context = QUIET_CONTEXT.model_copy(
            update={"user_roles": ["A", "B", "C", "D", "E", "F"]}
        )

        plan = build_plan(
            context, [TestType.AUTHORIZATION, TestType.SIT], 4, test_case_config
        )

        authorization = next(
            slot for slot in plan.slots if slot.test_type is TestType.AUTHORIZATION
        )
        sit = next(slot for slot in plan.slots if slot.test_type is TestType.SIT)
        assert authorization.priority.rank > TestPriority.MEDIUM.rank
        assert sit.priority is test_case_config.spec(TestType.SIT).default_priority

    def test_several_signals_never_escalate_further_than_the_configured_cap(
        self, test_case_config
    ):
        """Two signals firing at once must not push medium straight to critical."""
        context = FINANCIAL_CONTEXT.model_copy(
            update={"integrations": ["A", "B", "C", "D", "E"]}
        )

        plan = build_plan(context, [TestType.INTEGRATION], 1, test_case_config)

        base = test_case_config.spec(TestType.INTEGRATION).default_priority
        escalated = plan.slots[0].priority
        assert escalated.rank - base.rank <= test_case_config.priority.max_escalation_steps

    def test_signals_are_read_from_the_context_the_user_typed(self, test_case_config):
        signals = read_signals(FINANCIAL_CONTEXT, test_case_config)

        assert "invoice" in signals.keyword_hits
        assert signals.integration_count == 3
        assert signals.role_count == 4


# ---------------------------------------------------------------------------
# Identifiers after editing
# ---------------------------------------------------------------------------


class TestNextIdentifier:
    def test_the_next_identifier_continues_the_series(self, test_case_config):
        existing = ["TC-SIT-001", "TC-SIT-002", "TC-NEG-001"]

        assert next_identifier(existing, TestType.SIT, test_case_config) == "TC-SIT-003"
        assert next_identifier(existing, TestType.NEGATIVE, test_case_config) == "TC-NEG-002"

    def test_a_deleted_identifier_is_never_reissued(self, test_case_config):
        """A gap in the numbering is better than one name for two different tests."""
        existing = ["TC-SIT-001", "TC-SIT-003"]  # 002 was deleted

        assert next_identifier(existing, TestType.SIT, test_case_config) == "TC-SIT-004"

    def test_the_first_identifier_of_a_type_starts_the_series(self, test_case_config):
        assert (
            next_identifier(["TC-SIT-009"], TestType.SECURITY, test_case_config)
            == "TC-SEC-001"
        )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_the_shipped_configuration_declares_every_test_type(self, test_case_config):
        assert set(test_case_config.test_types) == {item.value for item in TEST_TYPE_ORDER}

    def test_editing_the_configuration_changes_the_outcome_with_no_code_change(
        self, tmp_path
    ):
        """The point of the JSON: retune the generator without touching Python."""
        raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        raw["test_types"]["negative"]["default_priority"] = "critical"
        raw["generation"]["id_prefix"] = "ZTC"
        path = tmp_path / "edited_rules.json"
        path.write_text(json.dumps(raw), encoding="utf-8")

        edited = load_test_case_config(path)
        plan = build_plan(QUIET_CONTEXT, [TestType.NEGATIVE], 2, edited)

        assert plan.slots[0].priority is TestPriority.CRITICAL
        assert plan.slots[0].slot_id.startswith("ZTC-NEG-")

    def test_a_missing_test_type_is_rejected_at_load_time(self, tmp_path):
        raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        raw["test_types"].pop("security")
        path = tmp_path / "broken_rules.json"
        path.write_text(json.dumps(raw), encoding="utf-8")

        with pytest.raises(ConfigurationError):
            load_test_case_config(path)

    def test_two_test_types_may_not_share_an_identifier_code(self, tmp_path):
        """Sharing a code would make TC-SIT-001 ambiguous across two types."""
        raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        raw["test_types"]["uat"]["id_code"] = raw["test_types"]["sit"]["id_code"]
        path = tmp_path / "colliding_rules.json"
        path.write_text(json.dumps(raw), encoding="utf-8")

        with pytest.raises(ConfigurationError):
            load_test_case_config(path)

    def test_a_missing_configuration_file_is_reported_clearly(self, tmp_path):
        with pytest.raises(ConfigurationError):
            load_test_case_config(tmp_path / "not_here.json")


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


class TestRequestValidation:
    def test_duplicate_test_types_are_removed_but_the_order_is_kept(self):
        request = GenerateTestCasesRequest(
            context=QUIET_CONTEXT,
            test_types=[TestType.UAT, TestType.SIT, TestType.UAT],
        )

        assert request.test_types == [TestType.UAT, TestType.SIT]

    def test_a_newline_block_is_accepted_where_a_list_is_expected(self):
        context = ProcessContextSchema.model_validate(
            {
                "sap_product": "SAP S/4HANA",
                "sap_module": "SD",
                "business_process": "Order to cash",
                "process_description": "A sales order becomes a delivery and a billing document.",
                "user_roles": "Sales clerk\n\nShipping clerk\n  ",
            }
        )

        assert context.user_roles == ["Sales clerk", "Shipping clerk"]

    def test_a_short_process_description_is_rejected(self):
        with pytest.raises(Exception):
            ProcessContextSchema(
                sap_product="SAP S/4HANA",
                sap_module="SD",
                business_process="Order to cash",
                process_description="too short",
            )


# ---------------------------------------------------------------------------
# Summary and coverage arithmetic
# ---------------------------------------------------------------------------


def _case(
    identifier: str,
    test_type: TestType,
    *,
    result: ExecutionResult = ExecutionResult.NOT_RUN,
    source: TestCaseSource = TestCaseSource.AI_GENERATED,
    approved: bool = False,
) -> TestCaseSchema:
    return TestCaseSchema(
        id=identifier,
        suite_id="suite",
        test_case_id=identifier,
        sequence=1,
        test_type=test_type,
        title="A test",
        priority=TestPriority.MEDIUM,
        steps=[TestStepSchema(step_number=1, action="Do the thing")],
        status=TestCaseStatus.DRAFT,
        execution_result=result,
        source=source,
        output_origin=OutputOrigin.MOCK_AI,
        approved_at="2026-07-01T00:00:00Z" if approved else None,
    )


class TestSummary:
    def test_counts_split_by_source_status_and_result(self):
        cases = [
            _case("a", TestType.SIT, result=ExecutionResult.PASSED, approved=True),
            _case("b", TestType.SIT, result=ExecutionResult.FAILED),
            _case("c", TestType.UAT, source=TestCaseSource.TEMPLATE),
            _case("d", TestType.UAT, source=TestCaseSource.MANUAL),
        ]

        summary = summarise_cases(cases)

        assert summary.test_case_count == 4
        assert summary.ai_drafted_count == 2
        assert summary.template_built_count == 1
        assert summary.manual_count == 1
        assert summary.approved_count == 1
        assert summary.passed_count == 1
        assert summary.failed_count == 1
        assert summary.step_count == 4

    def test_a_blocked_run_is_not_counted_as_a_failure(self):
        """A test that could not run has no verdict; calling it a failure is a lie."""
        cases = [
            _case("a", TestType.SIT, result=ExecutionResult.PASSED),
            _case("b", TestType.SIT, result=ExecutionResult.BLOCKED),
        ]

        summary = summarise_cases(cases)

        assert summary.failed_count == 0
        assert summary.executed_count == 2
        assert summary.pass_rate_pct == 100.0

    def test_no_decided_run_leaves_the_pass_rate_unstated(self):
        summary = summarise_cases([_case("a", TestType.SIT)])

        assert summary.pass_rate_pct is None

    def test_a_verdict_whose_script_has_changed_is_counted_separately(self):
        """The suite still reports the failure, and reports that it is stale."""
        stale = _case("a", TestType.SIT, result=ExecutionResult.FAILED)
        stale.execution_is_stale = True

        summary = summarise_cases([stale, _case("b", TestType.SIT)])

        assert summary.failed_count == 1
        assert summary.stale_execution_count == 1

    def test_a_case_that_never_ran_is_never_counted_as_stale(self):
        never_run = _case("a", TestType.SIT)
        never_run.execution_is_stale = True

        assert summarise_cases([never_run]).stale_execution_count == 0


class TestCoverage:
    def test_a_requested_type_with_no_case_is_reported_as_zero(self, test_case_config):
        coverage = build_coverage(
            [TestType.SIT, TestType.SECURITY],
            [_case("a", TestType.SIT)],
            {"sit": 1, "security": 1},
            test_case_config,
        )

        security = next(item for item in coverage if item.test_type is TestType.SECURITY)
        assert security.planned == 1
        assert security.generated == 0
        assert security.covered is False

    def test_a_type_added_by_hand_appears_even_though_it_was_not_requested(
        self, test_case_config
    ):
        coverage = build_coverage(
            [TestType.SIT],
            [_case("a", TestType.SIT), _case("b", TestType.SECURITY,
                                             source=TestCaseSource.MANUAL)],
            {"sit": 1},
            test_case_config,
        )

        security = next(item for item in coverage if item.test_type is TestType.SECURITY)
        assert security.generated == 1
        assert security.manual == 1
        assert security.planned == 0
