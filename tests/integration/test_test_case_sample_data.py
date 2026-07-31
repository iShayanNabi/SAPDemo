"""Integration tests for the bundled Test Case Generator demo processes.

Every documented scenario in ``data/sample/test_case_scenario_manifest.json`` is
asserted here, and the recorded baseline in
``data/sample/expected_test_case_baseline.json`` is re-derived from the shipped
process definitions.

The baseline covers the **deterministic** half of the module only - identifiers,
type allocation, priorities, focus areas, owners and step counts. Those are what
must not move when a provider, an API key or a model changes; the drafted prose
is the one part that is allowed to differ, so it is deliberately not baselined.
"""

from __future__ import annotations

import pytest

from app.modules.test_case_generator.engine import ENGINE_VERSION, generate_suite
from app.schemas.test_case_generator import ProcessContextSchema, TestType


def _context(processes: dict, name: str) -> ProcessContextSchema:
    definition = next(
        item for item in processes["processes"] if item["name"] == name
    )
    return ProcessContextSchema.model_validate(definition["context"])


def _definition(processes: dict, name: str) -> dict:
    return next(item for item in processes["processes"] if item["name"] == name)


def _run(processes: dict, name: str, config):
    definition = _definition(processes, name)
    return generate_suite(
        ProcessContextSchema.model_validate(definition["context"]),
        [TestType(item) for item in definition["suggested_test_types"]],
        int(definition["suggested_test_case_count"]),
        config,
        use_ai=False,
    )


# ---------------------------------------------------------------------------
# The recorded baseline
# ---------------------------------------------------------------------------


class TestBaseline:
    def test_the_baseline_matches_the_shipped_configuration(
        self, test_case_baseline, test_case_config
    ):
        assert test_case_baseline["config_version"] == test_case_config.config_version
        assert test_case_baseline["engine_version"] == ENGINE_VERSION

    def test_every_demo_process_reproduces_its_baseline_exactly(
        self, test_case_processes, test_case_baseline, test_case_config
    ):
        for name, expected in test_case_baseline["processes"].items():
            result = _run(test_case_processes, name, test_case_config)

            observed = [
                {
                    "test_case_id": case.slot.slot_id,
                    "test_type": case.slot.test_type.value,
                    "priority": case.slot.priority.value,
                    "focus": case.slot.focus,
                    "owner": case.slot.owner,
                    "step_count": len(case.steps),
                    "source": case.source.value,
                }
                for case in result.cases
            ]
            assert observed == expected["test_cases"], name
            assert {
                test_type.value: count
                for test_type, count in result.plan.allocation.items()
            } == expected["allocation"], name
            assert [
                item.value for item in result.plan.uncovered_types
            ] == expected["uncovered_test_types"], name

    def test_generation_is_repeatable(self, test_case_processes, test_case_config):
        """Same input, same suite - the property the whole design exists to keep."""
        first = _run(test_case_processes, "p2p_standard_po", test_case_config)
        second = _run(test_case_processes, "p2p_standard_po", test_case_config)

        assert [case.slot.slot_id for case in first.cases] == [
            case.slot.slot_id for case in second.cases
        ]
        assert [case.title for case in first.cases] == [
            case.title for case in second.cases
        ]


# ---------------------------------------------------------------------------
# The documented scenarios
# ---------------------------------------------------------------------------


