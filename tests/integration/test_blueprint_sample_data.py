"""Integration tests for the bundled Blueprint Generator demo projects.

These read the scenario manifest and assert that every documented condition is
actually produced, and that the recorded baseline still matches what the engine
does today. Between them they answer the question the manifest exists for: *is
what the documentation claims about this module still true?*

The baseline is deliberately deterministic-only. The wording of a section may
change when the provider, the key or the model changes; the section list, the
order, the identifiers, the statuses, the missing inputs and the derived items
may not.
"""

from __future__ import annotations

import pytest

from app.modules.blueprint_generator.engine import generate_blueprint, summarise_sections
from app.schemas.blueprint import (
    SECTION_ORDER,
    BlueprintProjectSchema,
    BlueprintSectionSchema,
    ItemSource,
    SectionKey,
)

BASE = "/api/v1/blueprints"


def _project(projects: dict, name: str) -> dict:
    for entry in projects["projects"]:
        if entry["name"] == name:
            return entry
    raise AssertionError(f"demo project '{name}' is missing from the sample file")


def _run(entry: dict, config) -> tuple[list[BlueprintSectionSchema], object]:
    """Reproduce a demo project the way the baseline recorded it."""
    project = BlueprintProjectSchema.model_validate(entry["project"])
    sections = [SectionKey(name) for name in entry.get("suggested_sections", [])]
    result = generate_blueprint(project, sections, config, use_ai=False)

    schemas = [
        BlueprintSectionSchema(
            id=built.slot.section_key,
            blueprint_id=entry["name"],
            section_id=built.slot.section_id,
            section_key=built.slot.section_key,
            position=built.slot.position,
            title=built.slot.title,
            is_custom=built.slot.is_custom,
            content_kind=built.slot.content_kind,
            description=built.slot.description,
            narrative=built.narrative,
            items=built.items,
            status=built.status,
            source=built.source,
            output_origin=built.output_origin,
            missing_inputs=list(built.slot.missing_inputs),
            validation_notes=list(built.validation_notes),
            content_revision=1,
            depends_on=list(built.slot.depends_on),
        )
        for built in result.sections
    ]
    return schemas, result


# ---------------------------------------------------------------------------
# The sample file itself
# ---------------------------------------------------------------------------


class TestSampleProjects:
    def test_every_demo_project_is_a_valid_project_request(self, blueprint_projects):
        for entry in blueprint_projects["projects"]:
            BlueprintProjectSchema.model_validate(entry["project"])

    def test_the_sample_file_states_that_everything_in_it_is_fiction(
        self, blueprint_projects
    ):
        assert "fictional" in blueprint_projects["disclaimer"].lower()

    def test_the_manifest_documents_every_demo_project(
        self, blueprint_projects, blueprint_manifest
    ):
        documented = {entry["name"] for entry in blueprint_manifest["projects"]}
        shipped = {entry["name"] for entry in blueprint_projects["projects"]}

        assert documented == shipped


# ---------------------------------------------------------------------------
# The documented scenarios
# ---------------------------------------------------------------------------


