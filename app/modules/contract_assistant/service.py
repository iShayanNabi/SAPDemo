"""Orchestration for the Contract Assistant.

This is the only layer that knows about the database. It wires the shared
services together in one direction:

    validate document -> store -> extract text -> persist pages
    -> run the deterministic engine -> persist clauses/risks/obligations
    -> optional AI narrative

The engine, the extractors and the question answerer stay pure, so they can be
tested without a database and reused unchanged by a future React front end
talking to the same API.

Persisting the extracted **pages** is what makes the later steps work: an
analysis can be re-run, a question can be answered and a citation can be shown
without the original upload still being on disk.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.contract_assistant import (
    Contract,
    ContractClause,
    ContractObligation,
    ContractPage,
    ContractRisk,
)
from app.models.po_risk import UploadedFile
from app.modules.contract_assistant.ai_narrative import ContractNarrativeService
from app.modules.contract_assistant.clauses import ClauseExtraction, SourceReference
from app.modules.contract_assistant.engine import (
    ENGINE_VERSION,
    ContractAnalysisResult,
    analyze_contract,
)
from app.modules.contract_assistant.qa import QA_VERSION, ContractAnswer, answer_question
from app.modules.contract_assistant.risk_rules import RULES
from app.modules.contract_assistant.thresholds import (
    CLAUSE_TYPES,
    ContractAssistantConfig,
    get_contract_config,
)
from app.schemas.common import OutputOrigin, Severity
from app.schemas.contract_assistant import (
    AnalyzeContractRequest,
    ClauseCatalogueItemSchema,
    ClauseListResponse,
    ClauseSchema,
    ContractAiNarrativeSchema,
    ContractAnswerSchema,
    ContractDetailSchema,
    ContractListItemSchema,
    ContractMethodologySchema,
    ContractPagePreviewSchema,
    ContractPartySchema,
    ContractQuestionRequest,
    ContractRiskSchema,
    ContractRuleInfoSchema,
    ContractStatus,
    ContractSummarySchema,
    ContractUploadResponse,
    ExtractionInfoSchema,
    KeyDatesSchema,
    MissingClauseSchema,
    ObligationSchema,
    SectionSchema,
    SourceReferenceSchema,
)
from app.services.documents.base import ExtractedPage, ExtractionResult
from app.services.documents.factory import describe_extractors, extract_document
from app.services.files.storage import store_upload
from app.services.files.validation import validate_document_upload

logger = get_logger(__name__)

PREVIEW_PAGE_LIMIT = 3
PREVIEW_CHARS = 600


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def handle_upload(db: Session, filename: str, content: bytes) -> ContractUploadResponse:
    """Validate, store and extract the text of an uploaded contract."""
    validated = validate_document_upload(filename, content)
    extraction = extract_document(validated.content, validated.safe_filename)
    stored = store_upload(validated)

    upload = UploadedFile(
        id=uuid.uuid4().hex[:32],
        module="contract_assistant",
        original_filename=validated.original_filename,
        stored_filename=stored.stored_filename,
        file_extension=validated.extension,
        size_bytes=validated.size_bytes,
        sha256=validated.sha256,
        row_count=extraction.page_count,
    )
    db.add(upload)
    db.flush()

    status = ContractStatus.NEEDS_OCR if extraction.needs_ocr else ContractStatus.UPLOADED
    contract = Contract(
        id=uuid.uuid4().hex[:32],
        upload_id=upload.id,
        filename=validated.original_filename,
        file_extension=validated.extension,
        size_bytes=validated.size_bytes,
        sha256=validated.sha256,
        status=status.value,
        extractor=extraction.extractor,
        source_format=extraction.source_format,
        page_basis=extraction.page_basis,
        page_count=extraction.page_count,
        char_count=extraction.char_count,
        needs_ocr=extraction.needs_ocr,
        ocr_used=extraction.ocr_used,
        ocr_provider=extraction.ocr_provider,
        extraction_notes=list(extraction.notes),
        extraction_metadata=dict(extraction.metadata),
        config_version=get_contract_config().config_version,
        engine_version=ENGINE_VERSION,
    )
    db.add(contract)
    db.flush()

    db.bulk_insert_mappings(
        ContractPage,
        [
            {
                "contract_id": contract.id,
                "page_number": page.page_number,
                "char_count": page.char_count,
                "text": page.text,
            }
            for page in extraction.pages
        ],
    )
    db.commit()

    message = (
        "The document parsed but contained no selectable text, so it cannot be analysed. "
        "Upload a text-based PDF, DOCX or TXT file, or configure an OCR provider."
        if extraction.needs_ocr
        else f"Extracted {extraction.char_count:,} characters from {extraction.page_count} page(s)."
    )
    logger.info(
        "Stored contract %s (%s, %d pages, needs_ocr=%s)",
        contract.id,
        validated.extension,
        extraction.page_count,
        extraction.needs_ocr,
    )

    return ContractUploadResponse(
        contract_id=contract.id,
        upload_id=upload.id,
        filename=validated.original_filename,
        file_extension=validated.extension,
        size_bytes=validated.size_bytes,
        status=status,
        page_count=extraction.page_count,
        char_count=extraction.char_count,
        extraction=_extraction_schema(extraction.to_dict()),
        preview=[
            ContractPagePreviewSchema(
                page_number=page.page_number,
                char_count=page.char_count,
                preview=page.text[:PREVIEW_CHARS],
            )
            for page in extraction.pages[:PREVIEW_PAGE_LIMIT]
        ],
        is_analyzable=not extraction.needs_ocr,
        message=message,
        notes=list(extraction.notes),
    )


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------


def analyze(
    db: Session, contract_id: str, request: AnalyzeContractRequest
) -> ContractDetailSchema:
    """Run the deterministic analysis over a stored contract and persist it."""
    config = get_contract_config()
    contract = _require_contract(db, contract_id)
    extraction = _extraction_from_rows(db, contract)

    if not extraction.pages or extraction.char_count == 0:
        raise ValidationError(
            "This document contains no extracted text, so it cannot be analysed. Upload a "
            "text-based PDF, DOCX or TXT file, or configure an OCR provider.",
            details={"contract_id": contract.id, "needs_ocr": contract.needs_ocr},
        )

    unknown = [
        rule_id for rule_id in (request.enabled_rules or []) if rule_id not in config.rules
    ]
    if unknown:
        raise ValidationError(
            f"Unknown contract rule id(s): {', '.join(sorted(unknown))}.",
            details={"unknown_rules": sorted(unknown), "known_rules": sorted(config.rules)},
        )

    result = analyze_contract(
        extraction,
        config,
        as_of_date=request.as_of_date,
        enabled_rules=request.enabled_rules,
    )
    _persist_analysis(db, contract, result, config)

    narrative = ContractAiNarrativeSchema()
    if request.generate_ai_summary:
        narrative = _generate_narrative(contract, result, config)
        _store_narrative(contract, narrative)

    db.commit()
    db.refresh(contract)
    return _detail_from_row(db, contract, config, narrative=narrative)


def _persist_analysis(
    db: Session,
    contract: Contract,
    result: ContractAnalysisResult,
    config: ContractAssistantConfig,
) -> None:
    """Replace any previous analysis of this contract with the new one."""
    for model in (ContractClause, ContractRisk, ContractObligation):
        for row in db.execute(
            select(model).where(model.contract_id == contract.id)
        ).scalars().all():
            db.delete(row)
    db.flush()

    contract.status = (
        ContractStatus.NEEDS_OCR.value if result.needs_ocr else ContractStatus.ANALYZED.value
    )
    contract.contract_title = result.contract_title
    contract.title_reference = (
        result.title_reference.to_dict() if result.title_reference else {}
    )
    contract.parties = [party.to_dict() for party in result.parties]
    contract.sections = list(result.sections)
    contract.section_count = result.section_count

    contract.effective_date = result.key_dates.get("effective_date")
    contract.expiration_date = result.key_dates.get("expiration_date")
    contract.renewal_date = result.key_dates.get("renewal_date")
    contract.notice_deadline = result.key_dates.get("notice_deadline")
    contract.auto_renewal = bool(result.key_dates.get("auto_renewal"))
    contract.notice_period_days = result.key_dates.get("notice_period_days")
    contract.key_dates = {
        key: (value.isoformat() if isinstance(value, date) else value)
        for key, value in result.key_dates.items()
    }

    contract.clauses_found = result.clauses_found
    contract.clauses_expected = result.clauses_expected
    contract.missing_clause_count = len(result.missing_clauses)
    contract.obligation_count = result.obligation_count
    contract.risk_count = len(result.risks)
    contract.severity_counts = dict(result.severity_counts)
    contract.risk_score = result.risk_score
    contract.risk_band = result.risk_band
    contract.missing_clauses = [item.to_dict() for item in result.missing_clauses]
    contract.injection_detected = result.injection_detected
    contract.injection_markers = list(result.injection_markers)
    contract.rule_errors = list(result.rule_errors)
    contract.as_of_date = result.as_of_date
    contract.config_version = result.config_version
    contract.engine_version = result.engine_version
    contract.duration_ms = result.duration_ms
    contract.analyzed_at = datetime.now(UTC)

    db.bulk_insert_mappings(
        ContractClause,
        [
            {
                "contract_id": contract.id,
                "clause_type": clause.clause_type,
                "label": clause.label,
                "present": clause.present,
                "required": clause.required,
                "importance": clause.importance,
                "confidence": clause.confidence,
                "needs_review": clause.needs_review,
                "heading_matched": clause.heading_matched,
                "page_number": clause.page_number,
                "section_heading": clause.section_heading,
                "excerpt": clause.excerpt,
                "matched_terms": list(clause.matched_terms),
                "values": dict(clause.values),
                "references": [ref.to_dict() for ref in clause.references],
                "ai_summary": clause.ai_summary,
                "ai_origin": clause.ai_origin,
                "output_origin": OutputOrigin.RULE_BASED.value,
            }
            for clause in (result.clauses[name] for name in CLAUSE_TYPES)
        ],
    )
    db.bulk_insert_mappings(
        ContractRisk,
        [
            {
                "contract_id": contract.id,
                "rule_id": finding.rule_id,
                "rule_name": finding.rule_name,
                "category": finding.category,
                "severity": finding.severity.value,
                "title": finding.title,
                "explanation": finding.explanation,
                "recommended_action": finding.recommended_action,
                "clause_type": finding.clause_type,
                "page_number": (
                    finding.references[0].page_number if finding.references else None
                ),
                "section_heading": (
                    finding.references[0].section_heading if finding.references else None
                ),
                "excerpt": finding.references[0].excerpt if finding.references else "",
                "evidence": finding.to_dict()["evidence"],
                "references": [ref.to_dict() for ref in finding.references],
                "output_origin": OutputOrigin.RULE_BASED.value,
            }
            for finding in result.risks
        ],
    )
    db.bulk_insert_mappings(
        ContractObligation,
        [
            {
                "contract_id": contract.id,
                "obligation_id": obligation.obligation_id,
                "text": obligation.text,
                "party": obligation.party,
                "party_role": obligation.party_role,
                "duty_type": obligation.duty_type,
                "is_prohibition": obligation.is_prohibition,
                "clause_type": obligation.clause_type,
                "page_number": obligation.reference.page_number,
                "section_heading": obligation.reference.section_heading,
                "confidence": obligation.reference.confidence,
                "reference": obligation.reference.to_dict(),
                "output_origin": OutputOrigin.RULE_BASED.value,
            }
            for obligation in result.obligations
        ],
    )
    db.flush()


def _generate_narrative(
    contract: Contract, result: ContractAnalysisResult, config: ContractAssistantConfig
) -> ContractAiNarrativeSchema:
    """Ask the AI layer for a narrative. A failure is reported, never raised."""
    outcome = ContractNarrativeService().summarise_analysis(
        contract_summary={
            "contract_title": result.contract_title,
            "clauses_found": result.clauses_found,
            "clauses_expected": result.clauses_expected,
            "page_count": result.page_count,
            "risk_score": result.risk_score,
            "risk_band": result.risk_band,
            "severity_counts": dict(result.severity_counts),
            "obligation_count": result.obligation_count,
            "injection_detected": result.injection_detected,
            "parties": [party.name for party in result.parties],
        },
        key_dates={
            key: (value.isoformat() if isinstance(value, date) else value)
            for key, value in result.key_dates.items()
            if not key.endswith("_excerpt")
        },
        clauses=[
            {
                "clause_type": clause.clause_type,
                "label": clause.label,
                "present": clause.present,
                "confidence": clause.confidence,
                "needs_review": clause.needs_review,
                "page_number": clause.page_number,
                "values": clause.values,
            }
            for clause in result.clauses.values()
        ],
        risks=[
            {
                "rule_id": finding.rule_id,
                "severity": finding.severity.value,
                "title": finding.title,
                "explanation": finding.explanation,
                "recommended_action": finding.recommended_action,
                "page_number": (
                    finding.references[0].page_number if finding.references else None
                ),
            }
            for finding in result.risks
        ],
        missing_clauses=[item.to_dict() for item in result.missing_clauses],
    )
    return _narrative_schema(outcome)


def _store_narrative(contract: Contract, narrative: ContractAiNarrativeSchema) -> None:
    contract.ai_provider = narrative.provider
    contract.ai_output_origin = narrative.origin.value if narrative.origin else None
    contract.ai_prompt_version = narrative.prompt_version
    contract.ai_summary = narrative.summary
    contract.ai_key_findings = list(narrative.key_findings)
    contract.ai_recommended_actions = list(narrative.recommended_actions)
    contract.ai_input_tokens = narrative.input_tokens
    contract.ai_output_tokens = narrative.output_tokens
    contract.ai_estimated_cost_usd = narrative.estimated_cost_usd
    contract.ai_error = narrative.error


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


def ask(
    db: Session, contract_id: str, request: ContractQuestionRequest
) -> ContractAnswerSchema:
    """Answer a question about an analysed contract, with citations."""
    config = get_contract_config()
    contract = _require_contract(db, contract_id)

    clause_rows = _clause_rows(db, contract.id)
    clauses = _clauses_from_rows(clause_rows, config) if clause_rows else None

    answer = answer_question(
        request.question,
        config=config,
        clauses=clauses,
        key_dates=_key_dates_from_row(contract),
        risks=[_risk_schema(row).model_dump() for row in _risk_rows(db, contract.id)],
        obligations=[
            _obligation_schema(row).model_dump() for row in _obligation_rows(db, contract.id)
        ],
        missing_clauses=list(contract.missing_clauses or []),
        parties=list(contract.parties or []),
        contract_title=contract.contract_title,
        needs_ocr=contract.needs_ocr,
    )

    narrative = ContractAiNarrativeSchema()
    if request.generate_ai_summary:
        outcome = ContractNarrativeService().rephrase_answer(
            question=answer.question,
            answer={"answer": answer.answer, "answered": answer.answered},
            citations=[citation.to_dict() for citation in answer.citations],
        )
        narrative = _narrative_schema(outcome)

    return _answer_schema(answer, contract.id, config, narrative)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_contract(db: Session, contract_id: str) -> ContractDetailSchema:
    """Return one contract with everything the analysis produced."""
    config = get_contract_config()
    contract = _require_contract(db, contract_id)
    return _detail_from_row(db, contract, config)


def list_contracts(
    db: Session, limit: int = 20, offset: int = 0
) -> tuple[int, list[ContractListItemSchema]]:
    """Return uploaded contracts, newest first."""
    total = db.execute(select(func.count(Contract.id))).scalar_one()
    rows = db.execute(
        select(Contract).order_by(Contract.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return total, [
        ContractListItemSchema(
            contract_id=row.id,
            filename=row.filename,
            file_extension=row.file_extension,
            status=ContractStatus(row.status),
            contract_title=row.contract_title,
            page_count=row.page_count,
            clauses_found=row.clauses_found,
            risk_count=row.risk_count,
            risk_score=row.risk_score,
            risk_band=row.risk_band,
            expiration_date=row.expiration_date,
            created_at=row.created_at,
            analyzed_at=row.analyzed_at,
        )
        for row in rows
    ]


def list_clauses(
    db: Session,
    contract_id: str,
    *,
    present_only: bool = False,
    clause_type: str | None = None,
    min_confidence: float | None = None,
) -> ClauseListResponse:
    """Return the clause table for one contract."""
    config = get_contract_config()
    contract = _require_contract(db, contract_id)
    rows = _clause_rows(db, contract.id)

    if not rows:
        raise ValidationError(
            "This contract has not been analysed yet. Run the analysis first.",
            details={"contract_id": contract.id},
        )

    selected = [
        row
        for row in rows
        if (not present_only or row.present)
        and (clause_type is None or row.clause_type == clause_type)
        and (min_confidence is None or row.confidence >= min_confidence)
    ]
    return ClauseListResponse(
        contract_id=contract.id,
        contract_title=contract.contract_title,
        total=len(selected),
        found=sum(1 for row in rows if row.present),
        expected=len(rows),
        clauses=[_clause_schema(row) for row in selected],
        missing_clauses=[
            MissingClauseSchema(**item) for item in (contract.missing_clauses or [])
        ],
        disclaimer=config.reporting.contract_disclaimer,
    )


def build_export_payload(db: Session, contract_id: str) -> dict[str, Any]:
    """Build the payload every export format is rendered from."""
    config = get_contract_config()
    detail = get_contract(db, contract_id)
    return {
        "contract": {
            "contract_id": detail.contract_id,
            "contract_title": detail.contract_title,
            "filename": detail.filename,
            "status": detail.status.value,
            "as_of_date": detail.as_of_date.isoformat() if detail.as_of_date else None,
            "config_version": detail.config_version,
            "engine_version": detail.engine_version,
            "created_at": detail.created_at.isoformat() if detail.created_at else None,
            "analyzed_at": detail.analyzed_at.isoformat() if detail.analyzed_at else None,
        },
        "summary": detail.summary.model_dump(),
        "key_dates": detail.key_dates.model_dump(mode="json"),
        "parties": [party.model_dump(mode="json") for party in detail.parties],
        "clauses": [clause.model_dump(mode="json") for clause in detail.clauses],
        "missing_clauses": [item.model_dump(mode="json") for item in detail.missing_clauses],
        "risks": [risk.model_dump(mode="json") for risk in detail.risks],
        "obligations": [item.model_dump(mode="json") for item in detail.obligations],
        "sections": [item.model_dump(mode="json") for item in detail.sections],
        "extraction": detail.extraction.model_dump(mode="json") if detail.extraction else {},
        "rule_errors": list(detail.rule_errors),
        "ai_narrative": detail.ai_narrative.model_dump(mode="json"),
        "methodology": {
            "clause_extraction": (
                "Deterministic pattern matching against the configured clause vocabulary. "
                "Every clause carries a page number, a section heading, an excerpt and a "
                "confidence score."
            ),
            "confidence_formula": config.confidence.model_dump(),
            "required_clauses": config.required_clauses,
            "risk_rules": f"{len(config.rules)} configured rules, isolated from each other.",
            "risk_score": (
                "Sum of the per-severity weights of every finding, capped at "
                f"{config.risk.score_cap:g}."
            ),
            "ai_role": (
                "AI never extracts, dates, scores or decides. It only rephrases results that "
                "the engine already produced, in separate fields labelled with their origin."
            ),
            "prompt_injection": config.reporting.injection_notice,
        },
        "disclaimer": config.reporting.contract_disclaimer,
    }


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------


def get_methodology() -> ContractMethodologySchema:
    """Return the documented clause catalogue, rules and settings."""
    config = get_contract_config()
    return ContractMethodologySchema(
        config_version=config.config_version,
        engine_version=ENGINE_VERSION,
        qa_version=QA_VERSION,
        clause_types=[
            ClauseCatalogueItemSchema(
                clause_type=name,
                label=config.clause(name).label,
                description=config.clause(name).description,
                required=config.clause(name).required,
                importance=config.clause(name).importance,
                heading_terms=list(config.clause(name).heading_patterns),
                primary_terms=list(config.clause(name).primary_patterns),
                missing_message=config.clause(name).missing_message,
            )
            for name in CLAUSE_TYPES
        ],
        rules=[
            ContractRuleInfoSchema(
                rule_id=rule_id,
                name=spec.name,
                category=spec.category,
                enabled=spec.enabled,
                base_severity=spec.base_severity,
                recommended_action=spec.recommended_action,
                params=dict(spec.params),
                implemented=rule_id in RULES,
            )
            for rule_id, spec in config.rules.items()
        ],
        required_clauses=config.required_clauses,
        confidence_formula={
            "description": config.confidence.description,
            **config.confidence.model_dump(exclude={"description"}),
            "review_below": config.extraction.review_below_confidence,
            "minimum_to_report": config.extraction.min_confidence,
        },
        date_settings={
            "day_first": config.dates.day_first,
            "expiring_within_days": config.dates.expiring_within_days,
            "critical_within_days": config.dates.critical_within_days,
            "notice_deadline_warning_days": config.dates.notice_deadline_warning_days,
            "description": config.dates.description,
        },
        risk_bands=[band.model_dump() for band in config.risk.bands],
        supported_documents=describe_extractors(),
        suggested_questions=list(config.questions.suggested_questions),
        disclaimer=config.reporting.contract_disclaimer,
        injection_notice=config.reporting.injection_notice,
    )


# ---------------------------------------------------------------------------
# Row -> schema mappers
# ---------------------------------------------------------------------------


def _require_contract(db: Session, contract_id: str) -> Contract:
    contract = db.get(Contract, contract_id)
    if contract is None:
        raise NotFoundError(
            "That contract does not exist.", details={"contract_id": contract_id}
        )
    return contract


def _clause_rows(db: Session, contract_id: str) -> list[ContractClause]:
    return list(
        db.execute(
            select(ContractClause)
            .where(ContractClause.contract_id == contract_id)
            .order_by(ContractClause.id)
        ).scalars().all()
    )


def _risk_rows(db: Session, contract_id: str) -> list[ContractRisk]:
    return list(
        db.execute(
            select(ContractRisk)
            .where(ContractRisk.contract_id == contract_id)
            .order_by(ContractRisk.id)
        ).scalars().all()
    )


def _obligation_rows(db: Session, contract_id: str) -> list[ContractObligation]:
    return list(
        db.execute(
            select(ContractObligation)
            .where(ContractObligation.contract_id == contract_id)
            .order_by(ContractObligation.id)
        ).scalars().all()
    )


def _extraction_from_rows(db: Session, contract: Contract) -> ExtractionResult:
    """Rebuild the extraction result from the persisted pages."""
    rows = db.execute(
        select(ContractPage)
        .where(ContractPage.contract_id == contract.id)
        .order_by(ContractPage.page_number)
    ).scalars().all()
    return ExtractionResult(
        pages=[ExtractedPage(page_number=row.page_number, text=row.text) for row in rows],
        extractor=contract.extractor or "unknown",
        source_format=contract.source_format or contract.file_extension.lstrip("."),
        page_basis=contract.page_basis or "pdf_page",
        needs_ocr=contract.needs_ocr,
        ocr_used=contract.ocr_used,
        ocr_provider=contract.ocr_provider,
        notes=list(contract.extraction_notes or []),
        metadata=dict(contract.extraction_metadata or {}),
    )


def _clauses_from_rows(
    rows: list[ContractClause], config: ContractAssistantConfig
) -> dict[str, ClauseExtraction]:
    """Rebuild the engine's clause objects so the answerer reads stored figures."""
    by_type = {row.clause_type: row for row in rows}
    result: dict[str, ClauseExtraction] = {}
    for name in CLAUSE_TYPES:
        row = by_type.get(name)
        spec = config.clause(name)
        if row is None:
            result[name] = ClauseExtraction(
                clause_type=name,
                label=spec.label,
                description=spec.description,
                present=False,
                importance=spec.importance,
                required=spec.required,
            )
            continue
        result[name] = ClauseExtraction(
            clause_type=row.clause_type,
            label=row.label,
            description=spec.description,
            present=row.present,
            importance=row.importance,
            required=row.required,
            confidence=row.confidence,
            text=row.excerpt,
            references=[
                SourceReference(**{k: v for k, v in reference.items() if k in _REFERENCE_FIELDS})
                for reference in (row.references or [])
            ],
            matched_terms=list(row.matched_terms or []),
            heading_matched=row.heading_matched,
            needs_review=row.needs_review,
            values=dict(row.values or {}),
            ai_summary=row.ai_summary,
            ai_origin=row.ai_origin,
        )
    return result


