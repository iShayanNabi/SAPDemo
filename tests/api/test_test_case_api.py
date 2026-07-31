"""API tests for the SAP Test Case Generator endpoints.

These drive the real FastAPI app through ``TestClient``, so they cover the
response envelope, the status codes, the validation and the six routes the
module is specified around, plus the editing, approval and execution endpoints
an editable suite needs.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

BASE = "/api/v1/test-cases"

PROCESS_CONTEXT = {
    "sap_product": "SAP S/4HANA 2023",
    "sap_module": "MM",
    "business_process": "Procure to Pay - standard purchase order",
    "process_description": (
        "A requisition becomes a purchase order, the warehouse posts a goods receipt and "
        "accounts payable posts the supplier invoice before the payment run settles it."
    ),
    "preconditions": ["Vendor 100234 exists and is not blocked"],
    "business_rules": ["Orders above 10,000 EUR need a second release"],
    "systems_involved": ["SAP S/4HANA", "SAP Ariba Buying"],
    "integrations": ["Ariba requisition replication", "Bank payment file", "Supplier portal"],
    "user_roles": ["Requisitioner", "Purchasing buyer", "Warehouse clerk", "AP clerk"],
    "test_data_requirements": ["Vendor 100234", "Material 100001"],
}


def _generate(client, **overrides) -> dict:
    body = {
        "context": PROCESS_CONTEXT,
        "test_case_count": 8,
        "test_types": ["sit", "uat", "negative", "integration"],
        **overrides,
    }
    response = client.post(f"{BASE}/generate", json=body)
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["success"] is True
    return envelope["data"]


@pytest.fixture(scope="module")
def suite(api_client) -> dict:
    """One generated suite shared by the read-only tests."""
    return _generate(api_client)


@pytest.fixture
def scratch_suite(api_client) -> dict:
    """A throwaway suite for the tests that modify one."""
    return _generate(api_client, test_case_count=6, test_types=["sit", "negative", "security"])


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_a_suite_is_generated_with_the_requested_number_of_cases(self, suite):
        assert len(suite["test_cases"]) == 8
        assert suite["summary"]["test_case_count"] == 8
        assert suite["summary"]["requested_count"] == 8
        assert suite["config_version"]
        assert suite["engine_version"]

    def test_every_test_case_carries_every_required_field(self, suite):
        case = suite["test_cases"][0]

        for field in (
            "test_case_id", "test_type", "title", "objective", "priority",
            "preconditions", "test_data", "steps", "expected_result", "owner",
            "status", "actual_result", "execution_result", "evidence_reference",
            "comments",
        ):
            assert field in case, field
        assert case["test_case_id"].startswith("TC-")
        assert case["steps"]
        assert [step["step_number"] for step in case["steps"]] == list(
            range(1, len(case["steps"]) + 1)
        )

    def test_every_requested_test_type_is_covered(self, suite):
        covered = {item["test_type"] for item in suite["coverage"] if item["generated"]}

        assert covered == {"sit", "uat", "negative", "integration"}
        assert suite["uncovered_test_types"] == []

    def test_identifiers_are_unique_inside_the_suite(self, suite):
        identifiers = [case["test_case_id"] for case in suite["test_cases"]]

        assert len(identifiers) == len(set(identifiers))

    def test_output_origin_is_labelled_on_every_case(self, suite):
        for case in suite["test_cases"]:
            assert case["output_origin"] in {"rule_based", "ai_generated", "mock_ai"}
            assert case["source"] in {"ai_generated", "template", "manual", "duplicated"}

    def test_mock_mode_drafts_the_wording_and_says_so(self, suite):
        assert suite["ai"]["requested"] is True
        assert suite["ai"]["used"] is True
        assert suite["ai"]["origin"] == "mock_ai"
        assert suite["ai"]["prompt_version"]

    def test_a_suite_can_be_generated_with_no_ai_at_all(self, api_client):
        data = _generate(api_client, use_ai=False, test_case_count=4, test_types=["sit", "uat"])

        assert len(data["test_cases"]) == 4
        assert data["ai"]["requested"] is False
        assert all(case["source"] == "template" for case in data["test_cases"])
        assert all(case["steps"] for case in data["test_cases"])

    def test_all_eight_test_types_are_supported(self, api_client):
        types = [
            "sit", "uat", "negative", "integration",
            "regression", "security", "authorization", "data_migration",
        ]

        data = _generate(api_client, test_case_count=8, test_types=types)

        assert {case["test_type"] for case in data["test_cases"]} == set(types)

    def test_asking_for_fewer_cases_than_types_reports_what_is_uncovered(self, api_client):
        data = _generate(
            api_client,
            test_case_count=2,
            test_types=["sit", "uat", "security", "regression"],
        )

        assert len(data["test_cases"]) == 2
        assert data["uncovered_test_types"] == ["security", "regression"]
        assert data["notes"]

    def test_a_request_with_no_test_type_is_rejected(self, api_client):
        response = api_client.post(
            f"{BASE}/generate",
            json={"context": PROCESS_CONTEXT, "test_case_count": 4, "test_types": []},
        )

        assert response.status_code == 422
        assert response.json()["success"] is False

    def test_a_request_over_the_maximum_case_count_is_rejected(self, api_client):
        response = api_client.post(
            f"{BASE}/generate",
            json={"context": PROCESS_CONTEXT, "test_case_count": 5000, "test_types": ["sit"]},
        )

        assert response.status_code == 422

    def test_an_incomplete_process_context_is_rejected(self, api_client):
        response = api_client.post(
            f"{BASE}/generate",
            json={
                "context": {"sap_product": "SAP", "sap_module": "MM"},
                "test_types": ["sit"],
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "request_validation_error"


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class TestReads:
    def test_a_suite_can_be_fetched_again(self, api_client, suite):
        response = api_client.get(f"{BASE}/suites/{suite['suite_id']}")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["suite_id"] == suite["suite_id"]
        assert len(data["test_cases"]) == len(suite["test_cases"])
        assert data["context"]["business_process"] == PROCESS_CONTEXT["business_process"]

    def test_an_unknown_suite_returns_404(self, api_client):
        response = api_client.get(f"{BASE}/suites/does-not-exist")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_suites_are_listed_newest_first(self, api_client, suite):
        response = api_client.get(f"{BASE}/suites", params={"limit": 5})

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total"] >= 1
        assert data["suites"]

    def test_one_test_case_can_be_fetched_by_its_id(self, api_client, suite):
        case = suite["test_cases"][0]

        response = api_client.get(f"{BASE}/{case['id']}")

        assert response.status_code == 200
        assert response.json()["data"]["test_case_id"] == case["test_case_id"]

    def test_an_unknown_test_case_returns_404(self, api_client):
        assert api_client.get(f"{BASE}/nope").status_code == 404

    def test_the_catalogue_describes_the_types_and_the_rules(self, api_client):
        response = api_client.get(f"{BASE}/catalog")

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["test_types"]) == 8
        assert data["priorities"] and data["statuses"] and data["execution_results"]
        assert data["methodology"]["deterministic"]
        assert data["methodology"]["ai_generated"]
        assert data["disclaimer"]

    def test_ai_status_never_leaks_a_key(self, api_client):
        response = api_client.get(f"{BASE}/ai-status")

        assert response.status_code == 200
        body = response.text.lower()
        assert "api_key" not in body and "sk-" not in body


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


class TestEditing:
    def test_a_partial_edit_changes_only_what_was_sent(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]

        response = api_client.put(
            f"{BASE}/{case['id']}", json={"title": "A better title", "owner": "Jana"}
        )

        assert response.status_code == 200
        updated = response.json()["data"]
        assert updated["title"] == "A better title"
        assert updated["owner"] == "Jana"
        assert updated["objective"] == case["objective"]
        assert len(updated["steps"]) == len(case["steps"])

    def test_edited_steps_are_renumbered(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]

        response = api_client.put(
            f"{BASE}/{case['id']}",
            json={
                "steps": [
                    {"step_number": 9, "action": "Open the transaction"},
                    {"step_number": 4, "action": "Enter the data"},
                    {"step_number": 7, "action": "Save the document",
                     "expected_result": "A number is issued"},
                ]
            },
        )

        assert response.status_code == 200
        steps = response.json()["data"]["steps"]
        assert [step["step_number"] for step in steps] == [1, 2, 3]
        assert steps[2]["expected_result"] == "A number is issued"

    def test_a_test_case_may_not_be_left_with_no_step(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]

        response = api_client.put(f"{BASE}/{case['id']}", json={"steps": []})

        assert response.status_code == 422
        assert response.json()["success"] is False

    def test_an_empty_update_is_rejected(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]

        response = api_client.put(f"{BASE}/{case['id']}", json={})

        assert response.status_code == 422

    def test_changing_the_test_type_reissues_the_identifier(self, api_client, scratch_suite):
        case = next(item for item in scratch_suite["test_cases"] if item["test_type"] == "sit")

        response = api_client.put(f"{BASE}/{case['id']}", json={"test_type": "regression"})

        assert response.status_code == 200
        updated = response.json()["data"]
        assert updated["test_type"] == "regression"
        assert updated["test_case_id"].startswith("TC-REG-")
        assert updated["test_case_id"] != case["test_case_id"]

    def test_editing_the_script_clears_an_approval(self, api_client, scratch_suite):
        """An approval describes the script that was read, not the one that replaced it.

        Found by driving the real API by hand: regenerating cleared the approval
        but a hand edit did not, so a completely rewritten test case still read
        "approved by Ingrid" above steps Ingrid never saw.
        """
        case = scratch_suite["test_cases"][0]
        api_client.post(f"{BASE}/{case['id']}/approve", json={"approved_by": "Ingrid"})

        edited = api_client.put(
            f"{BASE}/{case['id']}",
            json={
                "title": "A completely different test",
                "steps": [
                    {"action": "Something else"},
                    {"action": "And another"},
                    {"action": "And a third"},
                ],
            },
        ).json()["data"]

        assert edited["approved_by"] is None
        assert edited["approved_at"] is None
        assert edited["status"] == "draft"

    def test_editing_the_script_keeps_the_execution_record(self, api_client, scratch_suite):
        """Clearing the approval must not throw away what a tester recorded."""
        case = scratch_suite["test_cases"][0]
        api_client.post(f"{BASE}/{case['id']}/approve", json={"approved_by": "Ingrid"})
        api_client.post(
            f"{BASE}/{case['id']}/execution",
            json={
                "execution_result": "failed",
                "actual_result": "The release did not trigger",
                "evidence_reference": "SCR-0042",
            },
        )

        edited = api_client.put(
            f"{BASE}/{case['id']}", json={"title": "A reworded test"}
        ).json()["data"]

        assert edited["approved_at"] is None
        assert edited["execution_result"] == "failed"
        assert edited["actual_result"] == "The release did not trigger"
        assert edited["evidence_reference"] == "SCR-0042"

    def test_editing_the_script_marks_the_recorded_verdict_as_stale(
        self, api_client, scratch_suite
    ):
        """A suite must not report a failure against steps that no longer exist.

        Also found by hand: the summary read "1 executed, 1 failed" while every
        status read "draft", because the verdict belonged to a script that had
        been rewritten. The record is kept - a tester wrote it - but it is now
        flagged, and the flag clears when the test is run again.
        """
        case = scratch_suite["test_cases"][0]
        api_client.post(
            f"{BASE}/{case['id']}/execution",
            json={"execution_result": "failed", "actual_result": "It broke"},
        )

        edited = api_client.put(
            f"{BASE}/{case['id']}", json={"title": "A rewritten test"}
        ).json()["data"]

        assert edited["execution_result"] == "failed"
        assert edited["execution_is_stale"] is True

        summary = api_client.get(
            f"{BASE}/suites/{scratch_suite['suite_id']}"
        ).json()["data"]["summary"]
        assert summary["stale_execution_count"] == 1

    def test_running_the_test_again_clears_the_stale_flag(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]
        api_client.post(
            f"{BASE}/{case['id']}/execution",
            json={"execution_result": "failed", "actual_result": "It broke"},
        )
        api_client.put(f"{BASE}/{case['id']}", json={"title": "A rewritten test"})

        rerun = api_client.post(
            f"{BASE}/{case['id']}/execution",
            json={"execution_result": "passed", "actual_result": "Fixed"},
        ).json()["data"]

        assert rerun["execution_is_stale"] is False

    def test_regenerating_marks_a_kept_verdict_as_stale(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]
        api_client.post(
            f"{BASE}/{case['id']}/execution",
            json={"execution_result": "passed", "actual_result": "Fine"},
        )

        regenerated = api_client.post(
            f"{BASE}/{case['id']}/regenerate", json={}
        ).json()["data"]

        assert regenerated["execution_result"] == "passed"
        assert regenerated["execution_is_stale"] is True

    def test_discarding_the_execution_record_leaves_nothing_stale(
        self, api_client, scratch_suite
    ):
        case = scratch_suite["test_cases"][0]
        api_client.post(
            f"{BASE}/{case['id']}/execution",
            json={"execution_result": "passed", "actual_result": "Fine"},
        )

        regenerated = api_client.post(
            f"{BASE}/{case['id']}/regenerate", json={"keep_execution_record": False}
        ).json()["data"]

        assert regenerated["execution_result"] == "not_run"
        assert regenerated["execution_is_stale"] is False

    def test_an_administrative_edit_leaves_the_approval_alone(
        self, api_client, scratch_suite
    ):
        """Reassigning an owner is not a change to the test that was approved."""
        case = scratch_suite["test_cases"][0]
        api_client.post(f"{BASE}/{case['id']}/approve", json={"approved_by": "Ingrid"})

        edited = api_client.put(
            f"{BASE}/{case['id']}", json={"owner": "Jana", "evidence_reference": "SCR-1"}
        ).json()["data"]

        assert edited["approved_by"] == "Ingrid"
        assert edited["status"] == "approved"

    def test_an_over_long_title_is_rejected_by_validation(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]

        response = api_client.put(f"{BASE}/{case['id']}", json={"title": "x" * 5000})

        assert response.status_code == 422

    def test_a_row_can_be_added_by_hand(self, api_client, scratch_suite):
        response = api_client.post(
            f"{BASE}/suites/{scratch_suite['suite_id']}/test-cases",
            json={"test_type": "uat", "title": "Business signs off the reprint"},
        )

        assert response.status_code == 201
        created = response.json()["data"]
        assert created["test_case_id"] == "TC-UAT-001"
        assert created["source"] == "manual"
        assert created["steps"], "an added row must be usable, not an empty shell"
        assert created["priority"]

    def test_an_added_row_appears_in_the_suite_and_its_coverage(
        self, api_client, scratch_suite
    ):
        api_client.post(
            f"{BASE}/suites/{scratch_suite['suite_id']}/test-cases",
            json={"test_type": "data_migration", "title": "Reconcile the vendor load"},
        )

        data = api_client.get(f"{BASE}/suites/{scratch_suite['suite_id']}").json()["data"]

        migration = next(
            item for item in data["coverage"] if item["test_type"] == "data_migration"
        )
        assert migration["generated"] == 1
        assert migration["manual"] == 1
        assert migration["planned"] == 0

    def test_adding_a_row_to_an_unknown_suite_returns_404(self, api_client):
        response = api_client.post(
            f"{BASE}/suites/nope/test-cases", json={"test_type": "sit", "title": "A test"}
        )

        assert response.status_code == 404

    def test_a_row_can_be_duplicated_with_its_own_identifier(
        self, api_client, scratch_suite
    ):
        case = scratch_suite["test_cases"][0]

        response = api_client.post(f"{BASE}/{case['id']}/duplicate")

        assert response.status_code == 201
        copy = response.json()["data"]
        assert copy["test_case_id"] != case["test_case_id"]
        assert copy["test_type"] == case["test_type"]
        assert copy["title"] == case["title"]
        assert copy["source"] == "duplicated"
        assert copy["execution_result"] == "not_run"
        assert copy["approved_at"] is None


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


class TestDeletion:
    def test_deleting_a_case_removes_it_from_the_suite(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]

        response = api_client.delete(f"{BASE}/{case['id']}")

        assert response.status_code == 200
        result = response.json()["data"]
        assert result["deleted"] is True
        assert result["remaining_count"] == len(scratch_suite["test_cases"]) - 1

        remaining = api_client.get(f"{BASE}/suites/{scratch_suite['suite_id']}").json()["data"]
        assert case["test_case_id"] not in {
            item["test_case_id"] for item in remaining["test_cases"]
        }

    def test_deleting_the_last_case_of_a_type_reports_the_lost_coverage(
        self, api_client, scratch_suite
    ):
        security = [
            item for item in scratch_suite["test_cases"] if item["test_type"] == "security"
        ]
        assert security, "the fixture must contain at least one security test"

        results = [
            api_client.delete(f"{BASE}/{case['id']}").json()["data"] for case in security
        ]

        assert all(item["lost_test_types"] == [] for item in results[:-1])
        assert results[-1]["lost_test_types"] == ["security"]

    def test_deleting_one_of_several_does_not_report_lost_coverage(
        self, api_client, scratch_suite
    ):
        sit = [item for item in scratch_suite["test_cases"] if item["test_type"] == "sit"]
        assert len(sit) > 1

        result = api_client.delete(f"{BASE}/{sit[0]['id']}").json()["data"]

        assert result["lost_test_types"] == []

    def test_a_deleted_identifier_is_never_reissued(self, api_client, scratch_suite):
        """A gap in the numbering beats one identifier naming two different tests."""
        sit = [item for item in scratch_suite["test_cases"] if item["test_type"] == "sit"]
        highest = max(item["test_case_id"] for item in sit)
        api_client.delete(f"{BASE}/{sit[0]['id']}")

        created = api_client.post(
            f"{BASE}/suites/{scratch_suite['suite_id']}/test-cases",
            json={"test_type": "sit", "title": "A replacement test"},
        ).json()["data"]

        assert created["test_case_id"] > highest
        assert created["test_case_id"] not in {item["test_case_id"] for item in sit}

    def test_deleting_an_unknown_case_returns_404(self, api_client):
        assert api_client.delete(f"{BASE}/nope").status_code == 404


# ---------------------------------------------------------------------------
# Regeneration
# ---------------------------------------------------------------------------


class TestRegeneration:
    def test_regenerating_keeps_the_identifier_and_counts_the_attempt(
        self, api_client, scratch_suite
    ):
        case = scratch_suite["test_cases"][0]

        response = api_client.post(f"{BASE}/{case['id']}/regenerate", json={})

        assert response.status_code == 200
        updated = response.json()["data"]
        assert updated["test_case_id"] == case["test_case_id"]
        assert updated["sequence"] == case["sequence"]
        assert updated["regenerated_count"] == 1
        assert updated["steps"]

    def test_regenerating_with_no_body_is_allowed(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]

        assert api_client.post(f"{BASE}/{case['id']}/regenerate").status_code == 200

    def test_a_reviewer_instruction_reaches_the_draft(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]

        response = api_client.post(
            f"{BASE}/{case['id']}/regenerate",
            json={"instruction": "cover the second release step"},
        )

        assert response.status_code == 200
        assert "second release step" in response.json()["data"]["objective"]

    def test_regenerating_without_ai_uses_the_template(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]

        response = api_client.post(f"{BASE}/{case['id']}/regenerate", json={"use_ai": False})

        assert response.json()["data"]["source"] == "template"
        assert response.json()["data"]["output_origin"] == "rule_based"

    def test_regenerating_keeps_the_execution_record_by_default(
        self, api_client, scratch_suite
    ):
        """Improving the wording must not delete what a tester recorded."""
        case = scratch_suite["test_cases"][0]
        api_client.post(
            f"{BASE}/{case['id']}/execution",
            json={
                "execution_result": "failed",
                "actual_result": "The release did not trigger",
                "executed_by": "Jana",
                "evidence_reference": "SCR-0042",
            },
        )

        updated = api_client.post(f"{BASE}/{case['id']}/regenerate", json={}).json()["data"]

        assert updated["execution_result"] == "failed"
        assert updated["actual_result"] == "The release did not trigger"
        assert updated["evidence_reference"] == "SCR-0042"

    def test_the_execution_record_can_be_cleared_deliberately(
        self, api_client, scratch_suite
    ):
        case = scratch_suite["test_cases"][0]
        api_client.post(
            f"{BASE}/{case['id']}/execution",
            json={"execution_result": "passed", "actual_result": "Fine"},
        )

        updated = api_client.post(
            f"{BASE}/{case['id']}/regenerate", json={"keep_execution_record": False}
        ).json()["data"]

        assert updated["execution_result"] == "not_run"
        assert updated["actual_result"] == ""
        assert updated["executed_at"] is None

    def test_regenerating_always_clears_the_approval(self, api_client, scratch_suite):
        """An approval belongs to the script that was approved."""
        case = scratch_suite["test_cases"][0]
        api_client.post(f"{BASE}/{case['id']}/approve", json={"approved_by": "Test lead"})

        updated = api_client.post(f"{BASE}/{case['id']}/regenerate", json={}).json()["data"]

        assert updated["approved_by"] is None
        assert updated["approved_at"] is None
        assert updated["status"] == "draft"

    def test_regenerating_as_another_type_reissues_the_identifier(
        self, api_client, scratch_suite
    ):
        case = next(item for item in scratch_suite["test_cases"] if item["test_type"] == "sit")

        updated = api_client.post(
            f"{BASE}/{case['id']}/regenerate", json={"test_type": "authorization"}
        ).json()["data"]

        assert updated["test_type"] == "authorization"
        assert updated["test_case_id"].startswith("TC-AUT-")

    def test_regenerating_an_unknown_case_returns_404(self, api_client):
        assert api_client.post(f"{BASE}/nope/regenerate", json={}).status_code == 404


# ---------------------------------------------------------------------------
# Approval and execution
# ---------------------------------------------------------------------------


class TestApprovalAndExecution:
    def test_a_test_can_be_approved(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]

        response = api_client.post(
            f"{BASE}/{case['id']}/approve", json={"approved_by": "Test lead"}
        )

        assert response.status_code == 200
        approved = response.json()["data"]
        assert approved["status"] == "approved"
        assert approved["approved_by"] == "Test lead"
        assert approved["approved_at"]

    def test_an_approval_can_be_withdrawn(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]
        api_client.post(f"{BASE}/{case['id']}/approve", json={"approved_by": "Test lead"})

        withdrawn = api_client.post(
            f"{BASE}/{case['id']}/approve",
            json={"approved_by": "Test lead", "approved": False},
        ).json()["data"]

        assert withdrawn["approved_at"] is None
        assert withdrawn["status"] == "draft"

    def test_approving_without_a_name_is_rejected(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]

        response = api_client.post(f"{BASE}/{case['id']}/approve", json={})

        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("result", "expected_status"),
        [("passed", "executed"), ("failed", "executed"), ("blocked", "blocked")],
    )
    def test_recording_a_result_sets_the_status_deterministically(
        self, api_client, scratch_suite, result, expected_status
    ):
        case = scratch_suite["test_cases"][0]

        response = api_client.post(
            f"{BASE}/{case['id']}/execution",
            json={"execution_result": result, "actual_result": "What happened"},
        )

        assert response.status_code == 200
        recorded = response.json()["data"]
        assert recorded["execution_result"] == result
        assert recorded["status"] == expected_status
        assert recorded["executed_at"]

    def test_recording_an_execution_never_changes_the_script(
        self, api_client, scratch_suite
    ):
        case = scratch_suite["test_cases"][0]

        recorded = api_client.post(
            f"{BASE}/{case['id']}/execution",
            json={"execution_result": "passed", "actual_result": "As expected"},
        ).json()["data"]

        assert recorded["title"] == case["title"]
        assert recorded["objective"] == case["objective"]
        assert recorded["steps"] == case["steps"]

    def test_the_suite_summary_follows_the_recorded_results(
        self, api_client, scratch_suite
    ):
        cases = scratch_suite["test_cases"]
        api_client.post(
            f"{BASE}/{cases[0]['id']}/execution",
            json={"execution_result": "passed", "actual_result": "Fine"},
        )
        api_client.post(
            f"{BASE}/{cases[1]['id']}/execution",
            json={"execution_result": "failed", "actual_result": "Broken"},
        )
        api_client.post(
            f"{BASE}/{cases[2]['id']}/execution",
            json={"execution_result": "blocked", "actual_result": "No test data"},
        )

        summary = api_client.get(
            f"{BASE}/suites/{scratch_suite['suite_id']}"
        ).json()["data"]["summary"]

        assert summary["passed_count"] == 1
        assert summary["failed_count"] == 1
        assert summary["executed_count"] == 3
        # The blocked run has no verdict, so it is excluded from the pass rate.
        assert summary["pass_rate_pct"] == 50.0

    def test_an_unknown_execution_result_is_rejected(self, api_client, scratch_suite):
        case = scratch_suite["test_cases"][0]

        response = api_client.post(
            f"{BASE}/{case['id']}/execution", json={"execution_result": "maybe"}
        )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class TestExport:
    @pytest.mark.parametrize(
        ("file_format", "media_type"),
        [
            ("csv", "text/csv"),
            ("json", "application/json"),
            ("pdf", "application/pdf"),
            (
                "xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        ],
    )
    def test_every_format_downloads(self, api_client, suite, file_format, media_type):
        response = api_client.get(
            f"{BASE}/suites/{suite['suite_id']}/export", params={"format": file_format}
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith(media_type)
        assert f".{file_format}" in response.headers["content-disposition"]
        assert len(response.content) > 500

    def test_the_csv_holds_one_row_per_test_case(self, api_client, suite):
        response = api_client.get(
            f"{BASE}/suites/{suite['suite_id']}/export", params={"format": "csv"}
        )

        text = response.content.decode("utf-8-sig")
        assert "Test Case ID" in text
        assert "Pass / Fail" in text
        for case in suite["test_cases"]:
            assert case["test_case_id"] in text

    def test_the_workbook_has_the_expected_sheets(self, api_client, suite):
        response = api_client.get(
            f"{BASE}/suites/{suite['suite_id']}/export", params={"format": "xlsx"}
        )

        workbook = load_workbook(io.BytesIO(response.content))
        assert workbook.sheetnames == [
            "Summary", "Test Cases", "Steps", "Coverage", "Methodology"
        ]
        assert workbook["Test Cases"].max_row == len(suite["test_cases"]) + 1
        assert workbook["Steps"].max_row == suite["summary"]["step_count"] + 1

    def test_the_json_export_carries_the_disclaimer_and_the_methodology(
        self, api_client, suite
    ):
        response = api_client.get(
            f"{BASE}/suites/{suite['suite_id']}/export", params={"format": "json"}
        )

        payload = response.json()
        assert payload["report_type"] == "sap_test_case_suite"
        assert "not been executed" in payload["disclaimer"].lower()
        assert payload["methodology"]["deterministic"]
        assert len(payload["test_cases"]) == len(suite["test_cases"])

    def test_the_pdf_is_a_real_readable_pdf(self, api_client, suite):
        """Exported evidence a reviewer cannot open is not evidence."""
        from app.services.documents.factory import extract_document

        response = api_client.get(
            f"{BASE}/suites/{suite['suite_id']}/export", params={"format": "pdf"}
        )

        assert response.content.startswith(b"%PDF-")
        extracted = extract_document(response.content, "suite.pdf")
        text = "\n".join(page.text for page in extracted.pages)
        assert extracted.needs_ocr is False
        assert suite["test_cases"][0]["test_case_id"] in text
        assert "not been executed" in text.lower()

    def test_an_unknown_format_is_rejected(self, api_client, suite):
        response = api_client.get(
            f"{BASE}/suites/{suite['suite_id']}/export", params={"format": "docx"}
        )

        assert response.status_code == 422

    def test_exporting_an_unknown_suite_returns_404(self, api_client):
        assert api_client.get(f"{BASE}/suites/nope/export").status_code == 404


# ---------------------------------------------------------------------------
# Demo processes
# ---------------------------------------------------------------------------


class TestSamples:
    def test_the_demo_processes_are_described(self, api_client):
        response = api_client.get(f"{BASE}/sample/info")

        assert response.status_code == 200
        data = response.json()["data"]
        if not data["available"]:
            pytest.skip("Run 'python scripts/generate_test_case_sample_data.py' first.")
        assert data["process_count"] >= 1
        assert data["processes"][0]["name"]

    def test_a_demo_process_generates_a_suite_end_to_end(self, api_client):
        info = api_client.get(f"{BASE}/sample/info").json()["data"]
        if not info["available"]:
            pytest.skip("Run 'python scripts/generate_test_case_sample_data.py' first.")
        process = info["processes"][0]

        loaded = api_client.get(f"{BASE}/sample", params={"name": process["name"]})
        assert loaded.status_code == 200
        definition = loaded.json()["data"]

        data = _generate(
            api_client,
            context=definition["context"],
            test_types=definition["suggested_test_types"],
            test_case_count=definition["suggested_test_case_count"],
        )
        assert len(data["test_cases"]) == definition["suggested_test_case_count"]

    def test_an_unknown_demo_process_returns_404(self, api_client):
        response = api_client.get(f"{BASE}/sample", params={"name": "not_a_process"})

        assert response.status_code == 404
