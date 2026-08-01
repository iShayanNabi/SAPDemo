"""HTTP routes for the Supplier Recommendation Engine.

Two routers are exposed:

* ``/suppliers`` - the supplier catalogue (upload, list, detail, fields, sample).
* ``/supplier-recommendations`` - run and retrieve recommendations.

Routes stay thin: validate input, call the service layer, wrap the result in the
shared envelope. All business logic lives in ``app/modules/supplier_reco``.
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
from app.modules.supplier_reco import service
from app.schemas.common import ApiResponse
from app.schemas.supplier_reco import (
    ExportFormat,
    RecommendationDetailSchema,
    RecommendationListResponse,
    RecommendRequest,
    ScoringInfoSchema,
    SupplierCatalogListResponse,
    SupplierFieldDefinitionSchema,
    SupplierListResponse,
    SupplierSampleDataInfo,
    SupplierSchema,
    SupplierUploadResponse,
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

suppliers_router = APIRouter(
    prefix="/suppliers",
    tags=["Supplier Recommendation Engine"],
    responses=COMMON_ERROR_RESPONSES,
)
recommendations_router = APIRouter(
    prefix="/supplier-recommendations",
    tags=["Supplier Recommendation Engine"],
    responses=COMMON_ERROR_RESPONSES,
)


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------


@suppliers_router.post(
    "/upload",
    response_model=ApiResponse[SupplierUploadResponse],
    summary="Upload a supplier master file",
)
async def upload_suppliers(
    db: DbSession,
    file: Annotated[UploadFile, File(description="CSV, XLSX or JSON supplier master data")],
) -> ApiResponse[SupplierUploadResponse]:
    """Validate a supplier file, store it and load it into a catalogue."""
    content = await read_upload_within_limit(file)
    return ApiResponse.ok(service.handle_supplier_upload(db, file.filename or "upload", content))


@suppliers_router.get(
    "/fields",
    response_model=ApiResponse[list[SupplierFieldDefinitionSchema]],
    summary="Supplier field catalogue",
)
def get_supplier_fields() -> ApiResponse[list[SupplierFieldDefinitionSchema]]:
    """Return the canonical supplier fields and the column names that map to them."""
    return ApiResponse.ok(service.get_field_catalogue())


@suppliers_router.get(
    "/catalogs",
    response_model=ApiResponse[SupplierCatalogListResponse],
    summary="List supplier catalogues",
)
def list_catalogs(db: DbSession) -> ApiResponse[SupplierCatalogListResponse]:
    """Return every uploaded supplier catalogue, newest first."""
    catalogs = service.list_catalogs(db)
    return ApiResponse.ok(SupplierCatalogListResponse(total=len(catalogs), catalogs=catalogs))


@suppliers_router.get("/sample", summary="Download the demo supplier catalogue")
def download_sample(
    file_format: Annotated[str, Query(alias="format", pattern="^(csv|xlsx|json)$")] = "csv",
) -> Response:
    """Download the bundled fictional supplier master file."""
    from app.core.security import resolve_safe_path

    path = resolve_safe_path(settings.sample_dir, f"sample_suppliers.{file_format}")
    if not path.is_file():
        raise FileValidationError(
            "The supplier sample dataset has not been generated yet. "
            "Run: python scripts/generate_supplier_sample_data.py",
        )
    return Response(
        content=path.read_bytes(),
        media_type=MEDIA_TYPES[file_format],
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@suppliers_router.get(
    "/sample/info",
    response_model=ApiResponse[SupplierSampleDataInfo],
    summary="Demo supplier dataset info",
)
def sample_info() -> ApiResponse[SupplierSampleDataInfo]:
    """Describe the bundled demo supplier catalogue and its manifest."""
    import csv as csv_module
    import json as json_module

    sample_path = settings.sample_dir / "sample_suppliers.csv"
    manifest_path = settings.sample_dir / "supplier_scenario_manifest.json"

    if not sample_path.is_file():
        return ApiResponse.ok(SupplierSampleDataInfo(available=False))

    with sample_path.open(encoding="utf-8") as handle:
        supplier_count = sum(1 for _ in csv_module.reader(handle)) - 1

    scenario_count = None
    if manifest_path.is_file():
        manifest = json_module.loads(manifest_path.read_text(encoding="utf-8"))
        scenario_count = len(manifest.get("scenarios", []))

    return ApiResponse.ok(
        SupplierSampleDataInfo(
            available=True,
            filename=sample_path.name,
            supplier_count=supplier_count,
            scenario_count=scenario_count,
        )
    )


@suppliers_router.get(
    "", response_model=ApiResponse[SupplierListResponse], summary="List suppliers"
)
def list_suppliers(
    db: DbSession,
    catalog_id: Annotated[str | None, Query(max_length=64)] = None,
    material: Annotated[str | None, Query(max_length=40)] = None,
    region: Annotated[str | None, Query(max_length=80)] = None,
    plant: Annotated[str | None, Query(max_length=10)] = None,
    contract_status: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[SupplierListResponse]:
    """Return suppliers from a catalogue (the most recent one by default)."""
    resolved_catalog, total, suppliers = service.list_suppliers(
        db,
        catalog_id=catalog_id,
        material=material,
        region=region,
        plant=plant,
        contract_status=contract_status,
        limit=limit,
        offset=offset,
    )
    return ApiResponse.ok(
        SupplierListResponse(
            catalog_id=resolved_catalog,
            total=total,
            limit=limit,
            offset=offset,
            suppliers=suppliers,
        )
    )


@suppliers_router.get(
    "/{supplier_id}", response_model=ApiResponse[SupplierSchema], summary="Get one supplier"
)
def get_supplier(
    db: DbSession,
    supplier_id: str,
    catalog_id: Annotated[str | None, Query(max_length=64)] = None,
) -> ApiResponse[SupplierSchema]:
    """Return one supplier from a catalogue (the most recent one by default)."""
    return ApiResponse.ok(service.get_supplier(db, supplier_id, catalog_id=catalog_id))


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


@recommendations_router.post(
    "/recommend",
    response_model=ApiResponse[RecommendationDetailSchema],
    summary="Rank suppliers for a requirement",
)
def recommend(db: DbSession, request: RecommendRequest) -> ApiResponse[RecommendationDetailSchema]:
    """Apply eligibility filters, score every eligible supplier and rank them."""
    return ApiResponse.ok(service.recommend(db, request))


@recommendations_router.get(
    "",
    response_model=ApiResponse[RecommendationListResponse],
    summary="List recommendations",
)
def list_recommendations(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[RecommendationListResponse]:
    """Return previous recommendations, newest first."""
    total, recommendations = service.list_recommendations(db, limit=limit, offset=offset)
    return ApiResponse.ok(
        RecommendationListResponse(
            total=total, limit=limit, offset=offset, recommendations=recommendations
        )
    )


@recommendations_router.get(
    "/scoring", response_model=ApiResponse[ScoringInfoSchema], summary="Scoring model"
)
def get_scoring() -> ApiResponse[ScoringInfoSchema]:
    """Return the documented scoring model: weights, formulas and eligibility filters."""
    return ApiResponse.ok(service.get_scoring_info())


@recommendations_router.get(
    "/ai-status", response_model=ApiResponse[dict[str, Any]], summary="Active AI provider"
)
def ai_status() -> ApiResponse[dict[str, Any]]:
    """Report which AI provider is active. API keys are never included."""
    return ApiResponse.ok(describe_active_provider())


@recommendations_router.get(
    "/{recommendation_id}",
    response_model=ApiResponse[RecommendationDetailSchema],
    summary="Get one recommendation",
)
def get_recommendation(
    db: DbSession, recommendation_id: str
) -> ApiResponse[RecommendationDetailSchema]:
    """Return the ranked suppliers, scores, advantages, risks and narrative."""
    return ApiResponse.ok(service.get_recommendation(db, recommendation_id))


@recommendations_router.get(
    "/{recommendation_id}/export", summary="Download a recommendation report"
)
def export_recommendation(
    db: DbSession,
    recommendation_id: str,
    export_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.XLSX,
) -> Response:
    """Download the recommendation as XLSX, CSV or JSON."""
    content, filename, media_type = service.export_recommendation(
        db, recommendation_id, export_format
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
