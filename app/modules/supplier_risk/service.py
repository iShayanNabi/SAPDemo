"""Orchestration for the Supplier Risk Copilot.

This is the only layer that knows about the database. It wires the shared
services together in one direction:

    validate upload -> read file -> suggest mapping -> normalise -> persist
    -> run the deterministic engine -> persist -> optional AI narrative

The engine and the copilot stay pure, so they can be tested without a database
and reused unchanged by a future React front end talking to the same API.
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
from app.models.po_risk import UploadedFile
from app.models.supplier_risk import (
    SupplierRiskAssessment,
    SupplierRiskDataset,
    SupplierRiskProfileRow,
    SupplierRiskRecord,
)
from app.modules.supplier_risk.ai_narrative import SupplierRiskNarrativeService
from app.modules.supplier_risk.copilot import (
    CopilotIntent,
    answer_question,
)
from app.modules.supplier_risk.engine import (
    ENGINE_VERSION,
    RecommendedAction,
    RiskAssessmentResult,
    RiskTrend,
    SupplierRiskProfile,
    run_risk_assessment,
)
from app.modules.supplier_risk.field_definitions import (
    EVENT_REGISTRY,
    INHERITED_FIELDS,
    REGISTRY,
)
from app.modules.supplier_risk.normalizer import (
    NormalizedRiskEvent,
    NormalizedSupplierProfile,
    normalize_risk_event_dataframe,
    normalize_supplier_risk_dataframe,
)
from app.modules.supplier_risk.scoring import (
    CategoryScore,
    MetricContribution,
    SupplierRiskScore,
)
from app.modules.supplier_risk.thresholds import (
    RISK_CATEGORIES,
    CategoryWeights,
    SupplierRiskConfig,
    get_supplier_risk_config,
)
from app.schemas.common import OutputOrigin
from app.schemas.supplier_risk import (
    CalculateRiskRequest,
    CategoryScoreSchema,
    ChatRequest,
    ChatResponse,
    CitationSchema,
    ColumnSuggestionSchema,
    DataQualityIssueSchema,
    MetricContributionSchema,
    RecommendedActionSchema,
    RiskAssessmentDetailSchema,
    RiskAssessmentSummarySchema,
    RiskCategoryInfoSchema,
    RiskDatasetKind,
    RiskEventSchema,
    RiskScoringInfoSchema,
    RiskTrendSchema,
    RiskWeightsSchema,
    SupplierRiskAiNarrativeSchema,
    SupplierRiskDatasetSchema,
    SupplierRiskFieldDefinitionSchema,
    SupplierRiskProfileSchema,
    SupplierRiskSummarySchema,
    SupplierRiskUploadResponse,
)
from app.services.files.readers import preview_records, read_tabular
from app.services.files.storage import store_upload
from app.services.files.validation import validate_upload
from app.services.tabular.mapping import suggest_mapping

logger = get_logger(__name__)

PREVIEW_ROW_LIMIT = 10

#: Category name -> the column that holds its score on ``SupplierRiskProfileRow``.
_CATEGORY_COLUMNS = {name: f"{name}_score" for name in RISK_CATEGORIES}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def handle_upload(
    db: Session,
    filename: str,
    content: bytes,
    dataset: RiskDatasetKind = RiskDatasetKind.PROFILES,
    dataset_id: str | None = None,
) -> SupplierRiskUploadResponse:
    """Validate, store and load a supplier risk file.

    ``profiles`` creates a new dataset. ``events`` attaches dated internal
    records to an existing dataset - the most recent one unless told otherwise.
    """
    config = get_supplier_risk_config()
    validated = validate_upload(filename, content)
    read_result = read_tabular(validated.content, validated.extension)

    registry = REGISTRY if dataset is RiskDatasetKind.PROFILES else EVENT_REGISTRY
    mapping_result = suggest_mapping(read_result.source_columns, registry)
    stored = store_upload(validated)

    upload = UploadedFile(
        id=uuid.uuid4().hex[:32],
        module=f"supplier_risk:{dataset.value}",
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
        name for name in registry.required if name not in set(mapping_result.mapping.values())
    ]

    response = SupplierRiskUploadResponse(
        upload_id=upload.id,
        dataset=dataset,
        filename=validated.original_filename,
        file_extension=validated.extension,
        size_bytes=validated.size_bytes,
        row_count=read_result.row_count,
        detected_columns=list(read_result.source_columns),
        suggested_mapping=dict(mapping_result.mapping),
        suggestions=[
            ColumnSuggestionSchema(
                source_column=item.source_column,
                canonical_field=item.canonical_field,
                confidence=item.confidence,
                strategy=item.strategy,
            )
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
        logger.info(
            "Supplier risk %s upload stored but not loaded: missing %s",
            dataset.value,
            missing_required,
        )
        return response

    if dataset is RiskDatasetKind.PROFILES:
        loaded = normalize_supplier_risk_dataframe(
            read_result.dataframe, mapping_result.mapping, config
        )
        record = SupplierRiskDataset(
            id=uuid.uuid4().hex[:32],
            upload_id=upload.id,
            source_filename=validated.original_filename,
            config_version=config.config_version,
            base_currency=config.base_currency,
            applied_mapping=dict(mapping_result.mapping),
            unmapped_columns=list(mapping_result.unmapped_columns),
            data_quality_issues=loaded.issues_as_dicts(),
            supplier_count=loaded.profile_count,
        )
        db.add(record)
        db.flush()
        db.bulk_insert_mappings(
            SupplierRiskRecord,
            [
                {
                    "dataset_id": record.id,
                    "row_number": profile.row_number,
                    "supplier_id": profile.supplier_id,
                    "supplier_name": profile.supplier_name,
                    "country": profile.country,
                    "spend_category": profile.spend_category,
                    "payload": profile.to_record(),
                    "events": [],
                }
                for profile in loaded.profiles
            ],
        )
        response.dataset_id = record.id
        response.supplier_count = loaded.profile_count
        response.data_quality_issues = [
            DataQualityIssueSchema(**issue) for issue in loaded.issues_as_dicts()
        ]
        db.commit()
        logger.info(
            "Loaded supplier risk dataset %s with %d suppliers", record.id, loaded.profile_count
        )
        return response

    # Events attach to an existing dataset.
    target = _resolve_dataset(db, dataset_id)
    loaded_events = normalize_risk_event_dataframe(
        read_result.dataframe, mapping_result.mapping, config
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in loaded_events.events:
        grouped.setdefault(event.supplier_id, []).append(event.to_record())

    rows = db.execute(
        select(SupplierRiskRecord).where(SupplierRiskRecord.dataset_id == target.id)
    ).scalars().all()
    attached = 0
    for row in rows:
        events = grouped.get(row.supplier_id, [])
        row.events = events
        attached += len(events)

    target.event_upload_id = upload.id
    target.event_filename = validated.original_filename
    target.applied_event_mapping = dict(mapping_result.mapping)
    target.event_count = attached
    existing_issues = list(target.data_quality_issues or [])
    target.data_quality_issues = existing_issues + loaded_events.issues_as_dicts()

    response.dataset_id = target.id
    response.event_count = attached
    response.supplier_count = target.supplier_count
    response.data_quality_issues = [
        DataQualityIssueSchema(**issue) for issue in loaded_events.issues_as_dicts()
    ]
    db.commit()

    unmatched = loaded_events.event_count - attached
    if unmatched:
        logger.info(
            "%d risk event(s) did not match a supplier in dataset %s", unmatched, target.id
        )
    logger.info("Attached %d risk events to dataset %s", attached, target.id)
    return response


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------


def _resolve_dataset(db: Session, dataset_id: str | None) -> SupplierRiskDataset:
    """Return a dataset by id, or the most recent one."""
    if dataset_id:
        dataset = db.get(SupplierRiskDataset, dataset_id)
        if dataset is None:
            raise NotFoundError(
                "That supplier risk dataset does not exist.",
                details={"dataset_id": dataset_id},
            )
        return dataset

    dataset = db.execute(
        select(SupplierRiskDataset).order_by(SupplierRiskDataset.created_at.desc()).limit(1)
    ).scalars().first()
    if dataset is None:
        raise NotFoundError(
            "No supplier risk data has been uploaded yet. Upload a supplier risk profile "
            "file first."
        )
    return dataset


def _require_assessment(db: Session, assessment_id: str | None) -> SupplierRiskAssessment:
    """Return an assessment by id, or the most recent one."""
    if assessment_id:
        assessment = db.get(SupplierRiskAssessment, assessment_id)
        if assessment is None:
            raise NotFoundError(
                "That risk assessment does not exist.",
                details={"assessment_id": assessment_id},
            )
        return assessment

    assessment = db.execute(
        select(SupplierRiskAssessment).order_by(SupplierRiskAssessment.created_at.desc()).limit(1)
    ).scalars().first()
    if assessment is None:
        raise NotFoundError(
            "No risk assessment has been run yet. Run a risk calculation first."
        )
    return assessment


def _resolve_weights(
    weights: RiskWeightsSchema | None, config: SupplierRiskConfig
) -> CategoryWeights:
    """Validate supplied weights, or fall back to the configured defaults."""
    if weights is None:
        return config.default_weights
    resolved = CategoryWeights(**weights.model_dump())
    config.validate_weights(resolved)
    return resolved


def _load_records(
    db: Session, dataset_id: str
) -> tuple[list[NormalizedSupplierProfile], list[NormalizedRiskEvent]]:
    """Rebuild the engine's inputs from the stored dataset."""
    rows = db.execute(
        select(SupplierRiskRecord)
        .where(SupplierRiskRecord.dataset_id == dataset_id)
        .order_by(SupplierRiskRecord.supplier_id)
    ).scalars().all()

    profiles: list[NormalizedSupplierProfile] = []
    events: list[NormalizedRiskEvent] = []
    for row in rows:
        profiles.append(_profile_from_payload(row.payload or {}))
        for event in row.events or []:
            events.append(_event_from_payload(event))
    return profiles, events


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _profile_from_payload(payload: dict[str, Any]) -> NormalizedSupplierProfile:
    """Rebuild a normalised profile from its stored JSON."""
    date_fields = {"contract_expiration", "last_audit_date"}
    list_fields = {"materials_supplied", "plants_served", "regions_served"}
    kwargs: dict[str, Any] = {
        "row_number": int(payload.get("row_number") or 0),
        "supplier_id": str(payload.get("supplier_id") or ""),
    }
    for name in REGISTRY.names:
        if name == "supplier_id":
            continue
        value = payload.get(name)
        if name in date_fields:
            kwargs[name] = _as_date(value)
        elif name in list_fields:
            kwargs[name] = list(value or [])
        else:
            kwargs[name] = value
    kwargs["historical_spend_base"] = payload.get("historical_spend_base")
    return NormalizedSupplierProfile(**kwargs)


