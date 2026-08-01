"""Orchestration for the Inventory Predictor.

This is the only layer that knows about the database. It wires the shared
services together in one direction:

    validate upload -> read file -> suggest mapping -> normalise -> build series
    -> persist -> run the statistical engine -> persist -> optional AI narrative

The engine, the models and the projection stay pure, so they can be tested
without a database and reused unchanged by a future React front end talking to
the same API.

A dataset is stored once and can be forecast many times. Changing the horizon,
the confidence level or the model does not need the file again - which matters,
because a planner changes those three settings constantly and re-uploading a
warehouse extract to answer "what does 12 periods look like?" would be absurd.
"""

from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.inventory import (
    InventoryDatasetRow,
    InventoryForecast,
    InventoryForecastItem,
    InventoryRecord,
)
from app.models.po_risk import UploadedFile
from app.modules.inventory.accuracy import METRIC_LABELS
from app.modules.inventory.ai_narrative import InventoryNarrativeService
from app.modules.inventory.engine import ENGINE_VERSION, SeriesForecast, run_forecast
from app.modules.inventory.field_definitions import REGISTRY, SERIES_KEY_FIELDS
from app.modules.inventory.normalizer import (
    InventorySeries,
    NormalizedInventoryRecord,
    build_series,
    normalize_inventory_dataframe,
)
from app.modules.inventory.thresholds import (
    MODEL_NAMES,
    InventoryConfig,
    get_inventory_config,
)
from app.schemas.common import OutputOrigin
from app.schemas.inventory import (
    DataQualityIssueSchema,
    ExportFormat,
    ForecastDetailSchema,
    ForecastItemDetailSchema,
    ForecastItemSummarySchema,
    ForecastMethodInfoSchema,
    ForecastModelName,
    ForecastRequest,
    ForecastSummarySchema,
    InventoryAiNarrativeSchema,
    InventoryDatasetSchema,
    InventoryFieldDefinitionSchema,
    InventoryUploadResponse,
    ItemSort,
    MethodologySchema,
    SeriesSummarySchema,
)
from app.services.exports.inventory_report_builder import (
    build_inventory_csv_report,
    build_inventory_json_report,
    build_inventory_xlsx_report,
)
from app.services.files.readers import preview_records, read_tabular
from app.services.files.storage import store_upload
from app.services.files.validation import validate_upload
from app.services.tabular.mapping import suggest_mapping

logger = get_logger(__name__)

PREVIEW_ROW_LIMIT = 10
SERIES_PREVIEW_LIMIT = 50

