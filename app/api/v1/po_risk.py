"""HTTP routes for the Purchase Order Risk Checker.

Routes are intentionally thin: they validate input, call the service layer and
wrap the result in the shared response envelope. All business logic lives in
``app/modules/po_risk``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.openapi import COMMON_ERROR_RESPONSES
from app.core.config import settings
from app.core.exceptions import FileValidationError
from app.core.logging import get_logger
from app.models.session import get_db
from app.modules.po_risk import service
from app.schemas.common import ApiResponse
from app.schemas.po_risk import (
    AnalysisDetailSchema,
    AnalysisListResponse,
    AnalyzeRequest,
    ExportFormat,
    FieldDefinitionSchema,
    FindingListResponse,
    RuleInfoSchema,
    SampleDataInfo,
    UploadResponse,
)
from app.services.ai.factory import describe_active_provider
from app.services.files.uploads import read_upload_within_limit

logger = get_logger(__name__)

router = APIRouter(
    prefix="/po-risk",
    tags=["Purchase Order Risk Checker"],
    # The error shapes every route in this module can return, documented
    # once so a generated client writes its error handling against the
    # contract rather than against whatever it happened to hit first.
    responses=COMMON_ERROR_RESPONSES,
)

DbSession = Annotated[Session, Depends(get_db)]


@router.post("/upload", response_model=ApiResponse[UploadResponse], summary="Upload a PO file")
async def upload_file(
    db: DbSession,
    file: Annotated[UploadFile, File(description="CSV, XLSX or JSON purchase order export")],
) -> ApiResponse[UploadResponse]:
    """Validate a purchase order file, store it and suggest a column mapping."""
    content = await read_upload_within_limit(file)
    result = service.handle_upload(db, file.filename or "upload", content)
    return ApiResponse.ok(result)


@router.post("/analyze", response_model=ApiResponse[AnalysisDetailSchema], summary="Run the risk analysis")
def analyze(db: DbSession, request: AnalyzeRequest) -> ApiResponse[AnalysisDetailSchema]:
    """Run every enabled deterministic rule against a previously uploaded file."""
    result = service.run_analysis(db, request)
    return ApiResponse.ok(result)


@router.get("/analyses", response_model=ApiResponse[AnalysisListResponse], summary="List analyses")
def list_analyses(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[AnalysisListResponse]:
    """Return previous analyses, newest first."""
    total, analyses = service.list_analyses(db, limit=limit, offset=offset)
    return ApiResponse.ok(
        AnalysisListResponse(total=total, limit=limit, offset=offset, analyses=analyses)
    )


@router.get(
    "/analyses/{analysis_id}",
    response_model=ApiResponse[AnalysisDetailSchema],
    summary="Get one analysis",
)
def get_analysis(db: DbSession, analysis_id: str) -> ApiResponse[AnalysisDetailSchema]:
    """Return KPIs, supplier risk, data quality issues and the AI narrative."""
    return ApiResponse.ok(service.get_analysis(db, analysis_id))


@router.get(
    "/analyses/{analysis_id}/findings",
    response_model=ApiResponse[FindingListResponse],
    summary="List findings",
)
def list_findings(
    db: DbSession,
    analysis_id: str,
    severity: Annotated[list[str] | None, Query(description="low|medium|high|critical")] = None,
    rule_id: Annotated[str | None, Query(max_length=20)] = None,
    risk_category: Annotated[str | None, Query(max_length=60)] = None,
    supplier_id: Annotated[str | None, Query(max_length=20)] = None,
    po_number: Annotated[str | None, Query(max_length=20)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[FindingListResponse]:
    """Return a filtered, paginated list of findings."""
    total, findings = service.list_findings(
        db,
        analysis_id,
        severity=severity,
        rule_id=rule_id,
        risk_category=risk_category,
        supplier_id=supplier_id,
        po_number=po_number,
        limit=limit,
        offset=offset,
    )
    return ApiResponse.ok(
        FindingListResponse(
            analysis_id=analysis_id, total=total, limit=limit, offset=offset, findings=findings
        )
    )


@router.get("/analyses/{analysis_id}/export", summary="Download a report")
def export_analysis(
    db: DbSession,
    analysis_id: str,
    export_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.XLSX,
) -> Response:
    """Download the analysis as XLSX, CSV or JSON.

    This route returns the file itself rather than the JSON envelope, so a
    browser or ``fetch`` call can stream it straight to a download.
    """
    content, filename, media_type = service.export_analysis(db, analysis_id, export_format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/rules", response_model=ApiResponse[list[RuleInfoSchema]], summary="Rule catalogue")
def get_rules() -> ApiResponse[list[RuleInfoSchema]]:
    """Return every configured rule with its thresholds."""
    return ApiResponse.ok(service.get_rule_catalogue())


@router.get(
    "/fields", response_model=ApiResponse[list[FieldDefinitionSchema]], summary="Field catalogue"
)
def get_fields() -> ApiResponse[list[FieldDefinitionSchema]]:
    """Return the canonical fields and the SAP column names that map to them."""
    return ApiResponse.ok(service.get_field_catalogue())


@router.get("/sample", summary="Download the demo dataset")
def download_sample(
    file_format: Annotated[str, Query(alias="format", pattern="^(csv|xlsx|json)$")] = "csv",
) -> Response:
    """Download the bundled fictional sample purchase order file."""
    from app.core.security import resolve_safe_path

    path = resolve_safe_path(settings.sample_dir, f"sample_purchase_orders.{file_format}")
    if not path.is_file():
        raise FileValidationError(
            "The sample dataset has not been generated yet. "
            "Run: python scripts/generate_sample_data.py",
        )
    media_types = {
        "csv": "text/csv",
        "json": "application/json",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    return Response(
        content=path.read_bytes(),
        media_type=media_types[file_format],
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get("/sample/info", response_model=ApiResponse[SampleDataInfo], summary="Demo dataset info")
def sample_info() -> ApiResponse[SampleDataInfo]:
    """Describe the bundled demo dataset, including its anomaly manifest size."""
    import csv as csv_module

    sample_path = settings.sample_dir / "sample_purchase_orders.csv"
    manifest_path = settings.sample_dir / "anomaly_manifest.csv"

    if not sample_path.is_file():
        return ApiResponse.ok(
            SampleDataInfo(available=False, filename=None, row_count=None, anomaly_count=None)
        )

    with sample_path.open(encoding="utf-8") as handle:
        row_count = sum(1 for _ in csv_module.reader(handle)) - 1
    anomaly_count = None
    if manifest_path.is_file():
        with manifest_path.open(encoding="utf-8") as handle:
            anomaly_count = sum(1 for _ in csv_module.reader(handle)) - 1

    return ApiResponse.ok(
        SampleDataInfo(
            available=True,
            filename=sample_path.name,
            row_count=row_count,
            anomaly_count=anomaly_count,
        )
    )


@router.get("/ai-status", response_model=ApiResponse[dict[str, Any]], summary="Active AI provider")
def ai_status() -> ApiResponse[dict[str, Any]]:
    """Report which AI provider is active. API keys are never included."""
    return ApiResponse.ok(describe_active_provider())