def _event_from_payload(payload: dict[str, Any]) -> NormalizedRiskEvent:
    """Rebuild a normalised event from its stored JSON."""
    return NormalizedRiskEvent(
        row_number=int(payload.get("row_number") or 0),
        event_id=str(payload.get("event_id") or ""),
        supplier_id=str(payload.get("supplier_id") or ""),
        event_type=str(payload.get("event_type") or ""),
        event_date=_as_date(payload.get("event_date")),
        reference=payload.get("reference"),
        severity=payload.get("severity"),
        description=payload.get("description"),
        amount=payload.get("amount"),
        currency=payload.get("currency"),
        amount_base=payload.get("amount_base"),
    )


# ---------------------------------------------------------------------------
# Calculate
# ---------------------------------------------------------------------------


def calculate(db: Session, request: CalculateRiskRequest) -> RiskAssessmentDetailSchema:
    """Score every supplier in a dataset and persist the assessment."""
    started = time.perf_counter()
    config = get_supplier_risk_config()
    dataset = _resolve_dataset(db, request.dataset_id)

    profiles, events = _load_records(db, dataset.id)
    if not profiles:
        raise ValidationError(
            "That supplier risk dataset contains no suppliers to assess.",
            details={"dataset_id": dataset.id},
        )

    weights = _resolve_weights(request.weights, config)
    as_of = request.as_of_date or date.today()

    result = run_risk_assessment(profiles, events, weights, config, as_of)

    assessment = SupplierRiskAssessment(
        id=uuid.uuid4().hex[:32],
        dataset_id=dataset.id,
        status="completed",
        source_filename=dataset.source_filename,
        config_version=config.config_version,
        engine_version=ENGINE_VERSION,
        weights=weights.as_dict(),
        as_of_date=as_of,
        base_currency=config.base_currency,
        supplier_count=result.supplier_count,
        scored_count=result.scored_count,
        event_count=result.event_count,
        band_counts=dict(result.band_counts),
        category_averages=dict(result.category_averages),
        average_overall_score=result.average_overall_score,
        highest_risk_supplier_id=result.highest_risk_supplier_id,
        highest_risk_score=result.highest_risk_score,
        contracts_expiring_count=result.contracts_expiring_count,
        limited_data_count=result.limited_data_count,
        rule_errors=list(result.rule_errors),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(assessment)
    db.flush()

    ranked = _rank(result.profiles)
    db.bulk_insert_mappings(
        SupplierRiskProfileRow,
        [_profile_row(assessment.id, profile, rank) for profile, rank in ranked],
    )

    narrative = SupplierRiskAiNarrativeSchema()
    if request.generate_ai_summary:
        outcome = SupplierRiskNarrativeService().generate(
            assessment_summary=_summary_payload(result),
            top_suppliers=[
                _ai_supplier_payload(profile) for profile, _ in ranked[:5]
            ],
            category_averages=dict(result.category_averages),
        )
        assessment.ai_provider = outcome.provider
        assessment.ai_output_origin = outcome.origin.value if outcome.origin else None
        assessment.ai_prompt_version = outcome.prompt_version
        assessment.ai_summary = outcome.summary
        assessment.ai_key_findings = list(outcome.key_findings)
        assessment.ai_recommended_actions = list(outcome.recommended_actions)
        assessment.ai_input_tokens = outcome.input_tokens
        assessment.ai_output_tokens = outcome.output_tokens
        assessment.ai_estimated_cost_usd = outcome.estimated_cost_usd
        assessment.ai_error = outcome.error
        narrative = SupplierRiskAiNarrativeSchema(
            available=outcome.available,
            origin=outcome.origin,
            provider=outcome.provider,
            prompt_version=outcome.prompt_version,
            summary=outcome.summary,
            key_findings=list(outcome.key_findings),
            recommended_actions=list(outcome.recommended_actions),
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            estimated_cost_usd=outcome.estimated_cost_usd,
            error=outcome.error,
        )

    assessment.duration_ms = int((time.perf_counter() - started) * 1000)
    db.commit()
    db.refresh(assessment)

    return _assessment_detail(
        assessment,
        [_summary_schema_from_profile(profile, rank) for profile, rank in ranked],
        narrative,
        config,
    )


def _rank(profiles: list[SupplierRiskProfile]) -> list[tuple[SupplierRiskProfile, int | None]]:
    """Order suppliers by descending risk; unscored suppliers keep no rank."""
    scored = [item for item in profiles if item.overall_score is not None]
    unscored = [item for item in profiles if item.overall_score is None]
    scored.sort(key=lambda item: (-(item.overall_score or 0.0), item.supplier_id))
    unscored.sort(key=lambda item: item.supplier_id)
    ranked: list[tuple[SupplierRiskProfile, int | None]] = [
        (item, index) for index, item in enumerate(scored, start=1)
    ]
    ranked.extend((item, None) for item in unscored)
    return ranked


def _profile_row(
    assessment_id: str, profile: SupplierRiskProfile, rank: int | None
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "assessment_id": assessment_id,
        "supplier_id": profile.supplier_id,
        "supplier_name": profile.supplier_name,
        "country": profile.country,
        "spend_category": profile.spend_category,
        "overall_score": profile.overall_score,
        "overall_band": profile.overall_band,
        "rank": rank,
        "trend_direction": profile.trend.direction,
        "trend_delta": profile.trend.delta,
        "data_completeness_pct": profile.score.data_completeness_pct,
        "limited_data": profile.score.limited_data,
        "total_spend_base": profile.total_spend_base,
        "purchase_order_count": profile.purchase_order_count,
        "active_contract_count": profile.active_contract_count,
        "contract_status": profile.contract_status,
        "contract_expiration": profile.contract_expiration,
        "contract_expiring_soon": profile.contract_expiring_soon,
        "on_time_delivery_rate": profile.on_time_delivery_rate,
        "late_delivery_count": profile.late_delivery_count,
        "invoice_exception_count": profile.invoice_exception_count,
        "breakdown": profile.to_dict(),
        "output_origin": OutputOrigin.RULE_BASED.value,
    }
    for name, column in _CATEGORY_COLUMNS.items():
        row[column] = profile.category_score(name)
    return row


def _summary_payload(result: RiskAssessmentResult) -> dict[str, Any]:
    return {
        "supplier_count": result.supplier_count,
        "scored_count": result.scored_count,
        "event_count": result.event_count,
        "band_counts": dict(result.band_counts),
        "average_overall_score": result.average_overall_score,
        "contracts_expiring_count": result.contracts_expiring_count,
        "limited_data_count": result.limited_data_count,
        "as_of_date": result.as_of_date.isoformat() if result.as_of_date else None,
    }


def _ai_supplier_payload(profile: SupplierRiskProfile) -> dict[str, Any]:
    return {
        "supplier_id": profile.supplier_id,
        "supplier_name": profile.supplier_name,
        "overall_score": profile.overall_score,
        "overall_band": profile.overall_band,
        "trend": profile.trend.direction,
        "top_drivers": [
            {"label": item.label, "score": item.score}
            for item in profile.score.top_drivers(3)
        ],
        "actions": [action.action for action in profile.actions],
    }


# ---------------------------------------------------------------------------
# Row -> schema mappers
# ---------------------------------------------------------------------------


def _summary_schema_from_profile(
    profile: SupplierRiskProfile, rank: int | None
) -> SupplierRiskSummarySchema:
    return SupplierRiskSummarySchema(
        supplier_id=profile.supplier_id,
        supplier_name=profile.supplier_name,
        country=profile.country,
        spend_category=profile.spend_category,
        overall_score=profile.overall_score,
        overall_band=profile.overall_band,
        rank=rank,
        trend_direction=profile.trend.direction,
        data_completeness_pct=profile.score.data_completeness_pct,
        limited_data=profile.score.limited_data,
        total_spend_base=profile.total_spend_base,
        contract_status=profile.contract_status,
        contract_expiration=profile.contract_expiration,
        contract_expiring_soon=profile.contract_expiring_soon,
        on_time_delivery_rate=profile.on_time_delivery_rate,
        late_delivery_count=profile.late_delivery_count,
        invoice_exception_count=profile.invoice_exception_count,
        category_scores={name: profile.category_score(name) for name in RISK_CATEGORIES},
    )


def _summary_schema_from_row(row: SupplierRiskProfileRow) -> SupplierRiskSummarySchema:
    return SupplierRiskSummarySchema(
        supplier_id=row.supplier_id,
        supplier_name=row.supplier_name,
        country=row.country,
        spend_category=row.spend_category,
        overall_score=row.overall_score,
        overall_band=row.overall_band,
        rank=row.rank,
        trend_direction=row.trend_direction,
        data_completeness_pct=row.data_completeness_pct,
        limited_data=row.limited_data,
        total_spend_base=float(row.total_spend_base) if row.total_spend_base is not None else None,
        contract_status=row.contract_status,
        contract_expiration=row.contract_expiration,
        contract_expiring_soon=row.contract_expiring_soon,
        on_time_delivery_rate=row.on_time_delivery_rate,
        late_delivery_count=row.late_delivery_count,
        invoice_exception_count=row.invoice_exception_count,
        category_scores={
            name: getattr(row, column) for name, column in _CATEGORY_COLUMNS.items()
        },
    )


def _category_schema(data: dict[str, Any]) -> CategoryScoreSchema:
    return CategoryScoreSchema(
        category=data.get("category", ""),
        label=data.get("label", ""),
        description=data.get("description", ""),
        score=data.get("score"),
        band=data.get("band"),
        weight=data.get("weight", 0.0),
        normalized_weight=data.get("normalized_weight", 0.0),
        contribution=data.get("contribution", 0.0),
        data_available=data.get("data_available", False),
        metrics=[MetricContributionSchema(**metric) for metric in data.get("metrics", [])],
        missing_metrics=list(data.get("missing_metrics", [])),
    )


def _profile_schema_from_row(row: SupplierRiskProfileRow) -> SupplierRiskProfileSchema:
    """Rebuild the full profile schema from the stored engine breakdown."""
    breakdown: dict[str, Any] = row.breakdown or {}
    score_data: dict[str, Any] = breakdown.get("score", {}) or {}
    categories_data: dict[str, Any] = score_data.get("categories", {}) or {}
    trend_data: dict[str, Any] = breakdown.get("trend", {}) or {}

    categories = [
        _category_schema(categories_data[name])
        for name in RISK_CATEGORIES
        if name in categories_data
    ]

    return SupplierRiskProfileSchema(
        supplier_id=row.supplier_id,
        supplier_name=row.supplier_name,
        country=row.country,
        spend_category=row.spend_category,
        materials_supplied=list(breakdown.get("materials_supplied", [])),
        regions_served=list(breakdown.get("regions_served", [])),
        overall_score=row.overall_score,
        overall_band=row.overall_band,
        rank=row.rank,
        data_completeness_pct=row.data_completeness_pct,
        limited_data=row.limited_data,
        weights_used=dict(score_data.get("weights_used", {})),
        categories=categories,
        scored_categories=list(score_data.get("scored_categories", [])),
        unscored_categories=list(score_data.get("unscored_categories", [])),
        trend=RiskTrendSchema(**trend_data) if trend_data else None,
        actions=[RecommendedActionSchema(**action) for action in breakdown.get("actions", [])],
        total_spend=breakdown.get("total_spend"),
        total_spend_base=breakdown.get("total_spend_base"),
        currency=breakdown.get("currency"),
        purchase_order_count=breakdown.get("purchase_order_count"),
        open_purchase_order_count=breakdown.get("open_purchase_order_count"),
        active_contract_count=breakdown.get("active_contract_count"),
        contract_status=breakdown.get("contract_status"),
        contract_expiration=_as_date(breakdown.get("contract_expiration")),
        contract_number=breakdown.get("contract_number"),
        days_to_contract_expiry=breakdown.get("days_to_contract_expiry"),
        contract_expiring_soon=bool(breakdown.get("contract_expiring_soon")),
        on_time_delivery_rate=breakdown.get("on_time_delivery_rate"),
        late_delivery_count=breakdown.get("late_delivery_count"),
        delivery_count=breakdown.get("delivery_count"),
        quality_score=breakdown.get("quality_score"),
        defect_rate=breakdown.get("defect_rate"),
        quality_incident_count=breakdown.get("quality_incident_count"),
        invoice_count=breakdown.get("invoice_count"),
        invoice_exception_count=breakdown.get("invoice_exception_count"),
        disputed_invoice_count=breakdown.get("disputed_invoice_count"),
        compliance_finding_count=breakdown.get("compliance_finding_count"),
        esg_score=breakdown.get("esg_score"),
        credit_score=breakdown.get("credit_score"),
        delivery_issues=[RiskEventSchema(**item) for item in breakdown.get("delivery_issues", [])],
        invoice_issues=[RiskEventSchema(**item) for item in breakdown.get("invoice_issues", [])],
        quality_issues=[RiskEventSchema(**item) for item in breakdown.get("quality_issues", [])],
        compliance_issues=[
            RiskEventSchema(**item) for item in breakdown.get("compliance_issues", [])
        ],
        event_count=breakdown.get("event_count", 0),
    )


def _assessment_detail(
    assessment: SupplierRiskAssessment,
    suppliers: list[SupplierRiskSummarySchema],
    narrative: SupplierRiskAiNarrativeSchema,
    config: SupplierRiskConfig,
) -> RiskAssessmentDetailSchema:
    return RiskAssessmentDetailSchema(
        assessment_id=assessment.id,
        dataset_id=assessment.dataset_id,
        status=assessment.status,
        source_filename=assessment.source_filename,
        config_version=assessment.config_version,
        engine_version=assessment.engine_version,
        as_of_date=assessment.as_of_date,
        base_currency=assessment.base_currency,
        weights=dict(assessment.weights or {}),
        summary=RiskAssessmentSummarySchema(
            supplier_count=assessment.supplier_count,
            scored_count=assessment.scored_count,
            event_count=assessment.event_count,
            band_counts=dict(assessment.band_counts or {}),
            category_averages=dict(assessment.category_averages or {}),
            average_overall_score=assessment.average_overall_score,
            highest_risk_supplier_id=assessment.highest_risk_supplier_id,
            highest_risk_score=assessment.highest_risk_score,
            contracts_expiring_count=assessment.contracts_expiring_count,
            limited_data_count=assessment.limited_data_count,
        ),
        suppliers=suppliers,
        rule_errors=list(assessment.rule_errors or []),
        ai_narrative=narrative,
        duration_ms=assessment.duration_ms,
        created_at=assessment.created_at,
        disclaimer=config.reporting.risk_disclaimer,
    )


def _narrative_from_row(assessment: SupplierRiskAssessment) -> SupplierRiskAiNarrativeSchema:
    if not assessment.ai_summary and not assessment.ai_error:
        return SupplierRiskAiNarrativeSchema()
    return SupplierRiskAiNarrativeSchema(
        available=assessment.ai_summary is not None,
        origin=(
            OutputOrigin(assessment.ai_output_origin) if assessment.ai_output_origin else None
        ),
        provider=assessment.ai_provider,
        prompt_version=assessment.ai_prompt_version,
        summary=assessment.ai_summary,
        key_findings=list(assessment.ai_key_findings or []),
        recommended_actions=list(assessment.ai_recommended_actions or []),
        input_tokens=assessment.ai_input_tokens,
        output_tokens=assessment.ai_output_tokens,
        estimated_cost_usd=assessment.ai_estimated_cost_usd,
        error=assessment.ai_error,
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_assessment(db: Session, assessment_id: str | None) -> RiskAssessmentDetailSchema:
    """Return one assessment with its ranked suppliers."""
    config = get_supplier_risk_config()
    assessment = _require_assessment(db, assessment_id)
    rows = db.execute(
        select(SupplierRiskProfileRow)
        .where(SupplierRiskProfileRow.assessment_id == assessment.id)
        .order_by(
            SupplierRiskProfileRow.rank.is_(None),
            SupplierRiskProfileRow.rank,
            SupplierRiskProfileRow.supplier_id,
        )
    ).scalars().all()
    return _assessment_detail(
        assessment,
        [_summary_schema_from_row(row) for row in rows],
        _narrative_from_row(assessment),
        config,
    )


def list_assessments(
    db: Session, limit: int = 20, offset: int = 0
) -> tuple[int, list[RiskAssessmentDetailSchema]]:
    """Return previous assessments, newest first, without their supplier lists."""
    config = get_supplier_risk_config()
    total = db.execute(select(func.count(SupplierRiskAssessment.id))).scalar_one()
    rows = db.execute(
        select(SupplierRiskAssessment)
        .order_by(SupplierRiskAssessment.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return total, [
        _assessment_detail(row, [], _narrative_from_row(row), config) for row in rows
    ]


def list_suppliers(
    db: Session,
    assessment_id: str | None = None,
    band: str | None = None,
    country: str | None = None,
    spend_category: str | None = None,
    expiring_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[str, str, int, list[SupplierRiskSummarySchema]]:
    """Return assessed suppliers, highest risk first."""
    assessment = _require_assessment(db, assessment_id)

    conditions = [SupplierRiskProfileRow.assessment_id == assessment.id]
    if band:
        conditions.append(SupplierRiskProfileRow.overall_band == band.strip().lower())
    if country:
        conditions.append(SupplierRiskProfileRow.country == country.strip())
    if spend_category:
        conditions.append(SupplierRiskProfileRow.spend_category == spend_category.strip())
    if expiring_only:
        conditions.append(SupplierRiskProfileRow.contract_expiring_soon.is_(True))

    total = db.execute(
        select(func.count(SupplierRiskProfileRow.id)).where(*conditions)
    ).scalar_one()
    rows = db.execute(
        select(SupplierRiskProfileRow)
        .where(*conditions)
        .order_by(
            SupplierRiskProfileRow.rank.is_(None),
            SupplierRiskProfileRow.rank,
            SupplierRiskProfileRow.supplier_id,
        )
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return (
        assessment.id,
        assessment.dataset_id,
        total,
        [_summary_schema_from_row(row) for row in rows],
    )


def get_supplier(
    db: Session, supplier_id: str, assessment_id: str | None = None
) -> SupplierRiskProfileSchema:
    """Return one supplier's complete risk profile."""
    assessment = _require_assessment(db, assessment_id)
    row = db.execute(
        select(SupplierRiskProfileRow).where(
            SupplierRiskProfileRow.assessment_id == assessment.id,
            SupplierRiskProfileRow.supplier_id == supplier_id,
        )
    ).scalars().first()
    if row is None:
        raise NotFoundError(
            "That supplier is not in this risk assessment.",
            details={"supplier_id": supplier_id, "assessment_id": assessment.id},
        )
    return _profile_schema_from_row(row)


def list_datasets(db: Session) -> list[SupplierRiskDatasetSchema]:
    """Return every uploaded dataset, newest first."""
    rows = db.execute(
        select(SupplierRiskDataset).order_by(SupplierRiskDataset.created_at.desc())
    ).scalars().all()
    return [
        SupplierRiskDatasetSchema(
            id=row.id,
            source_filename=row.source_filename,
            event_filename=row.event_filename,
            supplier_count=row.supplier_count,
            event_count=row.event_count,
            config_version=row.config_version,
            base_currency=row.base_currency,
            created_at=row.created_at,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------


def _assessment_to_result(
    db: Session, assessment: SupplierRiskAssessment
) -> RiskAssessmentResult:
    """Rebuild the engine result from persisted rows, so the copilot answers
    from exactly the figures that were stored."""
    rows = db.execute(
        select(SupplierRiskProfileRow)
        .where(SupplierRiskProfileRow.assessment_id == assessment.id)
        .order_by(
            SupplierRiskProfileRow.rank.is_(None),
            SupplierRiskProfileRow.rank,
            SupplierRiskProfileRow.supplier_id,
        )
    ).scalars().all()

    profiles: list[SupplierRiskProfile] = []
    for row in rows:
        breakdown = row.breakdown or {}
        score_data = breakdown.get("score", {}) or {}
        categories: dict[str, CategoryScore] = {}
        for name, data in (score_data.get("categories", {}) or {}).items():
            categories[name] = CategoryScore(
                category=data.get("category", name),
                label=data.get("label", name),
                description=data.get("description", ""),
                score=data.get("score"),
                band=data.get("band"),
                weight=data.get("weight", 0.0),
                normalized_weight=data.get("normalized_weight", 0.0),
                contribution=data.get("contribution", 0.0),
                data_available=data.get("data_available", False),
                metrics=[MetricContribution(**metric) for metric in data.get("metrics", [])],
                missing_metrics=list(data.get("missing_metrics", [])),
            )

        score = SupplierRiskScore(
            supplier_id=row.supplier_id,
            overall_score=row.overall_score,
            overall_band=row.overall_band,
            categories=categories,
            scored_categories=list(score_data.get("scored_categories", [])),
            unscored_categories=list(score_data.get("unscored_categories", [])),
            data_completeness_pct=row.data_completeness_pct,
            limited_data=row.limited_data,
            weights_used=dict(score_data.get("weights_used", {})),
        )
        trend_data = breakdown.get("trend", {}) or {}
        trend = RiskTrend(
            direction=trend_data.get("direction", "unknown"),
            recent_weight=trend_data.get("recent_weight", 0.0),
            previous_weight=trend_data.get("previous_weight", 0.0),
            delta=trend_data.get("delta", 0.0),
            recent_event_count=trend_data.get("recent_event_count", 0),
            previous_event_count=trend_data.get("previous_event_count", 0),
            window_days=trend_data.get("window_days", 0),
            basis=trend_data.get("basis", ""),
            data_available=trend_data.get("data_available", False),
        )

        profile = SupplierRiskProfile(
            supplier_id=row.supplier_id,
            supplier_name=row.supplier_name,
            country=row.country,
            spend_category=row.spend_category,
            materials_supplied=list(breakdown.get("materials_supplied", [])),
            regions_served=list(breakdown.get("regions_served", [])),
            score=score,
            trend=trend,
            actions=[
                RecommendedAction(
                    category=item.get("category", ""),
                    category_label=item.get("category_label", ""),
                    priority=item.get("priority", "medium"),
                    action=item.get("action", ""),
                    trigger=item.get("trigger", ""),
                )
                for item in breakdown.get("actions", [])
            ],
            total_spend=breakdown.get("total_spend"),
            total_spend_base=breakdown.get("total_spend_base"),
            currency=breakdown.get("currency"),
            purchase_order_count=breakdown.get("purchase_order_count"),
            open_purchase_order_count=breakdown.get("open_purchase_order_count"),
            active_contract_count=breakdown.get("active_contract_count"),
            contract_status=breakdown.get("contract_status"),
            contract_expiration=_as_date(breakdown.get("contract_expiration")),
            contract_number=breakdown.get("contract_number"),
            days_to_contract_expiry=breakdown.get("days_to_contract_expiry"),
            contract_expiring_soon=bool(breakdown.get("contract_expiring_soon")),
            on_time_delivery_rate=breakdown.get("on_time_delivery_rate"),
            late_delivery_count=breakdown.get("late_delivery_count"),
            delivery_count=breakdown.get("delivery_count"),
            quality_score=breakdown.get("quality_score"),
            defect_rate=breakdown.get("defect_rate"),
            quality_incident_count=breakdown.get("quality_incident_count"),
            invoice_count=breakdown.get("invoice_count"),
            invoice_exception_count=breakdown.get("invoice_exception_count"),
            disputed_invoice_count=breakdown.get("disputed_invoice_count"),
            compliance_finding_count=breakdown.get("compliance_finding_count"),
            esg_score=breakdown.get("esg_score"),
            credit_score=breakdown.get("credit_score"),
            delivery_issues=list(breakdown.get("delivery_issues", [])),
            invoice_issues=list(breakdown.get("invoice_issues", [])),
            quality_issues=list(breakdown.get("quality_issues", [])),
            compliance_issues=list(breakdown.get("compliance_issues", [])),
            event_count=breakdown.get("event_count", 0),
        )
        profiles.append(profile)

    return RiskAssessmentResult(
        profiles=profiles,
        as_of_date=assessment.as_of_date,
        weights=dict(assessment.weights or {}),
        supplier_count=assessment.supplier_count,
        scored_count=assessment.scored_count,
        event_count=assessment.event_count,
        band_counts=dict(assessment.band_counts or {}),
        category_averages=dict(assessment.category_averages or {}),
        average_overall_score=assessment.average_overall_score,
        highest_risk_supplier_id=assessment.highest_risk_supplier_id,
        highest_risk_score=assessment.highest_risk_score,
        contracts_expiring_count=assessment.contracts_expiring_count,
        limited_data_count=assessment.limited_data_count,
        rule_errors=list(assessment.rule_errors or []),
        engine_version=assessment.engine_version,
    )


def chat(db: Session, request: ChatRequest) -> ChatResponse:
    """Answer a question about the loaded supplier risk data."""
    config = get_supplier_risk_config()

    try:
        assessment = _require_assessment(db, request.assessment_id)
    except NotFoundError:
        if request.assessment_id:
            # The caller named an assessment that does not exist. That is a
            # genuine 404, not a "nothing has been loaded yet" answer.
            raise
        # No assessment at all is a legitimate answer, not an error: the copilot
        # says plainly that nothing has been loaded.
        answer = answer_question(request.question, None, config)
        return ChatResponse(
            question=answer.question,
            intent=answer.intent.value,
            answer=answer.answer,
            data_available=False,
            unavailable_reason=answer.unavailable_reason,
            follow_up_suggestions=answer.follow_up_suggestions,
            disclaimer=config.copilot.disclaimer,
        )

    result = _assessment_to_result(db, assessment)
    answer = answer_question(request.question, result, config, supplier_id=request.supplier_id)

    narrative = SupplierRiskAiNarrativeSchema()
    if request.generate_ai_summary and answer.data_available:
        referenced = [
            profile
            for profile in result.profiles
            if profile.supplier_id in set(answer.suppliers_referenced)
        ]
        outcome = SupplierRiskNarrativeService().generate(
            assessment_summary={
                **_summary_payload(result),
                "question": answer.question,
                "deterministic_answer": answer.answer,
            },
            top_suppliers=[_ai_supplier_payload(profile) for profile in referenced[:5]],
            category_averages=dict(result.category_averages),
        )
        narrative = SupplierRiskAiNarrativeSchema(
            available=outcome.available,
            origin=outcome.origin,
            provider=outcome.provider,
            prompt_version=outcome.prompt_version,
            summary=outcome.summary,
            key_findings=list(outcome.key_findings),
            recommended_actions=list(outcome.recommended_actions),
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            estimated_cost_usd=outcome.estimated_cost_usd,
            error=outcome.error,
        )

    return ChatResponse(
        question=answer.question,
        intent=answer.intent.value,
        answer=answer.answer,
        data_available=answer.data_available,
        unavailable_reason=answer.unavailable_reason,
        citations=[CitationSchema(**citation.to_dict()) for citation in answer.citations],
        suppliers_referenced=list(answer.suppliers_referenced),
        follow_up_suggestions=list(answer.follow_up_suggestions),
        assessment_id=assessment.id,
        ai_narrative=narrative,
        disclaimer=config.copilot.disclaimer,
    )


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------


def get_field_catalogue() -> list[SupplierRiskFieldDefinitionSchema]:
    """Return the canonical fields and the column names that map to them."""
    inherited = set(INHERITED_FIELDS)
    return [
        SupplierRiskFieldDefinitionSchema(
            name=definition.name,
            label=definition.label,
            field_type=definition.field_type.value,
            required=definition.required,
            description=definition.description,
            aliases=list(definition.aliases),
            inherited_from_supplier_master=definition.name in inherited,
        )
        for definition in REGISTRY.definitions
    ]


def get_scoring_info() -> RiskScoringInfoSchema:
    """Return the documented scoring model."""
    config = get_supplier_risk_config()
    weights = config.default_weights.as_dict()

    categories = [
        RiskCategoryInfoSchema(
            category=name,
            label=config.categories[name].label,
            description=config.categories[name].description,
            default_weight=weights.get(name, 0.0),
            metrics=[
                {
                    "metric": metric_name,
                    "label": spec.label,
                    "weight_within_category": spec.weight,
                    "direction": spec.direction,
                    "unit": spec.unit,
                    "best_value": spec.best_value,
                    "worst_value": spec.worst_value,
                    "score_map": spec.score_map_key,
                }
                for metric_name, spec in config.categories[name].metrics.items()
            ],
        )
        for name in RISK_CATEGORIES
    ]

    return RiskScoringInfoSchema(
        config_version=config.config_version,
        engine_version=ENGINE_VERSION,
        weight_total=config.weight_total,
        default_weights=weights,
        categories=categories,
        risk_bands=[
            {"label": band.label, "min_score": band.min_score, "max_score": band.max_score}
            for band in config.risk_bands.bands
        ],
        trend={
            "window_days": config.trend.window_days,
            "minimum_events": config.trend.minimum_events,
            "improving_delta": config.trend.improving_delta,
            "deteriorating_delta": config.trend.deteriorating_delta,
            "severity_weights": dict(config.trend.severity_weights),
            "description": config.trend.description,
        },
        missing_data={
            "description": config.missing_data.description,
            "renormalise_category_weights": config.missing_data.renormalise_category_weights,
            "renormalise_metric_weights": config.missing_data.renormalise_metric_weights,
            "minimum_categories_for_overall": config.missing_data.minimum_categories_for_overall,
            "flag_below_completeness_pct": config.missing_data.flag_below_completeness_pct,
        },
        contract_expiry={
            "expiring_within_days": config.contract_expiry.expiring_within_days,
            "critical_within_days": config.contract_expiry.critical_within_days,
        },
        copilot_intents=[intent.value for intent in CopilotIntent],
        disclaimer=config.reporting.risk_disclaimer,
    )