MEDIA_TYPES = {
    ExportFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ExportFormat.CSV: "text/csv",
    ExportFormat.JSON: "application/json",
}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def handle_upload(db: Session, filename: str, content: bytes) -> InventoryUploadResponse:
    """Validate, store and load an inventory history file."""
    config = get_inventory_config()
    validated = validate_upload(filename, content)
    read_result = read_tabular(validated.content, validated.extension)
    mapping_result = suggest_mapping(read_result.source_columns, REGISTRY)
    stored = store_upload(validated)

    upload = UploadedFile(
        id=uuid.uuid4().hex[:32],
        module="inventory",
        original_filename=validated.original_filename,
        stored_filename=stored.stored_filename,
        file_extension=validated.extension,
        size_bytes=validated.size_bytes,
        sha256=validated.sha256,
        row_count=read_result.row_count,
    )
    db.add(upload)
    db.flush()

    missing_required = [
        name for name in REGISTRY.required if name not in set(mapping_result.mapping.values())
    ]

    response = InventoryUploadResponse(
        upload_id=upload.id,
        filename=validated.original_filename,
        file_extension=validated.extension,
        size_bytes=validated.size_bytes,
        row_count=read_result.row_count,
        detected_columns=list(read_result.source_columns),
        suggested_mapping=dict(mapping_result.mapping),
        suggestions=[
            {
                "source_column": item.source_column,
                "canonical_field": item.canonical_field,
                "confidence": item.confidence,
                "strategy": item.strategy,
            }
            for item in mapping_result.suggestions
        ],
        unmapped_columns=list(mapping_result.unmapped_columns),
        missing_required_fields=missing_required,
        is_analyzable=not missing_required,
        preview=preview_records(read_result.dataframe, PREVIEW_ROW_LIMIT),
        notes=list(read_result.notes),
    )

    if missing_required:
        db.commit()
        logger.info("Inventory upload stored but not loaded: missing %s", missing_required)
        return response

    loaded = normalize_inventory_dataframe(
        read_result.dataframe, mapping_result.mapping, config
    )
    series = build_series(loaded.records, config)

    if len(series) > config.reporting.max_series_per_dataset:
        raise ValidationError(
            f"The file contains {len(series):,} material/plant combinations, which exceeds the "
            f"configured limit of {config.reporting.max_series_per_dataset:,}.",
            details={
                "series_count": len(series),
                "limit": config.reporting.max_series_per_dataset,
            },
        )

    frequencies = {item.frequency for item in series}
    dataset = InventoryDatasetRow(
        id=uuid.uuid4().hex[:32],
        upload_id=upload.id,
        source_filename=validated.original_filename,
        config_version=config.config_version,
        applied_mapping=dict(mapping_result.mapping),
        unmapped_columns=list(mapping_result.unmapped_columns),
        data_quality_issues=loaded.issues_as_dicts(),
        row_count=loaded.record_count,
        series_count=len(series),
        material_count=len({item.material for item in series}),
        plant_count=len({item.plant for item in series}),
        history_start=min((item.first_period_date for item in series if item.first_period_date), default=None),
        history_end=max((item.last_period_date for item in series if item.last_period_date), default=None),
        frequency=sorted(frequencies)[0] if len(frequencies) == 1 else "mixed",
    )
    db.add(dataset)
    db.flush()

    db.bulk_insert_mappings(
        InventoryRecord,
        [
            {
                "dataset_id": dataset.id,
                "row_number": record.row_number,
                "material": record.material,
                "plant": record.plant,
                "storage_location": record.storage_location,
                "period_date": record.period_date,
                "payload": record.to_record(),
            }
            for record in loaded.records
        ],
    )

    response.dataset_id = dataset.id
    response.series_count = dataset.series_count
    response.material_count = dataset.material_count
    response.plant_count = dataset.plant_count
    response.frequency = dataset.frequency
    response.history_start = dataset.history_start
    response.history_end = dataset.history_end
    response.data_quality_issues = [
        DataQualityIssueSchema(**issue) for issue in loaded.issues_as_dicts()
    ]
    response.series = [_series_summary(item) for item in series[:SERIES_PREVIEW_LIMIT]]

    db.commit()
    logger.info(
        "Loaded inventory dataset %s: %d rows, %d series, %s",
        dataset.id,
        dataset.row_count,
        dataset.series_count,
        dataset.frequency,
    )
    return response


def _series_summary(series: InventorySeries) -> SeriesSummarySchema:
    return SeriesSummarySchema(
        series_key=series.series_key,
        material=series.material,
        material_description=series.material_description,
        plant=series.plant,
        storage_location=series.storage_location,
        supplier_id=series.supplier_id,
        frequency=series.frequency,
        period_count=series.observation_count,
        observed_period_count=series.observed_period_count,
        missing_period_count=len(series.missing_period_indexes),
        history_start=series.first_period_date,
        history_end=series.last_period_date,
        total_demand=round(sum(series.demand_values), 2),
        closing_inventory=series.closing_inventory,
    )


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------


def _resolve_dataset(db: Session, dataset_id: str | None) -> InventoryDatasetRow:
    """Return a dataset by id, or the most recent one."""
    if dataset_id:
        dataset = db.get(InventoryDatasetRow, dataset_id)
        if dataset is None:
            raise NotFoundError(
                "That inventory dataset does not exist.", details={"dataset_id": dataset_id}
            )
        return dataset

    dataset = db.execute(
        select(InventoryDatasetRow).order_by(InventoryDatasetRow.created_at.desc()).limit(1)
    ).scalars().first()
    if dataset is None:
        raise NotFoundError(
            "No inventory history has been uploaded yet. Upload an inventory file first."
        )
    return dataset


def _require_forecast(db: Session, forecast_id: str | None) -> InventoryForecast:
    """Return a forecast run by id, or the most recent one."""
    if forecast_id:
        forecast = db.get(InventoryForecast, forecast_id)
        if forecast is None:
            raise NotFoundError(
                "That forecast does not exist.", details={"forecast_id": forecast_id}
            )
        return forecast

    forecast = db.execute(
        select(InventoryForecast).order_by(InventoryForecast.created_at.desc()).limit(1)
    ).scalars().first()
    if forecast is None:
        raise NotFoundError("No forecast has been run yet. Run a forecast first.")
    return forecast