class TestDocumentedScenarios:
    def test_the_manifest_documents_every_demo_process(
        self, test_case_manifest, test_case_processes
    ):
        documented = {item["name"] for item in test_case_manifest["processes"]}
        shipped = {item["name"] for item in test_case_processes["processes"]}

        assert documented == shipped
        assert len(test_case_manifest["scenarios"]) >= 5

    def test_s001_every_escalation_signal_fires_for_the_financial_process(
        self, test_case_processes, test_case_config
    ):
        result = _run(test_case_processes, "p2p_standard_po", test_case_config)
        signals = result.plan.signals

        assert signals.keyword_hits
        assert signals.integration_count >= test_case_config.priority.integration_escalation_threshold
        assert signals.role_count >= test_case_config.priority.role_escalation_threshold

    def test_s002_system_integration_tests_are_escalated(
        self, test_case_processes, test_case_config
    ):
        result = _run(test_case_processes, "p2p_standard_po", test_case_config)

        sit_cases = [case for case in result.cases if case.slot.test_type is TestType.SIT]
        base = test_case_config.spec(TestType.SIT).default_priority
        assert sit_cases
        for case in sit_cases:
            assert case.slot.priority.rank > base.rank
            assert case.slot.priority_reasons

    def test_s003_a_quiet_process_escalates_nothing(
        self, test_case_processes, test_case_config
    ):
        result = _run(test_case_processes, "pm_notification", test_case_config)

        assert result.plan.signals.keyword_hits == ()
        for case in result.cases:
            base = test_case_config.spec(case.slot.test_type).default_priority
            assert case.slot.priority is base
            assert case.slot.priority_reasons == ()

    def test_s004_a_shortfall_of_cases_is_reported_and_keeps_the_first_choice(
        self, test_case_processes, test_case_config
    ):
        result = _run(test_case_processes, "migration_vendor", test_case_config)

        assert [item.value for item in result.plan.uncovered_types] == [
            "security",
            "regression",
        ]
        assert result.notes, "an uncovered test type must produce a note"
        assert any(
            case.slot.test_type is TestType.DATA_MIGRATION for case in result.cases
        ), "the type the process lists first must survive the shortfall"

    def test_s005_many_roles_escalate_only_the_access_test_types(
        self, test_case_processes, test_case_config
    ):
        result = _run(test_case_processes, "fiori_approval", test_case_config)

        for case in result.cases:
            base = test_case_config.spec(case.slot.test_type).default_priority
            if case.slot.test_type in (TestType.AUTHORIZATION, TestType.SECURITY):
                assert case.slot.priority.rank > base.rank, case.slot.slot_id
            else:
                assert case.slot.priority is base, case.slot.slot_id

    def test_s006_every_case_is_complete_with_no_ai_at_all(
        self, test_case_processes, test_case_config
    ):
        minimum = test_case_config.generation.min_steps_per_case

        for definition in test_case_processes["processes"]:
            result = _run(test_case_processes, definition["name"], test_case_config)

            assert result.cases
            for case in result.cases:
                assert case.source.value == "template"
                assert len(case.steps) >= minimum
                assert case.title and case.objective and case.expected_result
                assert case.preconditions and case.test_data

    def test_s007_identifiers_are_unique_and_carry_their_type_code(
        self, test_case_processes, test_case_config
    ):
        for definition in test_case_processes["processes"]:
            result = _run(test_case_processes, definition["name"], test_case_config)

            identifiers = [case.slot.slot_id for case in result.cases]
            assert len(identifiers) == len(set(identifiers)), definition["name"]
            for case in result.cases:
                code = test_case_config.spec(case.slot.test_type).id_code.upper()
                assert f"-{code}-" in case.slot.slot_id


# ---------------------------------------------------------------------------
# The demo definitions themselves
# ---------------------------------------------------------------------------


class TestDemoDefinitions:
    def test_every_demo_process_validates_as_a_process_context(self, test_case_processes):
        for definition in test_case_processes["processes"]:
            context = ProcessContextSchema.model_validate(definition["context"])
            assert context.business_process
            assert len(context.process_description) > 50

    def test_the_demo_processes_carry_no_instruction_like_text(self, test_case_processes):
        """The demo data must not itself be an injection fixture."""
        from app.modules.test_case_generator.engine import detect_injection

        for definition in test_case_processes["processes"]:
            context = ProcessContextSchema.model_validate(definition["context"])
            assert detect_injection(context) == [], definition["name"]

    def test_the_demo_processes_are_declared_as_fiction(self, test_case_processes):
        assert "fiction" in test_case_processes["description"].lower()

    @pytest.mark.parametrize("name", ["p2p_standard_po", "migration_vendor"])
    def test_the_suggested_types_are_all_supported(
        self, test_case_processes, test_case_config, name
    ):
        definition = _definition(test_case_processes, name)

        for item in definition["suggested_test_types"]:
            assert test_case_config.spec(TestType(item))
