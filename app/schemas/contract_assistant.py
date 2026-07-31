"""Request and response schemas for the Contract Assistant.

These are the module's API contract. A future React or Next.js front end can
build the whole contract page - upload, extraction status, summary, key dates,
clause table, obligations, risks, missing clauses, source references, chat and
export - from these shapes alone.

Two conventions carry through every schema:

* every user-facing object carries an ``output_origin``, so a reader can tell a
  pattern-matched clause (``rule_based``) from an AI narrative
  (``ai_generated`` / ``mock_ai``) and from fictional demo data (``demo_data``);
* every extracted claim carries a :class:`SourceReferenceSchema`, so nothing
  the assistant says is unverifiable.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import OutputOrigin, Severity


class ExportFormat(str, Enum):
    """Formats a contract analysis can be downloaded in."""

    XLSX = "xlsx"
    CSV = "csv"
    JSON = "json"


class ContractStatus(str, Enum):
    """Where an uploaded contract is in the pipeline."""

    UPLOADED = "uploaded"
    ANALYZED = "analyzed"
    #: The document parsed but held no text: it needs OCR that is not configured.
    NEEDS_OCR = "needs_ocr"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Source references - the backbone of the module
# ---------------------------------------------------------------------------


class SourceReferenceSchema(BaseModel):
    """Where one extracted claim came from.

    Every clause, answer, obligation and risk finding carries at least one of
    these. Page number and section heading are optional because not every
    document has them (a TXT file has no real pages), but the excerpt and the
    confidence always exist.
    """

    page_number: int | None = Field(default=None, description="1-based page number")
    section_heading: str | None = Field(default=None, description="Heading as printed")
    section_number: str | None = None
    excerpt: str = Field(default="", description="Short supporting quotation")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    char_offset: int | None = None
    clause_type: str | None = None


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


class ExtractionInfoSchema(BaseModel):
    """How the document's text was obtained."""

    extractor: str
    source_format: str
    page_basis: str = Field(description="pdf_page, page_break or char_budget")
    page_count: int = 0
    char_count: int = 0
    empty_page_count: int = 0
    needs_ocr: bool = False
    ocr_used: bool = False
    ocr_provider: str | None = None
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContractPagePreviewSchema(BaseModel):
    """A short preview of one extracted page."""

    page_number: int
    char_count: int
    preview: str


class ContractUploadResponse(BaseModel):
    """The result of uploading a contract document."""

    contract_id: str
    upload_id: str
    filename: str
    file_extension: str
    size_bytes: int
    status: ContractStatus
    page_count: int = 0
    char_count: int = 0
    section_count: int = 0
    detected_title: str | None = None
    extraction: ExtractionInfoSchema
    preview: list[ContractPagePreviewSchema] = Field(default_factory=list)
    is_analyzable: bool = True
    message: str = ""
    notes: list[str] = Field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


class AnalyzeContractRequest(BaseModel):
    """Body of ``POST /contracts/{contract_id}/analyze``."""

    model_config = ConfigDict(extra="forbid")

    as_of_date: date | None = Field(
        default=None,
        description="Date the expiry and notice windows are measured against. Defaults to today.",
    )
    enabled_rules: list[str] | None = Field(
        default=None, description="Restrict the run to these rule ids."
    )
    generate_ai_summary: bool = Field(
        default=False,
        description=(
            "Ask the configured AI provider for a plain-language summary of the already "
            "computed results. Never changes a clause, a date or a risk."
        ),
    )