def _load_records(
    db: Session,
    dataset_id: str,
    materials: list[str] | None = None,
    plants: list[str] | None = None,
) -> list[NormalizedInventoryRecord]:
    """Rebuild the engine's inputs from the stored dataset."""
    conditions = [InventoryRecord.dataset_id == dataset_id]
    if materials:
        conditions.append(InventoryRecord.material.in_(materials))
    if plants:
        conditions.append(InventoryRecord.plant.in_(plants))

    rows = db.execute(
        select(InventoryRecord)
        .where(*conditions)
        .order_by(InventoryRecord.material, InventoryRecord.plant, InventoryRecord.period_date)
    ).scalars().all()
    return [_record_from_payload(row.payload or {}) for row in rows]


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _record_from_payload(payload: dict[str, Any]) -> NormalizedInventoryRecord:
    """Rebuild a normalised row from its stored JSON."""
    date_fields = {"period_date", "po_expected_date"}
    kwargs: dict[str, Any] = {
        "row_number": int(payload.get("row_number") or 0),
        "material": str(payload.get("material") or ""),
        "plant": str(payload.get("plant") or ""),
        "period_date": _as_date(payload.get("period_date")) or date.today(),
    }
    for name in REGISTRY.names:
        if name in {"material", "plant", "period_date"}:
            continue
        value = payload.get(name)
        kwargs[name] = _as_date(value) if name in date_fields else value
    return NormalizedInventoryRecord(**kwargs)


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


