"""HTTP routes for the Supplier Risk Copilot.

Routes stay thin: validate input, call the service layer, wrap the result in
the shared envelope. All business logic lives in ``app/modules/supplier_risk``.

The four routes the module is specified around are:

* ``GET  /supplier-risk/suppliers``              - assessed suppliers
* ``GET  /supplier-risk/suppliers/{supplier_id}`` - one full risk profile
* ``POST /supplier-risk/calculate``              - run the risk model
* ``POST /supplier-risk/chat``                   - ask the copilot a question
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.openapi import COMMON_ERROR_RESPONSES
from app.core.config import settings
from app.core.exceptions import FileValidationError
from app.core.logging import get_logger
from app.models.session import get_db
from app.modules.supplier_risk import service
from app.schemas.common import ApiResponse
from app.schemas.supplier_risk import (
    CalculateRiskRequest,
    ChatRequest,
    ChatResponse,
    RiskAssessmentDetailSchema,
    RiskAssessmentListResponse,
    RiskDatasetKind,
    RiskScoringInfoSchema,
    SupplierRiskDatasetListResponse,
    SupplierRiskFieldDefinitionSchema,
    SupplierRiskListResponse,
    SupplierRiskProfileSchema,
    SupplierRiskSampleDataInfo,
    SupplierRiskUploadResponse,
)
from app.services.ai.factory import describe_active_provider
from app.services.files.uploads import read_upload_within_limit

logger = get_logger(__name__)

DbSession = Annotated[Session, Depends(get_db)]

MEDIA_TYPES = {
    "csv": "text/csv",
    "json": "application/json",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

SAMPLE_STEMS = {
    RiskDatasetKind.PROFILES: "sample_supplier_risk_profiles",
    RiskDatasetKind.EVENTS: "sample_supplier_risk_events",
}

router = APIRouter(
    prefix="/supplier-risk",
    tags=["Supplier Risk Copilot"],
    # The error shapes every route in this module can return, documented
    # once so a generated client writes its error handling against the
    # contract rather than against whatever it happened to hit first.
    responses=COMMON_ERROR_RESPONSES,
)


# ---------------------------------------------------------------------------
# Upload and datasets
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=ApiResponse[SupplierRiskUploadResponse],
    summary="Upload supplier risk profiles or risk events",
)
async def upload(
    db: DbSession,
    file: Annotated[UploadFile, File(description="CSV, XLSX or JSON supplier risk data")],
    dataset: Annotated[RiskDatasetKind, Form()] = RiskDatasetKind.PROFILES,
    dataset_id: Annotated[str | None, Form()] = None,
) -> ApiResponse[SupplierRiskUploadResponse]:
    """Validate a supplier risk file, store it and load it.

    ``profiles`` starts a new dataset; ``events`` attaches the dated internal
    records that drive the risk trend and the copilot's citations.
    """
    content = await read_upload_within_limit(file)
    return ApiResponse.ok(
        service.handle_upload(db, file.filename or "upload", content, dataset, dataset_id)
    )


@router.get(
    "/datasets",
    response_model=ApiResponse[SupplierRiskDatasetListResponse],
    summary="List uploaded supplier risk datasets",
)
def list_datasets(db: DbSession) -> ApiResponse[SupplierRiskDatasetListResponse]:
    """Return every uploaded supplier risk dataset, newest first."""
    datasets = service.list_datasets(db)
    return ApiResponse.ok(
        SupplierRiskDatasetListResponse(total=len(datasets), datasets=datasets)
    )


@router.get(
    "/fields",
    response_model=ApiResponse[list[SupplierRiskFieldDefinitionSchema]],
    summary="Supplier risk field catalogue",
)
def get_fields() -> ApiResponse[list[SupplierRiskFieldDefinitionSchema]]:
    """Return the canonical risk fields and the column names that map to them."""
    return ApiResponse.ok(service.get_field_catalogue())


@router.get("/sample", summary="Download the demo supplier risk dataset")
def download_sample(
    dataset: Annotated[RiskDatasetKind, Query()] = RiskDatasetKind.PROFILES,
    file_format: Annotated[str, Query(alias="format", pattern="^(csv|xlsx|json)$")] = "csv",
) -> Response:
    """Download a bundled fictional supplier risk file."""
    from app.core.security import resolve_safe_path

    path = resolve_safe_path(settings.sample_dir, f"{SAMPLE_STEMS[dataset]}.{file_format}")
    if not path.is_file():
        raise FileValidationError(
            "The supplier risk sample dataset has not been generated yet. "
            "Run: python scripts/generate_supplier_risk_sample_data.py",
        )
    return Response(
        content=path.read_bytes(),
        media_type=MEDIA_TYPES[file_format],
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get(
    "/sample/info",
    response_model=ApiResponse[SupplierRiskSampleDataInfo],
    summary="Demo supplier risk dataset info",
)
def sample_info() -> ApiResponse[SupplierRiskSampleDataInfo]:
    """Describe the bundled demo supplier risk dataset and its manifest."""
    import csv as csv_module
    import json as json_module

    profiles_path = settings.sample_dir / "sample_supplier_risk_profiles.csv"
    events_path = settings.sample_dir / "sample_supplier_risk_events.csv"
    manifest_path = settings.sample_dir / "supplier_risk_scenario_manifest.json"

    if not profiles_path.is_file():
        return ApiResponse.ok(SupplierRiskSampleDataInfo(available=False))

    with profiles_path.open(encoding="utf-8") as handle:
        supplier_count = sum(1 for _ in csv_module.reader(handle)) - 1

    event_count = None
    if events_path.is_file():
        with events_path.open(encoding="utf-8") as handle:
            event_count = sum(1 for _ in csv_module.reader(handle)) - 1

    scenario_count = None
    as_of_date = None
    if manifest_path.is_file():
        manifest = json_module.loads(manifest_path.read_text(encoding="utf-8"))
        scenario_count = len(manifest.get("scenarios", []))
        as_of_date = manifest.get("as_of_date")

    return ApiResponse.ok(
        SupplierRiskSampleDataInfo(
            available=True,
            filename=profiles_path.name,
            event_filename=events_path.name if events_path.is_file() else None,
            supplier_count=supplier_count,
            event_count=event_count,
            scenario_count=scenario_count,
            as_of_date=as_of_date,
        )
    )


@router.get(
    "/scoring",
    response_model=ApiResponse[RiskScoringInfoSchema],
    summary="The documented risk scoring model",
)
def get_scoring() -> ApiResponse[RiskScoringInfoSchema]:
    """Return the categories, weights, metrics, bands and missing-data behaviour."""
    return ApiResponse.ok(service.get_scoring_info())


@router.get(
    "/ai-status", response_model=ApiResponse[dict[str, Any]], summary="Active AI provider"
)
def ai_status() -> ApiResponse[dict[str, Any]]:
    """Report which AI provider is active. API keys are never included."""
    return ApiResponse.ok(describe_active_provider())


# ---------------------------------------------------------------------------
# Calculate and assessments
# ---------------------------------------------------------------------------


@router.post(
    "/calculate",
    response_model=ApiResponse[RiskAssessmentDetailSchema],
    summary="Calculate supplier risk",
)
def calculate(
    db: DbSession, request: CalculateRiskRequest
) -> ApiResponse[RiskAssessmentDetailSchema]:
    """Score every supplier in a dataset across the ten risk categories."""
    return ApiResponse.ok(service.calculate(db, request))


@router.get(
    "/assessments",
    response_model=ApiResponse[RiskAssessmentListResponse],
    summary="List risk assessments",
)
def list_assessments(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[RiskAssessmentListResponse]:
    """Return previous risk assessments, newest first."""
    total, assessments = service.list_assessments(db, limit=limit, offset=offset)
    return ApiResponse.ok(
        RiskAssessmentListResponse(
            total=total, limit=limit, offset=offset, assessments=assessments
        )
    )


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ApiResponse[ChatResponse], summary="Ask the copilot")
def chat(db: DbSession, request: ChatRequest) -> ApiResponse[ChatResponse]:
    """Answer a question about the loaded supplier risk data, with citations.

    The answer is produced by deterministic rules over the computed assessment.
    When the information is not in the loaded records, the copilot says so.
    """
    return ApiResponse.ok(service.chat(db, request))


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------


@router.get(
    "/suppliers",
    response_model=ApiResponse[SupplierRiskListResponse],
    summary="List assessed suppliers",
)
def list_suppliers(
    db: DbSession,
    assessment_id: Annotated[str | None, Query(max_length=64)] = None,
    band: Annotated[str | None, Query(max_length=20)] = None,
    country: Annotated[str | None, Query(max_length=40)] = None,
    spend_category: Annotated[str | None, Query(max_length=80)] = None,
    expiring_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[SupplierRiskListResponse]:
    """Return assessed suppliers, highest risk first."""
    resolved_assessment, dataset_id, total, suppliers = service.list_suppliers(
        db,
        assessment_id=assessment_id,
        band=band,
        country=country,
        spend_category=spend_category,
        expiring_only=expiring_only,
        limit=limit,
        offset=offset,
    )
    return ApiResponse.ok(
        SupplierRiskListResponse(
            assessment_id=resolved_assessment,
            dataset_id=dataset_id,
            total=total,
            limit=limit,
            offset=offset,
            suppliers=suppliers,
        )
    )


@router.get(
    "/suppliers/{supplier_id}",
    response_model=ApiResponse[SupplierRiskProfileSchema],
    summary="Get one supplier risk profile",
)
def get_supplier(
    db: DbSession,
    supplier_id: str,
    assessment_id: Annotated[str | None, Query(max_length=64)] = None,
) -> ApiResponse[SupplierRiskProfileSchema]:
    """Return the full risk profile: category breakdown, trend, supporting
    records and recommended actions."""
    return ApiResponse.ok(service.get_supplier(db, supplier_id, assessment_id=assessment_id))


@router.get(
    "/assessments/{assessment_id}",
    response_model=ApiResponse[RiskAssessmentDetailSchema],
    summary="Get one risk assessment",
)
def get_assessment(
    db: DbSession, assessment_id: str
) -> ApiResponse[RiskAssessmentDetailSchema]:
    """Return one assessment with its ranked suppliers."""
    return ApiResponse.ok(service.get_assessment(db, assessment_id))