class TestDocumentedScenarios:
    def test_bp_s001_a_complete_request_leaves_nothing_waiting_for_input(
        self, blueprint_projects, blueprint_manifest, blueprint_config
    ):
        scenario = next(
            item for item in blueprint_manifest["scenarios"] if item["id"] == "BP-S001"
        )
        sections, _ = _run(_project(blueprint_projects, scenario["project"]), blueprint_config)
        summary = summarise_sections(sections, blueprint_config)

        assert len(sections) == scenario["expectation"]["section_count"]
        assert summary.needs_input_count == 0
        assert summary.completeness_pct == scenario["expectation"]["completeness_pct"]

    def test_bp_s002_the_organisational_structure_is_exactly_what_was_named(
        self, blueprint_projects, blueprint_manifest, blueprint_config
    ):
        scenario = next(
            item for item in blueprint_manifest["scenarios"] if item["id"] == "BP-S002"
        )
        entry = _project(blueprint_projects, scenario["project"])
        sections, _ = _run(entry, blueprint_config)

        org = next(
            section
            for section in sections
            if section.section_key == scenario["expectation"]["section_key"]
        )
        derived = [item for item in org.items if item.source is ItemSource.DERIVED]

        assert len(derived) == scenario["expectation"]["derived_item_count"]
        # Every row traces back to a value the project request actually holds.
        supplied = set()
        for field in (
            "countries",
            "company_codes",
            "plants",
            "purchasing_organizations",
            "locations",
        ):
            supplied.update(entry["project"][field])
        assert {item.title for item in derived} <= supplied
        assert len(org.items) == len(derived), "no template row may creep in here"

    def test_bp_s003_the_gapped_request_reports_what_it_is_waiting_for(
        self, blueprint_projects, blueprint_manifest, blueprint_config
    ):
        scenario = next(
            item for item in blueprint_manifest["scenarios"] if item["id"] == "BP-S003"
        )
        sections, result = _run(
            _project(blueprint_projects, scenario["project"]), blueprint_config
        )

        waiting = [
            section.section_key for section in sections if section.status.value == "needs_input"
        ]
        assert waiting == scenario["expectation"]["needs_input_sections"]
        assert result.plan.missing_inputs == scenario["expectation"]["missing_inputs"]

    def test_bp_s004_a_gapped_section_invents_absolutely_nothing(
        self, blueprint_projects, blueprint_manifest, blueprint_config
    ):
        """The failure this scenario guards against looks exactly like success."""
        scenario = next(
            item for item in blueprint_manifest["scenarios"] if item["id"] == "BP-S004"
        )
        sections, _ = _run(
            _project(blueprint_projects, scenario["project"]), blueprint_config
        )
        summary = summarise_sections(sections, blueprint_config)

        waiting = [section for section in sections if section.status.value == "needs_input"]
        assert waiting, "the gapped project must leave some section waiting"
        for section in waiting:
            assert section.items == []
            assert section.missing_inputs
            assert "waiting for project input" in section.narrative
        assert summary.completeness_pct == scenario["expectation"]["completeness_pct"]

    def test_bp_s005_a_subset_is_returned_in_canonical_order(
        self, blueprint_projects, blueprint_manifest, blueprint_config
    ):
        scenario = next(
            item for item in blueprint_manifest["scenarios"] if item["id"] == "BP-S005"
        )
        entry = _project(blueprint_projects, scenario["project"])
        sections, result = _run(entry, blueprint_config)

        assert [section.section_key for section in sections] == scenario["expectation"][
            "section_order"
        ]
        assert (
            len(result.plan.excluded_sections)
            == scenario["expectation"]["excluded_section_count"]
        )
        # The request listed them in a different order on purpose.
        assert entry["suggested_sections"] != scenario["expectation"]["section_order"]

    def test_bp_s006_injection_bait_is_reported_and_never_obeyed(
        self, blueprint_projects, blueprint_manifest, blueprint_config
    ):
        scenario = next(
            item for item in blueprint_manifest["scenarios"] if item["id"] == "BP-S006"
        )
        sections, result = _run(
            _project(blueprint_projects, scenario["project"]), blueprint_config
        )

        assert result.injection_detected is scenario["expectation"]["injection_detected"]
        assert result.injection_markers == scenario["expectation"]["injection_markers"]
        assert any("was never acted on" in note for note in result.notes)
        for section in sections:
            lowered = section.narrative.lower()
            assert "validated in a live sap production system" not in lowered
            assert "approved by sap" not in lowered


# ---------------------------------------------------------------------------
# The recorded baseline
# ---------------------------------------------------------------------------


