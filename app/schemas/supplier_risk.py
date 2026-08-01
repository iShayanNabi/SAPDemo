"""Request and response schemas for the Supplier Risk Copilot.

These are the module's API contract. A future React or Next.js front end can
build the whole supplier risk page from these shapes without knowing anything
about the Python engine behind them.

Every user-facing schema carries an ``output_origin`` so a reader can always
tell a computed figure (``rule_based``) from an AI narrative (``ai_generated``
or ``mock_ai``) and from fictional demo data (``demo_data``).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import AnalysisStatus, DataQualityIssueSchema, OutputOrigin


class ExportFormat(str, Enum):
    """Formats a risk assessment can be downloaded in."""

    XLSX = "xlsx"
    CSV = "csv"
    JSON = "json"


class RiskDatasetKind(str, Enum):
    """Which of the module's two uploads a file is."""

    PROFILES = "profiles"
    EVENTS = "events"


# ---------------------------------------------------------------------------
# Upload and dataset
# ---------------------------------------------------------------------------


class ColumnSuggestionSchema(BaseModel):
    """One suggested source-column -> canonical-field mapping."""

    source_column: str
    canonical_field: str
    confidence: float = Field(ge=0.0, le=1.0, description="A 0.0-1.0 confidence score.")
    strategy: str


class SupplierRiskFieldDefinitionSchema(BaseModel):
    """One canonical field and the column names that map to it."""

    name: str
    label: str
    field_type: str
    required: bool
    description: str
    aliases: list[str] = Field(default_factory=list)
    inherited_from_supplier_master: bool = False


