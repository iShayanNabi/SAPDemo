"""The conventions every module has to keep, asserted across all of them at once.

The workflow tests in this package check that each module *works*. These check
that the ten of them agree - that a front end can write one response handler,
one error handler, one pagination control and one severity legend rather than
ten. Most of them read the generated OpenAPI schema, so a new module is covered
the moment it registers a route, without anybody remembering to add a test.

Each failure here has a concrete cost written next to it. "Be consistent" is not
a reason; "a generated TypeScript client cannot describe this field" is.
"""

from __future__ import annotations

import json

import pytest

from app.main import app
from app.schemas.common import AnalysisStatus, IssueSeverity, OutputOrigin, Severity
from tests.e2e.conftest import envelope, failure, ok

V1 = "/api/v1"


@pytest.fixture(scope="module")
def spec() -> dict:
    """The generated OpenAPI document."""
    return app.openapi()


@pytest.fixture(scope="module")
def schemas(spec) -> dict:
    return spec["components"]["schemas"]


def _resolve(schemas: dict, ref: str) -> dict:
    return schemas.get(ref.split("/")[-1], {})


def _success_content(operation: dict) -> dict:
    """Return the JSON content of an operation's success response.

    Looking only at ``"200"`` would miss the routes that create something and
    correctly answer ``201``, and report them as having no response model.
    """
    responses = operation.get("responses", {})
    for status in sorted(responses):
        if status.isdigit() and 200 <= int(status) < 300:
            return responses[status].get("content", {}).get("application/json", {})
    return {}


def _data_schema(schemas: dict, operation: dict) -> dict:
    """Return the schema of the ``data`` block of a success response, if any."""
    content = _success_content(operation)
    envelope_schema = _resolve(schemas, content.get("schema", {}).get("$ref", ""))
    data = envelope_schema.get("properties", {}).get("data", {})
    for option in data.get("anyOf", []) + data.get("allOf", []):
        if "$ref" in option:
            return _resolve(schemas, option["$ref"])
    if "$ref" in data:
        return _resolve(schemas, data["$ref"])
    return {}


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------
class TestResponseEnvelope:
    def test_every_json_endpoint_returns_the_envelope(self, spec, schemas):
        """One response shape, or a front end needs one handler per endpoint."""
        offenders = []
        for path, operations in spec["paths"].items():
            for method, operation in operations.items():
                content = _success_content(operation)
                ref = content.get("schema", {}).get("$ref", "")
                if not ref:
                    # A download route returns the file itself, deliberately -
                    # a browser cannot stream a base64 blob out of an envelope.
                    # Those are covered by TestFileAndExportMetadata instead.
                    continue
                model = _resolve(schemas, ref)
                if set(model.get("properties", {})) != {"success", "data", "error", "meta"}:
                    offenders.append(f"{method.upper()} {path} -> {ref.split('/')[-1]}")
        assert offenders == [], f"endpoints not using the shared envelope: {offenders}"

    def test_the_only_routes_outside_the_envelope_are_downloads(self, spec):
        """Every exception to the rule has to be a file, and be named here.

        A route that quietly stops declaring a response model looks exactly like
        a download to the check above, so the exceptions are enumerated.
        """
        untyped = []
        for path, operations in spec["paths"].items():
            for method, operation in operations.items():
                if _success_content(operation).get("schema", {}).get("$ref"):
                    continue
                untyped.append(path)
        expected = {
            "/",  # the API index: a plain document, not a data resource
            *(path for path in untyped if path.endswith(("/export", "/sample"))),
        }
        assert set(untyped) == expected, (
            f"a route stopped declaring a response model: {sorted(set(untyped) - expected)}"
        )

    def test_the_four_error_shapes_are_identical(self, client):
        """A 404, a 405, a validation error and a domain error look the same.

        These four arrive from four different layers - Starlette's router,
        FastAPI's validator, the application's own exceptions - and a client
        that special-cases one of them has a bug waiting for the others.
        """
        responses = {
            "unknown route": client.get(f"{V1}/no-such-endpoint"),
            "wrong method": client.post(f"{V1}/health"),
            "invalid body": client.post(f"{V1}/po-risk/analyze", json={}),
            "missing resource": client.get(f"{V1}/po-risk/analyses/does-not-exist"),
        }
        for label, response in responses.items():
            assert response.status_code >= 400, f"{label} unexpectedly succeeded"
            body = envelope(response, expected_status=response.status_code)
            assert body["success"] is False, label
            assert set(body["error"]) == {"code", "message", "details"}, label
            assert body["meta"]["timestamp"], f"{label} has no timestamp"
            assert body["meta"]["request_id"], f"{label} has no request id"

    def test_the_request_id_in_the_body_matches_the_header(self, client):
        """The id a user reads off a response has to be the one in the log."""
        response = client.get(f"{V1}/health")
        body = envelope(response)
        assert body["meta"]["request_id"] == response.headers["X-Request-ID"]

    def test_a_successful_response_carries_a_request_id_too(self, client):
        """The response nobody captured a header for is the one that succeeded."""
        assert ok(client.get(f"{V1}/health"))
        body = envelope(client.get(f"{V1}/health"))
        assert body["meta"]["request_id"], "successes must be correlatable to a log line"

    def test_an_error_never_leaks_an_internal_detail(self, client):
        """A safe message: no paths, no stack traces, no provider payloads."""
        error = failure(client.get(f"{V1}/po-risk/analyses/../../etc/passwd"), expected_status=404)
        rendered = json.dumps(error)
        for leak in ("Traceback", "/home/", "/app/", "site-packages", "sqlalchemy"):
            assert leak not in rendered, f"the error response leaked {leak!r}"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