_REFERENCE_FIELDS = {
    "page_number",
    "section_heading",
    "section_number",
    "excerpt",
    "confidence",
    "char_offset",
    "clause_type",
}


def _reference_schema(data: dict[str, Any]) -> SourceReferenceSchema:
    return SourceReferenceSchema(
        **{key: value for key, value in data.items() if key in _REFERENCE_FIELDS}
    )


def _clause_schema(row: ContractClause) -> ClauseSchema:
    return ClauseSchema(
        clause_type=row.clause_type,
        label=row.label,
        present=row.present,
        importance=row.importance,
        required=row.required,
        confidence=row.confidence,
        page_number=row.page_number,
        section_heading=row.section_heading,
        excerpt=row.excerpt,
        matched_terms=list(row.matched_terms or []),
        heading_matched=row.heading_matched,
        needs_review=row.needs_review,
        values=dict(row.values or {}),
        references=[_reference_schema(item) for item in (row.references or [])],
        ai_summary=row.ai_summary,
        ai_origin=OutputOrigin(row.ai_origin) if row.ai_origin else None,
    )


def _risk_schema(row: ContractRisk) -> ContractRiskSchema:
    return ContractRiskSchema(
        rule_id=row.rule_id,
        rule_name=row.rule_name,
        category=row.category,
        severity=Severity(row.severity),
        title=row.title,
        explanation=row.explanation,
        recommended_action=row.recommended_action,
        clause_type=row.clause_type,
        page_number=row.page_number,
        section_heading=row.section_heading,
        excerpt=row.excerpt,
        evidence=dict(row.evidence or {}),
        references=[_reference_schema(item) for item in (row.references or [])],
    )


