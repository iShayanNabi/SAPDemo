"""Request and response schemas for the Spend Analytics Dashboard.

These types *are* the API contract. A future React front end can be generated
from the OpenAPI schema these produce, which is why every field is typed and
described rather than passed around as a loose dictionary.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import AnalysisStatus, DataQualityIssueSchema, OutputOrigin


class ExportFormat(str, Enum):
    """Supported export formats."""

    XLSX = "xlsx"
    CSV = "csv"
    JSON = "json"


class ColumnSuggestionSchema(BaseModel):
    """One suggested column mapping with its confidence."""

    source_column: str
    canonical_field: str
    confidence: float = Field(ge=0.0, le=1.0)
    strategy: str


class SpendUploadResponse(BaseModel):
    """Result of uploading a spend file."""

    upload_id: str
    original_filename: str
    file_extension: str
    size_bytes: int
    row_count: int
    column_count: int
    detected_columns: list[str]
    preview_rows: list[dict[str, Any]]
    suggested_mapping: dict[str, str]
    mapping_suggestions: list[ColumnSuggestionSchema]
    unmapped_columns: list[str]
    missing_required_fields: list[str]
    is_analyzable: bool
    parser_notes: list[str] = Field(default_factory=list)


class SpendFilterSchema(BaseModel):
    """Filter selection sent with an analysis request."""

    model_config = ConfigDict(extra="forbid")

    date_from: date | None = None
    date_to: date | None = None
    supplier_id: list[str] = Field(default_factory=list)
    material: list[str] = Field(default_factory=list)
    material_group: list[str] = Field(default_factory=list)
    category: list[str] = Field(default_factory=list)
    subcategory: list[str] = Field(default_factory=list)
    plant: list[str] = Field(default_factory=list)
    company_code: list[str] = Field(default_factory=list)
    purchasing_org: list[str] = Field(default_factory=list)
    purchasing_group: list[str] = Field(default_factory=list)
    currency: list[str] = Field(default_factory=list)
    contract_status: list[str] = Field(default_factory=list)
    preferred_supplier_status: list[str] = Field(default_factory=list)

    def to_values(self) -> dict[str, list[str]]:
        """Return only the categorical selections, keyed by canonical field."""
        payload = self.model_dump(exclude={"date_from", "date_to"})
        return {name: values for name, values in payload.items() if values}


class SpendAnalyzeRequest(BaseModel):
    """Request body for ``POST /spend/analyze``."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"upload_id": "9f4c2a1e8b7d4f0aa1c3e5d7b9f10246", "generate_ai_summary": True},
                {
                    "upload_id": "9f4c2a1e8b7d4f0aa1c3e5d7b9f10246",
                    "filters": {
                        "date_from": "2026-01-01",
                        "date_to": "2026-06-30",
                        "category": ["Indirect materials"],
                    },
                    "top_n": 20,
                    "generate_ai_summary": False,
                },
            ]
        },
    )

    upload_id: str = Field(min_length=8, max_length=64)
    column_mapping_overrides: dict[str, str] = Field(default_factory=dict)
    filters: SpendFilterSchema = Field(default_factory=SpendFilterSchema)
    enabled_savings_rules: list[str] | None = Field(
        default=None, description="Restrict the savings engine to these rule IDs."
    )
    generate_ai_summary: bool = True
    top_n: int | None = Field(default=None, ge=1, le=100)


class SpendMetricsSchema(BaseModel):
    """Every headline metric, all deterministically calculated."""

    total_spend: float
    purchase_order_count: int
    line_item_count: int
    supplier_count: int
    average_po_value: float
    median_po_value: float

    contracted_spend: float
    non_contracted_spend: float
    contracted_spend_pct: float
    maverick_spend: float
    maverick_spend_pct: float
    spend_under_management: float
    spend_under_management_pct: float

    supplier_concentration_hhi: float
    supplier_concentration_level: str
    top_supplier_share_pct: float
    top_supplier_id: str | None = None
    top_five_supplier_share_pct: float
    tail_spend: float
    tail_spend_pct: float
    tail_supplier_count: int

    price_variance_base: float
    price_variance_pct: float
    price_variance_line_count: int
    estimated_savings_opportunity: float

    spend_by_currency: list[dict[str, Any]] = Field(default_factory=list)
    base_currency: str = "EUR"
    metrics_version: str = "1.0.0"
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class SavingsOpportunitySchema(BaseModel):
    """One modelled savings opportunity.

    ``is_estimate`` is always true: these figures are models, not commitments.
    """

    opportunity_id: str
    rule_id: str
    rule_name: str
    opportunity_type: str
    scope: str
    scope_value: str
    scope_label: str | None = None
    title: str
    description: str
    method: str
    addressable_spend_base: float
    gross_saving_base: float
    realization_factor: float
    estimated_saving_base: float
    confidence: float = Field(ge=0.0, le=1.0, description="A 0.0-1.0 confidence score.")
    transaction_count: int
    supplier_count: int
    evidence: dict[str, Any] = Field(default_factory=dict)
    is_estimate: bool = True
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class SpendAiNarrativeSchema(BaseModel):
    """Optional AI commentary. Never the source of any figure."""

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


