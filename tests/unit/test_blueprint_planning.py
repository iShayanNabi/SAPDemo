"""Unit tests for the deterministic blueprint skeleton.

Everything asserted here happens before any provider is contacted: which
sections exist, in what order, which project inputs they need, which items they
hold because the request named them, and what happens when a required input is
missing.
"""

from __future__ import annotations

import json

import pytest

from app.core.exceptions import ConfigurationError
from app.modules.blueprint_generator.planning import (
    build_plan,
    derived_items_for,
    field_label,
    missing_inputs_for,
    next_custom_number,
)
from app.modules.blueprint_generator.thresholds import (
    DEFAULT_CONFIG_PATH,
    BlueprintConfig,
    load_blueprint_config,
)
from app.schemas.blueprint import (
    SECTION_ORDER,
    BlueprintProjectSchema,
    ContentKind,
    SectionKey,
)

FULL_PROJECT = {
    "company": "Nordwind Logistics GmbH",
    "industry": "Wholesale distribution",
    "sap_product": "SAP S/4HANA 2023",
    "modules": ["MM", "FI"],
    "business_objectives": ["Cut cycle time"],
    "current_process": "Orders are keyed in by hand from emailed PDFs.",
    "desired_process": "Orders arrive electronically and post straight into SAP.",
    "countries": ["Germany", "Poland"],
    "locations": ["Hamburg DC"],
    "company_codes": ["1000", "2000"],
    "plants": ["1010"],
    "purchasing_organizations": ["1000"],
    "systems_involved": ["SAP S/4HANA", "Legacy WMS"],
    "integrations": ["EDI order intake", "Bank payment file"],
    "data_sources": ["Legacy ERP"],
    "user_groups": ["Buyer", "Warehouse clerk"],
    "timeline": "Go-live in October",
    "constraints": ["No WMS change this year"],
    "assumptions": ["Master data is cleansed first"],
}


@pytest.fixture(scope="module")
def project() -> BlueprintProjectSchema:
    return BlueprintProjectSchema.model_validate(FULL_PROJECT)


# ---------------------------------------------------------------------------
# The section list
# ---------------------------------------------------------------------------


class TestSectionSkeleton:
    def test_the_full_plan_holds_every_canonical_section_in_order(
        self, project, blueprint_config
    ):
        plan = build_plan(project, [], blueprint_config)

        assert [slot.section_key for slot in plan.slots] == [
            item.value for item in SECTION_ORDER
        ]
        assert len(plan.slots) == 30
        assert plan.excluded_sections == []

    def test_positions_are_gap_free_and_start_at_one(self, project, blueprint_config):
        plan = build_plan(project, [], blueprint_config)

        assert [slot.position for slot in plan.slots] == list(range(1, len(plan.slots) + 1))

    def test_section_identifiers_are_unique_and_use_the_configured_template(
        self, project, blueprint_config
    ):
        plan = build_plan(project, [], blueprint_config)
        identifiers = [slot.section_id for slot in plan.slots]

        assert len(set(identifiers)) == len(identifiers)
        assert all(identifier.startswith("BP-") for identifier in identifiers)

    def test_a_subset_request_is_returned_in_canonical_order_not_request_order(
        self, project, blueprint_config
    ):
        """The order a caller happens to type is not the order a document reads in."""
        plan = build_plan(
            project,
            [SectionKey.RISKS, SectionKey.SCOPE, SectionKey.EXECUTIVE_SUMMARY],
            blueprint_config,
        )

        assert [slot.section_key for slot in plan.slots] == [
            "executive_summary",
            "scope",
            "risks",
        ]

    def test_excluded_sections_are_reported_rather_than_silently_absent(
        self, project, blueprint_config
    ):
        plan = build_plan(project, [SectionKey.SCOPE], blueprint_config)

        assert len(plan.excluded_sections) == len(SECTION_ORDER) - 1
        assert SectionKey.RISKS in plan.excluded_sections
        assert any("were not generated" in note for note in plan.notes)


# ---------------------------------------------------------------------------
# Derived items - the factual content
# ---------------------------------------------------------------------------


