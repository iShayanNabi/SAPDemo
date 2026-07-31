"""HTTP routes for the Inventory Predictor.

Routes stay thin: validate input, call the service layer, wrap the result in the
shared envelope. All business logic lives in ``app/modules/inventory``.

The four routes the module is specified around are:

* ``POST /inventory/upload``                     - load an inventory history
* ``POST /inventory/forecast``                   - forecast and plan
* ``GET  /inventory/forecasts/{forecast_id}``    - one forecast run
* ``GET  /inventory/forecasts/{forecast_id}/export`` - download the report

The material-level routes take the material and plant as **query** parameters
rather than path segments on purpose: a material number can legitimately contain
a slash, and a path segment cannot.
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
from app.modules.inventory import service
from app.schemas.common import ApiResponse
from app.schemas.inventory import (
    ExportFormat,
    ForecastDetailSchema,
    ForecastItemDetailSchema,
    ForecastItemListResponse,
    ForecastListResponse,
    ForecastRequest,
    InventoryDatasetListResponse,
    InventoryFieldDefinitionSchema,
    InventorySampleDataInfo,
    InventoryUploadResponse,
    ItemSort,
    MethodologySchema,
)
from app.services.ai.factory import describe_active_provider

logger = get_logger(__name__)

router = APIRouter(prefix="/inventory", tags=["Inventory Predictor"])

DbSession = Annotated[Session, Depends(get_db)]

MEDIA_TYPES = {
    "csv": "text/csv",
    "json": "application/json",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

SAMPLE_STEM = "sample_inventory_history"


# ---------------------------------------------------------------------------
# Upload and datasets
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=ApiResponse[InventoryUploadResponse],
    summary="Upload an inventory history",
)
async def upload(
    db: DbSession,
    file: Annotated[UploadFile, File(description="CSV, XLSX or JSON inventory history")],
) -> ApiResponse[InventoryUploadResponse]:
    """Validate an inventory history file, store it and load it into a dataset.

    The response describes every material/plant series the file contains, the
    period granularity that was inferred from the dates, and any data-quality
    problems found while loading.
    """
    content = await file.read()
    if not content:
        raise FileValidationError("The uploaded file is empty.")
    if len(content) > settings.max_upload_bytes:
        raise FileValidationError(
            f"The file exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit."
        )
    return ApiResponse.ok(service.handle_upload(db, file.filename or "upload", content))


@router.get(
    "/datasets",
    response_model=ApiResponse[InventoryDatasetListResponse],
    summary="List uploaded inventory datasets",
)
def list_datasets(db: DbSession) -> ApiResponse[InventoryDatasetListResponse]:
    """Return every uploaded inventory dataset, newest first."""
    datasets = service.list_datasets(db)
    return ApiResponse.ok(
        InventoryDatasetListResponse(total=len(datasets), datasets=datasets)
    )


@router.get(
    "/fields",
    response_model=ApiResponse[list[InventoryFieldDefinitionSchema]],
    summary="Inventory field catalogue",
)
def get_fields() -> ApiResponse[list[InventoryFieldDefinitionSchema]]:
    """Return the canonical inventory fields and the column names that map to them."""
    return ApiResponse.ok(service.get_field_catalogue())


@router.get(
    "/methods",
    response_model=ApiResponse[MethodologySchema],
    summary="The documented forecasting and planning method",
)
def get_methods() -> ApiResponse[MethodologySchema]:
    """Return every forecasting method with its assumptions, plus the model
    selection rules, the reorder policy formulae and the stock thresholds."""
    return ApiResponse.ok(service.get_methodology())


@router.get("/sample", summary="Download the demo inventory history")
def download_sample(
    file_format: Annotated[str, Query(alias="format", pattern="^(csv|xlsx|json)$")] = "csv",
) -> Response:
    """Download the bundled fictional inventory history."""
    from app.core.security import resolve_safe_path

    path = resolve_safe_path(settings.sample_dir, f"{SAMPLE_STEM}.{file_format}")
    if not path.is_file():
        raise FileValidationError(
            "The inventory sample dataset has not been generated yet. "
            "Run: python scripts/generate_inventory_sample_data.py",
        )
    return Response(
        content=path.read_bytes(),
        media_type=MEDIA_TYPES[file_format],
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get(
    "/sample/info",
    response_model=ApiResponse[InventorySampleDataInfo],
    summary="Demo inventory dataset info",
)
def sample_info() -> ApiResponse[InventorySampleDataInfo]:
    """Describe the bundled demo inventory dataset and its scenario manifest."""
    import csv as csv_module
    import json as json_module

    history_path = settings.sample_dir / f"{SAMPLE_STEM}.csv"
    manifest_path = settings.sample_dir / "inventory_scenario_manifest.json"

    if not history_path.is_file():
        return ApiResponse.ok(InventorySampleDataInfo(available=False))

    with history_path.open(encoding="utf-8") as handle:
        row_count = sum(1 for _ in csv_module.reader(handle)) - 1

    info = InventorySampleDataInfo(
        available=True, filename=history_path.name, row_count=row_count
    )
    if manifest_path.is_file():
        manifest = json_module.loads(manifest_path.read_text(encoding="utf-8"))
        info.scenario_count = len(manifest.get("scenarios", []))
        info.as_of_date = manifest.get("as_of_date")
        info.material_count = manifest.get("material_count")
        info.plant_count = manifest.get("plant_count")
        info.series_count = manifest.get("series_count")
        info.period_count = manifest.get("period_count")
        info.history_start = manifest.get("history_start")
        info.history_end = manifest.get("history_end")
    return ApiResponse.ok(info)


@router.get(
    "/ai-status", response_model=ApiResponse[dict[str, Any]], summary="Active AI provider"
)
def ai_status() -> ApiResponse[dict[str, Any]]:
    """Report which AI provider is active. API keys are never included."""
    return ApiResponse.ok(describe_active_provider())


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


@router.post(
    "/forecast",
    response_model=ApiResponse[ForecastDetailSchema],
    summary="Forecast demand and plan replenishment",
)
def create_forecast(db: DbSession, request: ForecastRequest) -> ApiResponse[ForecastDetailSchema]:
    """Forecast every material in a dataset and project its stock forward.

    For each material/plant the engine backtests the eligible statistical models,
    picks the winner, forecasts the horizon with a confidence range, projects the
    stock day by day, and derives the shortage date, the reorder date and
    quantity, the recommended safety stock and the stock classification.
    """
    return ApiResponse.ok(service.forecast(db, request))


@router.get(
    "/forecasts",
    response_model=ApiResponse[ForecastListResponse],
    summary="List forecast runs",
)
def list_forecasts(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[ForecastListResponse]:
    """Return previous forecast runs, newest first."""
    total, forecasts = service.list_forecasts(db, limit=limit, offset=offset)
    return ApiResponse.ok(
        ForecastListResponse(total=total, limit=limit, offset=offset, forecasts=forecasts)
    )


@router.get(
    "/forecasts/{forecast_id}",
    response_model=ApiResponse[ForecastDetailSchema],
    summary="Get one forecast run",
)
def get_forecast(
    db: DbSession,
    forecast_id: str,
    item_limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> ApiResponse[ForecastDetailSchema]:
    """Return the run's settings, portfolio summary, data-quality issues and materials."""
    return ApiResponse.ok(service.get_forecast(db, forecast_id, item_limit=item_limit))