class TestPagination:
    def test_every_paged_endpoint_echoes_its_window(self, spec, schemas):
        """``total`` alone cannot tell 100-of-137 from all-of-100."""
        offenders = []
        for path, operations in spec["paths"].items():
            for method, operation in operations.items():
                names = {p["name"] for p in operation.get("parameters", [])}
                if not {"limit", "offset"} & names:
                    continue
                properties = set(_data_schema(schemas, operation).get("properties", {}))
                missing = {"total", "limit", "offset"} - properties
                if missing:
                    offenders.append(f"{method.upper()} {path} is missing {sorted(missing)}")
        assert offenders == [], f"paged endpoints with an incomplete window: {offenders}"

    def test_limit_and_offset_are_bounded_everywhere(self, spec):
        """An unbounded limit is a way to ask one request for the whole table."""
        offenders = []
        for path, operations in spec["paths"].items():
            for method, operation in operations.items():
                for parameter in operation.get("parameters", []):
                    schema = parameter.get("schema", {})
                    if parameter["name"] == "limit":
                        if schema.get("maximum") is None or schema.get("minimum") is None:
                            offenders.append(f"{method.upper()} {path} limit={schema}")
                    if parameter["name"] == "offset" and schema.get("minimum") is None:
                        offenders.append(f"{method.upper()} {path} offset={schema}")
        assert offenders == [], f"unbounded paging parameters: {offenders}"

    def test_paging_actually_pages(self, client):
        """Offset must move the window, not return the same rows again."""
        listed = ok(client.get(f"{V1}/interviews/questions", params={"limit": 5, "offset": 0}))
        if listed["total"] < 10:
            pytest.skip("the bundled question bank is too small to page")
        second = ok(client.get(f"{V1}/interviews/questions", params={"limit": 5, "offset": 5}))
        first_ids = {row["question_id"] for row in listed["questions"]}
        assert not first_ids & {row["question_id"] for row in second["questions"]}


# ---------------------------------------------------------------------------
# Shared vocabularies
# ---------------------------------------------------------------------------
class TestSharedVocabularies:
    def test_output_origin_has_one_definition(self, schemas):
        """Every module labels where its output came from from one list."""
        assert set(schemas["OutputOrigin"]["enum"]) == {item.value for item in OutputOrigin}
        # No module may declare its own copy under a namespaced name.
        duplicates = [name for name in schemas if name.endswith("OutputOrigin") and name != "OutputOrigin"]
        assert duplicates == [], f"duplicate OutputOrigin definitions: {duplicates}"

    def test_the_two_severity_scales_stay_separate(self, schemas):
        """A data-quality note must not be colourable as a critical risk.

        ``Severity`` describes a finding about the data; ``IssueSeverity``
        describes a message about the processing. Merging them means a UI prints
        "three rows had no delivery date" in the same red as a fraud finding.
        """
        assert set(schemas["Severity"]["enum"]) == {item.value for item in Severity}
        assert set(schemas["IssueSeverity"]["enum"]) == {item.value for item in IssueSeverity}
        assert not set(schemas["Severity"]["enum"]) & set(schemas["IssueSeverity"]["enum"]) - {
            "high"
        }, "the two scales must not be confusable"

    def test_analysis_status_has_one_definition(self, schemas):
        assert set(schemas["AnalysisStatus"]["enum"]) == {item.value for item in AnalysisStatus}

    def test_every_analysis_run_reports_a_shared_status(self, schemas):
        """Six modules run an analysis; the state names must not be six lists."""
        run_schemas = [
            "AnalysisDetailSchema",           # module 1
            "SpendAnalysisDetailSchema",      # module 2
            "RecommendationDetailSchema",     # module 3
            "ValidationDetailSchema",         # module 4
            "RiskAssessmentDetailSchema",     # module 5
            "ForecastDetailSchema",           # module 7
        ]
        for name in run_schemas:
            status = schemas[name]["properties"]["status"]
            reference = status.get("$ref") or "".join(
                option.get("$ref", "") for option in status.get("allOf", [])
            )
            assert reference.endswith("AnalysisStatus"), (
                f"{name}.status is {status}, not the shared AnalysisStatus"
            )

    def test_data_quality_issues_have_one_shape(self, schemas):
        """One component, one field name, in all six modules that report them."""
        duplicates = [
            name
            for name in schemas
            if name.endswith("DataQualityIssueSchema") and name != "DataQualityIssueSchema"
        ]
        assert duplicates == [], f"per-module copies of the issue schema: {duplicates}"
        properties = schemas["DataQualityIssueSchema"]["properties"]
        assert "field" in properties, "the wire name is 'field', not 'field_name'"

    def test_every_confidence_score_is_bounded(self, schemas):
        """0.0-1.0 is a contract a UI draws a bar from, not a convention."""
        offenders = []
        for name, model in schemas.items():
            for field, definition in model.get("properties", {}).items():
                if field not in {"confidence", "confidence_score"}:
                    continue
                if definition.get("minimum") != 0.0 or definition.get("maximum") != 1.0:
                    offenders.append(f"{name}.{field}")
        assert offenders == [], f"unbounded confidence fields: {offenders}"