class TestDerivedItems:
    def test_the_organisational_structure_holds_exactly_what_the_request_named(
        self, project, blueprint_config
    ):
        spec = blueprint_config.spec(SectionKey.ORGANIZATIONAL_STRUCTURE)
        items = derived_items_for(project, spec, blueprint_config)

        titles = [item.title for item in items]
        assert titles == [
            "Germany",
            "Poland",
            "1000",
            "2000",
            "1010",
            "1000",
            "Hamburg DC",
        ]
        assert [item.category for item in items[:2]] == ["Country", "Country"]

    def test_each_derived_item_records_the_project_field_it_came_from(
        self, project, blueprint_config
    ):
        spec = blueprint_config.spec(SectionKey.ORGANIZATIONAL_STRUCTURE)
        items = derived_items_for(project, spec, blueprint_config)

        assert {item.source_field for item in items} == {
            "countries",
            "company_codes",
            "plants",
            "purchasing_organizations",
            "locations",
        }

    def test_the_same_value_under_two_fields_stays_two_items(
        self, project, blueprint_config
    ):
        """Company code 1000 and purchasing organisation 1000 are different things.

        Deduplication is per field, not across the section: collapsing them
        would delete a purchasing organisation the project actually has.
        """
        spec = blueprint_config.spec(SectionKey.ORGANIZATIONAL_STRUCTURE)
        items = derived_items_for(project, spec, blueprint_config)

        matching = [item for item in items if item.title == "1000"]
        assert len(matching) == 2
        assert {item.category for item in matching} == {
            "Company code",
            "Purchasing organization",
        }

    def test_a_repeated_value_in_one_field_is_recorded_once(self, blueprint_config):
        project = BlueprintProjectSchema.model_validate(
            {**FULL_PROJECT, "integrations": ["EDI order intake", "edi order intake"]}
        )
        spec = blueprint_config.spec(SectionKey.INTEGRATIONS)

        assert len(derived_items_for(project, spec, blueprint_config)) == 1

    def test_a_derived_detail_renders_the_project_values(self, project, blueprint_config):
        spec = blueprint_config.spec(SectionKey.INTEGRATIONS)
        items = derived_items_for(project, spec, blueprint_config)

        assert "EDI order intake" in items[0].detail
        assert "{" not in items[0].detail


# ---------------------------------------------------------------------------
# Missing inputs - the module's central rule
# ---------------------------------------------------------------------------


class TestMissingInputs:
    def test_a_section_whose_required_field_is_empty_is_reported(self, blueprint_config):
        project = BlueprintProjectSchema.model_validate({**FULL_PROJECT, "integrations": []})
        spec = blueprint_config.spec(SectionKey.INTEGRATIONS)

        assert missing_inputs_for(project, spec) == ("integrations",)

    def test_a_section_waiting_for_input_derives_no_items_at_all(self, blueprint_config):
        """The whole point: no input, no invented interface register."""
        project = BlueprintProjectSchema.model_validate({**FULL_PROJECT, "integrations": []})
        plan = build_plan(project, [], blueprint_config)

        integrations = next(
            slot for slot in plan.slots if slot.section_key == "integrations"
        )
        assert integrations.needs_input is True
        assert integrations.derived_items == ()

    def test_one_empty_field_can_block_several_sections(self, blueprint_config):
        project = BlueprintProjectSchema.model_validate({**FULL_PROJECT, "integrations": []})
        plan = build_plan(project, [], blueprint_config)

        blocked = {slot.section_key for slot in plan.slots if slot.needs_input}
        assert blocked == {"integrations", "interfaces_apis"}

    def test_the_plan_names_every_field_that_would_unlock_a_section(
        self, blueprint_config
    ):
        project = BlueprintProjectSchema.model_validate(
            {**FULL_PROJECT, "integrations": [], "user_groups": [], "data_sources": []}
        )
        plan = build_plan(project, [], blueprint_config)

        assert set(plan.missing_inputs) == {"integrations", "user_groups", "data_sources"}
        assert any("left unwritten rather than invented" in note for note in plan.notes)

    def test_a_section_that_only_derives_from_a_field_is_not_blocked_by_it(
        self, blueprint_config
    ):
        """Training derives from the user groups but does not require them.

        A project with no user groups still needs a training section; it just
        gets one with no audience rows in it.
        """
        project = BlueprintProjectSchema.model_validate({**FULL_PROJECT, "user_groups": []})
        plan = build_plan(project, [], blueprint_config)

        training = next(slot for slot in plan.slots if slot.section_key == "training")
        assert training.needs_input is False
        assert training.derived_items == ()

    def test_field_labels_are_readable(self):
        assert field_label("purchasing_organizations") == "purchasing organizations"