class ClauseSchema(BaseModel):
    """One extracted clause."""

    clause_type: str
    label: str
    description: str = ""
    present: bool
    importance: str
    required: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    page_number: int | None = None
    section_heading: str | None = None
    excerpt: str = ""
    matched_terms: list[str] = Field(default_factory=list)
    heading_matched: bool = False
    needs_review: bool = False
    values: dict[str, Any] = Field(default_factory=dict)
    references: list[SourceReferenceSchema] = Field(default_factory=list)
    #: Optional AI rewording of an already extracted clause. Never its source.
    ai_summary: str | None = None
    ai_origin: OutputOrigin | None = None
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class ContractPartySchema(BaseModel):
    """One party named in the contract."""

    name: str
    role: str | None = None
    page_number: int | None = None
    section_heading: str | None = None
    excerpt: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class KeyDatesSchema(BaseModel):
    """The dates a contract register needs.

    ``*_basis`` says whether a date was read from the document (``stated``) or
    computed from other values (``derived_from_term``,
    ``derived_from_expiration``). A derived date is never presented as one the
    contract actually printed.
    """

    effective_date: date | None = None
    effective_date_basis: str | None = None
    effective_date_page: int | None = None
    effective_date_excerpt: str | None = None

    expiration_date: date | None = None
    expiration_date_basis: str | None = None
    expiration_date_page: int | None = None
    expiration_date_excerpt: str | None = None

    renewal_date: date | None = None
    renewal_date_basis: str | None = None
    renewal_date_page: int | None = None
    renewal_date_excerpt: str | None = None

    signature_date: date | None = None
    signature_date_basis: str | None = None
    signature_date_page: int | None = None
    signature_date_excerpt: str | None = None

    notice_deadline: date | None = Field(
        default=None,
        description="Last day to give notice before the contract renews itself.",
    )
    notice_deadline_basis: str | None = None

    auto_renewal: bool = False
    term_length_days: int | None = None
    term_length_label: str | None = None
    notice_period_days: int | None = None
    notice_period_label: str | None = None
    renewal_term_days: int | None = None
    renewal_term_label: str | None = None
    renewal_notice_days: int | None = None
    renewal_notice_label: str | None = None

    days_to_expiration: int | None = None
    days_to_notice_deadline: int | None = None
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class ObligationSchema(BaseModel):
    """One duty found in the contract, quoted verbatim."""

    obligation_id: str
    text: str
    party: str | None = None
    party_role: str | None = None
    duty_type: str
    is_prohibition: bool = False
    clause_type: str | None = None
    page_number: int | None = None
    section_heading: str | None = None
    excerpt: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reference: SourceReferenceSchema | None = None
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class ContractRiskSchema(BaseModel):
    """One deterministic risk finding."""

    rule_id: str
    rule_name: str
    category: str
    severity: Severity
    title: str
    explanation: str
    recommended_action: str = ""
    clause_type: str | None = None
    page_number: int | None = None
    section_heading: str | None = None
    excerpt: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    references: list[SourceReferenceSchema] = Field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class MissingClauseSchema(BaseModel):
    """One expected clause the document does not contain."""

    clause_type: str
    label: str
    importance: str
    required: bool
    message: str = ""
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class SectionSchema(BaseModel):
    """One detected section of the document."""

    index: int
    number: str | None = None
    title: str = ""
    heading: str = ""
    page_number: int | None = None


class ContractAiNarrativeSchema(BaseModel):
    """The optional AI narrative for a contract analysis."""

    available: bool = False
    origin: OutputOrigin | None = None
    provider: str | None = None
    prompt_version: str | None = None
    summary: str | None = None
    key_findings: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    error: str | None = None


class ContractSummarySchema(BaseModel):
    """The headline figures of one analysis."""

    clauses_found: int = 0
    clauses_expected: int = 0
    missing_clause_count: int = 0
    obligation_count: int = 0
    risk_count: int = 0
    severity_counts: dict[str, int] = Field(default_factory=dict)
    risk_score: float = 0.0
    risk_band: str = "low"
    page_count: int = 0
    char_count: int = 0
    section_count: int = 0
    needs_ocr: bool = False
    injection_detected: bool = False


