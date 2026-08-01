"""The OpenAPI document has to be good enough to build a front end from.

That is not a stylistic aspiration. A future React or Next.js client generates
its types from this document and its error handling from the responses declared
in it. Anything missing here becomes a guess in the front end, and a guess about
an API is a bug with a long fuse.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from app.core.config import PROJECT_ROOT
from app.main import MODULES, app
from tests.e2e.conftest import ok

V1 = "/api/v1"


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


class TestTheDocumentIsComplete:
    def test_it_generates_at_all(self, client):
        """`/docs` renders from this; a schema error is a blank page."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        document = response.json()
        assert document["openapi"].startswith("3.")
        assert len(document["paths"]) > 100

    def test_every_endpoint_has_a_summary_and_a_description(self, spec):
        """The summary is the line in the sidebar; the description is the help."""
        missing_summary = []
        missing_description = []
        for path, operations in spec["paths"].items():
            for method, operation in operations.items():
                label = f"{method.upper()} {path}"
                if not operation.get("summary"):
                    missing_summary.append(label)
                if not (operation.get("description") or "").strip():
                    missing_description.append(label)
        assert missing_summary == [], f"endpoints with no summary: {missing_summary}"
        assert missing_description == [], f"endpoints with no description: {missing_description}"

    def test_every_tag_is_described(self, spec):
        """A module's tag description is the only place its purpose is stated."""
        described = {tag["name"] for tag in spec.get("tags", []) if tag.get("description")}
        used = {
            tag
            for operations in spec["paths"].values()
            for operation in operations.values()
            for tag in operation.get("tags", [])
        }
        assert used - described == set(), f"tags used but not described: {sorted(used - described)}"

    def test_there_is_one_tag_per_module_plus_the_two_cross_cutting_ones(self, spec):
        """Exactly one tag per module, plus System and Demonstration.

        Asserting the tag *set* rather than the tag count, which is what this
        checked before the Demonstration tag was added. A count passes when a
        module tag is renamed to something the API does not serve, or when one
        module gains a second tag while another loses its only one; the set does
        not. The two non-module tags are named explicitly so adding a third is a
        deliberate edit here rather than a number quietly going up.
        """
        described = {tag["name"] for tag in spec["tags"]}
        module_tags = {module["name"] for module in MODULES}
        cross_cutting = {"System", "Demonstration"}

        assert described == module_tags | cross_cutting
        # No duplicates in the declared list.
        assert len(spec["tags"]) == len(described)

    def test_the_description_explains_the_envelope_and_the_disclaimer(self, spec):
        """The two things a reader must know before trusting a single number."""
        description = spec["info"]["description"]
        assert '"success"' in description and '"data"' in description
        assert "output_origin" in description
        lowered = description.lower()
        assert "no sap system" in lowered
        assert "validated in a live sap environment" in lowered
        assert "fictional" in lowered
        assert "not connected to any sap system" in spec["info"]["x-disclaimer"].lower()


class TestErrorsAreDocumented:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/po-risk/analyze",
            "/api/v1/spend/analyze",
            "/api/v1/invoices/validate",
            "/api/v1/inventory/forecast",
            "/api/v1/test-cases/generate",
            "/api/v1/blueprints/generate",
        ],
    )
    def test_a_module_route_documents_its_failures(self, spec, path):
        """Not just 200 and 422: a client needs the 400, 404 and 500 shapes too."""
        responses = spec["paths"][path]["post"]["responses"]
        for status in ("400", "404", "422", "500"):
            assert status in responses, f"{path} does not document a {status}"

    def test_an_error_example_matches_the_envelope_the_api_really_returns(self, spec, client):
        """A documented example that does not match reality is worse than none."""
        documented = spec["paths"]["/api/v1/po-risk/analyze"]["post"]["responses"]["404"]
        example = documented["content"]["application/json"]["example"]
        assert set(example) == {"success", "data", "error", "meta"}

        actual = client.get(f"{V1}/po-risk/analyses/does-not-exist").json()
        assert set(actual) == set(example)
        assert set(actual["error"]) == set(example["error"])
        assert set(actual["meta"]) == set(example["meta"])


