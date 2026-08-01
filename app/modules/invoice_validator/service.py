"""Service layer for the Invoice Validator.

This is the only place that knows the whole story: it wires the readers, the
column mapper, the three normalisers, the matching engine, the optional AI
narrative and the database together.

Unlike modules 1-3 it joins *three* uploaded files. The invoice file is
mandatory; the purchase order and goods receipt files are optional, and the
rules that depend on a missing dataset are reported as skipped rather than
silently producing nothing.

Data flow::

    3x (bytes -> validate -> store -> read -> suggest mapping)          (upload)
    invoice + optional PO + optional GR uploads
        -> read -> map -> normalise -> match + rules
        -> persist -> optional AI narrative -> response                 (validate)
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.invoice_validator import InvoiceException, InvoiceValidation
from app.models.po_risk import UploadedFile
from app.modules.invoice_validator.ai_narrative import InvoiceNarrativeService
from app.modules.invoice_validator.engine import ENGINE_VERSION, InvoiceValidationEngine
from app.modules.invoice_validator.field_definitions import (
    GOODS_RECEIPT_CANONICAL_FIELDS,
    GOODS_RECEIPT_REGISTRY,
    INVOICE_CANONICAL_FIELDS,
    INVOICE_REGISTRY,
    PO_CANONICAL_FIELDS,
    PO_REGISTRY,
)
from app.modules.invoice_validator.normalizer import (
    NormalizedDataset,
    normalize_goods_receipt_dataframe,
    normalize_invoice_dataframe,
    normalize_po_dataframe,
)
from app.modules.invoice_validator.rules import RULE_IDS
from app.modules.invoice_validator.thresholds import (
    TOLERANCE_KEYS,
    InvoiceValidatorConfig,
    Tolerance,
    get_invoice_validator_config,
)
from app.schemas.common import OutputOrigin, Severity
from app.schemas.invoice_validator import (
    AiNarrativeSchema,
    ColumnSuggestionSchema,
    DatasetFieldCatalogue,
    DatasetKind,
    ExceptionSchema,
    ExportFormat,
    FieldDefinitionSchema,
    InvoiceUploadResponse,
    RuleCatalogueSchema,
    RuleInfoSchema,
    TolerancesSchema,
    ValidateRequest,
    ValidationDetailSchema,
    ValidationSummarySchema,
)
from app.services.exports.invoice_validator_report_builder import (
    build_invoice_validator_csv_report,
    build_invoice_validator_json_report,
    build_invoice_validator_xlsx_report,
    invoice_validator_disclaimer,
)
from app.services.files.readers import preview_records, read_tabular
from app.services.files.storage import read_upload, store_upload
from app.services.files.validation import validate_upload
from app.services.tabular.field_registry import FieldRegistry
from app.services.tabular.mapping import merge_mapping, suggest_mapping, validate_mapping

logger = get_logger(__name__)

PREVIEW_ROW_LIMIT = 10
EXCEPTIONS_PREVIEW_LIMIT = 25

#: dataset -> (registry, canonical fields, normalise function)
_DATASET_SPECS: dict[DatasetKind, tuple[FieldRegistry, tuple[str, ...], Callable]] = {
    DatasetKind.INVOICES: (INVOICE_REGISTRY, INVOICE_CANONICAL_FIELDS, normalize_invoice_dataframe),
    DatasetKind.PURCHASE_ORDERS: (PO_REGISTRY, PO_CANONICAL_FIELDS, normalize_po_dataframe),
    DatasetKind.GOODS_RECEIPTS: (
        GOODS_RECEIPT_REGISTRY, GOODS_RECEIPT_CANONICAL_FIELDS, normalize_goods_receipt_dataframe,
    ),
}

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def handle_upload(
    db: Session, dataset: DatasetKind, filename: str, content: bytes
) -> InvoiceUploadResponse:
    """Validate, store and profile one of the three files."""
    registry, _fields, _normalize = _DATASET_SPECS[dataset]
    validated = validate_upload(filename, content)
    read_result = read_tabular(validated.content, validated.extension)
    mapping_result = suggest_mapping(read_result.source_columns, registry)
    stored = store_upload(validated)

    upload = UploadedFile(
        id=uuid.uuid4().hex[:32],
        module=f"invoice_validator:{dataset.value}",
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
        "Invoice validator upload %s (%s) accepted: %d rows, %d columns",
        upload.id, dataset.value, read_result.row_count, len(read_result.source_columns),
    )
    return InvoiceUploadResponse(
        upload_id=upload.id,
        dataset=dataset,
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
        missing_required_fields=mapping_result.missing_required_fields,
        is_mappable=mapping_result.is_analyzable,
        parser_notes=read_result.notes,
    )


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------
def validate(db: Session, request: ValidateRequest) -> ValidationDetailSchema:
    """Run the full validation pipeline over the three uploaded files."""
    started = time.perf_counter()
    config = _effective_config(get_invoice_validator_config(), request.tolerances)

    if request.enabled_rules:
        unknown = sorted(set(request.enabled_rules) - set(RULE_IDS))
        if unknown:
            raise ValidationError(
                "Unknown rule id(s) requested.",
                details={"unknown_rules": unknown, "available_rules": list(RULE_IDS)},
            )

    invoice_upload, invoice_dataset = _load_dataset(
        db, request.invoice_upload_id, DatasetKind.INVOICES, request.invoice_mapping_overrides, config
    )
    po_upload, po_dataset = _optional_dataset(
        db, request.po_upload_id, DatasetKind.PURCHASE_ORDERS, request.po_mapping_overrides, config
    )
    gr_upload, gr_dataset = _optional_dataset(
        db, request.gr_upload_id, DatasetKind.GOODS_RECEIPTS, request.gr_mapping_overrides, config
    )

    as_of = request.as_of_date or date.today()
    engine = InvoiceValidationEngine(config)
    result = engine.run(
        invoice_dataset.records,
        po_dataset.records if po_dataset else [],
        gr_dataset.records if gr_dataset else [],
        as_of_date=as_of,
        enabled_rules=request.enabled_rules,
    )

    validation_id = uuid.uuid4().hex[:32]
    exceptions_payload: list[dict[str, Any]] = []
    for exception in result.exceptions:
        payload = exception.to_dict()
        payload["exception_id"] = uuid.uuid4().hex[:32]
        payload["validation_id"] = validation_id
        exceptions_payload.append(payload)

    data_quality = _collect_issues(invoice_dataset, po_dataset, gr_dataset)

    # --- optional AI narrative, never allowed to fail the validation ---------
    narrative = None
    if request.generate_ai_summary:
        narrative = InvoiceNarrativeService().generate(
            result.summary, result.supplier_summary, exceptions_payload
        )

    duration_ms = int((time.perf_counter() - started) * 1000)
    validation = _persist_validation(
        db=db,
        validation_id=validation_id,
        invoice_upload=invoice_upload,
        po_upload=po_upload,
        gr_upload=gr_upload,
        config=config,
        as_of=as_of,
        invoice_dataset=invoice_dataset,
        po_dataset=po_dataset,
        gr_dataset=gr_dataset,
        result=result,
        exceptions_payload=exceptions_payload,
        data_quality=data_quality,
        narrative=narrative,
        duration_ms=duration_ms,
    )

    logger.info(
        "Invoice validation %s completed in %d ms with %d exceptions over %d invoices",
        validation_id, duration_ms, len(exceptions_payload), result.summary["invoice_count"],
    )
    return _to_detail(db, validation)


def _persist_validation(
    *,
    db: Session,
    validation_id: str,
    invoice_upload: UploadedFile,
    po_upload: UploadedFile | None,
    gr_upload: UploadedFile | None,
    config: InvoiceValidatorConfig,
    as_of: date,
    invoice_dataset: NormalizedDataset,
    po_dataset: NormalizedDataset | None,
    gr_dataset: NormalizedDataset | None,
    result: Any,
    exceptions_payload: list[dict[str, Any]],
    data_quality: list[dict[str, Any]],
    narrative: Any,
    duration_ms: int,
) -> InvoiceValidation:
    """Write the validation row and its exceptions to the database."""
    summary = result.summary
    severity_counts = summary["severity_counts"]

    validation = InvoiceValidation(
        id=validation_id,
        invoice_upload_id=invoice_upload.id,
        po_upload_id=po_upload.id if po_upload else None,
        gr_upload_id=gr_upload.id if gr_upload else None,
        status="completed",
        invoice_filename=invoice_upload.original_filename,
        po_filename=po_upload.original_filename if po_upload else None,
        gr_filename=gr_upload.original_filename if gr_upload else None,
        config_version=result.config_version,
        engine_version=result.engine_version,
        as_of_date=as_of,
        tolerances=config.tolerances.as_dict(),
        applied_invoice_mapping=invoice_dataset.applied_mapping,
        applied_po_mapping=po_dataset.applied_mapping if po_dataset else {},
        applied_gr_mapping=gr_dataset.applied_mapping if gr_dataset else {},
        data_quality_issues=data_quality,
        kpis=summary,
        supplier_summary=result.supplier_summary,
        three_way_matches=result.three_way_matches,
        rule_executions=[vars(execution) for execution in result.executions],
        rule_errors=result.rule_errors,
        invoice_count=summary["invoice_count"],
        purchase_order_line_count=summary["purchase_order_line_count"],
        goods_receipt_count=summary["goods_receipt_count"],
        supplier_count=summary["supplier_count"],
        total_invoice_amount=summary["total_invoice_amount_base"],
        base_currency=summary["base_currency"],
        exceptions_count=summary["exceptions_count"],
        critical_count=severity_counts["critical"],
        high_count=severity_counts["high"],
        medium_count=severity_counts["medium"],
        low_count=severity_counts["low"],
        flagged_value=summary["flagged_value_base"],
        estimated_exposure=summary["estimated_exposure_base"],
        exception_score=summary["exception_score"],
        duration_ms=duration_ms,
        completed_at=datetime.now(UTC),
    )

    if narrative is not None:
        validation.ai_provider = narrative.provider
        validation.ai_output_origin = narrative.origin.value if narrative.origin else None
        validation.ai_prompt_version = narrative.prompt_version
        validation.ai_summary = narrative.summary
        validation.ai_key_findings = narrative.key_findings
        validation.ai_recommended_actions = narrative.recommended_actions
        validation.ai_input_tokens = narrative.input_tokens
        validation.ai_output_tokens = narrative.output_tokens
        validation.ai_estimated_cost_usd = narrative.estimated_cost_usd
        validation.ai_error = narrative.error

    db.add(validation)
    db.flush()

    db.bulk_save_objects(
        [
            InvoiceException(
                id=payload["exception_id"],
                validation_id=validation_id,
                rule_id=payload["rule_id"],
                rule_name=payload["rule_name"],
                exception_type=payload["exception_type"],
                category=payload["category"],
                severity=payload["severity"],
                invoice_number=payload.get("invoice_number"),
                supplier_id=payload.get("supplier_id"),
                supplier_name=payload.get("supplier_name"),
                po_number=payload.get("po_number"),
                po_item=payload.get("po_item"),
                gr_number=payload.get("gr_number"),
                expected_value=payload.get("expected_value"),
                actual_value=payload.get("actual_value"),
                difference=payload.get("difference"),
                difference_amount=payload.get("difference_amount", 0.0),
                currency=payload.get("currency", config.base_currency),
                explanation=payload["explanation"],
                recommended_action=payload["recommended_action"],
                confidence_score=payload["confidence_score"],
                evidence=payload["evidence"],
                output_origin=payload["output_origin"],
            )
            for payload in exceptions_payload
        ]
    )
    db.commit()
    db.refresh(validation)
    return validation


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------
def _load_dataset(
    db: Session,
    upload_id: str,
    dataset: DatasetKind,
    overrides: dict[str, str] | None,
    config: InvoiceValidatorConfig,
) -> tuple[UploadedFile, NormalizedDataset]:
    """Read, map and normalise one uploaded dataset."""
    upload = db.get(UploadedFile, upload_id)
    if upload is None:
        raise NotFoundError(
            f"The {dataset.value} upload was not found. Upload the file again before validating.",
            details={"upload_id": upload_id},
        )
    registry, _fields, normalize = _DATASET_SPECS[dataset]
    content = read_upload(upload.stored_filename)
    read_result = read_tabular(content, upload.file_extension)
    suggested = suggest_mapping(read_result.source_columns, registry).mapping
    mapping = merge_mapping(suggested, overrides)
    validate_mapping(mapping, read_result.source_columns, registry)
    normalized = normalize(read_result.dataframe, mapping, config)
    return upload, normalized


def _optional_dataset(
    db: Session,
    upload_id: str | None,
    dataset: DatasetKind,
    overrides: dict[str, str] | None,
    config: InvoiceValidatorConfig,
) -> tuple[UploadedFile | None, NormalizedDataset | None]:
    if not upload_id:
        return None, None
    return _load_dataset(db, upload_id, dataset, overrides, config)


def _effective_config(
    config: InvoiceValidatorConfig, overrides: TolerancesSchema | None
) -> InvoiceValidatorConfig:
    """Apply per-run tolerance overrides on top of the configured tolerances."""
    if overrides is None:
        return config
    updates: dict[str, Tolerance] = {}
    for key in TOLERANCE_KEYS:
        override = getattr(overrides, key)
        if override is not None:
            updates[key] = Tolerance(pct=override.pct, abs=override.abs)
    if not updates:
        return config
    return config.with_tolerances(config.tolerances.model_copy(update=updates))


def _collect_issues(
    invoice_dataset: NormalizedDataset,
    po_dataset: NormalizedDataset | None,
    gr_dataset: NormalizedDataset | None,
) -> list[dict[str, Any]]:
    """Combine the three datasets' data-quality issues, tagged by dataset."""
    issues: list[dict[str, Any]] = []
    for label, dataset in (
        ("invoices", invoice_dataset),
        ("purchase_orders", po_dataset),
        ("goods_receipts", gr_dataset),
    ):
        if dataset is None:
            continue
        for issue in dataset.issues_as_dicts():
            issues.append({"dataset": label, **issue})
    return issues


