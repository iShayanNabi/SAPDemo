"""Service layer for the Supplier Recommendation Engine.

This is the only place that knows the whole story: readers, column mapper,
normaliser, eligibility, scoring engine, optional AI narrative and the database.

Data flow::

    bytes -> validate -> store -> read -> map -> normalise -> persist catalogue   (upload)
    catalogue + requirement + weights -> eligibility -> scoring -> rank
        -> estimate cost/delivery, advantages, risks -> persist -> narrative      (recommend)
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.po_risk import UploadedFile
from app.models.supplier_reco import (
    Supplier,
    SupplierCatalog,
    SupplierRecommendation,
    SupplierRecommendationEntry,
)
from app.modules.supplier_reco.ai_narrative import SupplierRecoNarrativeService
from app.modules.supplier_reco.engine import RankedSupplier, run_recommendation
from app.modules.supplier_reco.field_definitions import LIST_FIELDS, REGISTRY
from app.modules.supplier_reco.normalizer import (
    NormalizedSupplier,
    normalize_supplier_dataframe,
)
from app.modules.supplier_reco.requirement import Requirement
from app.modules.supplier_reco.scoring import SCORING_ENGINE_VERSION
from app.modules.supplier_reco.thresholds import (
    SCORE_DIMENSIONS,
    SupplierRecoConfig,
    Weights,
    get_supplier_reco_config,
)
from app.schemas.common import OutputOrigin
from app.schemas.supplier_reco import (
    ColumnSuggestionSchema,
    ExportFormat,
    RecommendationDetailSchema,
    RecommendationEntrySchema,
    RecommendationSummarySchema,
    RecommendRequest,
    RequirementSchema,
    ScoringDimensionInfo,
    ScoringInfoSchema,
    SupplierCatalogInfoSchema,
    SupplierFieldDefinitionSchema,
    SupplierRecoAiNarrativeSchema,
    SupplierSchema,
    SupplierUploadResponse,
    WeightsSchema,
)
from app.services.exports.supplier_reco_report_builder import (
    build_supplier_reco_csv_report,
    build_supplier_reco_json_report,
    build_supplier_reco_xlsx_report,
    supplier_reco_disclaimer,
)
from app.services.files.readers import preview_records, read_tabular
from app.services.files.storage import read_upload, store_upload
from app.services.files.validation import validate_upload
from app.services.tabular.mapping import suggest_mapping

logger = get_logger(__name__)

PREVIEW_ROW_LIMIT = 10

#: Columns copied from a normalised supplier into the ``suppliers`` table.
SUPPLIER_COLUMNS: tuple[str, ...] = (
    "row_number", "supplier_id", "supplier_name", "materials_supplied", "plants_served",
    "regions_served", "unit_price", "currency", "unit_price_base", "lead_time_days",
    "available_capacity", "on_time_delivery_rate", "quality_score", "defect_rate",
    "risk_score", "esg_score", "contract_status", "contract_expiration", "payment_terms",
    "historical_order_count", "historical_spend", "historical_spend_base",
)

_DIMENSION_LABELS = {
    "cost": "Cost", "delivery": "Delivery", "quality": "Quality", "capacity": "Capacity",
    "risk": "Risk", "esg": "ESG", "contract": "Contract", "geographic": "Geographic fit",
    "past_performance": "Past performance",
}


# ---------------------------------------------------------------------------
# Upload / catalogue
# ---------------------------------------------------------------------------


def handle_supplier_upload(db: Session, filename: str, content: bytes) -> SupplierUploadResponse:
    """Validate, store and load an uploaded supplier master file into a catalogue."""
    config = get_supplier_reco_config()
    validated = validate_upload(filename, content)
    read_result = read_tabular(validated.content, validated.extension)
    mapping_result = suggest_mapping(read_result.source_columns, REGISTRY)
    stored = store_upload(validated)

    upload = UploadedFile(
        id=uuid.uuid4().hex[:32],
        module="supplier_reco",
        original_filename=validated.safe_filename,
        stored_filename=stored.stored_filename,
        file_extension=validated.extension,
        size_bytes=validated.size_bytes,
        sha256=validated.sha256,
        row_count=read_result.row_count,
        column_count=len(read_result.source_columns),
        detected_columns=read_result.source_columns,
        suggested_mapping=mapping_result.mapping,
    )
    db.add(upload)
    db.flush()

    missing = [f for f in REGISTRY.required if f not in set(mapping_result.mapping.values())]
    dataset = None
    catalog_id = uuid.uuid4().hex[:32]
    if not missing:
        dataset = normalize_supplier_dataframe(read_result.dataframe, mapping_result.mapping, config)
        catalog = SupplierCatalog(
            id=catalog_id,
            upload_id=upload.id,
            source_filename=upload.original_filename,
            config_version=config.config_version,
            base_currency=config.base_currency,
            applied_mapping=dataset.applied_mapping,
            unmapped_columns=dataset.unmapped_columns,
            data_quality_issues=dataset.issues_as_dicts(),
            supplier_count=dataset.supplier_count,
        )
        db.add(catalog)
        db.flush()
        _persist_suppliers(db, catalog_id, dataset.suppliers)

    db.commit()

    logger.info(
        "Supplier upload %s accepted: %d rows, %d suppliers loaded",
        upload.id, read_result.row_count, dataset.supplier_count if dataset else 0,
    )

    return SupplierUploadResponse(
        catalog_id=catalog_id if dataset else "",
        upload_id=upload.id,
        original_filename=upload.original_filename,
        file_extension=upload.file_extension,
        size_bytes=upload.size_bytes,
        supplier_count=dataset.supplier_count if dataset else 0,
        detected_columns=read_result.source_columns,
        preview_rows=preview_records(read_result.dataframe, PREVIEW_ROW_LIMIT),
        applied_mapping=mapping_result.mapping,
        mapping_suggestions=[
            ColumnSuggestionSchema(
                source_column=s.source_column,
                canonical_field=s.canonical_field,
                confidence=s.confidence,
                strategy=s.strategy,
            )
            for s in mapping_result.suggestions
        ],
        unmapped_columns=mapping_result.unmapped_columns,
        missing_required_fields=missing,
        data_quality_issues=dataset.issues_as_dicts() if dataset else [],
        parser_notes=read_result.notes,
    )


def _persist_suppliers(db: Session, catalog_id: str, suppliers: list[NormalizedSupplier]) -> None:
    """Store the normalised suppliers so recommendations never re-read the file."""
    records = []
    for supplier in suppliers:
        record = supplier.to_record()
        payload = {key: record.get(key) for key in SUPPLIER_COLUMNS}
        # contract_expiration is stored as a real date, not the isoformat string.
        payload["contract_expiration"] = supplier.contract_expiration
        for list_field in LIST_FIELDS:
            payload[list_field] = list(getattr(supplier, list_field))
        payload["catalog_id"] = catalog_id
        records.append(payload)
    if records:
        db.bulk_insert_mappings(Supplier, records)


# ---------------------------------------------------------------------------
# Recommend
# ---------------------------------------------------------------------------


def recommend(db: Session, request: RecommendRequest) -> RecommendationDetailSchema:
    """Run the deterministic recommendation for a requirement over a catalogue."""
    started = time.perf_counter()
    config = get_supplier_reco_config()

    catalog = _resolve_catalog(db, request.catalog_id)
    suppliers = _load_suppliers(db, catalog.id)
    if not suppliers:
        raise ValidationError(
            "The selected supplier catalogue is empty.",
            details={"catalog_id": catalog.id},
        )

    weights = _resolve_weights(request.weights, config)
    requirement = _to_requirement(request.requirement)
    result = run_recommendation(suppliers, requirement, weights, config)

    # Build the entries to persist and return.
    eligible_entries = [e for e in result.ranked if e.is_eligible]
    if request.top_n:
        eligible_entries = eligible_entries[: request.top_n]
    ineligible_entries = (
        [e for e in result.ranked if not e.is_eligible] if request.include_ineligible else []
    )
    entries = eligible_entries + ineligible_entries

    recommendation = SupplierRecommendation(
        id=uuid.uuid4().hex[:32],
        catalog_id=catalog.id,
        status="completed",
        source_filename=catalog.source_filename,
        config_version=config.config_version,
        scoring_engine_version=SCORING_ENGINE_VERSION,
        requirement=request.requirement.model_dump(mode="json"),
        weights=weights.as_dict(),
        base_currency=config.base_currency,
        total_supplier_count=result.total_supplier_count,
        eligible_count=result.eligible_count,
        ineligible_count=result.ineligible_count,
        top_supplier_id=result.top_supplier_id,
        top_supplier_score=result.top_supplier_score,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(recommendation)
    db.flush()
    _persist_entries(db, recommendation.id, entries)

    # --- optional narrative, never allowed to fail the recommendation ----
    narrative = SupplierRecoAiNarrativeSchema()
    if request.generate_ai_summary:
        ranking_summary = {
            "base_currency": result.base_currency,
            "total_supplier_count": result.total_supplier_count,
            "eligible_count": result.eligible_count,
            "ineligible_count": result.ineligible_count,
        }
        outcome = SupplierRecoNarrativeService().generate(
            request.requirement.model_dump(mode="json"),
            weights.as_dict(),
            ranking_summary,
            [e.to_dict() for e in eligible_entries[:5]],
        )
        recommendation.ai_provider = outcome.provider
        recommendation.ai_output_origin = outcome.origin.value if outcome.origin else None
        recommendation.ai_prompt_version = outcome.prompt_version
        recommendation.ai_summary = outcome.summary
        recommendation.ai_key_findings = outcome.key_findings
        recommendation.ai_recommended_actions = outcome.recommended_actions
        recommendation.ai_input_tokens = outcome.input_tokens
        recommendation.ai_output_tokens = outcome.output_tokens
        recommendation.ai_estimated_cost_usd = outcome.estimated_cost_usd
        recommendation.ai_error = outcome.error
        narrative = SupplierRecoAiNarrativeSchema(
            available=outcome.available,
            origin=outcome.origin,
            provider=outcome.provider,
            prompt_version=outcome.prompt_version,
            summary=outcome.summary,
            key_findings=outcome.key_findings,
            recommended_actions=outcome.recommended_actions,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            estimated_cost_usd=outcome.estimated_cost_usd,
            error=outcome.error,
        )

    recommendation.duration_ms = int((time.perf_counter() - started) * 1000)
    db.commit()
    db.refresh(recommendation)

    logger.info(
        "Recommendation %s completed: %d/%d eligible, top=%s, %d ms",
        recommendation.id, result.eligible_count, result.total_supplier_count,
        result.top_supplier_id, recommendation.duration_ms,
    )
    entry_schemas = [_entry_schema_from_ranked(e) for e in entries]
    return _to_detail_schema(recommendation, entry_schemas, narrative, config)


def _persist_entries(
    db: Session, recommendation_id: str, entries: list[RankedSupplier]
) -> None:
    """Store the ranked entries."""
    records = []
    for entry in entries:
        record = entry.to_dict()
        record["recommendation_id"] = recommendation_id
        record["estimated_delivery_date"] = entry.estimated_delivery_date
        records.append(record)
    if records:
        db.bulk_insert_mappings(SupplierRecommendationEntry, records)


def _resolve_catalog(db: Session, catalog_id: str | None) -> SupplierCatalog:
    """Load the requested catalogue, or the most recent one when none is given."""
    if catalog_id:
        catalog = db.get(SupplierCatalog, catalog_id)
        if catalog is None:
            raise NotFoundError(f"Supplier catalogue '{catalog_id}' was not found.")
        return catalog
    catalog = db.scalars(
        select(SupplierCatalog).order_by(SupplierCatalog.created_at.desc()).limit(1)
    ).first()
    if catalog is None:
        raise NotFoundError(
            "No supplier catalogue is available yet. Upload a supplier file first "
            "(POST /api/v1/suppliers/upload)."
        )
    return catalog


def _resolve_weights(weights: WeightsSchema | None, config: SupplierRecoConfig) -> Weights:
    """Return validated weights, defaulting to the configured ones."""
    if weights is None:
        return config.default_weights
    resolved = Weights(**weights.model_dump())
    total = resolved.total()
    if abs(total - config.weight_total) > config.weight_total_tolerance:
        raise ValidationError(
            f"Scoring weights must sum to {config.weight_total:g}% (got {total:g}%).",
            details={"weights": resolved.as_dict(), "total": total, "required_total": config.weight_total},
        )
    return resolved


def _to_requirement(schema: RequirementSchema) -> Requirement:
    """Convert the API requirement schema into the engine's dataclass."""
    return Requirement(
        material=schema.material,
        material_description=schema.material_description,
        material_group=schema.material_group,
        quantity=schema.quantity,
        unit_of_measure=schema.unit_of_measure,
        plant=schema.plant,
        company_code=schema.company_code,
        required_delivery_date=schema.required_delivery_date,
        order_date=schema.order_date,
        target_price=schema.target_price,
        currency=schema.currency,
        preferred_region=schema.preferred_region,
        risk_tolerance=schema.risk_tolerance,
        sustainability_requirement=schema.sustainability_requirement,
        contract_requirement=schema.contract_requirement,
        minimum_quality_score=schema.minimum_quality_score,
        minimum_available_capacity=schema.minimum_available_capacity,
    )


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def get_recommendation(db: Session, recommendation_id: str) -> RecommendationDetailSchema:
    """Load one recommendation with its ranked entries."""
    recommendation = _require_recommendation(db, recommendation_id)
    config = get_supplier_reco_config()
    entries = db.scalars(
        select(SupplierRecommendationEntry)
        .where(SupplierRecommendationEntry.recommendation_id == recommendation_id)
        .order_by(
            SupplierRecommendationEntry.is_eligible.desc(),
            SupplierRecommendationEntry.rank.asc().nulls_last(),
            SupplierRecommendationEntry.supplier_id.asc(),
        )
    ).all()
    entry_schemas = [_entry_schema_from_row(row) for row in entries]
    return _to_detail_schema(
        recommendation, entry_schemas, _narrative_from_row(recommendation), config
    )


