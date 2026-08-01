"""API tests for the SAP Blueprint Generator endpoints.

These drive the real FastAPI app through ``TestClient``, so they cover the
response envelope, the status codes, the validation and the six routes the
module is specified around, plus the editing, approval, custom-section and
versioning endpoints an editable document needs.
"""

from __future__ import annotations

import io
import json

import pytest

BASE = "/api/v1/blueprints"

PROJECT = {
    "company": "Nordwind Logistics GmbH",
    "industry": "Wholesale distribution",
    "sap_product": "SAP S/4HANA 2023, private cloud edition",
    "modules": ["MM", "FI", "SD"],
    "business_objectives": [
        "Cut the time from requisition to purchase order",
        "Remove the manual three-way match",
    ],
    "current_process": (
        "Requisitions are raised on paper, keyed into a legacy system and emailed to the "
        "supplier as a PDF."
    ),
    "desired_process": (
        "Requisitions are raised in SAP, released by the value based release strategy and "
        "sent to the supplier electronically."
    ),
    "countries": ["Germany", "Poland"],
    "locations": ["Hamburg distribution centre"],
    "company_codes": ["1000", "2000"],
    "plants": ["1010", "2010"],
    "purchasing_organizations": ["1000"],
    "systems_involved": ["SAP S/4HANA", "Legacy warehouse system"],
    "integrations": ["Purchase order transmission", "Payment file to the bank"],
    "data_sources": ["Legacy purchasing system"],
    "user_groups": ["Requisitioner", "Purchasing buyer", "Accounts payable clerk"],
    "timeline": "Design Q1, build Q2, go-live Q3",
    "constraints": ["The warehouse system cannot change this year"],
    "assumptions": ["The group vendor register stays the master for supplier data"],
}


def _generate(client, **overrides) -> dict:
    body = {"project": PROJECT, **overrides}
    response = client.post(f"{BASE}/generate", json=body)
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["success"] is True
    return envelope["data"]


@pytest.fixture(scope="module")
def blueprint(api_client) -> dict:
    """One generated blueprint shared by the read-only tests."""
    return _generate(api_client)


@pytest.fixture
def scratch(api_client) -> dict:
    """A throwaway blueprint for the tests that modify one."""
    return _generate(api_client, blueprint_name="Scratch blueprint")


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_a_complete_blueprint_is_generated(self, blueprint):
        assert len(blueprint["sections"]) == 30
        assert blueprint["summary"]["section_count"] == 30
        assert blueprint["config_version"]
        assert blueprint["engine_version"]

    def test_the_result_is_labelled_a_proposal_requiring_review(self, blueprint):
        assert "PROPOSED" in blueprint["disclaimer"]
        assert "qualified SAP professionals" in blueprint["disclaimer"]
        assert "not connected" in blueprint["disclaimer"]

    def test_every_section_carries_every_required_field(self, blueprint):
        section = blueprint["sections"][0]

        for field in (
            "section_id", "section_key", "position", "title", "content_kind",
            "narrative", "items", "status", "source", "output_origin",
            "missing_inputs", "content_revision", "depends_on",
            "stale_dependencies", "approval_is_stale",
        ):
            assert field in section, field

    def test_sections_are_returned_in_document_order(self, blueprint):
        positions = [section["position"] for section in blueprint["sections"]]

        assert positions == sorted(positions)
        assert blueprint["sections"][0]["section_key"] == "executive_summary"
        assert blueprint["sections"][-1]["section_key"] == "open_decisions"

    def test_the_organisational_structure_is_computed_from_the_request(self, blueprint):
        org = next(
            section
            for section in blueprint["sections"]
            if section["section_key"] == "organizational_structure"
        )

        assert all(item["source"] == "derived" for item in org["items"])
        titles = [item["title"] for item in org["items"]]
        assert titles == ["Germany", "Poland", "1000", "2000", "1010", "2010", "1000",
                          "Hamburg distribution centre"]

    def test_every_item_is_labelled_with_how_it_came_to_exist(self, blueprint):
        for section in blueprint["sections"]:
            for item in section["items"]:
                assert item["source"] in {"derived", "ai_generated", "template", "manual"}
                assert item["output_origin"] in {
                    "rule_based", "ai_generated", "mock_ai", "forecast", "demo_data"
                }

    def test_a_subset_request_reports_what_was_excluded(self, api_client):
        data = _generate(api_client, sections=["risks", "scope", "executive_summary"])

        assert [section["section_key"] for section in data["sections"]] == [
            "executive_summary",
            "scope",
            "risks",
        ]
        assert len(data["excluded_sections"]) == 27
        assert any("were not generated" in note for note in data["notes"])

    def test_generation_with_ai_off_still_produces_a_complete_document(self, api_client):
        data = _generate(api_client, use_ai=False)

        assert len(data["sections"]) == 30
        assert all(section["narrative"].strip() for section in data["sections"])
        assert data["ai"]["used"] is False

    def test_the_ai_block_never_contains_a_credential(self, blueprint):
        assert set(blueprint["ai"]) == {
            "requested", "used", "provider", "model", "origin", "prompt_version",
            "input_tokens", "output_tokens", "estimated_cost_usd", "error",
        }

    def test_an_invalid_request_is_rejected_with_422(self, api_client):
        response = api_client.post(
            f"{BASE}/generate", json={"project": {**PROJECT, "company": "X"}}
        )

        assert response.status_code == 422

    def test_a_missing_process_description_is_rejected(self, api_client):
        response = api_client.post(
            f"{BASE}/generate", json={"project": {**PROJECT, "desired_process": ""}}
        )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Sections waiting for input