class SupplierRiskUploadResponse(BaseModel):
    """The result of uploading a supplier risk file."""

    dataset_id: str | None = None
    upload_id: str
    dataset: RiskDatasetKind = RiskDatasetKind.PROFILES
    filename: str
    file_extension: str = ""
    size_bytes: int = 0
    row_count: int
    supplier_count: int = 0
    event_count: int = 0
    detected_columns: list[str] = Field(default_factory=list)
    suggested_mapping: dict[str, str] = Field(default_factory=dict)
    suggestions: list[ColumnSuggestionSchema] = Field(default_factory=list)
    unmapped_columns: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)
    is_analyzable: bool = False
    data_quality_issues: list[DataQualityIssueSchema] = Field(default_factory=list)
    preview: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class SupplierRiskDatasetSchema(BaseModel):
    """One uploaded supplier risk dataset."""

    id: str
    source_filename: str
    event_filename: str | None = None
    supplier_count: int
    event_count: int
    config_version: str
    base_currency: str
    created_at: datetime | None = None
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class SupplierRiskDatasetListResponse(BaseModel):
    """Every uploaded dataset, newest first."""

    total: int
    datasets: list[SupplierRiskDatasetSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scoring breakdown
# ---------------------------------------------------------------------------


class MetricContributionSchema(BaseModel):
    """One input metric's audited journey into a category score.

    This is what makes the model transparent: the raw value that was read, the
    weight it was given, the 0-100 risk it normalised to, and the points it
    contributed.
    """

    metric: str
    label: str
    raw_value: Any = None
    unit: str = ""
    direction: str
    weight: float
    normalized_weight: float
    normalized_score: float
    contribution: float
    available: bool
    basis: str
    note: str | None = None


class CategoryScoreSchema(BaseModel):
    """One risk category's score and the metrics behind it."""

    category: str
    label: str
    description: str = ""
    score: float | None = None
    band: str | None = None
    weight: float
    normalized_weight: float
    contribution: float
    data_available: bool
    metrics: list[MetricContributionSchema] = Field(default_factory=list)
    missing_metrics: list[str] = Field(default_factory=list)


class RiskTrendSchema(BaseModel):
    """How a supplier's recorded risk events moved between two windows."""

    direction: str
    recent_weight: float = 0.0
    previous_weight: float = 0.0
    delta: float = 0.0
    recent_event_count: int = 0
    previous_event_count: int = 0
    window_days: int = 0
    basis: str = ""
    data_available: bool = False
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class RecommendedActionSchema(BaseModel):
    """One rule-based recommended action."""

    category: str
    category_label: str
    priority: str
    action: str
    trigger: str
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class RiskEventSchema(BaseModel):
    """One dated internal record behind a supplier's risk."""

    event_id: str
    event_type: str
    event_date: str | None = None
    reference: str | None = None
    severity: str | None = None
    description: str | None = None
    amount: float | None = None
    amount_base: float | None = None
    currency: str | None = None


class SupplierRiskSummarySchema(BaseModel):
    """A supplier as it appears in a list."""

    supplier_id: str
    supplier_name: str | None = None
    country: str | None = None
    spend_category: str | None = None
    overall_score: float | None = None
    overall_band: str | None = None
    rank: int | None = None
    trend_direction: str | None = None
    data_completeness_pct: float = 0.0
    limited_data: bool = False
    total_spend_base: float | None = None
    contract_status: str | None = None
    contract_expiration: date | None = None
    contract_expiring_soon: bool = False
    on_time_delivery_rate: float | None = None
    late_delivery_count: int | None = None
    invoice_exception_count: int | None = None
    category_scores: dict[str, float | None] = Field(default_factory=dict)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class SupplierRiskProfileSchema(BaseModel):
    """The complete risk profile for one supplier."""

    supplier_id: str
    supplier_name: str | None = None
    country: str | None = None
    spend_category: str | None = None
    materials_supplied: list[str] = Field(default_factory=list)
    regions_served: list[str] = Field(default_factory=list)

    overall_score: float | None = None
    overall_band: str | None = None
    rank: int | None = None
    data_completeness_pct: float = 0.0
    limited_data: bool = False
    weights_used: dict[str, float] = Field(default_factory=dict)
    categories: list[CategoryScoreSchema] = Field(default_factory=list)
    scored_categories: list[str] = Field(default_factory=list)
    unscored_categories: list[str] = Field(default_factory=list)
    trend: RiskTrendSchema | None = None
    actions: list[RecommendedActionSchema] = Field(default_factory=list)

    # Supporting metrics shown on the profile
    total_spend: float | None = None
    total_spend_base: float | None = None
    currency: str | None = None
    purchase_order_count: int | None = None
    open_purchase_order_count: int | None = None
    active_contract_count: int | None = None
    contract_status: str | None = None
    contract_expiration: date | None = None
    contract_number: str | None = None
    days_to_contract_expiry: int | None = None
    contract_expiring_soon: bool = False
    on_time_delivery_rate: float | None = None
    late_delivery_count: int | None = None
    delivery_count: int | None = None
    quality_score: float | None = None
    defect_rate: float | None = None
    quality_incident_count: int | None = None
    invoice_count: int | None = None
    invoice_exception_count: int | None = None
    disputed_invoice_count: int | None = None
    compliance_finding_count: int | None = None
    esg_score: float | None = None
    credit_score: float | None = None

    delivery_issues: list[RiskEventSchema] = Field(default_factory=list)
    invoice_issues: list[RiskEventSchema] = Field(default_factory=list)
    quality_issues: list[RiskEventSchema] = Field(default_factory=list)
    compliance_issues: list[RiskEventSchema] = Field(default_factory=list)
    event_count: int = 0

    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class SupplierRiskListResponse(BaseModel):
    """A page of assessed suppliers."""

    assessment_id: str
    dataset_id: str
    total: int
    limit: int
    offset: int
    suppliers: list[SupplierRiskSummarySchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Calculate
# ---------------------------------------------------------------------------


class RiskWeightsSchema(BaseModel):
    """Category weights for one run. Must sum to the configured total (100)."""

    model_config = ConfigDict(extra="forbid")

    delivery: float = Field(ge=0.0, le=100.0)
    quality: float = Field(ge=0.0, le=100.0)
    financial: float = Field(ge=0.0, le=100.0)
    spend_concentration: float = Field(ge=0.0, le=100.0)
    contract: float = Field(ge=0.0, le=100.0)
    invoice: float = Field(ge=0.0, le=100.0)
    compliance: float = Field(ge=0.0, le=100.0)
    esg: float = Field(ge=0.0, le=100.0)
    geographic: float = Field(ge=0.0, le=100.0)
    operational: float = Field(ge=0.0, le=100.0)


class CalculateRiskRequest(BaseModel):
    """Run the risk model over a loaded dataset."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str | None = Field(
        default=None,
        max_length=64,
        description="Dataset to assess. Defaults to the most recently uploaded one.",
    )
    weights: RiskWeightsSchema | None = Field(
        default=None, description="Override the configured category weights for this run."
    )
    as_of_date: date | None = Field(
        default=None,
        description=(
            "Reference date for contract expiry and the risk trend windows. "
            "Defaults to today."
        ),
    )
    generate_ai_summary: bool = Field(
        default=False,
        description="Also produce an optional AI narrative. Never changes a score.",
    )


class SupplierRiskAiNarrativeSchema(BaseModel):
    """The optional AI narrative. Always separate from the computed figures."""

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


class RiskAssessmentSummarySchema(BaseModel):
    """Portfolio level results of one assessment."""

    supplier_count: int = 0
    scored_count: int = 0
    event_count: int = 0
    band_counts: dict[str, int] = Field(default_factory=dict)
    category_averages: dict[str, float | None] = Field(default_factory=dict)
    average_overall_score: float | None = None
    highest_risk_supplier_id: str | None = None
    highest_risk_score: float | None = None
    contracts_expiring_count: int = 0
    limited_data_count: int = 0


class RiskAssessmentDetailSchema(BaseModel):
    """One complete risk calculation run."""

    assessment_id: str
    dataset_id: str
    status: AnalysisStatus
    source_filename: str | None = None
    config_version: str
    engine_version: str
    as_of_date: date | None = None
    base_currency: str
    weights: dict[str, float] = Field(default_factory=dict)
    summary: RiskAssessmentSummarySchema = Field(default_factory=RiskAssessmentSummarySchema)
    suppliers: list[SupplierRiskSummarySchema] = Field(default_factory=list)
    rule_errors: list[dict[str, Any]] = Field(default_factory=list)
    ai_narrative: SupplierRiskAiNarrativeSchema = Field(
        default_factory=SupplierRiskAiNarrativeSchema
    )
    duration_ms: int = 0
    created_at: datetime | None = None
    disclaimer: str = ""
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class RiskAssessmentListResponse(BaseModel):
    """Previous assessments, newest first."""

    total: int
    limit: int
    offset: int
    assessments: list[RiskAssessmentDetailSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Copilot chat
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    """A question for the copilot."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    assessment_id: str | None = Field(
        default=None,
        max_length=64,
        description="Assessment to answer from. Defaults to the most recent one.",
    )
    supplier_id: str | None = Field(
        default=None,
        max_length=20,
        description=(
            "Supplier the question is about, for follow-ups like 'why is this supplier "
            "high risk?'."
        ),
    )
    generate_ai_summary: bool = Field(
        default=False,
        description=(
            "Also produce an optional AI rephrasing of the deterministic answer. "
            "The computed answer and its citations are never replaced."
        ),
    )


class CitationSchema(BaseModel):
    """A pointer to the internal record that backs part of an answer."""

    source: str
    record_type: str
    record_id: str
    field_name: str | None = None
    value: Any = None
    detail: str | None = None


class ChatResponse(BaseModel):
    """The copilot's answer, with the records it used."""

    question: str
    intent: str
    answer: str
    data_available: bool = True
    unavailable_reason: str | None = None
    citations: list[CitationSchema] = Field(default_factory=list)
    suppliers_referenced: list[str] = Field(default_factory=list)
    follow_up_suggestions: list[str] = Field(default_factory=list)
    assessment_id: str | None = None
    ai_narrative: SupplierRiskAiNarrativeSchema = Field(
        default_factory=SupplierRiskAiNarrativeSchema
    )
    disclaimer: str = ""
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


# ---------------------------------------------------------------------------
# Model documentation and sample data
# ---------------------------------------------------------------------------


class RiskCategoryInfoSchema(BaseModel):
    """One documented risk category."""

    category: str
    label: str
    description: str
    default_weight: float
    metrics: list[dict[str, Any]] = Field(default_factory=list)


class RiskScoringInfoSchema(BaseModel):
    """The documented scoring model: categories, weights, bands and behaviour."""

    config_version: str
    engine_version: str
    scale: str = "0 = no risk, 100 = maximum risk"
    weight_total: float
    default_weights: dict[str, float] = Field(default_factory=dict)
    categories: list[RiskCategoryInfoSchema] = Field(default_factory=list)
    risk_bands: list[dict[str, Any]] = Field(default_factory=list)
    trend: dict[str, Any] = Field(default_factory=dict)
    missing_data: dict[str, Any] = Field(default_factory=dict)
    contract_expiry: dict[str, Any] = Field(default_factory=dict)
    copilot_intents: list[str] = Field(default_factory=list)
    disclaimer: str = ""
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class SupplierRiskSampleDataInfo(BaseModel):
    """Describes the bundled fictional demo dataset."""

    available: bool = False
    filename: str | None = None
    event_filename: str | None = None
    supplier_count: int | None = None
    event_count: int | None = None
    scenario_count: int | None = None
    as_of_date: str | None = None
    data_origin: OutputOrigin = OutputOrigin.DEMO_DATA