class ContractDetailSchema(BaseModel):
    """One contract with everything the analysis produced."""

    contract_id: str
    filename: str
    file_extension: str
    status: ContractStatus
    contract_title: str | None = None
    title_reference: SourceReferenceSchema | None = None
    parties: list[ContractPartySchema] = Field(default_factory=list)
    key_dates: KeyDatesSchema = Field(default_factory=KeyDatesSchema)
    summary: ContractSummarySchema = Field(default_factory=ContractSummarySchema)
    clauses: list[ClauseSchema] = Field(default_factory=list)
    missing_clauses: list[MissingClauseSchema] = Field(default_factory=list)
    risks: list[ContractRiskSchema] = Field(default_factory=list)
    obligations: list[ObligationSchema] = Field(default_factory=list)
    sections: list[SectionSchema] = Field(default_factory=list)
    extraction: ExtractionInfoSchema | None = None
    injection_markers: list[str] = Field(default_factory=list)
    rule_errors: list[dict[str, str]] = Field(default_factory=list)
    ai_narrative: ContractAiNarrativeSchema = Field(default_factory=ContractAiNarrativeSchema)
    as_of_date: date | None = None
    config_version: str = ""
    engine_version: str = ""
    duration_ms: int = 0
    created_at: datetime | None = None
    analyzed_at: datetime | None = None
    disclaimer: str = ""
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class ContractListItemSchema(BaseModel):
    """One row of the uploaded-contract list."""

    contract_id: str
    filename: str
    file_extension: str
    status: ContractStatus
    contract_title: str | None = None
    page_count: int = 0
    clauses_found: int = 0
    risk_count: int = 0
    risk_score: float = 0.0
    risk_band: str | None = None
    expiration_date: date | None = None
    created_at: datetime | None = None
    analyzed_at: datetime | None = None


class ContractListResponse(BaseModel):
    """Every uploaded contract, newest first."""

    total: int
    limit: int
    offset: int
    contracts: list[ContractListItemSchema] = Field(default_factory=list)


class ClauseListResponse(BaseModel):
    """The clause table for one contract."""

    contract_id: str
    contract_title: str | None = None
    total: int
    found: int
    expected: int
    clauses: list[ClauseSchema] = Field(default_factory=list)
    missing_clauses: list[MissingClauseSchema] = Field(default_factory=list)
    disclaimer: str = ""


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


class ContractQuestionRequest(BaseModel):
    """Body of ``POST /contracts/{contract_id}/questions``."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    generate_ai_summary: bool = Field(
        default=False,
        description=(
            "Ask the AI provider to rephrase the deterministic answer. The answer itself and "
            "its citations are always produced by code."
        ),
    )


class ContractAnswerSchema(BaseModel):
    """One answer, with its citations."""

    question: str
    intent: str
    answer: str
    answered: bool = True
    clause_types: list[str] = Field(default_factory=list)
    citations: list[SourceReferenceSchema] = Field(default_factory=list)
    unavailable_reason: str | None = None
    follow_up_suggestions: list[str] = Field(default_factory=list)
    contract_id: str | None = None
    qa_version: str = ""
    ai_narrative: ContractAiNarrativeSchema = Field(default_factory=ContractAiNarrativeSchema)
    disclaimer: str = ""
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


# ---------------------------------------------------------------------------
# Documentation endpoints
# ---------------------------------------------------------------------------


class ClauseCatalogueItemSchema(BaseModel):
    """One clause type the module knows how to extract."""

    clause_type: str
    label: str
    description: str
    required: bool
    importance: str
    heading_terms: list[str] = Field(default_factory=list)
    primary_terms: list[str] = Field(default_factory=list)
    missing_message: str = ""


class ContractRuleInfoSchema(BaseModel):
    """One configured risk rule."""

    rule_id: str
    name: str
    category: str
    enabled: bool
    base_severity: Severity
    recommended_action: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    implemented: bool = True


class ContractMethodologySchema(BaseModel):
    """How the module decides what it decides."""

    config_version: str
    engine_version: str
    qa_version: str
    clause_types: list[ClauseCatalogueItemSchema] = Field(default_factory=list)
    rules: list[ContractRuleInfoSchema] = Field(default_factory=list)
    required_clauses: list[str] = Field(default_factory=list)
    confidence_formula: dict[str, Any] = Field(default_factory=dict)
    date_settings: dict[str, Any] = Field(default_factory=dict)
    risk_bands: list[dict[str, Any]] = Field(default_factory=list)
    supported_documents: dict[str, Any] = Field(default_factory=dict)
    suggested_questions: list[str] = Field(default_factory=list)
    disclaimer: str = ""
    injection_notice: str = ""


class ContractSampleDataInfo(BaseModel):
    """Describes the bundled fictional sample contracts."""

    available: bool = False
    contract_count: int | None = None
    scenario_count: int | None = None
    as_of_date: str | None = None
    formats: list[str] = Field(default_factory=list)
    contracts: list[dict[str, Any]] = Field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.DEMO_DATA