# ---------------------------------------------------------------------------


class TestNeedsInput:
    @pytest.fixture(scope="class")
    def gapped(self, api_client) -> dict:
        project = {**PROJECT, "integrations": [], "data_sources": [], "user_groups": []}
        response = api_client.post(
            f"{BASE}/generate", json={"project": project, "blueprint_name": "Gapped"}
        )
        assert response.status_code == 200, response.text
        return response.json()["data"]

    def test_the_sections_that_need_the_missing_fields_say_so(self, gapped):
        waiting = {
            section["section_key"]
            for section in gapped["sections"]
            if section["status"] == "needs_input"
        }

        assert waiting == {
            "integrations",
            "interfaces_apis",
            "data_migration",
            "security_roles",
        }

    def test_a_section_waiting_for_input_invents_nothing(self, gapped):
        integrations = next(
            section for section in gapped["sections"] if section["section_key"] == "integrations"
        )

        assert integrations["items"] == []
        assert integrations["missing_inputs"] == ["integrations"]
        assert "waiting for project input" in integrations["narrative"]

    def test_the_summary_names_the_fields_that_would_unlock_a_section(self, gapped):
        assert set(gapped["summary"]["missing_inputs"]) == {
            "integrations",
            "data_sources",
            "user_groups",
        }
        assert gapped["summary"]["needs_input_count"] == 4
        assert gapped["summary"]["completeness_pct"] < 100

    def test_approving_a_section_with_no_content_is_refused(self, api_client, gapped):
        response = api_client.post(
            f"{BASE}/{gapped['blueprint_id']}/sections/integrations/approve",
            json={"approved_by": "Ingrid Vogel"},
        )

        assert response.status_code == 422
        assert "waiting for project input" in response.json()["error"]["message"]

    def test_supplying_the_field_unblocks_the_section(self, api_client, gapped):
        project = {**PROJECT, "data_sources": [], "user_groups": []}
        response = api_client.put(
            f"{BASE}/{gapped['blueprint_id']}", json={"project": project}
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]

        integrations = next(
            section for section in data["sections"] if section["section_key"] == "integrations"
        )
        assert integrations["status"] != "needs_input"
        assert [item["title"] for item in integrations["items"]] == [
            "Purchase order transmission",
            "Payment file to the bank",
        ]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