class TestExamplesAndAuth:
    def test_the_main_request_bodies_carry_an_example(self, spec):
        """"Try it out" with an empty body teaches a reader nothing."""
        for name in ("AnalyzeRequest", "SpendAnalyzeRequest"):
            schema = spec["components"]["schemas"][name]
            assert schema.get("examples"), f"{name} has no example"

    def test_an_upload_endpoint_documents_its_file_field(self, spec):
        upload = spec["paths"]["/api/v1/po-risk/upload"]["post"]
        content = upload["requestBody"]["content"]["multipart/form-data"]
        properties = content["schema"]["$ref"] if "$ref" in content["schema"] else content["schema"]
        assert properties, "the upload endpoint declares no multipart body"

    def test_the_authentication_placeholder_is_declared_but_optional(self, spec):
        """Declared so a generated client has the seam; optional because it is."""
        schemes = spec["components"]["securitySchemes"]
        assert schemes["bearerAuth"]["scheme"] == "bearer"
        assert "not enforced" in schemes["bearerAuth"]["description"].lower()
        # `{}` alongside the scheme means "no credential is also acceptable".
        assert {} in spec["security"]

    def test_no_endpoint_actually_requires_a_credential(self, client):
        """Local demo mode has to keep working with no token at all."""
        assert ok(client.get(f"{V1}/health"))
        assert client.get("/").status_code == 200
        assert client.get(f"{V1}/po-risk/rules").status_code == 200


class TestTheModuleIndex:
    def test_it_lists_all_ten_modules_as_available(self, client):
        """This said eight for two modules after they shipped."""
        body = client.get("/").json()
        assert body["module_count"] == 10
        assert len(body["modules"]) == 10
        assert all(module["status"] == "available" for module in body["modules"])
        assert "planned_modules" not in body, (
            "every module is built; a 'planned' list can only be wrong"
        )

    def test_every_listed_base_path_is_a_path_the_api_serves(self, client, spec):
        """A base path nobody serves sends a new client straight into a 404."""
        served = set(spec["paths"])
        for module in client.get("/").json()["modules"]:
            base = module["base_path"]
            assert any(path.startswith(base) for path in served), (
                f"{module['id']} advertises {base}, which serves nothing"
            )

    def test_the_index_names_where_the_contract_lives(self, client):
        body = client.get("/").json()
        assert body["docs"]["openapi"] == "/openapi.json"
        assert body["health"] == f"{V1}/health"
        assert "not connected to any sap system" in body["disclaimer"].lower()


class TestTheGeneratedCollection:
    def test_the_committed_collection_is_current(self):
        """A stale collection is the one somebody imports.

        Regenerate with: python scripts/generate_api_collection.py
        """
        completed = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "generate_api_collection.py"), "--check"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_it_has_a_folder_per_module_and_covers_every_endpoint(self, spec):
        collection = json.loads(
            (PROJECT_ROOT / "docs" / "postman_collection.json").read_text(encoding="utf-8")
        )
        folders = {folder["name"] for folder in collection["item"]}
        assert folders == {tag["name"] for tag in spec["tags"]}

        requests = sum(len(folder["item"]) for folder in collection["item"])
        endpoints = sum(
            1
            for operations in spec["paths"].values()
            for method in operations
            if method in {"get", "post", "put", "patch", "delete"}
        )
        assert requests == endpoints

    def test_it_carries_no_credential(self):
        """A collection people import must not ship somebody's token."""
        raw = (PROJECT_ROOT / "docs" / "postman_collection.json").read_text(encoding="utf-8")
        assert "sk-ant-" not in raw and "sk-proj" not in raw
        collection = json.loads(raw)
        token = next(
            variable for variable in collection["variable"] if variable["key"] == "authToken"
        )
        assert token["value"] == ""