# ---------------------------------------------------------------------------
# Read APIs
# ---------------------------------------------------------------------------
def list_validations(
    db: Session, limit: int = 20, offset: int = 0
) -> tuple[int, list[ValidationSummarySchema]]:
    """Return a page of validations, newest first."""
    total = db.scalar(select(func.count()).select_from(InvoiceValidation)) or 0
    rows = db.scalars(
        select(InvoiceValidation).order_by(InvoiceValidation.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return total, [_to_summary(row) for row in rows]


def get_validation(db: Session, validation_id: str) -> ValidationDetailSchema:
    """Return the full detail payload for one validation."""
    validation = _require_validation(db, validation_id)
    return _to_detail(db, validation)


def list_exceptions(
    db: Session,
    validation_id: str,
    *,
    severity: list[str] | None = None,
    rule_id: str | None = None,
    exception_type: str | None = None,
    category: str | None = None,
    supplier_id: str | None = None,
    invoice_number: str | None = None,
    po_number: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, list[ExceptionSchema]]:
    """Return a filtered page of exceptions for a validation."""
    _require_validation(db, validation_id)

    statement = select(InvoiceException).where(InvoiceException.validation_id == validation_id)
    count_statement = select(func.count()).select_from(InvoiceException).where(
        InvoiceException.validation_id == validation_id
    )

    def _apply(stmt, condition):
        return stmt.where(condition)

    if severity:
        normalised = [value.lower() for value in severity]
        statement = _apply(statement, InvoiceException.severity.in_(normalised))
        count_statement = _apply(count_statement, InvoiceException.severity.in_(normalised))
    if rule_id:
        statement = _apply(statement, InvoiceException.rule_id == rule_id)
        count_statement = _apply(count_statement, InvoiceException.rule_id == rule_id)
    if exception_type:
        statement = _apply(statement, InvoiceException.exception_type == exception_type)
        count_statement = _apply(count_statement, InvoiceException.exception_type == exception_type)
    if category:
        statement = _apply(statement, InvoiceException.category == category)
        count_statement = _apply(count_statement, InvoiceException.category == category)
    if supplier_id:
        statement = _apply(statement, InvoiceException.supplier_id == supplier_id)
        count_statement = _apply(count_statement, InvoiceException.supplier_id == supplier_id)
    if invoice_number:
        statement = _apply(statement, InvoiceException.invoice_number == invoice_number)
        count_statement = _apply(count_statement, InvoiceException.invoice_number == invoice_number)
    if po_number:
        statement = _apply(statement, InvoiceException.po_number == po_number)
        count_statement = _apply(count_statement, InvoiceException.po_number == po_number)

    total = db.scalar(count_statement) or 0
    rows = db.scalars(statement).all()
    rows = sorted(
        rows,
        key=lambda row: (
            _SEVERITY_ORDER.get(row.severity, 9),
            -float(row.difference_amount or 0.0),
        ),
    )[offset : offset + limit]
    return total, [_to_exception_schema(row) for row in rows]


def export_validation(
    db: Session, validation_id: str, export_format: ExportFormat
) -> tuple[bytes, str, str]:
    """Build a downloadable report. Returns ``(content, filename, media_type)``."""
    validation = _require_validation(db, validation_id)
    exceptions = db.scalars(
        select(InvoiceException).where(InvoiceException.validation_id == validation_id)
    ).all()
    exceptions = sorted(
        exceptions,
        key=lambda row: (_SEVERITY_ORDER.get(row.severity, 9), -float(row.difference_amount or 0.0)),
    )
    exceptions_payload = [_to_exception_schema(row).model_dump(mode="json") for row in exceptions]

    payload: dict[str, Any] = {
        "validation": _to_summary(validation).model_dump(mode="json"),
        "kpis": validation.kpis or {},
        "supplier_summary": validation.supplier_summary or [],
        "three_way_matches": validation.three_way_matches or [],
        "data_quality_issues": validation.data_quality_issues or [],
        "tolerances": validation.tolerances or {},
        "applied_mappings": {
            "invoices": validation.applied_invoice_mapping or {},
            "purchase_orders": validation.applied_po_mapping or {},
            "goods_receipts": validation.applied_gr_mapping or {},
        },
        "ai_narrative": _narrative_schema(validation).model_dump(mode="json"),
        "methodology": methodology(get_invoice_validator_config()),
        "exceptions": exceptions_payload,
    }

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    if export_format is ExportFormat.XLSX:
        return (
            build_invoice_validator_xlsx_report(payload),
            f"invoice_validation_{validation_id[:8]}_{stamp}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if export_format is ExportFormat.CSV:
        return (
            build_invoice_validator_csv_report(exceptions_payload),
            f"invoice_exceptions_{validation_id[:8]}_{stamp}.csv",
            "text/csv",
        )
    return (
        build_invoice_validator_json_report(payload),
        f"invoice_validation_{validation_id[:8]}_{stamp}.json",
        "application/json",
    )


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------
def get_field_catalogue() -> DatasetFieldCatalogue:
    """Return the canonical fields for all three datasets."""
    return DatasetFieldCatalogue(
        invoices=[_field_schema(d) for d in INVOICE_REGISTRY.definitions],
        purchase_orders=[_field_schema(d) for d in PO_REGISTRY.definitions],
        goods_receipts=[_field_schema(d) for d in GOODS_RECEIPT_REGISTRY.definitions],
    )


def get_rule_catalogue() -> RuleCatalogueSchema:
    """Return the configured rule catalogue with the active tolerances."""
    config = get_invoice_validator_config()
    rules = [
        RuleInfoSchema(
            rule_id=rule_id,
            name=settings.name,
            category=settings.category,
            enabled=settings.enabled,
            base_severity=settings.base_severity,
            confidence=settings.confidence,
            recommended_action=settings.recommended_action,
            params=settings.params,
        )
        for rule_id in RULE_IDS
        for settings in [config.rule(rule_id)]
    ]
    return RuleCatalogueSchema(
        config_version=config.config_version,
        engine_version=ENGINE_VERSION,
        base_currency=config.base_currency,
        tolerances=config.tolerances.as_dict(),
        expected_tax_rate=config.expected_tax_rate,
        freight_policy=config.freight_policy.model_dump(),
        closed_po_status_values=list(config.closed_po_status_values),
        rules=rules,
    )


def methodology(config: InvoiceValidatorConfig) -> dict[str, Any]:
    """Describe how the validation was produced, for the UI and the export."""
    return {
        "validation_basis": "deterministic three-way matching and tolerance arithmetic, no AI",
        "ai_role": "optional narrative summary of the exceptions, clearly labelled",
        "engine_version": ENGINE_VERSION,
        "config_version": config.config_version,
        "base_currency": config.base_currency,
        "currency_rates": config.currency_rates,
        "tolerances": config.tolerances.as_dict(),
        "expected_tax_rate": config.expected_tax_rate,
        "freight_policy": config.freight_policy.model_dump(),
        "join_keys": "invoices join to purchase orders and goods receipts on PO number + item.",
        "exception_score_method": (
            "weighted severity points (low=1, medium=3, high=8, critical=20) divided by the number "
            "of invoice lines, multiplied by 10, capped at 100"
        ),
        "data_disclaimer": (
            "Results are derived exclusively from the uploaded files. This module is not connected "
            "to any SAP system and no result has been validated in a live SAP environment."
        ),
    }


# ---------------------------------------------------------------------------
# Mappers
# ---------------------------------------------------------------------------
def _field_schema(definition) -> FieldDefinitionSchema:
    return FieldDefinitionSchema(
        name=definition.name,
        label=definition.label,
        field_type=definition.field_type.value,
        required=definition.required,
        description=definition.description,
        aliases=list(definition.aliases),
    )


def _require_validation(db: Session, validation_id: str) -> InvoiceValidation:
    validation = db.get(InvoiceValidation, validation_id)
    if validation is None:
        raise NotFoundError("Validation not found.", details={"validation_id": validation_id})
    return validation


def _to_summary(validation: InvoiceValidation) -> ValidationSummarySchema:
    return ValidationSummarySchema(
        validation_id=validation.id,
        status=validation.status,
        invoice_filename=validation.invoice_filename,
        po_filename=validation.po_filename,
        gr_filename=validation.gr_filename,
        created_at=validation.created_at,
        completed_at=validation.completed_at,
        invoice_count=validation.invoice_count,
        purchase_order_line_count=validation.purchase_order_line_count,
        goods_receipt_count=validation.goods_receipt_count,
        supplier_count=validation.supplier_count,
        total_invoice_amount=float(validation.total_invoice_amount or 0),
        base_currency=validation.base_currency,
        exceptions_count=validation.exceptions_count,
        critical_count=validation.critical_count,
        high_count=validation.high_count,
        medium_count=validation.medium_count,
        low_count=validation.low_count,
        exception_score=validation.exception_score,
        estimated_exposure=float(validation.estimated_exposure or 0),
        config_version=validation.config_version,
        engine_version=validation.engine_version,
        ai_provider=validation.ai_provider,
        ai_output_origin=OutputOrigin(validation.ai_output_origin)
        if validation.ai_output_origin
        else None,
        duration_ms=validation.duration_ms,
        error_message=validation.error_message,
    )


def _to_detail(db: Session, validation: InvoiceValidation) -> ValidationDetailSchema:
    _, preview = list_exceptions(db, validation.id, limit=EXCEPTIONS_PREVIEW_LIMIT)
    config = get_invoice_validator_config()
    return ValidationDetailSchema(
        **_to_summary(validation).model_dump(),
        as_of_date=validation.as_of_date,
        tolerances=validation.tolerances or {},
        applied_invoice_mapping=validation.applied_invoice_mapping or {},
        applied_po_mapping=validation.applied_po_mapping or {},
        applied_gr_mapping=validation.applied_gr_mapping or {},
        data_quality_issues=validation.data_quality_issues or [],
        kpis=validation.kpis or {},
        supplier_summary=validation.supplier_summary or [],
        three_way_matches=validation.three_way_matches or [],
        rule_executions=validation.rule_executions or [],
        rule_errors=validation.rule_errors or [],
        exceptions_preview=preview,
        ai_narrative=_narrative_schema(validation),
        methodology=methodology(config),
        disclaimer=config.reporting.validation_disclaimer or invoice_validator_disclaimer(),
    )


def _to_exception_schema(row: InvoiceException) -> ExceptionSchema:
    return ExceptionSchema(
        exception_id=row.id,
        validation_id=row.validation_id,
        rule_id=row.rule_id,
        rule_name=row.rule_name,
        exception_type=row.exception_type,
        category=row.category,
        severity=Severity(row.severity),
        invoice_number=row.invoice_number,
        supplier_id=row.supplier_id,
        supplier_name=row.supplier_name,
        po_number=row.po_number,
        po_item=row.po_item,
        gr_number=row.gr_number,
        expected_value=row.expected_value,
        actual_value=row.actual_value,
        difference=row.difference,
        difference_amount=float(row.difference_amount or 0.0),
        currency=row.currency,
        explanation=row.explanation,
        recommended_action=row.recommended_action,
        confidence_score=row.confidence_score,
        evidence=row.evidence or {},
        output_origin=OutputOrigin(row.output_origin),
        ai_explanation=row.ai_explanation,
        ai_recommended_action=row.ai_recommended_action,
        ai_output_origin=OutputOrigin(row.ai_output_origin) if row.ai_output_origin else None,
        created_at=row.created_at,
    )


def _narrative_schema(validation: InvoiceValidation) -> AiNarrativeSchema:
    return AiNarrativeSchema(
        available=bool(validation.ai_summary),
        origin=OutputOrigin(validation.ai_output_origin) if validation.ai_output_origin else None,
        provider=validation.ai_provider,
        prompt_version=validation.ai_prompt_version,
        summary=validation.ai_summary,
        key_findings=list(validation.ai_key_findings or []),
        recommended_actions=list(validation.ai_recommended_actions or []),
        input_tokens=validation.ai_input_tokens,
        output_tokens=validation.ai_output_tokens,
        estimated_cost_usd=validation.ai_estimated_cost_usd,
        error=validation.ai_error,
    )