class TestRead:
    def test_a_blueprint_can_be_read_back(self, api_client, blueprint):
        response = api_client.get(f"{BASE}/{blueprint['blueprint_id']}")

        assert response.status_code == 200
        assert response.json()["data"]["blueprint_id"] == blueprint["blueprint_id"]

    def test_an_unknown_blueprint_returns_404(self, api_client):
        response = api_client.get(f"{BASE}/does-not-exist")

        assert response.status_code == 404
        assert response.json()["success"] is False

    def test_a_section_can_be_fetched_by_identifier_key_or_id(self, api_client, blueprint):
        section = blueprint["sections"][2]

        for reference in (section["section_id"], section["section_key"], section["id"]):
            response = api_client.get(
                f"{BASE}/{blueprint['blueprint_id']}/sections/{reference}"
            )
            assert response.status_code == 200, reference
            assert response.json()["data"]["section_key"] == section["section_key"]

    def test_the_catalogue_describes_the_sections_and_the_project_form(self, api_client):
        response = api_client.get(f"{BASE}/catalog")
        data = response.json()["data"]

        assert len(data["sections"]) == 30
        assert len(data["project_fields"]) == 19
        assert data["export_formats"] == ["markdown", "json", "docx", "pdf"]
        assert data["methodology"]["deterministic"]
        assert data["disclaimer"]

    def test_the_blueprint_list_is_paginated(self, api_client, blueprint):
        response = api_client.get(BASE, params={"limit": 5, "offset": 0})
        data = response.json()["data"]

        assert data["limit"] == 5
        assert data["total"] >= 1
        assert all("blueprint_id" in item for item in data["blueprints"])

    def test_the_ai_status_endpoint_never_returns_a_key(self, api_client):
        response = api_client.get(f"{BASE}/ai-status")
        body = json.dumps(response.json())

        assert response.status_code == 200
        assert "api_key" not in body.lower()


# ---------------------------------------------------------------------------
# Editing, approving, regenerating
# ---------------------------------------------------------------------------