def _obligation_schema(row: ContractObligation) -> ObligationSchema:
    reference = dict(row.reference or {})
    return ObligationSchema(
        obligation_id=row.obligation_id,
        text=row.text,
        party=row.party,
        party_role=row.party_role,
        duty_type=row.duty_type,
        is_prohibition=row.is_prohibition,
        clause_type=row.clause_type,
        page_number=row.page_number,
        section_heading=row.section_heading,
        excerpt=reference.get("excerpt", row.text),
        confidence=row.confidence,
        reference=_reference_schema(reference) if reference else None,
    )


def _key_dates_from_row(contract: Contract) -> dict[str, Any]:
    """Rebuild the key-date payload, with the date columns as real dates."""
    payload = dict(contract.key_dates or {})
    payload["effective_date"] = contract.effective_date
    payload["expiration_date"] = contract.expiration_date
    payload["renewal_date"] = contract.renewal_date
    payload["notice_deadline"] = contract.notice_deadline
    payload["auto_renewal"] = contract.auto_renewal
    signature = payload.get("signature_date")
    if isinstance(signature, str):
        try:
            payload["signature_date"] = date.fromisoformat(signature)
        except ValueError:
            payload["signature_date"] = None
    return payload


def _key_dates_schema(contract: Contract) -> KeyDatesSchema:
    payload = _key_dates_from_row(contract)
    fields = set(KeyDatesSchema.model_fields)
    data = {key: value for key, value in payload.items() if key in fields}

    as_of = contract.as_of_date or date.today()
    if contract.expiration_date:
        data["days_to_expiration"] = (contract.expiration_date - as_of).days
    if contract.notice_deadline:
        data["days_to_notice_deadline"] = (contract.notice_deadline - as_of).days
    return KeyDatesSchema(**data)


