"""HTTP routes for the Spend Analytics Dashboard.

Routes stay thin: validate input, call the service layer, wrap the result in
the shared envelope. All business logic lives in ``app/modules/spend``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import FileValidationError
from app.core.logging import get_logger
from app.models.session import get_db
from app.modules.spend import service
from app.modules.spend.analytics import BREAKDOWN_DIMENSIONS
from app.modules.spend.thresholds import get_spend_config
from app.schemas.common import ApiResponse
from app.schemas.spend import (
    ExportFormat,
    SavingsRuleInfoSchema,
    SpendAnalysisDetailSchema,
    SpendAnalysisListResponse,
    SpendAnalyzeRequest,
    SpendFieldDefinitionSchema,
    SpendOpportunityListResponse,
    SpendSampleDataInfo,
    SpendTransactionListResponse,
    SpendUploadResponse,
)
from app.services.files.uploads import read_upload_within_limit

logger = get_logger(__name__)

router = APIRouter(prefix="/spend", tags=["Spend Analytics Dashboard"])

DbSession = Annotated[Session, Depends(get_db)]

MEDIA_TYPES = {
    "csv": "text/csv",
    "json": "application/json",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.post("/upload", response_model=ApiResponse[SpendUploadResponse], summary="Upload spend data")
async def upload_file(
    db: DbSession,
    file: Annotated[UploadFile, File(description="CSV, XLSX or JSON procurement transactions")],
) -> ApiResponse[SpendUploadResponse]:
    """Validate a spend file, store it and suggest a column mapping."""
    content = await read_upload_within_limit(file)
    return ApiResponse.ok(service.handle_upload(db, file.filename or "upload", content))


@router.post(
    "/analyze",
    response_model=ApiResponse[SpendAnalysisDetailSchema],
    summary="Run the spend analysis",
)
def analyze(
    db: DbSession, request: SpendAnalyzeRequest
) -> ApiResponse[SpendAnalysisDetailSchema]:
    """Calculate metrics, breakdowns and savings opportunities for an upload."""
    return ApiResponse.ok(service.run_analysis(db, request))


@router.get(
    "/analyses", response_model=ApiResponse[SpendAnalysisListResponse], summary="List analyses"
)
def list_analyses(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[SpendAnalysisListResponse]:
    """Return previous spend analyses, newest first."""
    total, analyses = service.list_analyses(db, limit=limit, offset=offset)
    return ApiResponse.ok(
        SpendAnalysisListResponse(total=total, limit=limit, offset=offset, analyses=analyses)
    )


@router.get(
    "/analyses/{analysis_id}",
    response_model=ApiResponse[SpendAnalysisDetailSchema],
    summary="Get one analysis",
)
def get_analysis(db: DbSession, analysis_id: str) -> ApiResponse[SpendAnalysisDetailSchema]:
    """Return metrics, analytics breakdowns, opportunities and the narrative."""
    return ApiResponse.ok(service.get_analysis(db, analysis_id))


@router.get(
    "/analyses/{analysis_id}/transactions",
    response_model=ApiResponse[SpendTransactionListResponse],
    summary="Drill down into transactions",
)
def list_transactions(
    db: DbSession,
    analysis_id: str,
    dimension: Annotated[
        str | None,
        Query(description=f"One of: {', '.join(sorted(BREAKDOWN_DIMENSIONS))}"),
    ] = None,
    value: Annotated[str | None, Query(max_length=120)] = None,
    supplier_id: Annotated[str | None, Query(max_length=20)] = None,
    material: Annotated[str | None, Query(max_length=40)] = None,
    category: Annotated[str | None, Query(max_length=80)] = None,
    spend_month: Annotated[str | None, Query(max_length=7, pattern=r"^\d{4}-\d{2}$")] = None,
    contracted: Annotated[bool | None, Query()] = None,
    maverick: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[SpendTransactionListResponse]:
    """Return the transactions behind a summary figure.

    Send the ``dimension`` and ``value`` of the chart element the user clicked
    to get exactly the lines that produced it.
    """
    total, total_spend, transactions = service.list_transactions(
        db,
        analysis_id,
        dimension=dimension,
        value=value,
        supplier_id=supplier_id,
        material=material,
        category=category,
        spend_month=spend_month,
        contracted=contracted,
        maverick=maverick,
        limit=limit,
        offset=offset,
    )
    return ApiResponse.ok(
        SpendTransactionListResponse(
            analysis_id=analysis_id,
            total=total,
            limit=limit,
            offset=offset,
            total_spend_base=total_spend,
            transactions=transactions,
        )
    )


@router.get(
    "/analyses/{analysis_id}/opportunities",
    response_model=ApiResponse[SpendOpportunityListResponse],
    summary="List savings opportunities",
)
def list_opportunities(
    db: DbSession,
    analysis_id: str,
    rule_id: Annotated[str | None, Query(max_length=20)] = None,
    opportunity_type: Annotated[str | None, Query(max_length=60)] = None,
    min_saving: Annotated[float | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[SpendOpportunityListResponse]:
    """Return modelled savings opportunities.

    Every figure returned here is an estimate produced from the uploaded data
    under the documented assumptions, not a guaranteed saving.
    """
    config = get_spend_config()
    total, total_saving, opportunities = service.list_opportunities(
        db,
        analysis_id,
        rule_id=rule_id,
        opportunity_type=opportunity_type,
        min_saving=min_saving,
        limit=limit,
        offset=offset,
    )
    return ApiResponse.ok(
        SpendOpportunityListResponse(
            analysis_id=analysis_id,
            total=total,
            limit=limit,
            offset=offset,
            total_estimated_saving_base=total_saving,
            base_currency=config.base_currency,
            disclaimer=config.reporting.opportunity_disclaimer,
            opportunities=opportunities,
        )
    )


@router.get("/analyses/{analysis_id}/export", summary="Download a spend report")
def export_analysis(
    db: DbSession,
    analysis_id: str,
    export_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.XLSX,
) -> Response:
    """Download the analysis as XLSX, CSV or JSON."""
    content, filename, media_type = service.export_analysis(db, analysis_id, export_format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/fields",
    response_model=ApiResponse[list[SpendFieldDefinitionSchema]],
    summary="Field catalogue",
)
def get_fields() -> ApiResponse[list[SpendFieldDefinitionSchema]]:
    """Return the canonical fields and the column names that map to them."""
    return ApiResponse.ok(service.get_field_catalogue())


@router.get(
    "/savings-rules",
    response_model=ApiResponse[list[SavingsRuleInfoSchema]],
    summary="Savings rule catalogue",
)
def get_savings_rules() -> ApiResponse[list[SavingsRuleInfoSchema]]:
    """Return every savings rule with the assumptions it applies."""
    return ApiResponse.ok(service.get_savings_rule_catalogue())


@router.get(
    "/methodology",
    response_model=ApiResponse[dict[str, Any]],
    summary="Calculation methodology",
)
def get_methodology() -> ApiResponse[dict[str, Any]]:
    """Describe how every figure is calculated, including the disclaimers."""
    return ApiResponse.ok(service.get_methodology())


@router.get("/sample", summary="Download the demo dataset")
def download_sample(
    file_format: Annotated[str, Query(alias="format", pattern="^(csv|xlsx|json)$")] = "csv",
) -> Response:
    """Download the bundled fictional spend transaction file."""
    from app.core.security import resolve_safe_path

    path = resolve_safe_path(settings.sample_dir, f"sample_spend_transactions.{file_format}")
    if not path.is_file():
        raise FileValidationError(
            "The spend sample dataset has not been generated yet. "
            "Run: python scripts/generate_spend_sample_data.py",
        )
    return Response(
        content=path.read_bytes(),
        media_type=MEDIA_TYPES[file_format],
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get(
    "/sample/info", response_model=ApiResponse[SpendSampleDataInfo], summary="Demo dataset info"
)
def sample_info() -> ApiResponse[SpendSampleDataInfo]:
    """Describe the bundled demo dataset and its scenario manifest."""
    import csv as csv_module
    import json as json_module

    sample_path = settings.sample_dir / "sample_spend_transactions.csv"
    manifest_path = settings.sample_dir / "spend_scenario_manifest.json"

    if not sample_path.is_file():
        return ApiResponse.ok(SpendSampleDataInfo(available=False))

    with sample_path.open(encoding="utf-8") as handle:
        row_count = sum(1 for _ in csv_module.reader(handle)) - 1

    scenario_count = None
    months_covered = None
    if manifest_path.is_file():
        manifest = json_module.loads(manifest_path.read_text(encoding="utf-8"))
        scenario_count = len(manifest.get("scenarios", []))
        months_covered = manifest.get("months_covered")

    return ApiResponse.ok(
        SpendSampleDataInfo(
            available=True,
            filename=sample_path.name,
            row_count=row_count,
            scenario_count=scenario_count,
            months_covered=months_covered,
        )
    )