class TestEditing:
    def test_editing_the_narrative_marks_the_section_as_written_by_a_person(
        self, api_client, scratch
    ):
        response = api_client.put(
            f"{BASE}/{scratch['blueprint_id']}/sections/scope",
            json={"narrative": "The scope agreed in the workshop on 3 February."},
        )
        data = response.json()["data"]

        assert response.status_code == 200
        assert data["source"] == "manual"
        assert data["edited_by_user"] is True
        assert data["content_revision"] == 2

    def test_an_empty_update_is_rejected(self, api_client, scratch):
        response = api_client.put(
            f"{BASE}/{scratch['blueprint_id']}/sections/scope", json={}
        )

        assert response.status_code == 422

    def test_editing_the_content_clears_an_approval(self, api_client, scratch):
        blueprint_id = scratch["blueprint_id"]
        api_client.post(
            f"{BASE}/{blueprint_id}/sections/risks/approve",
            json={"approved_by": "Ingrid Vogel"},
        )

        response = api_client.put(
            f"{BASE}/{blueprint_id}/sections/risks",
            json={"narrative": "A different risk picture entirely."},
        )
        data = response.json()["data"]

        assert data["approved_by"] is None
        assert data["status"] == "draft"

    def test_editing_only_a_comment_keeps_the_approval(self, api_client, scratch):
        blueprint_id = scratch["blueprint_id"]
        api_client.post(
            f"{BASE}/{blueprint_id}/sections/training/approve",
            json={"approved_by": "Ingrid Vogel"},
        )

        response = api_client.put(
            f"{BASE}/{blueprint_id}/sections/training",
            json={"comments": "Agreed with the training lead."},
        )
        data = response.json()["data"]

        assert data["approved_by"] == "Ingrid Vogel"
        assert data["status"] == "approved"

    def test_editing_the_items_replaces_them_and_renumbers_them(
        self, api_client, scratch
    ):
        response = api_client.put(
            f"{BASE}/{scratch['blueprint_id']}/sections/risks",
            json={
                "items": [
                    {"title": "Data quality", "detail": "Profile the sources early."},
                    {"title": "Business availability", "detail": "Name the people now."},
                ]
            },
        )
        data = response.json()["data"]

        assert [item["title"] for item in data["items"]] == [
            "Data quality",
            "Business availability",
        ]
        assert [item["item_id"] for item in data["items"]] == ["BP-RSK-001", "BP-RSK-002"]
        assert all(item["source"] == "manual" for item in data["items"])

    def test_a_section_cannot_be_marked_approved_without_an_approval(
        self, api_client, scratch
    ):
        """Status and approval are one statement; a PUT cannot set half of it."""
        response = api_client.put(
            f"{BASE}/{scratch['blueprint_id']}/sections/scope",
            json={"status": "approved"},
        )

        assert response.status_code == 422
        assert "approve endpoint" in response.json()["error"]["message"]

    def test_a_section_cannot_be_marked_needs_input_by_hand(self, api_client, scratch):
        response = api_client.put(
            f"{BASE}/{scratch['blueprint_id']}/sections/scope",
            json={"status": "needs_input"},
        )

        assert response.status_code == 422

    def test_regenerating_a_section_keeps_its_place_and_clears_the_approval(
        self, api_client, scratch
    ):
        blueprint_id = scratch["blueprint_id"]
        before = next(
            section for section in scratch["sections"] if section["section_key"] == "controls"
        )
        api_client.post(
            f"{BASE}/{blueprint_id}/sections/controls/approve",
            json={"approved_by": "Ingrid Vogel"},
        )

        response = api_client.post(
            f"{BASE}/{blueprint_id}/sections/controls/regenerate",
            json={"instruction": "Say more about segregation of duties."},
        )
        data = response.json()["data"]

        assert data["section_id"] == before["section_id"]
        assert data["position"] == before["position"]
        assert data["approved_by"] is None
        assert data["regenerated_count"] == 1
        assert data["narrative"].strip()

    def test_regenerating_a_derived_section_cannot_change_its_items(
        self, api_client, scratch
    ):
        response = api_client.post(
            f"{BASE}/{scratch['blueprint_id']}/sections/organizational_structure/regenerate"
        )
        data = response.json()["data"]

        assert [item["title"] for item in data["items"]] == [
            "Germany", "Poland", "1000", "2000", "1010", "2010", "1000",
            "Hamburg distribution centre",
        ]
        assert all(item["source"] == "derived" for item in data["items"])

    def test_regenerating_with_ai_off_still_writes_the_section(self, api_client, scratch):
        response = api_client.post(
            f"{BASE}/{scratch['blueprint_id']}/sections/hypercare/regenerate",
            json={"use_ai": False},
        )
        data = response.json()["data"]

        assert data["narrative"].strip()
        assert data["output_origin"] == "rule_based"

    def test_an_approval_can_be_withdrawn(self, api_client, scratch):
        blueprint_id = scratch["blueprint_id"]
        api_client.post(
            f"{BASE}/{blueprint_id}/sections/dependencies/approve",
            json={"approved_by": "Ingrid Vogel"},
        )

        response = api_client.post(
            f"{BASE}/{blueprint_id}/sections/dependencies/approve",
            json={"approved_by": "Ingrid Vogel", "approved": False},
        )
        data = response.json()["data"]

        assert data["approved_by"] is None
        assert data["status"] == "draft"

    def test_the_blueprint_name_and_owner_can_be_edited(self, api_client, scratch):
        response = api_client.put(
            f"{BASE}/{scratch['blueprint_id']}",
            json={"name": "Nordwind P2P blueprint v2", "owner": "Ingrid Vogel"},
        )
        data = response.json()["data"]

        assert data["name"] == "Nordwind P2P blueprint v2"
        assert data["owner"] == "Ingrid Vogel"


# ---------------------------------------------------------------------------
# The staleness pair
# ---------------------------------------------------------------------------


