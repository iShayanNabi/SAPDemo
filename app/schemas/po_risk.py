"""Request and response schemas for the Purchase Order Risk Checker API.

These models are the contract a future React/Next.js front end will code
against, so they are deliberately explicit: every risk figure carries its
origin label and every AI field is separate from its rule-based counterpart.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import AnalysisStatus, DataQualityIssueSchema, OutputOrigin, Severity


class ExportFormat(str, Enum):
    """Supported report export formats."""

    XLSX = "xlsx"
    CSV = "csv"
    JSON = "json"


class FieldDefinitionSchema(BaseModel):
    """A canonical field the module understands."""

    name: str
    label: str
    field_type: str
    required: bool
    description: str
    aliases: list[str]


class ColumnSuggestionSchema(BaseModel):
    """One automatic column mapping suggestion."""

    source_column: str
    canonical_field: str
    confidence: float = Field(ge=0.0, le=1.0)
    strategy: str


class UploadResponse(BaseModel):
    """Result of ``POST /po-risk/upload``."""

    upload_id: str
    original_filename: str
    file_extension: str
    size_bytes: int
    row_count: int
    column_count: int
    detected_columns: list[str]
    suggested_mapping: dict[str, str]
    mapping_suggestions: list[ColumnSuggestionSchema]
    unmapped_columns: list[str]
    missing_required_fields: list[str]
    is_analyzable: bool
    preview_rows: list[dict[str, Any]]
    parser_notes: list[str] = Field(default_factory=list)
    data_origin: OutputOrigin = OutputOrigin.RULE_BASED


class AnalyzeRequest(BaseModel):
    """Body of ``POST /po-risk/analyze``."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "upload_id": "9f4c2a1e8b7d4f0aa1c3e5d7b9f10246",
                    "generate_ai_summary": True,
                },
                {
                    "upload_id": "9f4c2a1e8b7d4f0aa1c3e5d7b9f10246",
                    "column_mapping_overrides": {"VENDOR_NO": "supplier_id"},
                    "enabled_rules": ["PO-R001", "PO-R009", "PO-R010"],
                    "generate_ai_summary": False,
                    "rewrite_findings": False,
                },
            ]
        },
    )

    upload_id: str = Field(min_length=1, max_length=36)
    column_mapping_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="source column -> canonical field. Empty value removes a column.",
    )
    enabled_rules: list[str] | None = Field(
        default=None, description="Optional subset of rule ids to execute."
    )
    generate_ai_summary: bool = Field(
        default=True, description="Generate the optional AI/mock executive summary."
    )
    rewrite_findings: bool = Field(
        default=False, description="Also rewrite the top findings in business language."
    )


class FindingSchema(BaseModel):
    """One risk finding as returned by the API."""

    finding_id: str
    analysis_id: str
    po_number: str | None
    po_item: str | None
    supplier_id: str | None
    supplier_name: str | None
    risk_category: str
    rule_id: str
    rule_name: str
    severity: Severity
    explanation: str
    evidence: dict[str, Any]
    recommended_action: str
    confidence_score: float = Field(ge=0.0, le=1.0, description="A 0.0-1.0 confidence score.")
    estimated_financial_exposure: float
    exposure_currency: str
    output_origin: OutputOrigin
    ai_explanation: str | None = None
    ai_recommended_action: str | None = None
    ai_output_origin: OutputOrigin | None = None
    created_at: datetime


class AiNarrativeSchema(BaseModel):
    """The optional AI narrative block attached to an analysis."""

    available: bool
    provider: str | None = None
    origin: OutputOrigin | None = None
    prompt_version: str | None = None
    summary: str | None = None
    key_risks: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    error: str | None = None


class SupplierRiskSchema(BaseModel):
    """Per-supplier risk roll-up."""

    supplier_id: str
    supplier_name: str | None
    spend_base: float
    spend_share_pct: float
    line_items: int
    findings_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    estimated_exposure_base: float
    risk_points: int
    top_risk_category: str | None


class RuleExecutionSchema(BaseModel):
    """Bookkeeping for one rule run."""

    rule_id: str
    rule_name: str
    enabled: bool
    findings_count: int
    duration_ms: int
    error: str | None = None


class AnalysisSummarySchema(BaseModel):
    """Analysis header used in list responses."""

    analysis_id: str
    upload_id: str
    status: AnalysisStatus
    source_filename: str
    created_at: datetime
    completed_at: datetime | None
    record_count: int
    purchase_order_count: int
    supplier_count: int
    total_value: float
    base_currency: str
    findings_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    risk_score: float
    estimated_exposure: float
    config_version: str
    engine_version: str
    ai_provider: str | None = None
    ai_output_origin: OutputOrigin | None = None
    duration_ms: int = 0
    error_message: str | None = None


class AnalysisDetailSchema(AnalysisSummarySchema):
    """Full analysis payload with KPIs, supplier table and narrative."""

    applied_mapping: dict[str, str]
    unmapped_columns: list[str]
    data_quality_issues: list[DataQualityIssueSchema]
    kpis: dict[str, Any]
    supplier_risk: list[SupplierRiskSchema]
    rule_executions: list[RuleExecutionSchema] = Field(default_factory=list)
    rule_errors: list[dict[str, str]] = Field(default_factory=list)
    ai_narrative: AiNarrativeSchema
    findings_preview: list[FindingSchema] = Field(default_factory=list)
    methodology: dict[str, Any] = Field(default_factory=dict)


class FindingListResponse(BaseModel):
    """Paginated finding list."""

    analysis_id: str
    total: int
    limit: int
    offset: int
    findings: list[FindingSchema]


class AnalysisListResponse(BaseModel):
    """Paginated analysis list."""

    total: int
    limit: int
    offset: int
    analyses: list[AnalysisSummarySchema]


class RuleInfoSchema(BaseModel):
    """Description of a configured rule, used by the methodology section."""

    rule_id: str
    name: str
    category: str
    enabled: bool
    base_severity: Severity
    confidence: float = Field(ge=0.0, le=1.0, description="A 0.0-1.0 confidence score.")
    recommended_action: str
    params: dict[str, Any]


class SampleDataInfo(BaseModel):
    """Information about the bundled demo dataset."""

    available: bool
    filename: str | None
    row_count: int | None
    anomaly_count: int | None
    data_origin: OutputOrigin = OutputOrigin.DEMO_DATA
    note: str = (
        "Fictional SAP-style demo data generated for this lab. It does not come from any "
        "SAP system and contains no real company information."
    )


class NormalizedRecordSchema(BaseModel):
    """A normalised purchase order line item."""

    row_number: int
    po_number: str | None
    po_item: str | None
    supplier_id: str | None
    supplier_name: str | None
    material: str | None
    material_description: str | None
    material_group: str | None
    company_code: str | None
    purchasing_org: str | None
    purchasing_group: str | None
    plant: str | None
    quantity: float | None
    unit_of_measure: str | None
    unit_price: float | None
    currency: str | None
    total_value: float | None
    total_value_base: float | None
    order_date: date | None
    requested_delivery_date: date | None
    actual_delivery_date: date | None
    contract_number: str | None
    payment_terms: str | None
    approval_status: str | None
    created_by: str | None
    changed_by: str | None
    change_count: int | None