class TestBaseline:
    @pytest.mark.parametrize(
        "name", ["p2p_wholesale", "finance_gaps", "retail_subset", "hostile_rollout"]
    )
    def test_the_deterministic_output_still_matches_the_baseline(
        self, name, blueprint_projects, blueprint_baseline, blueprint_config
    ):
        recorded = blueprint_baseline["projects"][name]
        sections, result = _run(_project(blueprint_projects, name), blueprint_config)

        assert len(sections) == recorded["section_count"]
        assert [section.section_key for section in sections] == recorded["section_order"]
        assert [item.value for item in result.plan.excluded_sections] == recorded[
            "excluded_sections"
        ]
        assert result.plan.missing_inputs == recorded["missing_inputs"]

        for section, expected in zip(sections, recorded["sections"]):
            assert section.section_id == expected["section_id"]
            assert section.position == expected["position"]
            assert section.status.value == expected["status"]
            assert section.missing_inputs == expected["missing_inputs"]
            assert len(section.items) == expected["item_count"]
            derived = [
                {"item_id": item.item_id, "title": item.title, "category": item.category}
                for item in section.items
                if item.source is ItemSource.DERIVED
            ]
            assert derived == expected["derived_items"]

    def test_the_readiness_figures_still_match_the_baseline(
        self, blueprint_projects, blueprint_baseline, blueprint_config
    ):
        for name, recorded in blueprint_baseline["projects"].items():
            sections, _ = _run(_project(blueprint_projects, name), blueprint_config)
            summary = summarise_sections(sections, blueprint_config)

            assert summary.completeness_pct == recorded["summary"]["completeness_pct"], name
            assert summary.item_count == recorded["summary"]["item_count"], name
            assert summary.needs_input_count == recorded["summary"]["needs_input_count"], name

    def test_the_baseline_was_recorded_against_the_current_configuration(
        self, blueprint_baseline, blueprint_config
    ):
        assert blueprint_baseline["config_version"] == blueprint_config.config_version


# ---------------------------------------------------------------------------
# The demo projects through the real API
# ---------------------------------------------------------------------------


class TestSampleThroughTheApi:
    def test_the_sample_endpoints_describe_and_serve_the_demo_projects(
        self, api_client, blueprint_projects
    ):
        info = api_client.get(f"{BASE}/sample/info").json()["data"]

        assert info["available"] is True
        assert info["project_count"] == len(blueprint_projects["projects"])

        name = info["projects"][0]["name"]
        loaded = api_client.get(f"{BASE}/sample", params={"name": name}).json()["data"]
        assert loaded["name"] == name
        assert "project" in loaded

    def test_an_unknown_demo_project_returns_404(self, api_client):
        response = api_client.get(f"{BASE}/sample", params={"name": "not_a_project"})

        assert response.status_code == 404

    @pytest.mark.parametrize("name", ["p2p_wholesale", "finance_gaps", "hostile_rollout"])
    def test_every_demo_project_generates_through_the_api(
        self, api_client, blueprint_projects, blueprint_baseline, name
    ):
        entry = _project(blueprint_projects, name)
        response = api_client.post(
            f"{BASE}/generate",
            json={
                "project": entry["project"],
                "sections": entry.get("suggested_sections", []),
                "blueprint_name": entry["title"][:200],
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        recorded = blueprint_baseline["projects"][name]

        assert [section["section_key"] for section in data["sections"]] == recorded[
            "section_order"
        ]
        assert data["injection_detected"] is recorded["injection_detected"]
        assert data["summary"]["needs_input_count"] == recorded["summary"][
            "needs_input_count"
        ]
        # The prose may differ from the baseline - the skeleton may not.
        assert data["ai"]["used"] is True

    def test_the_demo_project_exports_carry_the_review_warning(
        self, api_client, blueprint_projects
    ):
        entry = _project(blueprint_projects, "p2p_wholesale")
        blueprint_id = api_client.post(
            f"{BASE}/generate", json={"project": entry["project"]}
        ).json()["data"]["blueprint_id"]

        for file_format in ("markdown", "json", "pdf"):
            content = api_client.get(
                f"{BASE}/{blueprint_id}/export", params={"format": file_format}
            ).content
            assert content
            if file_format != "pdf":
                assert b"qualified SAP professionals" in content

    def test_every_canonical_section_appears_in_a_full_demo_blueprint(
        self, api_client, blueprint_projects
    ):
        entry = _project(blueprint_projects, "p2p_wholesale")
        data = api_client.post(
            f"{BASE}/generate", json={"project": entry["project"]}
        ).json()["data"]

        assert {section["section_key"] for section in data["sections"]} == {
            item.value for item in SECTION_ORDER
        }