class TestStaleness:
    def test_editing_a_section_marks_the_sections_that_describe_it(
        self, api_client, scratch
    ):
        blueprint_id = scratch["blueprint_id"]
        api_client.put(
            f"{BASE}/{blueprint_id}/sections/scope",
            json={"narrative": "The scope now also covers the Polish company code."},
        )

        data = api_client.get(f"{BASE}/{blueprint_id}").json()["data"]
        summary_section = next(
            section for section in data["sections"] if section["section_key"] == "executive_summary"
        )

        assert summary_section["stale_dependencies"] == ["scope"]
        assert data["summary"]["stale_section_count"] >= 1

    def test_an_approval_given_before_the_change_is_reported_as_stale(
        self, api_client, scratch
    ):
        """The pair: "approved by Ingrid" over a scope Ingrid never read."""
        blueprint_id = scratch["blueprint_id"]
        api_client.post(
            f"{BASE}/{blueprint_id}/sections/executive_summary/approve",
            json={"approved_by": "Ingrid Vogel"},
        )
        api_client.put(
            f"{BASE}/{blueprint_id}/sections/scope",
            json={"narrative": "A materially different scope, agreed later."},
        )

        data = api_client.get(f"{BASE}/{blueprint_id}").json()["data"]
        summary_section = next(
            section for section in data["sections"] if section["section_key"] == "executive_summary"
        )

        assert summary_section["approved_by"] == "Ingrid Vogel"
        assert summary_section["approval_is_stale"] is True
        assert data["summary"]["stale_approved_count"] == 1

    def test_regenerating_the_dependent_section_clears_the_staleness(
        self, api_client, scratch
    ):
        blueprint_id = scratch["blueprint_id"]
        api_client.put(
            f"{BASE}/{blueprint_id}/sections/scope",
            json={"narrative": "A materially different scope, agreed later."},
        )

        response = api_client.post(
            f"{BASE}/{blueprint_id}/sections/executive_summary/regenerate"
        )
        data = response.json()["data"]

        assert data["stale_dependencies"] == []
        assert data["approval_is_stale"] is False


# ---------------------------------------------------------------------------
# Custom sections
# ---------------------------------------------------------------------------


class TestCustomSections:
    def test_a_custom_section_can_be_added_after_a_named_section(
        self, api_client, scratch
    ):
        blueprint_id = scratch["blueprint_id"]
        training = next(
            section for section in scratch["sections"] if section["section_key"] == "training"
        )

        response = api_client.post(
            f"{BASE}/{blueprint_id}/sections",
            json={
                "title": "Change management",
                "content_kind": "list",
                "narrative": "How the business is prepared for the change.",
                "items": [{"title": "Stakeholder map", "detail": "Who is affected."}],
                "after_section": "training",
            },
        )
        data = response.json()["data"]

        assert response.status_code == 201
        assert data["is_custom"] is True
        assert data["section_id"] == "BP-CUS-001"
        assert data["position"] == training["position"] + 1
        assert data["items"][0]["source"] == "manual"

    def test_adding_a_section_keeps_the_positions_gap_free(self, api_client, scratch):
        blueprint_id = scratch["blueprint_id"]
        api_client.post(
            f"{BASE}/{blueprint_id}/sections",
            json={"title": "Change management", "after_section": "scope"},
        )

        data = api_client.get(f"{BASE}/{blueprint_id}").json()["data"]
        positions = [section["position"] for section in data["sections"]]

        assert positions == list(range(1, len(positions) + 1))

    def test_a_canonical_section_cannot_be_deleted(self, api_client, scratch):
        response = api_client.delete(f"{BASE}/{scratch['blueprint_id']}/sections/scope")

        assert response.status_code == 422
        assert "cannot be deleted" in response.json()["error"]["message"]

    def test_a_custom_section_can_be_deleted(self, api_client, scratch):
        blueprint_id = scratch["blueprint_id"]
        created = api_client.post(
            f"{BASE}/{blueprint_id}/sections", json={"title": "Change management"}
        ).json()["data"]

        response = api_client.delete(
            f"{BASE}/{blueprint_id}/sections/{created['section_id']}"
        )
        data = response.json()["data"]

        assert response.status_code == 200
        assert data["deleted"] is True
        assert data["remaining_count"] == 30
        assert data["summary"]["custom_section_count"] == 0

    def test_a_deleted_custom_identifier_is_never_reissued(self, api_client, scratch):
        blueprint_id = scratch["blueprint_id"]
        first = api_client.post(
            f"{BASE}/{blueprint_id}/sections", json={"title": "First custom"}
        ).json()["data"]
        api_client.delete(f"{BASE}/{blueprint_id}/sections/{first['section_id']}")

        second = api_client.post(
            f"{BASE}/{blueprint_id}/sections", json={"title": "Second custom"}
        ).json()["data"]

        assert first["section_id"] == "BP-CUS-001"
        assert second["section_id"] == "BP-CUS-002"


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


