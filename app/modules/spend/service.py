"""Service layer for the Spend Analytics Dashboard.

This is the only place that knows the whole story: readers, column mapper,
normaliser, filters, metrics, analytics, savings engine, optional AI narrative
and the database.

Data flow::

    bytes -> validate -> store -> read -> suggest mapping            (upload)
    stored file -> read -> map -> normalise -> filter -> metrics
                -> analytics -> savings -> persist -> narrative      (analyze)
    persisted transactions -> filter -> page                         (drill-down)
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
from app.models.spend import SpendAnalysis, SpendOpportunity, SpendTransaction
from app.modules.spend.ai_narrative import SpendNarrativeService
from app.modules.spend.analytics import ANALYTICS_VERSION, BREAKDOWN_DIMENSIONS, build_analytics
from app.modules.spend.field_definitions import (
    DATE_FIELD_GROUP,
    REGISTRY,
    SPEND_SPECIFIC_FIELDS,
    VALUE_INGREDIENT_FIELDS,
)
from app.modules.spend.filters import (
    SpendFilter,
    apply_filter,
    available_filter_values,
    date_bounds,
)
from app.modules.spend.metrics import (
    METRICS_VERSION,
    calculate_metrics,
    calculate_supplier_spend,
    methodology,
)
from app.modules.spend.normalizer import normalize_spend_dataframe
from app.modules.spend.savings import (
    SAVINGS_ENGINE_VERSION,
    calculate_savings,
    savings_rule_catalogue,
)
from app.modules.spend.thresholds import get_spend_config
from app.schemas.common import OutputOrigin
from app.schemas.spend import (
    ColumnSuggestionSchema,
    ExportFormat,
    SavingsOpportunitySchema,
    SavingsRuleInfoSchema,
    SpendAiNarrativeSchema,
    SpendAnalysisDetailSchema,
    SpendAnalysisSummarySchema,
    SpendAnalyzeRequest,
    SpendFieldDefinitionSchema,
    SpendMetricsSchema,
    SpendTransactionSchema,
    SpendUploadResponse,
)
from app.services.exports.spend_report_builder import (
    build_spend_csv_report,
    build_spend_json_report,
    build_spend_xlsx_report,
    spend_disclaimer,
)
from app.services.files.readers import preview_records, read_tabular
from app.services.files.storage import read_upload, store_upload
from app.services.files.validation import validate_upload
from app.services.tabular.mapping import merge_mapping, suggest_mapping, validate_mapping

logger = get_logger(__name__)

PREVIEW_ROW_LIMIT = 10

#: Columns copied from the canonical frame into ``spend_transactions``.
TRANSACTION_FIELDS: tuple[str, ...] = (
    "row_number", "po_number", "po_item", "supplier_id", "supplier_name", "material",
    "material_description", "material_group", "category", "subcategory", "company_code",
    "purchasing_org", "purchasing_group", "plant", "quantity", "unit_of_measure", "unit_price",
    "baseline_price", "current_price", "currency", "total_value", "spend_base",
    "effective_date", "spend_month", "contract_number", "contract_status",
    "preferred_supplier_status", "payment_status", "is_contracted", "is_preferred_supplier",
    "is_maverick", "is_under_management", "price_variance_base", "price_variance_pct",
)


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def handle_upload(db: Session, filename: str, content: bytes) -> SpendUploadResponse:
    """Validate, store and profile an uploaded spend file."""
    validated = validate_upload(filename, content)
    read_result = read_tabular(validated.content, validated.extension)
    mapping_result = suggest_mapping(read_result.source_columns, REGISTRY)
    stored = store_upload(validated)

    upload = UploadedFile(
        id=uuid.uuid4().hex[:32],
        module="spend",
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
    db.commit()

    missing = _missing_requirements(set(mapping_result.mapping.values()))
    logger.info(
        "Spend upload %s accepted: %d rows, %d columns, %d fields auto-mapped",
        upload.id, read_result.row_count, len(read_result.source_columns),
        len(mapping_result.mapping),
    )

    return SpendUploadResponse(
        upload_id=upload.id,
        original_filename=upload.original_filename,
        file_extension=upload.file_extension,
        size_bytes=upload.size_bytes,
        row_count=upload.row_count,
        column_count=upload.column_count,
        detected_columns=read_result.source_columns,
        preview_rows=preview_records(read_result.dataframe, PREVIEW_ROW_LIMIT),
        suggested_mapping=mapping_result.mapping,
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
        is_analyzable=not missing,
        parser_notes=read_result.notes,
    )


def _missing_requirements(mapped_fields: set[str]) -> list[str]:
    """Return the requirements a mapping does not yet satisfy.

    Spend analysis is more forgiving than the risk rules: it needs a supplier,
    a document key, *a* date and *a* way to compute a value. Which particular
    date or value column supplies that is up to the file.
    """
    missing = [field for field in REGISTRY.required if field not in mapped_fields]
    if not mapped_fields.intersection(DATE_FIELD_GROUP):
        missing.append("transaction_date")
    if "total_value" not in mapped_fields and not set(VALUE_INGREDIENT_FIELDS).issubset(
        mapped_fields
    ):
        missing.append("total_value")
    return missing


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------


def run_analysis(db: Session, request: SpendAnalyzeRequest) -> SpendAnalysisDetailSchema:
    """Run the full spend analysis for a previously uploaded file."""
    started = time.perf_counter()
    config = get_spend_config()

    upload = db.get(UploadedFile, request.upload_id)
    if upload is None:
        raise NotFoundError(f"Upload '{request.upload_id}' was not found.")

    content = read_upload(upload.stored_filename)
    read_result = read_tabular(content, upload.file_extension)

    mapping = merge_mapping(upload.suggested_mapping, request.column_mapping_overrides)
    validate_mapping(mapping, read_result.source_columns, REGISTRY)
    missing = _missing_requirements(set(mapping.values()))
    if missing:
        raise ValidationError(
            "The column mapping does not provide everything a spend analysis needs.",
            details={"missing_required_fields": missing},
        )

    if request.enabled_savings_rules is not None:
        unknown = sorted(set(request.enabled_savings_rules) - set(config.savings_rules))
        if unknown:
            raise ValidationError(
                "The request refers to unknown savings rules.",
                details={"unknown_rules": unknown, "known_rules": list(config.savings_rules)},
            )

    dataset = normalize_spend_dataframe(read_result.dataframe, mapping, config)
    spend_filter = SpendFilter.from_request(
        date_from=request.filters.date_from,
        date_to=request.filters.date_to,
        values=request.filters.to_values(),
    )
    filtered = apply_filter(dataset.frame, spend_filter)

    supplier_rows = calculate_supplier_spend(filtered, config)
    savings = calculate_savings(filtered, config, supplier_rows, request.enabled_savings_rules)
    metrics = calculate_metrics(
        filtered, config, supplier_rows, estimated_savings=savings.total_estimated_saving
    )
    analytics = build_analytics(filtered, config, supplier_rows, top_n=request.top_n)
    period_start, period_end = date_bounds(filtered)

    analysis = SpendAnalysis(
        id=uuid.uuid4().hex[:32],
        upload_id=upload.id,
        status="completed",
        source_filename=upload.original_filename,
        config_version=config.config_version,
        metrics_version=METRICS_VERSION,
        savings_engine_version=SAVINGS_ENGINE_VERSION,
        applied_mapping=mapping,
        unmapped_columns=dataset.unmapped_columns,
        data_quality_issues=dataset.issues_as_dicts(),
        applied_filter=spend_filter.to_dict(),
        base_currency=config.base_currency,
        total_spend=metrics.total_spend,
        record_count=dataset.record_count,
        filtered_record_count=int(len(filtered)),
        purchase_order_count=metrics.purchase_order_count,
        supplier_count=metrics.supplier_count,
        contracted_spend=metrics.contracted_spend,
        maverick_spend=metrics.maverick_spend,
        tail_spend=metrics.tail_spend,
        spend_under_management_pct=metrics.spend_under_management_pct,
        supplier_concentration_hhi=metrics.supplier_concentration_hhi,
        estimated_savings=savings.total_estimated_saving,
        opportunity_count=len(savings.opportunities),
        period_start=period_start,
        period_end=period_end,
        metrics=metrics.to_dict(),
        analytics=analytics,
        supplier_spend=[row.to_dict() for row in supplier_rows],
        savings_executions=savings.rule_executions,
        savings_errors=savings.rule_errors,
        filter_options=available_filter_values(dataset.frame),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(analysis)
    db.flush()

    _persist_transactions(db, analysis.id, filtered)
    _persist_opportunities(db, analysis.id, savings.opportunities)

    # --- optional narrative, never allowed to fail the analysis ----------
    narrative = SpendAiNarrativeSchema()
    if request.generate_ai_summary:
        result = SpendNarrativeService().generate(
            metrics.to_dict(),
            [row.to_dict() for row in supplier_rows[:5]],
            analytics.get("spend_by_category", []),
            [o.to_dict() for o in savings.opportunities[:10]],
        )
        analysis.ai_provider = result.provider
        analysis.ai_output_origin = result.origin.value if result.origin else None
        analysis.ai_prompt_version = result.prompt_version
        analysis.ai_summary = result.summary
        analysis.ai_key_findings = result.key_findings
        analysis.ai_recommended_actions = result.recommended_actions
        analysis.ai_input_tokens = result.input_tokens
        analysis.ai_output_tokens = result.output_tokens
        analysis.ai_estimated_cost_usd = result.estimated_cost_usd
        analysis.ai_error = result.error
        narrative = SpendAiNarrativeSchema(
            available=result.available,
            origin=result.origin,
            provider=result.provider,
            prompt_version=result.prompt_version,
            summary=result.summary,
            key_findings=result.key_findings,
            recommended_actions=result.recommended_actions,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
            error=result.error,
        )

    analysis.duration_ms = int((time.perf_counter() - started) * 1000)
    db.commit()
    db.refresh(analysis)

    logger.info(
        "Spend analysis %s completed: %.2f %s across %d rows, %d opportunities, %d ms",
        analysis.id, metrics.total_spend, config.base_currency, len(filtered),
        len(savings.opportunities), analysis.duration_ms,
    )
    return _to_detail_schema(analysis, savings.opportunities, narrative)


def _persist_transactions(db: Session, analysis_id: str, frame) -> None:
    """Store the analysed transactions so drill-down never re-reads the file."""
    if frame.empty:
        return
    records = []
    for row in frame.to_dict(orient="records"):
        payload = {key: _clean(row.get(key)) for key in TRANSACTION_FIELDS}
        payload["analysis_id"] = analysis_id
        payload["row_number"] = int(payload.get("row_number") or 0)
        payload["spend_base"] = float(payload.get("spend_base") or 0.0)
        for flag in ("is_contracted", "is_preferred_supplier", "is_maverick", "is_under_management"):
            payload[flag] = bool(payload.get(flag))
        records.append(payload)
    db.bulk_insert_mappings(SpendTransaction, records)


def _persist_opportunities(db: Session, analysis_id: str, opportunities) -> None:
    """Store the modelled savings opportunities."""
    for opportunity in opportunities:
        db.add(
            SpendOpportunity(
                id=f"{analysis_id[:8]}-{opportunity.opportunity_id}"[:64],
                analysis_id=analysis_id,
                rule_id=opportunity.rule_id,
                rule_name=opportunity.rule_name,
                opportunity_type=opportunity.opportunity_type,
                scope=opportunity.scope,
                scope_value=opportunity.scope_value,
                scope_label=opportunity.scope_label,
                title=opportunity.title,
                description=opportunity.description,
                method=opportunity.method,
                addressable_spend_base=opportunity.addressable_spend_base,
                gross_saving_base=opportunity.gross_saving_base,
                realization_factor=opportunity.realization_factor,
                estimated_saving_base=opportunity.estimated_saving_base,
                confidence=opportunity.confidence,
                transaction_count=opportunity.transaction_count,
                supplier_count=opportunity.supplier_count,
                evidence=opportunity.evidence,
                is_estimate=True,
            )
        )


def _clean(value: Any) -> Any:
    """Convert a pandas value into something SQLAlchemy accepts."""
    import pandas as pd

    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def list_analyses(
    db: Session, limit: int = 20, offset: int = 0
) -> tuple[int, list[SpendAnalysisSummarySchema]]:
    """Return previous spend analyses, newest first."""
    total = db.scalar(select(func.count()).select_from(SpendAnalysis)) or 0
    rows = db.scalars(
        select(SpendAnalysis)
        .order_by(SpendAnalysis.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return total, [
        SpendAnalysisSummarySchema(
            analysis_id=row.id,
            status=row.status,
            source_filename=row.source_filename,
            base_currency=row.base_currency,
            total_spend=float(row.total_spend or 0),
            record_count=row.record_count,
            filtered_record_count=row.filtered_record_count,
            supplier_count=row.supplier_count,
            estimated_savings=float(row.estimated_savings or 0),
            opportunity_count=row.opportunity_count,
            period_start=row.period_start,
            period_end=row.period_end,
            created_at=row.created_at,
        )
        for row in rows
    ]


def get_analysis(db: Session, analysis_id: str) -> SpendAnalysisDetailSchema:
    """Load one analysis with its opportunities."""
    analysis = _require_analysis(db, analysis_id)
    opportunities = db.scalars(
        select(SpendOpportunity)
        .where(SpendOpportunity.analysis_id == analysis_id)
        .order_by(SpendOpportunity.estimated_saving_base.desc())
    ).all()
    return _to_detail_schema(analysis, opportunities, _narrative_from_row(analysis))


def list_transactions(
    db: Session,
    analysis_id: str,
    *,
    dimension: str | None = None,
    value: str | None = None,
    supplier_id: str | None = None,
    material: str | None = None,
    category: str | None = None,
    spend_month: str | None = None,
    contracted: bool | None = None,
    maverick: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, float, list[SpendTransactionSchema]]:
    """Return the transactions behind a summary figure.

    ``dimension`` plus ``value`` is the drill-down pair: the UI sends back the
    dimension and value of the chart element the user clicked and receives
    exactly the lines that produced it.
    """
    _require_analysis(db, analysis_id)

    statement = select(SpendTransaction).where(SpendTransaction.analysis_id == analysis_id)

    if dimension:
        column_name = BREAKDOWN_DIMENSIONS.get(dimension)
        if column_name is None:
            raise ValidationError(
                f"'{dimension}' is not a drill-down dimension.",
                details={"allowed_dimensions": sorted(BREAKDOWN_DIMENSIONS)},
            )
        if value is not None:
            column = getattr(SpendTransaction, column_name)
            statement = statement.where(column == value)

    for column_name, wanted in (
        ("supplier_id", supplier_id),
        ("material", material),
        ("category", category),
        ("spend_month", spend_month),
    ):
        if wanted:
            statement = statement.where(getattr(SpendTransaction, column_name) == wanted)
    if contracted is not None:
        statement = statement.where(SpendTransaction.is_contracted == contracted)
    if maverick is not None:
        statement = statement.where(SpendTransaction.is_maverick == maverick)

    # Aggregate over the *subquery columns*. Referencing SpendTransaction here
    # instead would join the base table again and multiply the sum.
    subquery = statement.subquery()
    total = db.scalar(select(func.count()).select_from(subquery)) or 0
    total_spend = float(
        db.scalar(select(func.sum(subquery.c.spend_base)).select_from(subquery)) or 0.0
    )

    rows = db.scalars(
        statement.order_by(SpendTransaction.spend_base.desc()).limit(limit).offset(offset)
    ).all()
    return total, round(total_spend, 2), [_transaction_schema(row) for row in rows]


def list_opportunities(
    db: Session,
    analysis_id: str,
    *,
    rule_id: str | None = None,
    opportunity_type: str | None = None,
    min_saving: float | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, float, list[SavingsOpportunitySchema]]:
    """Return the modelled savings opportunities for an analysis."""
    _require_analysis(db, analysis_id)

    statement = select(SpendOpportunity).where(SpendOpportunity.analysis_id == analysis_id)
    if rule_id:
        statement = statement.where(SpendOpportunity.rule_id == rule_id)
    if opportunity_type:
        statement = statement.where(SpendOpportunity.opportunity_type == opportunity_type)
    if min_saving is not None:
        statement = statement.where(SpendOpportunity.estimated_saving_base >= min_saving)

    subquery = statement.subquery()
    total = db.scalar(select(func.count()).select_from(subquery)) or 0
    total_saving = float(
        db.scalar(
            select(func.sum(subquery.c.estimated_saving_base)).select_from(subquery)
        )
        or 0.0
    )
    rows = db.scalars(
        statement.order_by(SpendOpportunity.estimated_saving_base.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return total, round(total_saving, 2), [_opportunity_schema(row) for row in rows]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_analysis(
    db: Session, analysis_id: str, export_format: ExportFormat
) -> tuple[bytes, str, str]:
    """Build a downloadable report. Returns ``(content, filename, media_type)``."""
    analysis = _require_analysis(db, analysis_id)
    config = get_spend_config()

    opportunities = db.scalars(
        select(SpendOpportunity)
        .where(SpendOpportunity.analysis_id == analysis_id)
        .order_by(SpendOpportunity.estimated_saving_base.desc())
    ).all()
    transactions = db.scalars(
        select(SpendTransaction)
        .where(SpendTransaction.analysis_id == analysis_id)
        .order_by(SpendTransaction.spend_base.desc())
        .limit(config.reporting.max_drilldown_rows * 50)
    ).all()

    transaction_dicts = [_transaction_schema(row).model_dump() for row in transactions]
    opportunity_dicts = [_opportunity_schema(row).model_dump() for row in opportunities]

    payload = {
        "analysis": {
            "analysis_id": analysis.id,
            "source_filename": analysis.source_filename,
            "created_at": analysis.created_at,
            "period_start": analysis.period_start,
            "period_end": analysis.period_end,
            "record_count": analysis.record_count,
            "filtered_record_count": analysis.filtered_record_count,
            "applied_filter": analysis.applied_filter,
            "applied_mapping": analysis.applied_mapping,
            "config_version": analysis.config_version,
            "metrics_version": analysis.metrics_version,
        },
        "metrics": analysis.metrics,
        "analytics": analysis.analytics,
        "supplier_spend": analysis.supplier_spend,
        "opportunities": opportunity_dicts,
        "transactions": transaction_dicts,
        "data_quality_issues": analysis.data_quality_issues,
        "ai_narrative": _narrative_from_row(analysis).model_dump(),
        "methodology": methodology(config),
        "savings_rule_catalogue": savings_rule_catalogue(config),
    }

    stem = f"spend_analysis_{analysis.id[:8]}"
    if export_format is ExportFormat.JSON:
        return build_spend_json_report(payload), f"{stem}.json", "application/json"
    if export_format is ExportFormat.CSV:
        return build_spend_csv_report(transaction_dicts), f"{stem}.csv", "text/csv"
    return (
        build_spend_xlsx_report(payload),
        f"{stem}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Catalogues
# ---------------------------------------------------------------------------


def get_field_catalogue() -> list[SpendFieldDefinitionSchema]:
    """Describe every canonical field, for building a mapping UI."""
    spend_specific = {definition.name for definition in SPEND_SPECIFIC_FIELDS}
    return [
        SpendFieldDefinitionSchema(
            name=definition.name,
            label=definition.label,
            field_type=definition.field_type.value,
            required=definition.required,
            description=definition.description,
            aliases=list(definition.aliases),
            is_spend_specific=definition.name in spend_specific,
        )
        for definition in REGISTRY.definitions
    ]


def get_savings_rule_catalogue() -> list[SavingsRuleInfoSchema]:
    """Describe every configured savings rule and its assumptions."""
    return [
        SavingsRuleInfoSchema(**entry) for entry in savings_rule_catalogue(get_spend_config())
    ]


def get_methodology() -> dict[str, Any]:
    """Return the methodology block on its own."""
    return methodology(get_spend_config())


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _require_analysis(db: Session, analysis_id: str) -> SpendAnalysis:
    analysis = db.get(SpendAnalysis, analysis_id)
    if analysis is None:
        raise NotFoundError(f"Spend analysis '{analysis_id}' was not found.")
    return analysis


def _narrative_from_row(analysis: SpendAnalysis) -> SpendAiNarrativeSchema:
    """Rebuild the narrative schema from a stored analysis row."""
    return SpendAiNarrativeSchema(
        available=analysis.ai_summary is not None,
        origin=OutputOrigin(analysis.ai_output_origin) if analysis.ai_output_origin else None,
        provider=analysis.ai_provider,
        prompt_version=analysis.ai_prompt_version,
        summary=analysis.ai_summary,
        key_findings=list(analysis.ai_key_findings or []),
        recommended_actions=list(analysis.ai_recommended_actions or []),
        input_tokens=analysis.ai_input_tokens,
        output_tokens=analysis.ai_output_tokens,
        estimated_cost_usd=analysis.ai_estimated_cost_usd,
        error=analysis.ai_error,
    )


def _transaction_schema(row: SpendTransaction) -> SpendTransactionSchema:
    return SpendTransactionSchema(
        row_number=row.row_number,
        po_number=row.po_number,
        po_item=row.po_item,
        supplier_id=row.supplier_id,
        supplier_name=row.supplier_name,
        material=row.material,
        material_description=row.material_description,
        material_group=row.material_group,
        category=row.category,
        subcategory=row.subcategory,
        company_code=row.company_code,
        purchasing_org=row.purchasing_org,
        purchasing_group=row.purchasing_group,
        plant=row.plant,
        quantity=row.quantity,
        unit_of_measure=row.unit_of_measure,
        unit_price=row.unit_price,
        baseline_price=row.baseline_price,
        current_price=row.current_price,
        currency=row.currency,
        total_value=float(row.total_value) if row.total_value is not None else None,
        spend_base=float(row.spend_base or 0),
        effective_date=row.effective_date,
        spend_month=row.spend_month,
        contract_number=row.contract_number,
        contract_status=row.contract_status,
        preferred_supplier_status=row.preferred_supplier_status,
        payment_status=row.payment_status,
        is_contracted=row.is_contracted,
        is_preferred_supplier=row.is_preferred_supplier,
        is_maverick=row.is_maverick,
        is_under_management=row.is_under_management,
        price_variance_base=row.price_variance_base,
        price_variance_pct=row.price_variance_pct,
    )


def _opportunity_schema(row: Any) -> SavingsOpportunitySchema:
    """Build the schema from either an ORM row or a dataclass opportunity."""
    if isinstance(row, SpendOpportunity):
        return SavingsOpportunitySchema(
            opportunity_id=row.id,
            rule_id=row.rule_id,
            rule_name=row.rule_name,
            opportunity_type=row.opportunity_type,
            scope=row.scope,
            scope_value=row.scope_value,
            scope_label=row.scope_label,
            title=row.title,
            description=row.description,
            method=row.method,
            addressable_spend_base=float(row.addressable_spend_base or 0),
            gross_saving_base=float(row.gross_saving_base or 0),
            realization_factor=row.realization_factor,
            estimated_saving_base=float(row.estimated_saving_base or 0),
            confidence=row.confidence,
            transaction_count=row.transaction_count,
            supplier_count=row.supplier_count,
            evidence=row.evidence or {},
            is_estimate=True,
        )
    return SavingsOpportunitySchema(**row.to_dict())


def _to_detail_schema(
    analysis: SpendAnalysis,
    opportunities: list[Any],
    narrative: SpendAiNarrativeSchema,
) -> SpendAnalysisDetailSchema:
    """Assemble the full analysis payload."""
    config = get_spend_config()
    return SpendAnalysisDetailSchema(
        analysis_id=analysis.id,
        upload_id=analysis.upload_id,
        status=analysis.status,
        source_filename=analysis.source_filename,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
        duration_ms=analysis.duration_ms,
        config_version=analysis.config_version,
        metrics_version=analysis.metrics_version,
        savings_engine_version=analysis.savings_engine_version,
        applied_mapping=analysis.applied_mapping or {},
        unmapped_columns=list(analysis.unmapped_columns or []),
        data_quality_issues=list(analysis.data_quality_issues or []),
        applied_filter=analysis.applied_filter or {},
        filter_options=analysis.filter_options or {},
        record_count=analysis.record_count,
        filtered_record_count=analysis.filtered_record_count,
        period_start=analysis.period_start,
        period_end=analysis.period_end,
        metrics=SpendMetricsSchema(**(analysis.metrics or {})),
        analytics=analysis.analytics or {},
        supplier_spend=list(analysis.supplier_spend or []),
        opportunities=[_opportunity_schema(o) for o in opportunities],
        savings_executions=list(analysis.savings_executions or []),
        savings_errors=list(analysis.savings_errors or []),
        ai_narrative=narrative,
        methodology={
            **methodology(config),
            "analytics_version": ANALYTICS_VERSION,
            "export_disclaimer": spend_disclaimer(),
        },
    )
