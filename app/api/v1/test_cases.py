"""HTTP routes for the SAP Test Case Generator.

Routes stay thin: validate input, call the service layer, wrap the result in the
shared envelope. All business logic lives in
``app/modules/test_case_generator``.

The six routes the module is specified around:

* ``POST   /test-cases/generate``                  - generate a suite
* ``GET    /test-cases/suites/{suite_id}``         - the suite with its cases
* ``PUT    /test-cases/{test_case_id}``            - edit one test case
* ``DELETE /test-cases/{test_case_id}``            - delete one test case
* ``POST   /test-cases/{test_case_id}/regenerate`` - redraft one test case
* ``GET    /test-cases/suites/{suite_id}/export``  - download the suite

plus the endpoints an editable, executable suite needs: add a row, duplicate a
row, approve a test, record an execution result, list suites, read one case, and
the catalogue that lets a client render the form and the table.

Route order matters here: the static paths (``/catalog``, ``/ai-status``,
``/sample``, ``/suites``) are declared before ``/{test_case_id}``, otherwise
FastAPI would match "catalog" as a test case id.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.openapi import COMMON_ERROR_RESPONSES
from app.core.logging import get_logger
from app.models.session import get_db
from app.modules.test_case_generator import service
from app.schemas.common import ApiResponse
from app.schemas.test_case_generator import (
    ApproveTestCaseRequest,
    CreateTestCaseRequest,
    DeleteTestCaseResponse,
    ExportFormat,
    GenerateTestCasesRequest,
    RecordExecutionRequest,
    RegenerateTestCaseRequest,
    SuiteListResponse,
    TestCaseCatalogueSchema,
    TestCaseSampleInfo,
    TestCaseSchema,
    TestSuiteSchema,
    UpdateTestCaseRequest,
)
from app.services.ai.factory import describe_active_provider
from app.services.exports.test_case_report_builder import (
    build_test_case_csv_report,
    build_test_case_json_report,
    build_test_case_pdf_report,
    build_test_case_xlsx_report,
)

logger = get_logger(__name__)

DbSession = Annotated[Session, Depends(get_db)]

EXPORT_MEDIA_TYPES = {
    ExportFormat.CSV: "text/csv",
    ExportFormat.JSON: "application/json",
    ExportFormat.PDF: "application/pdf",
    ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

router = APIRouter(
    prefix="/test-cases",
    tags=["SAP Test Case Generator"],
    # The error shapes every route in this module can return, documented
    # once so a generated client writes its error handling against the
    # contract rather than against whatever it happened to hit first.
    responses=COMMON_ERROR_RESPONSES,
)


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


@router.post(
    "/generate",
    response_model=ApiResponse[TestSuiteSchema],
    summary="Generate a suite of SAP test cases",
)
def generate(
    db: DbSession, request: GenerateTestCasesRequest
) -> ApiResponse[TestSuiteSchema]:
    """Generate a test suite from a business process description.

    The identifiers, the type allocation and the priorities are computed by
    deterministic Python before any provider is called. If the provider is
    unavailable, or ``use_ai`` is false, the configured templates fill every
    case - the suite is complete either way, and each case says which produced
    it.
    """
    return ApiResponse.ok(service.generate(db, request))


# ---------------------------------------------------------------------------
# Catalogue and samples (declared before /{test_case_id})
# ---------------------------------------------------------------------------


@router.get(
    "/catalog",
    response_model=ApiResponse[TestCaseCatalogueSchema],
    summary="Test types, limits and the deterministic rules",
)
def catalog() -> ApiResponse[TestCaseCatalogueSchema]:
    """Return the supported test types and how the generator makes its decisions."""
    return ApiResponse.ok(service.get_catalogue())


@router.get(
    "/ai-status", response_model=ApiResponse[dict[str, Any]], summary="Active AI provider"
)
def ai_status() -> ApiResponse[dict[str, Any]]:
    """Report which AI provider is active. API keys are never included."""
    return ApiResponse.ok(describe_active_provider())


@router.get(
    "/sample/info",
    response_model=ApiResponse[TestCaseSampleInfo],
    summary="Demo process definitions",
)
def sample_info() -> ApiResponse[TestCaseSampleInfo]:
    """Describe the bundled fictional SAP process definitions."""
    return ApiResponse.ok(service.sample_info())


@router.get(
    "/sample",
    response_model=ApiResponse[dict[str, Any]],
    summary="Load one demo process definition",
)
def sample(
    name: Annotated[str, Query(max_length=80, description="Demo process name")],
) -> ApiResponse[dict[str, Any]]:
    """Return one fictional process definition, ready to post to ``/generate``."""
    return ApiResponse.ok(service.load_sample_process(name))


# ---------------------------------------------------------------------------
# Suites
# ---------------------------------------------------------------------------


@router.get(
    "/suites",
    response_model=ApiResponse[SuiteListResponse],
    summary="List generated suites",
)
def list_suites(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[SuiteListResponse]:
    """Return generated suites, newest first."""
    total, suites = service.list_suites(db, limit=limit, offset=offset)
    return ApiResponse.ok(
        SuiteListResponse(total=total, limit=limit, offset=offset, suites=suites)
    )


@router.get(
    "/suites/{suite_id}",
    response_model=ApiResponse[TestSuiteSchema],
    summary="Get one suite with its test cases",
)
def get_suite(db: DbSession, suite_id: str) -> ApiResponse[TestSuiteSchema]:
    """Return the suite, its coverage, its summary and every test case."""
    return ApiResponse.ok(service.get_suite(db, suite_id))


@router.post(
    "/suites/{suite_id}/test-cases",
    response_model=ApiResponse[TestCaseSchema],
    status_code=201,
    summary="Add a test case to a suite",
)
def add_test_case(
    db: DbSession, suite_id: str, request: CreateTestCaseRequest
) -> ApiResponse[TestCaseSchema]:
    """Add one test case by hand. It receives the next free identifier of its type."""
    return ApiResponse.ok(service.add_test_case(db, suite_id, request))


@router.get("/suites/{suite_id}/export", summary="Download the test suite")
def export_suite(
    db: DbSession,
    suite_id: str,
    file_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.XLSX,
) -> Response:
    """Download the suite as XLSX, CSV, JSON or PDF."""
    payload = service.build_export_payload(db, suite_id)

    if file_format is ExportFormat.JSON:
        content = build_test_case_json_report(payload)
    elif file_format is ExportFormat.CSV:
        content = build_test_case_csv_report(payload.get("test_cases", []))
    elif file_format is ExportFormat.PDF:
        content = build_test_case_pdf_report(payload)
    else:
        content = build_test_case_xlsx_report(payload)

    filename = f"test_suite_{suite_id[:8]}.{file_format.value}"
    return Response(
        content=content,
        media_type=EXPORT_MEDIA_TYPES[file_format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# One test case
# ---------------------------------------------------------------------------


@router.get(
    "/{test_case_id}",
    response_model=ApiResponse[TestCaseSchema],
    summary="Get one test case",
)
def get_test_case(db: DbSession, test_case_id: str) -> ApiResponse[TestCaseSchema]:
    """Return one test case by its id, or by its identifier when that is unique."""
    return ApiResponse.ok(service.get_test_case(db, test_case_id))


@router.put(
    "/{test_case_id}",
    response_model=ApiResponse[TestCaseSchema],
    summary="Edit one test case",
)
def update_test_case(
    db: DbSession, test_case_id: str, request: UpdateTestCaseRequest
) -> ApiResponse[TestCaseSchema]:
    """Apply a partial edit. Only the fields present in the body are changed.

    Editing the script (type, title, objective, preconditions, test data, steps
    or expected result) clears any approval and returns the case to draft, just
    as regenerating does - the approval described the script that was replaced.
    Editing only the administrative fields leaves the approval in place.
    """
    return ApiResponse.ok(service.update_test_case(db, test_case_id, request))


@router.delete(
    "/{test_case_id}",
    response_model=ApiResponse[DeleteTestCaseResponse],
    summary="Delete one test case",
)
def delete_test_case(
    db: DbSession, test_case_id: str
) -> ApiResponse[DeleteTestCaseResponse]:
    """Delete one test case and report the coverage the suite lost."""
    return ApiResponse.ok(service.delete_test_case(db, test_case_id))


@router.post(
    "/{test_case_id}/regenerate",
    response_model=ApiResponse[TestCaseSchema],
    summary="Redraft one test case",
)
def regenerate_test_case(
    db: DbSession, test_case_id: str, request: RegenerateTestCaseRequest | None = None
) -> ApiResponse[TestCaseSchema]:
    """Redraft the script of one test case, keeping its place in the suite.

    The approval is cleared, because it belonged to the script that was
    replaced. The execution record is kept unless the request says otherwise.
    """
    return ApiResponse.ok(
        service.regenerate_test_case(db, test_case_id, request or RegenerateTestCaseRequest())
    )


@router.post(
    "/{test_case_id}/duplicate",
    response_model=ApiResponse[TestCaseSchema],
    status_code=201,
    summary="Duplicate one test case",
)
def duplicate_test_case(db: DbSession, test_case_id: str) -> ApiResponse[TestCaseSchema]:
    """Copy a test case's script into a new row with its own identifier."""
    return ApiResponse.ok(service.duplicate_test_case(db, test_case_id))


@router.post(
    "/{test_case_id}/approve",
    response_model=ApiResponse[TestCaseSchema],
    summary="Approve or un-approve one test case",
)
def approve_test_case(
    db: DbSession, test_case_id: str, request: ApproveTestCaseRequest
) -> ApiResponse[TestCaseSchema]:
    """Record a review decision against one test case."""
    return ApiResponse.ok(service.approve_test_case(db, test_case_id, request))


@router.post(
    "/{test_case_id}/execution",
    response_model=ApiResponse[TestCaseSchema],
    summary="Record an execution result",
)
def record_execution(
    db: DbSession, test_case_id: str, request: RecordExecutionRequest
) -> ApiResponse[TestCaseSchema]:
    """Record what happened when the test was run. The script is never changed."""
    return ApiResponse.ok(service.record_execution(db, test_case_id, request))