@router.get(
    "/forecasts/{forecast_id}/items",
    response_model=ApiResponse[ForecastItemListResponse],
    summary="List materials in a forecast run",
)
def list_items(
    db: DbSession,
    forecast_id: str,
    material: Annotated[str | None, Query(max_length=40)] = None,
    plant: Annotated[str | None, Query(max_length=10)] = None,
    supplier_id: Annotated[str | None, Query(max_length=20)] = None,
    model: Annotated[str | None, Query(max_length=40)] = None,
    status: Annotated[str | None, Query(max_length=20)] = None,
    movement_class: Annotated[str | None, Query(max_length=20)] = None,
    shortage_only: Annotated[bool, Query()] = False,
    reorder_only: Annotated[bool, Query()] = False,
    overstock_only: Annotated[bool, Query()] = False,
    dead_stock_only: Annotated[bool, Query()] = False,
    sort: Annotated[ItemSort, Query()] = ItemSort.SHORTAGE,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[ForecastItemListResponse]:
    """Return a filtered, paginated list of materials, soonest shortage first."""
    resolved_id, total, items = service.list_items(
        db,
        forecast_id,
        material=material,
        plant=plant,
        supplier_id=supplier_id,
        model=model,
        status=status,
        movement_class=movement_class,
        shortage_only=shortage_only,
        reorder_only=reorder_only,
        overstock_only=overstock_only,
        dead_stock_only=dead_stock_only,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return ApiResponse.ok(
        ForecastItemListResponse(
            forecast_id=resolved_id, total=total, limit=limit, offset=offset, items=items
        )
    )


@router.get(
    "/forecasts/{forecast_id}/item",
    response_model=ApiResponse[ForecastItemDetailSchema],
    summary="Get one material's forecast",
)
def get_item(
    db: DbSession,
    forecast_id: str,
    material: Annotated[str, Query(max_length=40)],
    plant: Annotated[str, Query(max_length=10)],
    storage_location: Annotated[str | None, Query(max_length=20)] = None,
) -> ApiResponse[ForecastItemDetailSchema]:
    """Return the full result for one material: history, forecast with its
    confidence range, every model candidate and its backtest score, the projected
    stock path, the reorder rationale and the data-quality warnings."""
    return ApiResponse.ok(
        service.get_item(db, forecast_id, material, plant, storage_location)
    )


@router.get("/forecasts/{forecast_id}/export", summary="Download a forecast report")
def export_forecast(
    db: DbSession,
    forecast_id: str,
    export_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.XLSX,
) -> Response:
    """Download the forecast run as XLSX, CSV or JSON."""
    content, filename, media_type = service.export_forecast(db, forecast_id, export_format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