def list_recommendations(
    db: Session, limit: int = 20, offset: int = 0
) -> tuple[int, list[RecommendationSummarySchema]]:
    """Return previous recommendations, newest first."""
    total = db.scalar(select(func.count()).select_from(SupplierRecommendation)) or 0
    rows = db.scalars(
        select(SupplierRecommendation)
        .order_by(SupplierRecommendation.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return total, [
        RecommendationSummarySchema(
            recommendation_id=row.id,
            catalog_id=row.catalog_id,
            status=row.status,
            base_currency=row.base_currency,
            material=(row.requirement or {}).get("material"),
            total_supplier_count=row.total_supplier_count,
            eligible_count=row.eligible_count,
            top_supplier_id=row.top_supplier_id,
            top_supplier_score=row.top_supplier_score,
            created_at=row.created_at,
        )
        for row in rows
    ]


def list_suppliers(
    db: Session,
    *,
    catalog_id: str | None = None,
    material: str | None = None,
    region: str | None = None,
    plant: str | None = None,
    contract_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[str | None, int, list[SupplierSchema]]:
    """Return suppliers from a catalogue, filtered and paginated.

    ``material``/``region``/``plant`` match against the multi-valued list columns
    in Python, because those are stored as JSON arrays.
    """
    catalog = _resolve_catalog(db, catalog_id)

    statement = select(Supplier).where(Supplier.catalog_id == catalog.id)
    if contract_status:
        statement = statement.where(Supplier.contract_status == contract_status)
    rows = db.scalars(statement.order_by(Supplier.supplier_id.asc())).all()

    def _matches(row: Supplier) -> bool:
        if material and not _contains(row.materials_supplied, material):
            return False
        if region and not _contains(row.regions_served, region):
            return False
        if plant and not _contains(row.plants_served, plant):
            return False
        return True

    filtered = [row for row in rows if _matches(row)]
    total = len(filtered)
    page = filtered[offset : offset + limit]
    return catalog.id, total, [_supplier_schema(row) for row in page]


def get_supplier(
    db: Session, supplier_id: str, *, catalog_id: str | None = None
) -> SupplierSchema:
    """Return one supplier from a catalogue."""
    catalog = _resolve_catalog(db, catalog_id)
    row = db.scalars(
        select(Supplier)
        .where(Supplier.catalog_id == catalog.id, Supplier.supplier_id == supplier_id)
        .limit(1)
    ).first()
    if row is None:
        raise NotFoundError(
            f"Supplier '{supplier_id}' was not found in catalogue '{catalog.id}'."
        )
    return _supplier_schema(row)


def list_catalogs(db: Session) -> list[SupplierCatalogInfoSchema]:
    """Return every supplier catalogue, newest first."""
    rows = db.scalars(
        select(SupplierCatalog).order_by(SupplierCatalog.created_at.desc())
    ).all()
    return [
        SupplierCatalogInfoSchema(
            catalog_id=row.id,
            source_filename=row.source_filename,
            supplier_count=row.supplier_count,
            base_currency=row.base_currency,
            created_at=row.created_at,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_recommendation(
    db: Session, recommendation_id: str, export_format: ExportFormat
) -> tuple[bytes, str, str]:
    """Build a downloadable report. Returns ``(content, filename, media_type)``."""
    detail = get_recommendation(db, recommendation_id)
    entry_dicts = [entry.model_dump(mode="json") for entry in detail.results]
    payload = {
        "recommendation": {
            "recommendation_id": detail.recommendation_id,
            "catalog_id": detail.catalog_id,
            "created_at": detail.created_at,
            "base_currency": detail.base_currency,
            "config_version": detail.config_version,
            "scoring_engine_version": detail.scoring_engine_version,
            "total_supplier_count": detail.total_supplier_count,
            "eligible_count": detail.eligible_count,
            "ineligible_count": detail.ineligible_count,
            "top_supplier_id": detail.top_supplier_id,
            "top_supplier_score": detail.top_supplier_score,
        },
        "requirement": detail.requirement.model_dump(mode="json"),
        "weights": detail.weights.model_dump(mode="json"),
        "results": entry_dicts,
        "ai_narrative": detail.ai_narrative.model_dump(mode="json"),
        "methodology": detail.methodology,
    }

    stem = f"supplier_recommendation_{detail.recommendation_id[:8]}"
    if export_format is ExportFormat.JSON:
        return build_supplier_reco_json_report(payload), f"{stem}.json", "application/json"
    if export_format is ExportFormat.CSV:
        return build_supplier_reco_csv_report(entry_dicts), f"{stem}.csv", "text/csv"
    return (
        build_supplier_reco_xlsx_report(payload),
        f"{stem}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Catalogues / documentation
# ---------------------------------------------------------------------------


def get_field_catalogue() -> list[SupplierFieldDefinitionSchema]:
    """Describe every canonical supplier field, for building a mapping UI."""
    return [
        SupplierFieldDefinitionSchema(
            name=definition.name,
            label=definition.label,
            field_type=definition.field_type.value,
            required=definition.required,
            description=definition.description,
            aliases=list(definition.aliases),
            is_list_field=definition.name in LIST_FIELDS,
        )
        for definition in REGISTRY.definitions
    ]


def get_scoring_info() -> ScoringInfoSchema:
    """Return the documented scoring model: weights, formulas and eligibility."""
    config = get_supplier_reco_config()
    return ScoringInfoSchema(
        config_version=config.config_version,
        scoring_engine_version=SCORING_ENGINE_VERSION,
        base_currency=config.base_currency,
        weight_total=config.weight_total,
        default_weights=config.default_weights.as_dict(),
        dimensions=[
            ScoringDimensionInfo(
                dimension=dim,
                label=_DIMENSION_LABELS[dim],
                default_weight=config.default_weights.as_dict()[dim],
                formula=_dimension_formula(dim, config),
            )
            for dim in SCORE_DIMENSIONS
        ],
        eligibility_filters=_eligibility_descriptions(config),
        normalization=(
            "Relative dimensions (cost, delivery lead time, capacity when no quantity is given, "
            "past performance) are min-max normalised across the eligible suppliers to a 0-100 "
            "scale; missing values score 0. The overall score is the weighted sum of the nine "
            "dimensions."
        ),
        disclaimer=config.reporting.recommendation_disclaimer or supplier_reco_disclaimer(),
    )


def methodology(config: SupplierRecoConfig) -> dict[str, Any]:
    """Describe how the recommendation was produced, for the UI and the export."""
    return {
        "calculation_basis": "deterministic weighted scoring, no AI involvement in any score or rank",
        "scoring_engine_version": SCORING_ENGINE_VERSION,
        "config_version": config.config_version,
        "base_currency": config.base_currency,
        "currency_rates": config.currency_rates,
        "weight_total": config.weight_total,
        "default_weights": config.default_weights.as_dict(),
        "normalization": (
            "Relative dimensions are min-max normalised across the eligible suppliers; missing "
            "values score 0."
        ),
        "eligibility": _eligibility_descriptions(config),
        "estimated_cost_definition": "unit price (base currency) x requested quantity.",
        "estimated_delivery_definition": "order date + supplier lead time (when both are supplied).",
        "recommendation_disclaimer": config.reporting.recommendation_disclaimer,
        "data_disclaimer": (
            "All figures describe the supplier data supplied only. This application is not "
            "connected to any SAP system and no recommendation has been validated in a live SAP "
            "environment."
        ),
    }


def _dimension_formula(dim: str, config: SupplierRecoConfig) -> str:
    scoring = config.scoring
    return {
        "cost": "min-max (lower is better) of the unit price in base currency.",
        "delivery": (
            f"{scoring.delivery.on_time_weight:g} x on-time-delivery-rate + "
            f"{scoring.delivery.lead_time_weight:g} x min-max (shorter lead time is better)."
        ),
        "quality": (
            f"{scoring.quality.quality_weight:g} x quality score + "
            f"{scoring.quality.defect_weight:g} x (100 - defect_rate x "
            f"{scoring.quality.defect_rate_scale:g})."
        ),
        "capacity": (
            f"available_capacity / (quantity x {scoring.capacity.target_coverage_ratio:g}) x 100, "
            "capped at 100; min-max of capacity when no quantity is given."
        ),
        "risk": "100 - risk score (a low risk score scores highly).",
        "esg": "the ESG score, used directly.",
        "contract": (
            f"active={scoring.contract.active_score:g}, expiring={scoring.contract.expiring_score:g}, "
            f"none={scoring.contract.none_score:g}, unknown={scoring.contract.unknown_score:g}."
        ),
        "geographic": (
            "share of the specified location criteria (preferred region, requested plant) the "
            f"supplier satisfies; {scoring.geographic.no_preference_score:g} when none is specified."
        ),
        "past_performance": (
            f"{scoring.past_performance.order_weight:g} x min-max of the historical order count + "
            f"{scoring.past_performance.spend_weight:g} x min-max of the historical spend."
        ),
    }[dim]


def _eligibility_descriptions(config: SupplierRecoConfig) -> list[str]:
    settings = config.eligibility
    items: list[str] = []
    if settings.enforce_material_match:
        items.append("Supplier must supply the requested material.")
    if settings.enforce_plant_match:
        items.append("Supplier must serve the requested plant (when it lists plants).")
    if settings.enforce_min_capacity:
        items.append("Available capacity must meet the requested minimum and cover the quantity.")
    if settings.enforce_min_quality:
        items.append("Quality score must meet the requested minimum.")
    if settings.enforce_risk_tolerance:
        tolerances = ", ".join(
            f"{k}<={v:g}" for k, v in settings.risk_tolerance_max_score.items()
        )
        items.append(f"Risk score must sit within the risk tolerance ceiling ({tolerances}).")
    if settings.enforce_sustainability:
        items.append("ESG score must meet the sustainability requirement (minimum ESG).")
    if settings.enforce_contract_requirement:
        items.append("Supplier must hold an active contract when the requirement demands one.")
    return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_recommendation(db: Session, recommendation_id: str) -> SupplierRecommendation:
    recommendation = db.get(SupplierRecommendation, recommendation_id)
    if recommendation is None:
        raise NotFoundError(f"Recommendation '{recommendation_id}' was not found.")
    return recommendation


def _load_suppliers(db: Session, catalog_id: str) -> list[NormalizedSupplier]:
    """Rebuild the normalised supplier records from the persisted catalogue."""
    rows = db.scalars(
        select(Supplier).where(Supplier.catalog_id == catalog_id).order_by(Supplier.supplier_id)
    ).all()
    return [_supplier_from_row(row) for row in rows]


def _supplier_from_row(row: Supplier) -> NormalizedSupplier:
    return NormalizedSupplier(
        row_number=row.row_number,
        supplier_id=row.supplier_id,
        supplier_name=row.supplier_name,
        materials_supplied=list(row.materials_supplied or []),
        plants_served=list(row.plants_served or []),
        regions_served=list(row.regions_served or []),
        unit_price=row.unit_price,
        currency=row.currency,
        unit_price_base=row.unit_price_base,
        lead_time_days=row.lead_time_days,
        available_capacity=row.available_capacity,
        on_time_delivery_rate=row.on_time_delivery_rate,
        quality_score=row.quality_score,
        defect_rate=row.defect_rate,
        risk_score=row.risk_score,
        esg_score=row.esg_score,
        contract_status=row.contract_status,
        contract_expiration=row.contract_expiration,
        payment_terms=row.payment_terms,
        historical_order_count=row.historical_order_count,
        historical_spend=row.historical_spend,
        historical_spend_base=row.historical_spend_base,
    )


def _supplier_schema(row: Supplier) -> SupplierSchema:
    return SupplierSchema(
        supplier_id=row.supplier_id,
        supplier_name=row.supplier_name,
        catalog_id=row.catalog_id,
        materials_supplied=list(row.materials_supplied or []),
        plants_served=list(row.plants_served or []),
        regions_served=list(row.regions_served or []),
        unit_price=row.unit_price,
        currency=row.currency,
        unit_price_base=row.unit_price_base,
        lead_time_days=row.lead_time_days,
        available_capacity=row.available_capacity,
        on_time_delivery_rate=row.on_time_delivery_rate,
        quality_score=row.quality_score,
        defect_rate=row.defect_rate,
        risk_score=row.risk_score,
        esg_score=row.esg_score,
        contract_status=row.contract_status,
        contract_expiration=row.contract_expiration,
        payment_terms=row.payment_terms,
        historical_order_count=row.historical_order_count,
        historical_spend=row.historical_spend,
        historical_spend_base=row.historical_spend_base,
    )


def _entry_schema_from_ranked(entry: RankedSupplier) -> RecommendationEntrySchema:
    return RecommendationEntrySchema(**entry.to_dict())


def _entry_schema_from_row(row: SupplierRecommendationEntry) -> RecommendationEntrySchema:
    return RecommendationEntrySchema(
        supplier_id=row.supplier_id,
        supplier_name=row.supplier_name,
        rank=row.rank,
        eligibility_status=row.eligibility_status,
        is_eligible=row.is_eligible,
        overall_score=row.overall_score,
        cost_score=row.cost_score,
        delivery_score=row.delivery_score,
        quality_score=row.quality_score,
        capacity_score=row.capacity_score,
        risk_score=row.risk_score,
        esg_score=row.esg_score,
        contract_score=row.contract_score,
        geographic_score=row.geographic_score,
        past_performance_score=row.past_performance_score,
        estimated_unit_price_base=row.estimated_unit_price_base,
        estimated_total_cost_base=float(row.estimated_total_cost_base)
        if row.estimated_total_cost_base is not None
        else None,
        estimated_delivery_date=row.estimated_delivery_date,
        lead_time_days=row.lead_time_days,
        contract_status=row.contract_status,
        contract_classification=row.contract_classification,
        advantages=list(row.advantages or []),
        risks=list(row.risks or []),
        explanation=row.explanation,
        ineligibility_reasons=list(row.ineligibility_reasons or []),
        evidence=row.evidence or {},
    )


def _narrative_from_row(row: SupplierRecommendation) -> SupplierRecoAiNarrativeSchema:
    return SupplierRecoAiNarrativeSchema(
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


def _to_detail_schema(
    recommendation: SupplierRecommendation,
    entries: list[RecommendationEntrySchema],
    narrative: SupplierRecoAiNarrativeSchema,
    config: SupplierRecoConfig,
) -> RecommendationDetailSchema:
    return RecommendationDetailSchema(
        recommendation_id=recommendation.id,
        catalog_id=recommendation.catalog_id,
        status=recommendation.status,
        created_at=recommendation.created_at,
        completed_at=recommendation.completed_at,
        duration_ms=recommendation.duration_ms,
        config_version=recommendation.config_version,
        scoring_engine_version=recommendation.scoring_engine_version,
        base_currency=recommendation.base_currency,
        requirement=RequirementSchema(**(recommendation.requirement or {})),
        weights=WeightsSchema(**(recommendation.weights or config.default_weights.as_dict())),
        total_supplier_count=recommendation.total_supplier_count,
        eligible_count=recommendation.eligible_count,
        ineligible_count=recommendation.ineligible_count,
        top_supplier_id=recommendation.top_supplier_id,
        top_supplier_score=recommendation.top_supplier_score,
        results=entries,
        ai_narrative=narrative,
        methodology=methodology(config),
        disclaimer=config.reporting.recommendation_disclaimer or supplier_reco_disclaimer(),
    )


def _contains(haystack: list[str] | None, needle: str) -> bool:
    if not haystack:
        return False
    wanted = needle.strip().lower()
    return any(str(item).strip().lower() == wanted for item in haystack)