def forecast(db: Session, request: ForecastRequest) -> ForecastDetailSchema:
    """Forecast every series in a dataset and persist the run."""
    started = time.perf_counter()
    config = get_inventory_config()
    dataset = _resolve_dataset(db, request.dataset_id)

    if request.confidence_level is not None:
        # Fail fast and helpfully rather than deep inside the engine.
        config.forecast.z_for(request.confidence_level)

    records = _load_records(db, dataset.id, request.materials, request.plants)
    if not records:
        raise ValidationError(
            "That inventory dataset contains no rows to forecast for the requested filters.",
            details={
                "dataset_id": dataset.id,
                "materials": request.materials,
                "plants": request.plants,
            },
        )

    series = build_series(records, config, as_of=request.as_of_date)
    requested_model = (
        None if request.model is ForecastModelName.AUTO else request.model.value
    )

    result = run_forecast(
        series,
        config,
        as_of=request.as_of_date,
        horizon_periods=request.horizon_periods,
        confidence_level=request.confidence_level,
        requested_model=requested_model,
    )

    row = InventoryForecast(
        id=uuid.uuid4().hex[:32],
        dataset_id=dataset.id,
        status="completed",
        source_filename=dataset.source_filename,
        config_version=config.config_version,
        engine_version=ENGINE_VERSION,
        as_of_date=request.as_of_date,
        horizon_periods=result.horizon_periods,
        confidence_level=result.confidence_level,
        service_level=config.reorder.service_level,
        requested_model=requested_model,
        selection_metric=config.selection.metric,
        series_count=result.series_count,
        forecast_count=result.forecast_count,
        insufficient_data_count=result.insufficient_data_count,
        shortage_count=result.shortage_count,
        reorder_now_count=result.reorder_now_count,
        overstock_count=result.overstock_count,
        slow_moving_count=result.slow_moving_count,
        dead_stock_count=result.dead_stock_count,
        total_forecast_demand=result.total_forecast_demand,
        model_usage=dict(result.model_usage),
        accuracy_summary=dict(result.accuracy_summary),
        frequency_counts=dict(result.frequency_counts),
        warning_counts=dict(result.warning_counts),
        series_errors=list(result.series_errors),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()

    db.bulk_insert_mappings(
        InventoryForecastItem, [_item_row(row.id, item) for item in result.items]
    )

    narrative = InventoryAiNarrativeSchema()
    if request.generate_ai_summary:
        outcome = InventoryNarrativeService().generate(
            forecast_summary={
                **result.summary_payload(),
                "horizon_periods": result.horizon_periods,
                "confidence_level": result.confidence_level,
                "as_of_date": request.as_of_date.isoformat() if request.as_of_date else None,
            },
            shortage_items=[
                _ai_item_payload(item)
                for item in result.items
                if item.predicted_shortage_date is not None
            ][:10],
            overstock_items=[
                _ai_item_payload(item)
                for item in result.items
                if item.projection.health.overstock_risk != "none"
            ][:10],
            accuracy_summary=dict(result.accuracy_summary),
        )
        row.ai_provider = outcome.provider
        row.ai_output_origin = outcome.origin.value if outcome.origin else None
        row.ai_prompt_version = outcome.prompt_version
        row.ai_summary = outcome.summary
        row.ai_key_findings = list(outcome.key_findings)
        row.ai_recommended_actions = list(outcome.recommended_actions)
        row.ai_input_tokens = outcome.input_tokens
        row.ai_output_tokens = outcome.output_tokens
        row.ai_estimated_cost_usd = outcome.estimated_cost_usd
        row.ai_error = outcome.error
        narrative = _narrative_schema(row)

    row.duration_ms = int((time.perf_counter() - started) * 1000)
    db.commit()
    db.refresh(row)

    return _forecast_detail(
        row,
        [_item_summary_from_engine(item) for item in result.items],
        narrative,
        dataset,
        config,
    )


def _item_row(forecast_id: str, item: SeriesForecast) -> dict[str, Any]:
    """Flatten one engine result into its persistence row."""
    projection = item.projection
    reorder = projection.reorder
    health = projection.health
    accuracy = item.accuracy_headline()

    return {
        "forecast_id": forecast_id,
        "series_key": item.series_key,
        "material": item.material,
        "material_description": item.material_description,
        "plant": item.plant,
        "storage_location": item.storage_location,
        "supplier_id": item.supplier_id,
        "supplier_name": item.supplier_name,
        "status": item.status,
        "frequency": item.frequency,
        "model": item.model,
        "model_label": item.model_label,
        "selection_basis": item.selection.selection_basis if item.selection else None,
        "history_period_count": item.history_period_count,
        "missing_period_count": item.missing_period_count,
        "history_end": item.history_end,
        "total_forecast_demand": item.total_forecast_demand,
        "opening_inventory": projection.opening_inventory,
        "ending_projected_inventory": projection.ending_projected_inventory,
        "minimum_projected_inventory": projection.minimum_projected_inventory,
        "predicted_shortage_date": projection.predicted_shortage_date,
        "days_to_shortage": projection.days_to_shortage,
        "recommended_reorder_date": reorder.recommended_reorder_date,
        "recommended_reorder_quantity": reorder.recommended_reorder_quantity,
        "recommended_safety_stock": reorder.recommended_safety_stock,
        "calculated_reorder_point": reorder.calculated_reorder_point,
        "order_urgency": reorder.order_urgency,
        "expedite_recommended": reorder.expedite_recommended,
        "movement_class": health.movement_class,
        "is_slow_moving": health.is_slow_moving,
        "is_dead_stock": health.is_dead_stock,
        "overstock_risk": health.overstock_risk,
        "days_of_cover": health.days_of_cover,
        "annual_turnover": health.annual_turnover,
        "accuracy_basis": "backtest" if item.accuracy_backtest else "in_sample",
        "mae": accuracy.mae if accuracy else None,
        "rmse": accuracy.rmse if accuracy else None,
        "mape": accuracy.mape if accuracy else None,
        "smape": accuracy.smape if accuracy else None,
        "mase": accuracy.mase if accuracy else None,
        "warning_count": len(item.warnings),
        "payload": item.to_dict(),
        "output_origin": OutputOrigin.FORECAST.value,
    }


def _ai_item_payload(item: SeriesForecast) -> dict[str, Any]:
    """The narrow slice of an item the AI narrative is allowed to see."""
    return {
        "material": item.material,
        "material_description": item.material_description,
        "plant": item.plant,
        "predicted_shortage_date": (
            item.predicted_shortage_date.isoformat() if item.predicted_shortage_date else None
        ),
        "days_to_shortage": item.projection.days_to_shortage,
        "recommended_reorder_date": (
            item.recommended_reorder_date.isoformat() if item.recommended_reorder_date else None
        ),
        "recommended_reorder_quantity": item.recommended_reorder_quantity,
        "expedite_recommended": item.projection.reorder.expedite_recommended,
        "model": item.model,
        "days_of_cover": item.projection.health.days_of_cover,
        "overstock_risk": item.projection.health.overstock_risk,
        "movement_class": item.projection.health.movement_class,
        "is_dead_stock": item.projection.health.is_dead_stock,
    }


# ---------------------------------------------------------------------------
# Row -> schema mappers
# ---------------------------------------------------------------------------


def _item_summary_from_engine(item: SeriesForecast) -> ForecastItemSummarySchema:
    row = _item_row("", item)
    row.pop("forecast_id", None)
    row.pop("payload", None)
    return ForecastItemSummarySchema(**row)


def _item_summary_from_row(row: InventoryForecastItem) -> ForecastItemSummarySchema:
    return ForecastItemSummarySchema(
        series_key=row.series_key,
        material=row.material,
        material_description=row.material_description,
        plant=row.plant,
        storage_location=row.storage_location,
        supplier_id=row.supplier_id,
        supplier_name=row.supplier_name,
        status=row.status,
        frequency=row.frequency,
        model=row.model,
        model_label=row.model_label,
        selection_basis=row.selection_basis,
        history_period_count=row.history_period_count,
        missing_period_count=row.missing_period_count,
        history_end=row.history_end,
        total_forecast_demand=row.total_forecast_demand,
        opening_inventory=row.opening_inventory,
        ending_projected_inventory=row.ending_projected_inventory,
        minimum_projected_inventory=row.minimum_projected_inventory,
        predicted_shortage_date=row.predicted_shortage_date,
        days_to_shortage=row.days_to_shortage,
        recommended_reorder_date=row.recommended_reorder_date,
        recommended_reorder_quantity=row.recommended_reorder_quantity,
        recommended_safety_stock=row.recommended_safety_stock,
        calculated_reorder_point=row.calculated_reorder_point,
        order_urgency=row.order_urgency,
        expedite_recommended=row.expedite_recommended,
        movement_class=row.movement_class,
        is_slow_moving=row.is_slow_moving,
        is_dead_stock=row.is_dead_stock,
        overstock_risk=row.overstock_risk,
        days_of_cover=row.days_of_cover,
        annual_turnover=row.annual_turnover,
        accuracy_basis=row.accuracy_basis,
        mae=row.mae,
        rmse=row.rmse,
        mape=row.mape,
        smape=row.smape,
        mase=row.mase,
        warning_count=row.warning_count,
    )


def _item_detail_from_row(row: InventoryForecastItem) -> ForecastItemDetailSchema:
    """Rebuild the full item schema from the stored engine payload."""
    payload = dict(row.payload or {})
    payload.pop("output_origin", None)
    return ForecastItemDetailSchema(**payload)


def _narrative_schema(row: InventoryForecast) -> InventoryAiNarrativeSchema:
    if not row.ai_summary and not row.ai_error:
        return InventoryAiNarrativeSchema()
    return InventoryAiNarrativeSchema(
        available=row.ai_summary is not None,
        origin=OutputOrigin(row.ai_output_origin) if row.ai_output_origin else None,
        provider=row.ai_provider,
        prompt_version=row.ai_prompt_version,
        summary=row.ai_summary,
        key_findings=list(row.ai_key_findings or []),
        recommended_actions=list(row.ai_recommended_actions or []),
        input_tokens=row.ai_input_tokens,
        output_tokens=row.ai_output_tokens,
        estimated_cost_usd=row.ai_estimated_cost_usd,
        error=row.ai_error,
    )


def _forecast_detail(
    row: InventoryForecast,
    items: list[ForecastItemSummarySchema],
    narrative: InventoryAiNarrativeSchema,
    dataset: InventoryDatasetRow | None,
    config: InventoryConfig,
) -> ForecastDetailSchema:
    issues = (dataset.data_quality_issues if dataset else []) or []
    return ForecastDetailSchema(
        forecast_id=row.id,
        dataset_id=row.dataset_id,
        status=row.status,
        source_filename=row.source_filename,
        config_version=row.config_version,
        engine_version=row.engine_version,
        as_of_date=row.as_of_date,
        horizon_periods=row.horizon_periods,
        confidence_level=row.confidence_level,
        service_level=row.service_level,
        requested_model=row.requested_model,
        selection_metric=row.selection_metric,
        summary=ForecastSummarySchema(
            series_count=row.series_count,
            forecast_count=row.forecast_count,
            insufficient_data_count=row.insufficient_data_count,
            shortage_count=row.shortage_count,
            reorder_now_count=row.reorder_now_count,
            overstock_count=row.overstock_count,
            slow_moving_count=row.slow_moving_count,
            dead_stock_count=row.dead_stock_count,
            total_forecast_demand=row.total_forecast_demand,
            model_usage=dict(row.model_usage or {}),
            accuracy_summary=dict(row.accuracy_summary or {}),
            frequency_counts=dict(row.frequency_counts or {}),
            warning_counts=dict(row.warning_counts or {}),
        ),
        items=items,
        data_quality_issues=[DataQualityIssueSchema(**issue) for issue in issues],
        series_errors=list(row.series_errors or []),
        ai_narrative=narrative,
        duration_ms=row.duration_ms,
        created_at=row.created_at,
        disclaimer=config.reporting.forecast_disclaimer,
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_forecast(
    db: Session, forecast_id: str | None, item_limit: int = 200
) -> ForecastDetailSchema:
    """Return one forecast run with its materials."""
    config = get_inventory_config()
    row = _require_forecast(db, forecast_id)
    dataset = db.get(InventoryDatasetRow, row.dataset_id)
    items = db.execute(
        _item_query(row.id).limit(item_limit)
    ).scalars().all()
    return _forecast_detail(
        row,
        [_item_summary_from_row(item) for item in items],
        _narrative_schema(row),
        dataset,
        config,
    )


def list_forecasts(
    db: Session, limit: int = 20, offset: int = 0
) -> tuple[int, list[ForecastDetailSchema]]:
    """Return previous forecast runs, newest first, without their item lists."""
    config = get_inventory_config()
    total = db.execute(select(func.count(InventoryForecast.id))).scalar_one()
    rows = db.execute(
        select(InventoryForecast)
        .order_by(InventoryForecast.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return total, [
        _forecast_detail(row, [], _narrative_schema(row), None, config) for row in rows
    ]


def _item_query(forecast_id: str):
    """Base query for a run's items, in the default shortage-first order."""
    return (
        select(InventoryForecastItem)
        .where(InventoryForecastItem.forecast_id == forecast_id)
        .order_by(
            InventoryForecastItem.predicted_shortage_date.is_(None),
            InventoryForecastItem.predicted_shortage_date,
            InventoryForecastItem.material,
            InventoryForecastItem.plant,
        )
    )


def list_items(
    db: Session,
    forecast_id: str | None,
    *,
    material: str | None = None,
    plant: str | None = None,
    supplier_id: str | None = None,
    model: str | None = None,
    status: str | None = None,
    movement_class: str | None = None,
    shortage_only: bool = False,
    reorder_only: bool = False,
    overstock_only: bool = False,
    dead_stock_only: bool = False,
    sort: ItemSort = ItemSort.SHORTAGE,
    limit: int = 100,
    offset: int = 0,
) -> tuple[str, int, list[ForecastItemSummarySchema]]:
    """Return a filtered, paginated page of materials inside a run."""
    row = _require_forecast(db, forecast_id)

    conditions = [InventoryForecastItem.forecast_id == row.id]
    if material:
        conditions.append(InventoryForecastItem.material == material.strip())
    if plant:
        conditions.append(InventoryForecastItem.plant == plant.strip())
    if supplier_id:
        conditions.append(InventoryForecastItem.supplier_id == supplier_id.strip())
    if model:
        conditions.append(InventoryForecastItem.model == model.strip())
    if status:
        conditions.append(InventoryForecastItem.status == status.strip())
    if movement_class:
        conditions.append(InventoryForecastItem.movement_class == movement_class.strip())
    if shortage_only:
        conditions.append(InventoryForecastItem.predicted_shortage_date.is_not(None))
    if reorder_only:
        conditions.append(InventoryForecastItem.recommended_reorder_date.is_not(None))
    if overstock_only:
        conditions.append(InventoryForecastItem.overstock_risk != "none")
    if dead_stock_only:
        conditions.append(InventoryForecastItem.is_dead_stock.is_(True))

    total = db.execute(
        select(func.count(InventoryForecastItem.id)).where(*conditions)
    ).scalar_one()

    ordering = {
        ItemSort.SHORTAGE: (
            InventoryForecastItem.predicted_shortage_date.is_(None),
            InventoryForecastItem.predicted_shortage_date,
        ),
        ItemSort.REORDER: (
            InventoryForecastItem.recommended_reorder_date.is_(None),
            InventoryForecastItem.recommended_reorder_date,
        ),
        ItemSort.DEMAND: (InventoryForecastItem.total_forecast_demand.desc(),),
        ItemSort.ACCURACY: (
            InventoryForecastItem.smape.is_(None),
            InventoryForecastItem.smape,
        ),
        ItemSort.MATERIAL: (),
    }[sort]

    rows = db.execute(
        select(InventoryForecastItem)
        .where(*conditions)
        .order_by(*ordering, InventoryForecastItem.material, InventoryForecastItem.plant)
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return row.id, total, [_item_summary_from_row(item) for item in rows]


def get_item(
    db: Session,
    forecast_id: str | None,
    material: str,
    plant: str,
    storage_location: str | None = None,
) -> ForecastItemDetailSchema:
    """Return one material's complete forecast."""
    row = _require_forecast(db, forecast_id)
    conditions = [
        InventoryForecastItem.forecast_id == row.id,
        InventoryForecastItem.material == material,
        InventoryForecastItem.plant == plant,
    ]
    if storage_location:
        conditions.append(InventoryForecastItem.storage_location == storage_location)

    item = db.execute(select(InventoryForecastItem).where(*conditions)).scalars().first()
    if item is None:
        raise NotFoundError(
            "That material is not in this forecast.",
            details={
                "material": material,
                "plant": plant,
                "storage_location": storage_location,
                "forecast_id": row.id,
            },
        )
    return _item_detail_from_row(item)


def list_datasets(db: Session) -> list[InventoryDatasetSchema]:
    """Return every uploaded dataset, newest first."""
    rows = db.execute(
        select(InventoryDatasetRow).order_by(InventoryDatasetRow.created_at.desc())
    ).scalars().all()
    return [
        InventoryDatasetSchema(
            id=row.id,
            source_filename=row.source_filename,
            row_count=row.row_count,
            series_count=row.series_count,
            material_count=row.material_count,
            plant_count=row.plant_count,
            frequency=row.frequency,
            history_start=row.history_start,
            history_end=row.history_end,
            config_version=row.config_version,
            created_at=row.created_at,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_forecast(
    db: Session, forecast_id: str, export_format: ExportFormat
) -> tuple[bytes, str, str]:
    """Build a downloadable report. Returns ``(content, filename, media_type)``."""
    config = get_inventory_config()
    row = _require_forecast(db, forecast_id)
    dataset = db.get(InventoryDatasetRow, row.dataset_id)
    items = db.execute(_item_query(row.id)).scalars().all()

    item_payloads: list[dict[str, Any]] = []
    for item in items:
        summary = _item_summary_from_row(item).model_dump(mode="json")
        summary["payload"] = item.payload or {}
        item_payloads.append(summary)

    detail = _forecast_detail(row, [], _narrative_schema(row), dataset, config)
    payload: dict[str, Any] = {
        "forecast": detail.model_dump(mode="json", exclude={"items", "summary"}),
        "summary": detail.summary.model_dump(mode="json"),
        "data_quality_issues": [
            issue.model_dump(mode="json", by_alias=True) for issue in detail.data_quality_issues
        ],
        "series_errors": list(row.series_errors or []),
        "ai_narrative": detail.ai_narrative.model_dump(mode="json"),
        "methodology": methodology_payload(config),
        "items": item_payloads,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if export_format is ExportFormat.XLSX:
        content = build_inventory_xlsx_report(payload)
    elif export_format is ExportFormat.CSV:
        content = build_inventory_csv_report(item_payloads)
    else:
        content = build_inventory_json_report(payload)

    filename = f"inventory_forecast_{row.id[:8]}_{stamp}.{export_format.value}"
    logger.info("Exported inventory forecast %s as %s", row.id, export_format.value)
    return content, filename, MEDIA_TYPES[export_format]


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------


def get_field_catalogue() -> list[InventoryFieldDefinitionSchema]:
    """Return the canonical fields and the column names that map to them."""
    return [
        InventoryFieldDefinitionSchema(
            name=definition.name,
            label=definition.label,
            field_type=definition.field_type.value,
            required=definition.required,
            description=definition.description,
            aliases=list(definition.aliases),
            is_series_key=definition.name in SERIES_KEY_FIELDS,
        )
        for definition in REGISTRY.definitions
    ]


def methodology_payload(config: InventoryConfig) -> dict[str, Any]:
    """The documented method, as a plain dict for exports and the API."""
    return {
        "config_version": config.config_version,
        "engine_version": ENGINE_VERSION,
        "methods": [
            {
                "model": name,
                "label": config.model(name).label,
                "enabled": config.model(name).enabled,
                "min_observations": config.model(name).min_observations,
                "parameters": _model_parameters(config, name),
                "assumptions": list(config.model(name).assumptions),
            }
            for name in MODEL_NAMES
        ],
        "selection": {
            "method": config.selection.method,
            "metric": config.selection.metric,
            "metric_label": METRIC_LABELS.get(config.selection.metric, ""),
            "holdout_periods": config.selection.holdout_periods,
            "folds": config.selection.folds,
            "minimum_train_observations": config.selection.minimum_train_observations,
            "fallback_model": config.selection.fallback_model,
            "description": config.selection.description,
        },
        "intermittent": {
            "enabled": config.intermittent.enabled,
            "adi_threshold": config.intermittent.adi_threshold,
            "cv_squared_threshold": config.intermittent.cv_squared_threshold,
            "min_zero_period_pct": config.intermittent.min_zero_period_pct,
            "allowed_models": list(config.intermittent.allowed_models),
            "description": config.intermittent.description,
        },
        "forecast": {
            "default_horizon_periods": config.forecast.default_horizon_periods,
            "max_horizon_periods": config.forecast.max_horizon_periods,
            "minimum_observations": config.forecast.minimum_observations,
            "confidence_level": config.forecast.confidence_level,
            "available_confidence_levels": config.forecast.available_confidence_levels,
            "clip_negative_forecast": config.forecast.clip_negative_forecast,
        },
        "reorder": {
            "service_level": config.reorder.service_level,
            "available_service_levels": config.reorder.available_service_levels,
            "safety_stock_basis": config.reorder.safety_stock_basis,
            "safety_stock_formula": (
                "z(service level) x per-period demand sigma x sqrt(lead time / period length)"
            ),
            "reorder_point_formula": (
                "forecast demand over the lead time + recommended safety stock"
            ),
            "order_quantity_formula": (
                "forecast demand over (lead time + review period) + safety stock - projected "
                "inventory position on the reorder date"
            ),
            "default_lead_time_days": config.reorder.default_lead_time_days,
            "review_period_days": config.reorder.review_period_days,
            "rounding_multiple": config.reorder.rounding_multiple,
            "minimum_order_quantity": config.reorder.minimum_order_quantity,
            "description": config.reorder.description,
        },
        "stock_health": {
            "overstock_days_of_cover": config.stock_health.overstock_days_of_cover,
            "critical_overstock_days_of_cover": (
                config.stock_health.critical_overstock_days_of_cover
            ),
            "excess_cover_days": config.stock_health.excess_cover_days,
            "fast_moving_turnover": config.stock_health.fast_moving_turnover,
            "slow_moving_turnover": config.stock_health.slow_moving_turnover,
            "very_slow_turnover": config.stock_health.very_slow_turnover,
            "slow_moving_zero_demand_pct": config.stock_health.slow_moving_zero_demand_pct,
            "dead_stock_zero_demand_periods": config.stock_health.dead_stock_zero_demand_periods,
            "shortage_horizon_days": config.stock_health.shortage_horizon_days,
            "description": config.stock_health.description,
        },
        "period": {
            "frequencies": {
                name: {
                    "label": spec.label,
                    "days": spec.days,
                    "periods_per_year": spec.periods_per_year,
                    "season_length": spec.season_length,
                }
                for name, spec in config.period.frequencies.items()
            },
            "default_frequency": config.period.default_frequency,
            "missing_period_fill": config.period.missing_period_fill,
            "max_missing_period_pct": config.period.max_missing_period_pct,
            "description": config.period.description,
        },
        "accuracy_metrics": dict(METRIC_LABELS),
        "disclaimer": config.reporting.forecast_disclaimer,
    }


def _model_parameters(config: InventoryConfig, name: str) -> dict[str, Any]:
    """The configured parameters of one method, without the empty ones."""
    spec = config.model(name)
    values: dict[str, Any] = {
        "window": spec.window,
        "weights": spec.normalized_weights or None,
        "alpha": spec.alpha,
        "beta": spec.beta,
        "gamma": spec.gamma,
        "damping": spec.damping,
        "optimize": spec.optimize,
        "min_seasons": spec.min_seasons if name == "holt_winters_seasonal" else None,
        "season_length": spec.season_length,
    }
    return {key: value for key, value in values.items() if value is not None}


def get_methodology() -> MethodologySchema:
    """Return the documented forecasting and planning method."""
    config = get_inventory_config()
    payload = methodology_payload(config)
    return MethodologySchema(
        config_version=payload["config_version"],
        engine_version=payload["engine_version"],
        methods=[ForecastMethodInfoSchema(**method) for method in payload["methods"]],
        selection=payload["selection"],
        intermittent=payload["intermittent"],
        forecast=payload["forecast"],
        reorder=payload["reorder"],
        stock_health=payload["stock_health"],
        period=payload["period"],
        accuracy_metrics=payload["accuracy_metrics"],
        disclaimer=payload["disclaimer"],
    )