class TestVersions:
    def test_a_version_can_be_saved_and_listed(self, api_client, scratch):
        blueprint_id = scratch["blueprint_id"]
        created = api_client.post(
            f"{BASE}/{blueprint_id}/versions",
            json={"label": "Design review draft", "created_by": "Ingrid"},
        )
        assert created.status_code == 201

        listed = api_client.get(f"{BASE}/{blueprint_id}/versions").json()["data"]

        assert listed["total"] == 1
        assert listed["current_version"] == 1
        assert listed["versions"][0]["label"] == "Design review draft"
        assert listed["versions"][0]["section_count"] == 30
        assert listed["versions"][0]["sections"] == []

    def test_a_saved_version_does_not_follow_later_edits(self, api_client, scratch):
        blueprint_id = scratch["blueprint_id"]
        api_client.post(f"{BASE}/{blueprint_id}/versions", json={"label": "v1"})

        api_client.put(
            f"{BASE}/{blueprint_id}/sections/scope",
            json={"narrative": "Rewritten after version 1 was saved."},
        )

        version = api_client.get(f"{BASE}/{blueprint_id}/versions/1").json()["data"]
        saved_scope = next(
            section for section in version["sections"] if section["section_key"] == "scope"
        )

        assert "Rewritten after version 1" not in saved_scope["narrative"]

    def test_two_versions_can_be_compared(self, api_client, scratch):
        blueprint_id = scratch["blueprint_id"]
        api_client.post(f"{BASE}/{blueprint_id}/versions", json={"label": "v1"})
        api_client.put(
            f"{BASE}/{blueprint_id}/sections/risks",
            json={"narrative": "A different risk picture, agreed in the workshop."},
        )
        api_client.post(f"{BASE}/{blueprint_id}/versions", json={"label": "v2"})

        response = api_client.get(
            f"{BASE}/{blueprint_id}/versions/compare", params={"from": 1, "to": 2}
        )
        data = response.json()["data"]

        assert data["from_version"] == 1
        assert data["to_version"] == 2
        assert data["sections_modified"] >= 1
        risks = next(
            diff for diff in data["section_diffs"] if diff["section_key"] == "risks"
        )
        assert risks["change"] == "modified"
        assert risks["narrative_changed"] is True
        assert risks["narrative_diff"]

    def test_a_version_can_be_compared_against_the_live_document(
        self, api_client, scratch
    ):
        blueprint_id = scratch["blueprint_id"]
        api_client.post(f"{BASE}/{blueprint_id}/versions", json={"label": "v1"})
        api_client.put(
            f"{BASE}/{blueprint_id}/sections/training",
            json={"narrative": "Training changed after the version was saved."},
        )

        response = api_client.get(
            f"{BASE}/{blueprint_id}/versions/compare", params={"from": 1, "to": 0}
        )
        data = response.json()["data"]

        assert data["to_label"] == "current (unsaved)"
        training = next(
            diff for diff in data["section_diffs"] if diff["section_key"] == "training"
        )
        assert training["change"] == "modified"

    def test_comparing_a_version_with_itself_is_rejected(self, api_client, scratch):
        blueprint_id = scratch["blueprint_id"]
        api_client.post(f"{BASE}/{blueprint_id}/versions", json={"label": "v1"})

        response = api_client.get(
            f"{BASE}/{blueprint_id}/versions/compare", params={"from": 1, "to": 1}
        )

        assert response.status_code == 422

    def test_an_unknown_version_returns_404(self, api_client, scratch):
        response = api_client.get(f"{BASE}/{scratch['blueprint_id']}/versions/99")

        assert response.status_code == 404

    def test_version_zero_returns_the_live_document(self, api_client, scratch):
        response = api_client.get(f"{BASE}/{scratch['blueprint_id']}/versions/0")
        data = response.json()["data"]

        assert data["version_number"] == 0
        assert data["label"] == "current (unsaved)"
        assert len(data["sections"]) == 30

    def test_adding_and_removing_a_section_shows_in_the_comparison(
        self, api_client, scratch
    ):
        blueprint_id = scratch["blueprint_id"]
        api_client.post(f"{BASE}/{blueprint_id}/versions", json={"label": "v1"})
        api_client.post(
            f"{BASE}/{blueprint_id}/sections", json={"title": "Change management"}
        )
        api_client.post(f"{BASE}/{blueprint_id}/versions", json={"label": "v2"})

        data = api_client.get(
            f"{BASE}/{blueprint_id}/versions/compare", params={"from": 1, "to": 2}
        ).json()["data"]

        assert data["sections_added"] == 1
        assert data["sections_modified"] == 0


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestExport:
    def test_markdown_export_carries_the_document_and_the_disclaimer(
        self, api_client, blueprint
    ):
        response = api_client.get(
            f"{BASE}/{blueprint['blueprint_id']}/export", params={"format": "markdown"}
        )
        text = response.content.decode("utf-8")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert ".md" in response.headers["content-disposition"]
        assert text.startswith("# ")
        assert "PROPOSED" in text
        assert "## 1. Executive summary" in text
        assert "## 30. Open decisions" in text

    def test_json_export_is_parseable_and_complete(self, api_client, blueprint):
        response = api_client.get(
            f"{BASE}/{blueprint['blueprint_id']}/export", params={"format": "json"}
        )
        payload = json.loads(response.content)

        assert payload["report_type"] == "sap_implementation_blueprint"
        assert len(payload["sections"]) == 30
        assert payload["disclaimer"]
        assert payload["methodology"]["deterministic"]

    def test_docx_export_is_a_real_word_document(self, api_client, blueprint):
        docx = pytest.importorskip("docx")

        response = api_client.get(
            f"{BASE}/{blueprint['blueprint_id']}/export", params={"format": "docx"}
        )
        document = docx.Document(io.BytesIO(response.content))
        headings = [
            paragraph.text
            for paragraph in document.paragraphs
            if paragraph.style.name.startswith("Heading")
        ]

        assert response.status_code == 200
        assert any("Executive summary" in text for text in headings)
        assert any("Open decisions" in text for text in headings)
        assert document.tables

    def test_pdf_export_is_a_pdf(self, api_client, blueprint):
        response = api_client.get(
            f"{BASE}/{blueprint['blueprint_id']}/export", params={"format": "pdf"}
        )

        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")
        assert response.headers["content-type"] == "application/pdf"

    def test_the_default_export_format_is_markdown(self, api_client, blueprint):
        response = api_client.get(f"{BASE}/{blueprint['blueprint_id']}/export")

        assert response.headers["content-type"].startswith("text/markdown")

    def test_an_unknown_format_is_rejected(self, api_client, blueprint):
        response = api_client.get(
            f"{BASE}/{blueprint['blueprint_id']}/export", params={"format": "xlsx"}
        )

        assert response.status_code == 422

    def test_a_section_waiting_for_input_is_visible_in_the_export(self, api_client):
        project = {**PROJECT, "integrations": []}
        response = api_client.post(
            f"{BASE}/generate", json={"project": project, "blueprint_name": "Export gaps"}
        )
        blueprint_id = response.json()["data"]["blueprint_id"]

        text = api_client.get(
            f"{BASE}/{blueprint_id}/export", params={"format": "markdown"}
        ).content.decode("utf-8")

        assert "Waiting for project input" in text
        assert "## 16. Integrations" in text
