"""Service layer for the Purchase Order Risk Checker.

This module is the only place that knows the *whole* story: it wires the
readers, the column mapper, the normaliser, the rule engine, the optional AI
narrative and the database together.

FastAPI routes call these functions and translate the results into HTTP.
Streamlit calls the same HTTP API. A future React front end will do exactly the
same, which is why no business logic lives in either UI layer.

Data flow::

    bytes -> validate -> store -> read -> suggest mapping        (upload)
    stored file -> read -> apply mapping -> normalise -> rules
                -> persist -> optional AI narrative -> response  (analyze)
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
from app.models.po_risk import PoAnalysis, PoFinding, PoRecord, UploadedFile
from app.modules.po_risk.ai_narrative import NarrativeService
from app.modules.po_risk.column_mapping import (
    merge_mapping,
    suggest_mapping,
    validate_mapping,
)
from app.modules.po_risk.engine import ENGINE_VERSION, RiskEngine
from app.modules.po_risk.field_definitions import FIELD_DEFINITIONS
from app.modules.po_risk.normalizer import normalize_dataframe
from app.modules.po_risk.rules import RULE_IDS
from app.modules.po_risk.thresholds import get_rule_config
from app.schemas.common import OutputOrigin, Severity
from app.schemas.po_risk import (
    AiNarrativeSchema,
    AnalysisDetailSchema,
    AnalysisSummarySchema,
    AnalyzeRequest,
    ColumnSuggestionSchema,
    ExportFormat,
    FieldDefinitionSchema,
    FindingSchema,
    RuleInfoSchema,
    UploadResponse,
)
from app.services.exports.report_builder import (
    build_csv_report,
    build_json_report,
    build_xlsx_report,
)
from app.services.files.readers import preview_records, read_tabular
from app.services.files.storage import read_upload, store_upload
from app.services.files.validation import validate_upload

logger = get_logger(__name__)

PREVIEW_ROW_LIMIT = 10
FINDINGS_PREVIEW_LIMIT = 25


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def handle_upload(db: Session, filename: str, content: bytes) -> UploadResponse:
    """Validate, store and profile an uploaded purchase order file."""
    validated = validate_upload(filename, content)
    read_result = read_tabular(validated.content, validated.extension)
    mapping_result = suggest_mapping(read_result.source_columns)
    stored = store_upload(validated)

    upload = UploadedFile(
        id=uuid.uuid4().hex[:32],
        module="po_risk",
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

    logger.info(
        "Upload %s accepted: %d rows, %d columns, %d fields auto-mapped",
        upload.id, read_result.row_count, len(read_result.source_columns), len(mapping_result.mapping),
    )

    return UploadResponse(
        upload_id=upload.id,
        original_filename=upload.original_filename,
        file_extension=upload.file_extension,
        size_bytes=upload.size_bytes,
        row_count=upload.row_count,
        column_count=upload.column_count,
        detected_columns=read_result.source_columns,
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
        missing_required_fields=mapping_result.missing_required_fields,
        is_analyzable=mapping_result.is_analyzable,
        preview_rows=preview_records(read_result.dataframe, PREVIEW_ROW_LIMIT),
        parser_notes=read_result.notes,
    )


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def run_analysis(db: Session, request: AnalyzeRequest) -> AnalysisDetailSchema:
    """Run the full risk analysis pipeline for a previously uploaded file."""
    started = time.perf_counter()
    upload = db.get(UploadedFile, request.upload_id)
    if upload is None:
        raise NotFoundError(
            "The upload was not found. Upload the file again before analysing it.",
            details={"upload_id": request.upload_id},
        )

    if request.enabled_rules:
        unknown = sorted(set(request.enabled_rules) - set(RULE_IDS))
        if unknown:
            raise ValidationError(
                "Unknown rule id(s) requested.",
                details={"unknown_rules": unknown, "available_rules": list(RULE_IDS)},
            )

    content = read_upload(upload.stored_filename)
    read_result = read_tabular(content, upload.file_extension)

    mapping = merge_mapping(dict(upload.suggested_mapping or {}), request.column_mapping_overrides)
    validate_mapping(mapping, read_result.source_columns)

    config = get_rule_config()
    dataset = normalize_dataframe(read_result.dataframe, mapping, config)

    engine = RiskEngine(config)
    engine_result = engine.run(dataset.frame, enabled_rules=request.enabled_rules)

    analysis_id = uuid.uuid4().hex[:32]
    findings_payload: list[dict[str, Any]] = []
    for finding in engine_result.findings:
        payload = finding.to_dict()
        payload["finding_id"] = uuid.uuid4().hex[:32]
        payload["analysis_id"] = analysis_id
        findings_payload.append(payload)

    narrative = None
    if request.generate_ai_summary:
        narrative = NarrativeService().generate(
            summary=engine_result.summary,
            supplier_risk=engine_result.supplier_risk,
            findings=[{**f, "id": f["finding_id"]} for f in findings_payload],
            rewrite_findings=request.rewrite_findings,
        )
        for finding in findings_payload:
            enrichment = narrative.finding_explanations.get(finding["finding_id"])
            if enrichment:
                finding["ai_explanation"] = enrichment["explanation"]
                finding["ai_recommended_action"] = enrichment["action"]
                finding["ai_output_origin"] = enrichment["origin"]

    duration_ms = int((time.perf_counter() - started) * 1000)
    analysis = _persist_analysis(
        db=db,
        analysis_id=analysis_id,
        upload=upload,
        dataset=dataset,
        engine_result=engine_result,
        findings_payload=findings_payload,
        narrative=narrative,
        duration_ms=duration_ms,
    )

    logger.info(
        "Analysis %s completed in %d ms with %d findings",
        analysis_id, duration_ms, len(findings_payload),
    )
    return build_analysis_detail(db, analysis)


def _persist_analysis(
    *,
    db: Session,
    analysis_id: str,
    upload: UploadedFile,
    dataset: Any,
    engine_result: Any,
    findings_payload: list[dict[str, Any]],
    narrative: Any,
    duration_ms: int,
) -> PoAnalysis:
    """Write the analysis, its records and its findings to the database."""
    summary = engine_result.summary
    severity_counts = summary["severity_counts"]

    analysis = PoAnalysis(
        id=analysis_id,
        upload_id=upload.id,
        status="completed",
        source_filename=upload.original_filename,
        config_version=engine_result.config_version,
        engine_version=engine_result.engine_version,
        applied_mapping=dataset.applied_mapping,
        unmapped_columns=dataset.unmapped_columns,
        data_quality_issues=dataset.issues_as_dicts(),
        kpis=summary,
        supplier_risk=engine_result.supplier_risk,
        rule_executions=[vars(execution) for execution in engine_result.executions],
        rule_errors=engine_result.rule_errors,
        record_count=summary["record_count"],
        purchase_order_count=summary["purchase_order_count"],
        supplier_count=summary["supplier_count"],
        total_value=summary["total_value_base"],
        base_currency=summary["base_currency"],
        findings_count=summary["findings_count"],
        critical_count=severity_counts["critical"],
        high_count=severity_counts["high"],
        medium_count=severity_counts["medium"],
        low_count=severity_counts["low"],
        flagged_value=summary["flagged_value_base"],
        estimated_exposure=summary["estimated_exposure_base"],
        risk_score=summary["risk_score"],
        duration_ms=duration_ms,
        completed_at=datetime.now(timezone.utc),
    )

    if narrative is not None:
        analysis.ai_provider = narrative.provider
        analysis.ai_output_origin = narrative.origin.value if narrative.origin else None
        analysis.ai_prompt_version = narrative.prompt_version
        analysis.ai_summary = narrative.summary
        analysis.ai_key_risks = narrative.key_risks
        analysis.ai_recommended_actions = narrative.recommended_actions
        analysis.ai_input_tokens = narrative.input_tokens
        analysis.ai_output_tokens = narrative.output_tokens
        analysis.ai_estimated_cost_usd = narrative.estimated_cost_usd
        analysis.ai_error = narrative.error

    db.add(analysis)
    db.flush()

    db.bulk_save_objects(
        [
            PoRecord(analysis_id=analysis_id, **_record_columns(record))
            for record in dataset.frame.to_dict("records")
        ]
    )
    db.bulk_save_objects(
        [
            PoFinding(
                id=payload["finding_id"],
                analysis_id=analysis_id,
                po_number=payload.get("po_number"),
                po_item=payload.get("po_item"),
                supplier_id=payload.get("supplier_id"),
                supplier_name=payload.get("supplier_name"),
                risk_category=payload["risk_category"],
                rule_id=payload["rule_id"],
                rule_name=payload["rule_name"],
                severity=payload["severity"],
                explanation=payload["explanation"],
                evidence=payload["evidence"],
                recommended_action=payload["recommended_action"],
                confidence_score=payload["confidence_score"],
                estimated_financial_exposure=payload["estimated_financial_exposure"],
                exposure_currency=payload["exposure_currency"],
                output_origin=payload["output_origin"],
                ai_explanation=payload.get("ai_explanation"),
                ai_recommended_action=payload.get("ai_recommended_action"),
                ai_output_origin=payload.get("ai_output_origin"),
            )
            for payload in findings_payload
        ]
    )
    db.commit()
    db.refresh(analysis)
    return analysis


_RECORD_FIELDS = {column.name for column in PoRecord.__table__.columns} - {"id", "analysis_id"}


def _record_columns(record: dict[str, Any]) -> dict[str, Any]:
    """Keep only the keys that exist as columns on ``po_records``."""
    return {key: value for key, value in record.items() if key in _RECORD_FIELDS}


# ---------------------------------------------------------------------------
# Read APIs
# ---------------------------------------------------------------------------


def list_analyses(db: Session, limit: int = 20, offset: int = 0) -> tuple[int, list[AnalysisSummarySchema]]:
    """Return a page of analyses, newest first."""
    total = db.scalar(select(func.count()).select_from(PoAnalysis)) or 0
    rows = db.scalars(
        select(PoAnalysis).order_by(PoAnalysis.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return total, [_to_summary(row) for row in rows]


def get_analysis(db: Session, analysis_id: str) -> AnalysisDetailSchema:
    """Return the full detail payload for one analysis."""
    analysis = db.get(PoAnalysis, analysis_id)
    if analysis is None:
        raise NotFoundError("Analysis not found.", details={"analysis_id": analysis_id})
    return build_analysis_detail(db, analysis)


def list_findings(
    db: Session,
    analysis_id: str,
    *,
    severity: list[str] | None = None,
    rule_id: str | None = None,
    risk_category: str | None = None,
    supplier_id: str | None = None,
    po_number: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, list[FindingSchema]]:
    """Return a filtered page of findings for an analysis."""
    if db.get(PoAnalysis, analysis_id) is None:
        raise NotFoundError("Analysis not found.", details={"analysis_id": analysis_id})

    statement = select(PoFinding).where(PoFinding.analysis_id == analysis_id)
    count_statement = select(func.count()).select_from(PoFinding).where(
        PoFinding.analysis_id == analysis_id
    )

    if severity:
        normalised = [value.lower() for value in severity]
        statement = statement.where(PoFinding.severity.in_(normalised))
        count_statement = count_statement.where(PoFinding.severity.in_(normalised))
    if rule_id:
        statement = statement.where(PoFinding.rule_id == rule_id)
        count_statement = count_statement.where(PoFinding.rule_id == rule_id)
    if risk_category:
        statement = statement.where(PoFinding.risk_category == risk_category)
        count_statement = count_statement.where(PoFinding.risk_category == risk_category)
    if supplier_id:
        statement = statement.where(PoFinding.supplier_id == supplier_id)
        count_statement = count_statement.where(PoFinding.supplier_id == supplier_id)
    if po_number:
        statement = statement.where(PoFinding.po_number == po_number)
        count_statement = count_statement.where(PoFinding.po_number == po_number)

    total = db.scalar(count_statement) or 0
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    rows = db.scalars(statement).all()
    rows = sorted(
        rows,
        key=lambda row: (
            severity_order.get(row.severity, 9),
            -float(row.estimated_financial_exposure or 0.0),
        ),
    )[offset : offset + limit]
    return total, [_to_finding_schema(row) for row in rows]


def export_analysis(
    db: Session, analysis_id: str, export_format: ExportFormat
) -> tuple[bytes, str, str]:
    """Build a downloadable report. Returns ``(content, filename, media_type)``."""
    analysis = db.get(PoAnalysis, analysis_id)
    if analysis is None:
        raise NotFoundError("Analysis not found.", details={"analysis_id": analysis_id})

    findings = db.scalars(
        select(PoFinding).where(PoFinding.analysis_id == analysis_id)
    ).all()
    findings_payload = [_to_finding_schema(row).model_dump(mode="json") for row in findings]

    payload: dict[str, Any] = {
        "analysis": _to_summary(analysis).model_dump(mode="json"),
        "kpis": analysis.kpis or {},
        "supplier_risk": analysis.supplier_risk or [],
        "data_quality_issues": analysis.data_quality_issues or [],
        "applied_mapping": analysis.applied_mapping or {},
        "ai_narrative": _narrative_schema(analysis).model_dump(mode="json"),
        "rule_catalogue": [rule.model_dump(mode="json") for rule in get_rule_catalogue()],
        "findings": findings_payload,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if export_format is ExportFormat.XLSX:
        return (
            build_xlsx_report(payload),
            f"po_risk_report_{analysis_id[:8]}_{stamp}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if export_format is ExportFormat.CSV:
        return (
            build_csv_report(findings_payload),
            f"po_risk_findings_{analysis_id[:8]}_{stamp}.csv",
            "text/csv",
        )
    return (
        build_json_report(payload),
        f"po_risk_report_{analysis_id[:8]}_{stamp}.json",
        "application/json",
    )


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------


def get_rule_catalogue() -> list[RuleInfoSchema]:
    """Return the configured rule catalogue (used by the methodology section)."""
    config = get_rule_config()
    catalogue: list[RuleInfoSchema] = []
    for rule_id in RULE_IDS:
        settings_entry = config.rule(rule_id)
        catalogue.append(
            RuleInfoSchema(
                rule_id=rule_id,
                name=settings_entry.name,
                category=settings_entry.category,
                enabled=settings_entry.enabled,
                base_severity=settings_entry.base_severity,
                confidence=settings_entry.confidence,
                recommended_action=settings_entry.recommended_action,
                params=settings_entry.params,
            )
        )
    return catalogue


def get_field_catalogue() -> list[FieldDefinitionSchema]:
    """Return the canonical field definitions with their SAP aliases."""
    return [
        FieldDefinitionSchema(
            name=definition.name,
            label=definition.label,
            field_type=definition.field_type.value,
            required=definition.required,
            description=definition.description,
            aliases=list(definition.aliases),
        )
        for definition in FIELD_DEFINITIONS
    ]


def build_analysis_detail(db: Session, analysis: PoAnalysis) -> AnalysisDetailSchema:
    """Assemble the detail payload for one analysis row."""
    _, preview = list_findings(db, analysis.id, limit=FINDINGS_PREVIEW_LIMIT)
    config = get_rule_config()

    return AnalysisDetailSchema(
        **_to_summary(analysis).model_dump(),
        applied_mapping=analysis.applied_mapping or {},
        unmapped_columns=analysis.unmapped_columns or [],
        data_quality_issues=analysis.data_quality_issues or [],
        kpis=analysis.kpis or {},
        supplier_risk=analysis.supplier_risk or [],
        rule_executions=analysis.rule_executions or [],
        rule_errors=analysis.rule_errors or [],
        ai_narrative=_narrative_schema(analysis),
        findings_preview=preview,
        methodology={
            "risk_determination": "deterministic Python rules only",
            "ai_role": "optional narrative rewriting and executive summary, clearly labelled",
            "config_version": analysis.config_version,
            "engine_version": ENGINE_VERSION,
            "base_currency": config.base_currency,
            "currency_rates": config.currency_rates,
            "approval_thresholds": config.approval_thresholds,
            "risk_score_method": (analysis.kpis or {}).get("risk_score_method"),
            "exposure_note": (analysis.kpis or {}).get("exposure_note"),
            "data_disclaimer": (
                "Results are derived exclusively from the uploaded file. This module is not "
                "connected to any SAP system and no recommendation has been validated in a live "
                "SAP environment."
            ),
        },
    )


def _to_summary(analysis: PoAnalysis) -> AnalysisSummarySchema:
    """Map an ORM analysis row onto the summary schema."""
    return AnalysisSummarySchema(
        analysis_id=analysis.id,
        upload_id=analysis.upload_id,
        status=analysis.status,
        source_filename=analysis.source_filename,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
        record_count=analysis.record_count,
        purchase_order_count=analysis.purchase_order_count,
        supplier_count=analysis.supplier_count,
        total_value=float(analysis.total_value or 0),
        base_currency=analysis.base_currency,
        findings_count=analysis.findings_count,
        critical_count=analysis.critical_count,
        high_count=analysis.high_count,
        medium_count=analysis.medium_count,
        low_count=analysis.low_count,
        risk_score=analysis.risk_score,
        estimated_exposure=float(analysis.estimated_exposure or 0),
        config_version=analysis.config_version,
        engine_version=analysis.engine_version,
        ai_provider=analysis.ai_provider,
        ai_output_origin=OutputOrigin(analysis.ai_output_origin)
        if analysis.ai_output_origin
        else None,
        duration_ms=analysis.duration_ms,
        error_message=analysis.error_message,
    )


def _to_finding_schema(finding: PoFinding) -> FindingSchema:
    """Map an ORM finding row onto the API schema."""
    return FindingSchema(
        finding_id=finding.id,
        analysis_id=finding.analysis_id,
        po_number=finding.po_number,
        po_item=finding.po_item,
        supplier_id=finding.supplier_id,
        supplier_name=finding.supplier_name,
        risk_category=finding.risk_category,
        rule_id=finding.rule_id,
        rule_name=finding.rule_name,
        severity=Severity(finding.severity),
        explanation=finding.explanation,
        evidence=finding.evidence or {},
        recommended_action=finding.recommended_action,
        confidence_score=finding.confidence_score,
        estimated_financial_exposure=finding.estimated_financial_exposure,
        exposure_currency=finding.exposure_currency,
        output_origin=OutputOrigin(finding.output_origin),
        ai_explanation=finding.ai_explanation,
        ai_recommended_action=finding.ai_recommended_action,
        ai_output_origin=OutputOrigin(finding.ai_output_origin)
        if finding.ai_output_origin
        else None,
        created_at=finding.created_at,
    )


def _narrative_schema(analysis: PoAnalysis) -> AiNarrativeSchema:
    """Map the stored AI columns onto the narrative schema."""
    return AiNarrativeSchema(
        available=bool(analysis.ai_summary),
        provider=analysis.ai_provider,
        origin=OutputOrigin(analysis.ai_output_origin) if analysis.ai_output_origin else None,
        prompt_version=analysis.ai_prompt_version,
        summary=analysis.ai_summary,
        key_risks=analysis.ai_key_risks or [],
        recommended_actions=analysis.ai_recommended_actions or [],
        input_tokens=analysis.ai_input_tokens,
        output_tokens=analysis.ai_output_tokens,
        estimated_cost_usd=analysis.ai_estimated_cost_usd,
        error=analysis.ai_error,
    )