# ---------------------------------------------------------------------------
# Custom section numbering
# ---------------------------------------------------------------------------


class TestCustomSectionNumbering:
    def test_the_first_custom_section_takes_the_configured_start_number(
        self, blueprint_config
    ):
        assert next_custom_number([], blueprint_config) == 1

    def test_a_deleted_identifier_is_never_reissued(self, blueprint_config):
        """A review comment on BP-CUS-002 has to keep meaning what it meant."""
        assert next_custom_number(["BP-CUS-001", "BP-CUS-002"], blueprint_config) == 3
        # BP-CUS-002 has been deleted; the next section must not claim its name.
        assert next_custom_number(["BP-CUS-001", "BP-CUS-003"], blueprint_config) == 4

    def test_the_high_water_mark_survives_deleting_every_custom_section(
        self, blueprint_config
    ):
        """With nothing left to read, only the issued counter prevents a reissue."""
        assert next_custom_number([], blueprint_config, issued=3) == 4


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_every_canonical_section_is_configured(self, blueprint_config):
        assert set(blueprint_config.sections) == {item.value for item in SECTION_ORDER}

    def test_section_codes_and_item_codes_are_unique(self, blueprint_config):
        codes = [spec.section_code for spec in blueprint_config.sections.values()]
        item_codes = [spec.item_code for spec in blueprint_config.sections.values()]

        assert len(set(codes)) == len(codes)
        assert len(set(item_codes)) == len(item_codes)

    def test_every_dependency_names_a_real_section(self, blueprint_config):
        for name, spec in blueprint_config.sections.items():
            for dependency in spec.depends_on:
                assert dependency in blueprint_config.sections, f"{name} -> {dependency}"
                assert dependency != name

    def test_the_factual_sections_do_not_accept_drafted_items(self, blueprint_config):
        """A model may describe the organisational structure; it may not extend it."""
        for name in (
            "organizational_structure",
            "sap_products_modules",
            "integrations",
            "interfaces_apis",
            "security_roles",
        ):
            spec = blueprint_config.spec(name)
            assert spec.allow_ai_items is False
            assert spec.derives_from, f"{name} declares no derivation"

    def test_dependents_of_finds_the_sections_that_describe_one(self, blueprint_config):
        dependents = blueprint_config.dependents_of("scope")

        assert "executive_summary" in dependents
        assert "out_of_scope" in dependents

    def test_editing_the_configuration_changes_the_document_with_no_code_change(
        self, tmp_path
    ):
        """The project rule: thresholds live in JSON, never in code."""
        source = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        source["generation"]["id_prefix"] = "SAP"
        source["sections"]["scope"]["title"] = "Delivered scope"
        source["sections"]["scope"]["required_inputs"] = []
        path = tmp_path / "edited_rules.json"
        path.write_text(json.dumps(source), encoding="utf-8")

        edited = load_blueprint_config(path)
        project = BlueprintProjectSchema.model_validate({**FULL_PROJECT, "modules": []})
        plan = build_plan(project, [SectionKey.SCOPE], edited)

        assert plan.slots[0].title == "Delivered scope"
        assert plan.slots[0].section_id.startswith("SAP-")
        assert plan.slots[0].needs_input is False

    def test_an_unknown_project_field_in_the_configuration_is_rejected(self, tmp_path):
        source = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        source["sections"]["scope"]["required_inputs"] = ["moduls"]
        path = tmp_path / "typo_rules.json"
        path.write_text(json.dumps(source), encoding="utf-8")

        with pytest.raises(ConfigurationError):
            load_blueprint_config(path)

    def test_a_missing_section_in_the_configuration_is_rejected(self, tmp_path):
        source = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        source["sections"].pop("risks")
        path = tmp_path / "short_rules.json"
        path.write_text(json.dumps(source), encoding="utf-8")

        with pytest.raises(ConfigurationError):
            load_blueprint_config(path)

    def test_the_configuration_is_a_validated_object(self, blueprint_config):
        assert isinstance(blueprint_config, BlueprintConfig)
        assert blueprint_config.spec(SectionKey.EXECUTIVE_SUMMARY).content_kind is (
            ContentKind.NARRATIVE
        )
