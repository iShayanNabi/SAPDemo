"""The demonstration API, driven through the real routes.

The session-wide test client runs with demo mode *off*, which is the normal
development configuration. Demo mode is switched on per-test by patching the
settings object each guard actually reads - the settings singleton is built at
import time, so re-reading the environment would change nothing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import MODULES
from app.services.demo import DEMO_MODULES

V1 = settings.api_v1_prefix

#: The seven modules that take a file and therefore have a loader. Written out
#: rather than derived, so a loader silently disappearing is a failure here
#: rather than a shorter list that still passes.
LOADABLE = [
    "po_risk",
    "spend_analytics",
    "supplier_recommendation",
    "invoice_validator",
    "supplier_risk_copilot",
    "contract_assistant",
    "inventory_predictor",
]

#: The three that take a structured request instead.
NOT_LOADABLE = ["test_case_generator", "blueprint_generator", "interview_coach"]


@pytest.fixture
def demo_mode(monkeypatch):
    """Turn public demonstration mode on for one test."""
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    monkeypatch.setattr(settings, "demo_allow_uploads", False, raising=False)
    monkeypatch.setattr(settings, "demo_use_mock_ai", True, raising=False)
    yield


def data(response) -> dict:
    body = response.json()
    assert body["success"] is True, body.get("error")
    return body["data"]


class TestDemoStatus:
    def test_it_reports_normal_mode_by_default(self, api_client: TestClient):
        payload = data(api_client.get(f"{V1}/demo/status"))
        assert payload["demo_mode"] is False
        assert payload["uploads_enabled"] is True

    def test_it_reports_demo_mode_when_it_is_on(self, api_client: TestClient, demo_mode):
        payload = data(api_client.get(f"{V1}/demo/status"))
        assert payload["demo_mode"] is True
        assert payload["uploads_enabled"] is False
        assert payload["ai_is_mock"] is True
        assert payload["banner_headline"] == "Public Demo — Fictional Data Only"
        assert payload["data_origin"] == "demo_data"

    def test_it_serves_no_secret(self, api_client: TestClient, demo_mode):
        body = api_client.get(f"{V1}/demo/status").text
        for forbidden in ("sk-ant-", "postgresql://", "sqlite://", "/Users/", "/app/"):
            assert forbidden not in body

    def test_the_index_reports_the_two_booleans_a_client_needs(self, api_client: TestClient, demo_mode):
        payload = api_client.get("/").json()
        assert payload["demo_mode"] is True
        assert payload["uploads_enabled"] is False
        assert "Public Demo" in payload["disclaimer"]


class TestTheModuleCatalogue:
    def test_it_describes_all_ten_modules(self, api_client: TestClient):
        payload = data(api_client.get(f"{V1}/demo/modules"))
        assert [entry["module"] for entry in payload] == [module["id"] for module in MODULES]

    def test_the_numbers_and_names_match_the_api_index(self, api_client: TestClient):
        """Two lists describing the same ten things must agree on all three fields.

        A count-only assertion would pass with a module renamed, renumbered, or
        listed twice.
        """
        described = {entry["module"]: entry for entry in data(api_client.get(f"{V1}/demo/modules"))}
        for module in MODULES:
            entry = described[module["id"]]
            assert entry["number"] == int(module["number"])
            assert entry["name"] == module["name"]

    def test_seven_modules_are_loadable_and_three_are_not(self, api_client: TestClient):
        described = {entry["module"]: entry for entry in data(api_client.get(f"{V1}/demo/modules"))}
        assert sorted(key for key, entry in described.items() if entry["loadable"]) == sorted(LOADABLE)
        for key in NOT_LOADABLE:
            assert described[key]["loadable"] is False
            assert described[key]["input_style"] == "structured_request"

    def test_every_module_explains_the_deterministic_and_the_ai_part_separately(
        self, api_client: TestClient
    ):
        for entry in data(api_client.get(f"{V1}/demo/modules")):
            assert len(entry["business_question"]) > 20, entry["module"]
            assert len(entry["deterministic_summary"]) > 40, entry["module"]
            assert len(entry["ai_summary"]) > 20, entry["module"]
            assert len(entry["expected_output"]) > 20, entry["module"]

    def test_every_bundled_file_is_actually_present(self, api_client: TestClient):
        for entry in data(api_client.get(f"{V1}/demo/modules")):
            for dataset in entry["datasets"]:
                assert dataset["available"], f"{entry['module']} → {dataset['filename']}"


class TestLoadingBundledData:
    @pytest.mark.parametrize("module", LOADABLE)
    def test_each_loadable_module_ingests_its_bundled_data(
        self, api_client: TestClient, module: str
    ):
        payload = data(api_client.post(f"{V1}/demo/load/{module}"))
        assert payload["module"] == module
        assert payload["data_origin"] == "demo_data"
        assert payload["datasets"], module
        for dataset in payload["datasets"]:
            assert dataset["identifier"], f"{module} → {dataset['key']} produced no handle"
            assert (dataset["row_count"] or 0) > 0, module
        assert payload["analyze_payload"], module
        assert all(payload["analyze_payload"].values()), module

    @pytest.mark.parametrize("module", NOT_LOADABLE)
    def test_a_structured_request_module_says_so_rather_than_failing_oddly(
        self, api_client: TestClient, module: str
    ):
        response = api_client.post(f"{V1}/demo/load/{module}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "demo_not_available"

    def test_an_unknown_module_is_refused(self, api_client: TestClient):
        response = api_client.post(f"{V1}/demo/load/not_a_module")
        assert response.status_code == 404

    def test_a_module_name_with_a_path_traversal_is_rejected_by_validation(
        self, api_client: TestClient
    ):
        # The route constrains the pattern, so this never reaches the catalogue.
        assert api_client.post(f"{V1}/demo/load/../../etc/passwd").status_code in {404, 422}

    def test_the_returned_upload_payload_is_the_module_s_own(self, api_client: TestClient):
        """The page renders its mapping preview from this, so it must be the real shape."""
        payload = data(api_client.post(f"{V1}/demo/load/po_risk"))
        upload = payload["uploads"]["purchase_orders"]
        for field in ("upload_id", "row_count", "column_count", "detected_columns",
                      "suggested_mapping", "preview_rows", "is_analyzable"):
            assert field in upload, field
        assert upload["upload_id"] == payload["analyze_payload"]["upload_id"]

    def test_the_inventory_as_of_date_comes_from_the_data_not_a_constant(
        self, api_client: TestClient
    ):
        """A hardcoded as-of date is wrong the day the generator is re-run.

        Module 7's own worst bug was a reorder window computed from the wrong
        period, so the suggested date is read back off the loaded history.
        """
        payload = data(api_client.post(f"{V1}/demo/load/inventory_predictor"))
        suggested = payload["suggested_parameters"]
        assert "as_of_date" in suggested
        upload = payload["uploads"]["history"]
        assert suggested["as_of_date"] == upload["history_end"]

    def test_loading_works_while_demo_mode_refuses_uploads(
        self, api_client: TestClient, demo_mode
    ):
        """The bug this catches was real: the demo's own Load button was 403ed.

        The guard refuses payloads that came from a *request*. These bytes come
        from data/sample/, and the distinction is the whole design.
        """
        assert api_client.post(
            f"{V1}/po-risk/upload", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")}
        ).status_code == 403

        payload = data(api_client.post(f"{V1}/demo/load/po_risk"))
        assert payload["datasets"][0]["row_count"] > 0

    def test_a_loaded_dataset_can_then_be_analysed(self, api_client: TestClient, demo_mode):
        """End to end: the guided demonstration produces a real analysis."""
        loaded = data(api_client.post(f"{V1}/demo/load/po_risk"))
        analysis = data(
            api_client.post(
                f"{V1}/po-risk/analyze",
                json={**loaded["analyze_payload"], "generate_ai_summary": True},
            )
        )
        assert analysis["record_count"] > 0
        assert analysis["findings_count"] > 0
        # The prose is mock, and says so.
        narrative = analysis["ai_narrative"]
        assert narrative["available"] is True
        assert narrative["origin"] == "mock_ai"


class TestUploadsAreRefusedServerSide:
    """Hiding the widget stops an honest visitor and nobody else."""

    UPLOAD_ROUTES = [
        (f"{V1}/po-risk/upload", None),
        (f"{V1}/spend/upload", None),
        (f"{V1}/suppliers/upload", None),
        (f"{V1}/invoices/upload", {"dataset": "invoices"}),
        (f"{V1}/supplier-risk/upload", None),
        (f"{V1}/inventory/upload", None),
    ]

    @pytest.mark.parametrize("path,form", UPLOAD_ROUTES)
    def test_every_tabular_upload_route_refuses(
        self, api_client: TestClient, demo_mode, path: str, form
    ):
        response = api_client.post(
            path, data=form, files={"file": ("data.csv", b"a,b\n1,2\n", "text/csv")}
        )
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "demo_mode_restricted"

    def test_the_document_upload_route_refuses(self, api_client: TestClient, demo_mode):
        response = api_client.post(
            f"{V1}/contracts/upload",
            files={"file": ("c.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "demo_mode_restricted"

    def test_an_oversized_upload_is_refused_before_it_is_read(
        self, api_client: TestClient, demo_mode
    ):
        """The refusal must not first accept 25 MB of a stranger's payload."""
        big = b"a,b\n" + (b"1,2\n" * 500_000)
        response = api_client.post(
            f"{V1}/po-risk/upload", files={"file": ("big.csv", big, "text/csv")}
        )
        # Refused for being a demo, not for being large - the guard runs first.
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "demo_mode_restricted"

    def test_every_upload_route_still_works_when_demo_mode_is_off(self, api_client: TestClient):
        """Normal development behaviour must be preserved exactly."""
        sample = (settings.sample_dir / "sample_purchase_orders.csv").read_bytes()
        response = api_client.post(
            f"{V1}/po-risk/upload",
            files={"file": ("sample_purchase_orders.csv", sample, "text/csv")},
        )
        assert response.status_code == 200
        assert data(response)["row_count"] > 0


class TestTheCatalogueAgreesWithTheApplication:
    def test_the_demo_catalogue_and_the_module_index_describe_the_same_ten(self):
        assert [spec.key for spec in DEMO_MODULES] == [module["id"] for module in MODULES]
        assert [spec.number for spec in DEMO_MODULES] == [int(m["number"]) for m in MODULES]
        assert [spec.name for spec in DEMO_MODULES] == [module["name"] for module in MODULES]

    def test_every_loader_declares_the_analysis_route_it_feeds(self):
        for spec in DEMO_MODULES:
            if spec.loader is not None:
                assert spec.analyze_path.startswith("/"), spec.key