def _extraction_schema(data: dict[str, Any]) -> ExtractionInfoSchema:
    fields = set(ExtractionInfoSchema.model_fields)
    return ExtractionInfoSchema(**{k: v for k, v in data.items() if k in fields})


def _narrative_schema(outcome: Any) -> ContractAiNarrativeSchema:
    return ContractAiNarrativeSchema(
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


def _narrative_from_row(contract: Contract) -> ContractAiNarrativeSchema:
    if not contract.ai_summary and not contract.ai_error:
        return ContractAiNarrativeSchema()
    return ContractAiNarrativeSchema(
        available=contract.ai_summary is not None,
        origin=OutputOrigin(contract.ai_output_origin) if contract.ai_output_origin else None,
        provider=contract.ai_provider,
        prompt_version=contract.ai_prompt_version,
        summary=contract.ai_summary,
        key_findings=list(contract.ai_key_findings or []),
        recommended_actions=list(contract.ai_recommended_actions or []),
        input_tokens=contract.ai_input_tokens,
        output_tokens=contract.ai_output_tokens,
        estimated_cost_usd=contract.ai_estimated_cost_usd,
        error=contract.ai_error,
    )


def _answer_schema(
    answer: ContractAnswer,
    contract_id: str,
    config: ContractAssistantConfig,
    narrative: ContractAiNarrativeSchema,
) -> ContractAnswerSchema:
    return ContractAnswerSchema(
        question=answer.question,
        intent=answer.intent,
        answer=answer.answer,
        answered=answer.answered,
        clause_types=list(answer.clause_types),
        citations=[_reference_schema(item.to_dict()) for item in answer.citations],
        unavailable_reason=answer.unavailable_reason,
        follow_up_suggestions=list(answer.follow_up_suggestions),
        contract_id=contract_id,
        qa_version=QA_VERSION,
        ai_narrative=narrative,
        disclaimer=config.reporting.contract_disclaimer,
    )


def _detail_from_row(
    db: Session,
    contract: Contract,
    config: ContractAssistantConfig,
    *,
    narrative: ContractAiNarrativeSchema | None = None,
) -> ContractDetailSchema:
    clause_rows = _clause_rows(db, contract.id)
    risk_rows = _risk_rows(db, contract.id)
    obligation_rows = _obligation_rows(db, contract.id)

    return ContractDetailSchema(
        contract_id=contract.id,
        filename=contract.filename,
        file_extension=contract.file_extension,
        status=ContractStatus(contract.status),
        contract_title=contract.contract_title,
        title_reference=(
            _reference_schema(contract.title_reference) if contract.title_reference else None
        ),
        parties=[
            ContractPartySchema(
                **{
                    key: value
                    for key, value in party.items()
                    if key in set(ContractPartySchema.model_fields)
                }
            )
            for party in (contract.parties or [])
        ],
        key_dates=_key_dates_schema(contract),
        summary=ContractSummarySchema(
            clauses_found=contract.clauses_found,
            clauses_expected=contract.clauses_expected,
            missing_clause_count=contract.missing_clause_count,
            obligation_count=contract.obligation_count,
            risk_count=contract.risk_count,
            severity_counts=dict(contract.severity_counts or {}),
            risk_score=contract.risk_score,
            risk_band=contract.risk_band or "low",
            page_count=contract.page_count,
            char_count=contract.char_count,
            section_count=contract.section_count,
            needs_ocr=contract.needs_ocr,
            injection_detected=contract.injection_detected,
        ),
        clauses=[_clause_schema(row) for row in clause_rows],
        missing_clauses=[
            MissingClauseSchema(**item) for item in (contract.missing_clauses or [])
        ],
        risks=[_risk_schema(row) for row in risk_rows],
        obligations=[_obligation_schema(row) for row in obligation_rows],
        sections=[
            SectionSchema(
                **{
                    key: value
                    for key, value in section.items()
                    if key in set(SectionSchema.model_fields)
                }
            )
            for section in (contract.sections or [])
        ],
        extraction=_extraction_schema(
            {
                "extractor": contract.extractor or "unknown",
                "source_format": contract.source_format or "",
                "page_basis": contract.page_basis or "",
                "page_count": contract.page_count,
                "char_count": contract.char_count,
                "needs_ocr": contract.needs_ocr,
                "ocr_used": contract.ocr_used,
                "ocr_provider": contract.ocr_provider,
                "notes": list(contract.extraction_notes or []),
                "metadata": dict(contract.extraction_metadata or {}),
            }
        ),
        injection_markers=list(contract.injection_markers or []),
        rule_errors=list(contract.rule_errors or []),
        ai_narrative=narrative if narrative is not None else _narrative_from_row(contract),
        as_of_date=contract.as_of_date,
        config_version=contract.config_version,
        engine_version=contract.engine_version,
        duration_ms=contract.duration_ms,
        created_at=contract.created_at,
        analyzed_at=contract.analyzed_at,
        disclaimer=config.reporting.contract_disclaimer,
    )