class SpendTransactionSchema(BaseModel):
    """One transaction row, as returned by the drill-down endpoint."""

    row_number: int
    po_number: str | None = None
    po_item: str | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None
    material: str | None = None
    material_description: str | None = None
    material_group: str | None = None
    category: str | None = None
    subcategory: str | None = None
    company_code: str | None = None
    purchasing_org: str | None = None
    purchasing_group: str | None = None
    plant: str | None = None
    quantity: float | None = None
    unit_of_measure: str | None = None
    unit_price: float | None = None
    baseline_price: float | None = None
    current_price: float | None = None
    currency: str | None = None
    total_value: float | None = None
    spend_base: float = 0.0
    effective_date: date | None = None
    spend_month: str | None = None
    contract_number: str | None = None
    contract_status: str | None = None
    preferred_supplier_status: str | None = None
    payment_status: str | None = None
    is_contracted: bool = False
    is_preferred_supplier: bool = False
    is_maverick: bool = False
    is_under_management: bool = False
    price_variance_base: float | None = None
    price_variance_pct: float | None = None


class SpendAnalysisSummarySchema(BaseModel):
    """Compact analysis record used by the list endpoint."""

    analysis_id: str
    status: AnalysisStatus
    source_filename: str
    base_currency: str
    total_spend: float
    record_count: int
    filtered_record_count: int
    supplier_count: int
    estimated_savings: float
    opportunity_count: int
    period_start: date | None = None
    period_end: date | None = None
    created_at: datetime


class SpendAnalysisDetailSchema(BaseModel):
    """The full analysis payload."""

    analysis_id: str
    upload_id: str
    status: AnalysisStatus
    source_filename: str
    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: int

    config_version: str
    metrics_version: str
    savings_engine_version: str
    applied_mapping: dict[str, str]
    unmapped_columns: list[str]
    data_quality_issues: list[DataQualityIssueSchema] = Field(default_factory=list)

    applied_filter: dict[str, Any] = Field(default_factory=dict)
    filter_options: dict[str, list[str]] = Field(default_factory=dict)
    record_count: int
    filtered_record_count: int
    period_start: date | None = None
    period_end: date | None = None

    metrics: SpendMetricsSchema
    analytics: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    supplier_spend: list[dict[str, Any]] = Field(default_factory=list)
    opportunities: list[SavingsOpportunitySchema] = Field(default_factory=list)
    savings_executions: list[dict[str, Any]] = Field(default_factory=list)
    savings_errors: list[dict[str, Any]] = Field(default_factory=list)
    ai_narrative: SpendAiNarrativeSchema = Field(default_factory=SpendAiNarrativeSchema)
    methodology: dict[str, Any] = Field(default_factory=dict)


class SpendAnalysisListResponse(BaseModel):
    """Paginated list of analyses."""

    total: int
    limit: int
    offset: int
    analyses: list[SpendAnalysisSummarySchema]


class SpendTransactionListResponse(BaseModel):
    """Paginated, filtered transaction list used for drill-down."""

    analysis_id: str
    total: int
    limit: int
    offset: int
    total_spend_base: float
    transactions: list[SpendTransactionSchema]


class SpendOpportunityListResponse(BaseModel):
    """Savings opportunities with their standing disclaimer.

    ``limit`` and ``offset`` echo the window that was served. The endpoint has
    always paged; without them a client holding 100 of 137 opportunities had no
    way to tell that from holding all of them.
    """

    analysis_id: str
    total: int
    limit: int
    offset: int
    total_estimated_saving_base: float
    base_currency: str
    disclaimer: str
    opportunities: list[SavingsOpportunitySchema]


class SpendFieldDefinitionSchema(BaseModel):
    """One canonical field, for building a mapping UI."""

    name: str
    label: str
    field_type: str
    required: bool
    description: str
    aliases: list[str]
    is_spend_specific: bool = False


class SavingsRuleInfoSchema(BaseModel):
    """One configured savings rule and its assumptions."""

    rule_id: str
    name: str
    enabled: bool
    description: str
    confidence: float = Field(ge=0.0, le=1.0, description="A 0.0-1.0 confidence score.")
    realization_factor: float
    params: dict[str, Any] = Field(default_factory=dict)


class SpendSampleDataInfo(BaseModel):
    """Description of the bundled demo dataset."""

    available: bool
    filename: str | None = None
    row_count: int | None = None
    scenario_count: int | None = None
    months_covered: int | None = None
    data_origin: OutputOrigin = OutputOrigin.DEMO_DATA