# ---------------------------------------------------------------------------
# File and export metadata
# ---------------------------------------------------------------------------
class TestFileAndExportMetadata:
    def test_every_upload_response_identifies_the_stored_file(self, schemas):
        """A website needs the same four facts back from every upload."""
        upload_schemas = [
            name for name in schemas if name.endswith("UploadResponse")
        ]
        assert len(upload_schemas) >= 6
        for name in upload_schemas:
            properties = set(schemas[name]["properties"])
            assert "upload_id" in properties, f"{name} has no upload_id"
            assert properties & {"original_filename", "filename"}, f"{name} has no filename"
            assert properties & {"size_bytes"}, f"{name} does not report a size"

    @pytest.mark.parametrize(
        ("path_template", "formats"),
        [
            ("/po-risk/analyses/{id}/export", ("xlsx", "csv", "json")),
            ("/spend/analyses/{id}/export", ("xlsx", "csv", "json")),
        ],
    )
    def test_every_export_names_the_file_it_returns(
        self, client, path_template, formats, po_analysis_id, spend_analysis_id
    ):
        """A download with no filename saves as the endpoint name in a browser."""
        analysis_id = po_analysis_id if path_template.startswith("/po-risk") else spend_analysis_id
        for export_format in formats:
            response = client.get(
                f"{V1}{path_template.format(id=analysis_id)}", params={"format": export_format}
            )
            assert response.status_code == 200, response.text
            disposition = response.headers["content-disposition"]
            assert "attachment" in disposition
            assert f".{export_format}" in disposition
            assert response.content

    def test_an_export_in_an_unknown_format_is_a_clean_rejection(
        self, client, po_analysis_id
    ):
        """Not a 500, and not a silent fallback to some default format."""
        response = client.get(
            f"{V1}/po-risk/analyses/{po_analysis_id}/export", params={"format": "docx"}
        )
        failure(response, expected_status=422)


# ---------------------------------------------------------------------------
# Fixtures shared by the export checks
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def po_analysis_id(client) -> str:
    """One PO analysis, reused by the export checks."""
    from tests.e2e.conftest import CSV_MIME, upload

    from app.core.config import PROJECT_ROOT

    path = PROJECT_ROOT / "data" / "sample" / "sample_purchase_orders.csv"
    if not path.is_file():
        pytest.skip("the demo purchase order dataset is not generated")
    uploaded = upload(
        client, path, f"{V1}/po-risk/upload", filename=path.name, mime=CSV_MIME
    )
    analysis = ok(
        client.post(
            f"{V1}/po-risk/analyze",
            json={"upload_id": uploaded["upload_id"], "generate_ai_summary": False},
        )
    )
    return analysis["analysis_id"]


@pytest.fixture(scope="module")
def spend_analysis_id(client) -> str:
    """One spend analysis, reused by the export checks."""
    from tests.e2e.conftest import CSV_MIME, upload

    from app.core.config import PROJECT_ROOT

    path = PROJECT_ROOT / "data" / "sample" / "sample_spend_transactions.csv"
    if not path.is_file():
        pytest.skip("the demo spend dataset is not generated")
    uploaded = upload(
        client, path, f"{V1}/spend/upload", filename=path.name, mime=CSV_MIME
    )
    analysis = ok(
        client.post(
            f"{V1}/spend/analyze",
            json={"upload_id": uploaded["upload_id"], "generate_ai_summary": False},
        )
    )
    return analysis["analysis_id"]
