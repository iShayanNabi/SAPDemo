"""Request and response schemas for the Invoice Validator.

These types *are* the API contract. A future React front end can be generated
from the OpenAPI schema they produce, which is why every field is typed and
described rather than passed around as a loose dictionary.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import AnalysisStatus, DataQualityIssueSchema, OutputOrigin, Severity


class ExportFormat(str, Enum):
    """Supported export formats."""

    XLSX = "xlsx"
    CSV = "csv"
    JSON = "json"


class DatasetKind(str, Enum):
    """Which of the three datasets an upload belongs to."""

    INVOICES = "invoices"
    PURCHASE_ORDERS = "purchase_orders"
    GOODS_RECEIPTS = "goods_receipts"


class ColumnSuggestionSchema(BaseModel):
    """One suggested source column -> canonical field mapping."""

    source_column: str
    canonical_field: str
    confidence: float = Field(ge=0.0, le=1.0)
    strategy: str


class FieldDefinitionSchema(BaseModel):
    """One canonical field, for building a mapping UI."""

    name: str
    label: str
    field_type: str
    required: bool
    description: str
    aliases: list[str]


class DatasetFieldCatalogue(BaseModel):
    """Canonical fields for all three datasets."""

    invoices: list[FieldDefinitionSchema]
    purchase_orders: list[FieldDefinitionSchema]
    goods_receipts: list[FieldDefinitionSchema]


class InvoiceUploadResponse(BaseModel):
    """Result of uploading one of the three files."""

    upload_id: str
    dataset: DatasetKind
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
    is_mappable: bool
    parser_notes: list[str] = Field(default_factory=list)


class ToleranceSchema(BaseModel):
    """A percentage + absolute allowance."""

    model_config = ConfigDict(extra="forbid")

    pct: float = Field(default=0.0, ge=0.0)
    abs: float = Field(default=0.0, ge=0.0)


class TolerancesSchema(BaseModel):
    """The four configurable tolerances."""

    model_config = ConfigDict(extra="forbid")

    price: ToleranceSchema | None = None
    quantity: ToleranceSchema | None = None
    tax: ToleranceSchema | None = None
    freight: ToleranceSchema | None = None


class ValidateRequest(BaseModel):
    """Request body for ``POST /invoices/validate``."""

    model_config = ConfigDict(extra="forbid")

    invoice_upload_id: str = Field(description="Upload id of the invoices file.")
    po_upload_id: str | None = Field(
        default=None, description="Upload id of the purchase orders file (optional)."
    )
    gr_upload_id: str | None = Field(
        default=None, description="Upload id of the goods receipts file (optional)."
    )
    invoice_mapping_overrides: dict[str, str] | None = None
    po_mapping_overrides: dict[str, str] | None = None
    gr_mapping_overrides: dict[str, str] | None = None
    tolerances: TolerancesSchema | None = Field(
        default=None, description="Override the configured price/quantity/tax/freight tolerances."
    )
    as_of_date: date | None = Field(
        default=None,
        description="Reference date for the future-invoice-date check. Defaults to today.",
    )
    enabled_rules: list[str] | None = Field(
        default=None, description="Optional subset of rule ids to run. Defaults to every enabled rule."
    )
    generate_ai_summary: bool = True


class ExceptionSchema(BaseModel):
    """One invoice exception, as returned by the API and exports."""

    exception_id: str
    validation_id: str
    rule_id: str
    rule_name: str
    exception_type: str
    category: str
    severity: Severity
    invoice_number: str | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None
    po_number: str | None = None
    po_item: str | None = None
    gr_number: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    difference: str | None = None
    difference_amount: float = 0.0
    currency: str = "EUR"
    explanation: str
    recommended_action: str
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="A 0.0-1.0 confidence score.")
    evidence: dict[str, Any] = Field(default_factory=dict)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED
    ai_explanation: str | None = None
    ai_recommended_action: str | None = None
    ai_output_origin: OutputOrigin | None = None
    created_at: datetime | None = None


class AiNarrativeSchema(BaseModel):
    """Optional AI commentary. Never the source of any exception."""

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


class ValidationSummarySchema(BaseModel):
    """Compact validation record used by the list endpoint and detail header."""

    validation_id: str
    status: AnalysisStatus
    invoice_filename: str | None = None
    po_filename: str | None = None
    gr_filename: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    invoice_count: int
    purchase_order_line_count: int
    goods_receipt_count: int
    supplier_count: int
    total_invoice_amount: float
    base_currency: str
    exceptions_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    exception_score: float
    estimated_exposure: float
    config_version: str
    engine_version: str
    ai_provider: str | None = None
    ai_output_origin: OutputOrigin | None = None
    duration_ms: int
    error_message: str | None = None


class ValidationDetailSchema(ValidationSummarySchema):
    """The full validation payload."""

    as_of_date: date | None = None
    tolerances: dict[str, Any] = Field(default_factory=dict)
    applied_invoice_mapping: dict[str, str] = Field(default_factory=dict)
    applied_po_mapping: dict[str, str] = Field(default_factory=dict)
    applied_gr_mapping: dict[str, str] = Field(default_factory=dict)
    data_quality_issues: list[DataQualityIssueSchema] = Field(default_factory=list)
    kpis: dict[str, Any] = Field(default_factory=dict)
    supplier_summary: list[dict[str, Any]] = Field(default_factory=list)
    three_way_matches: list[dict[str, Any]] = Field(default_factory=list)
    rule_executions: list[dict[str, Any]] = Field(default_factory=list)
    rule_errors: list[dict[str, Any]] = Field(default_factory=list)
    exceptions_preview: list[ExceptionSchema] = Field(default_factory=list)
    ai_narrative: AiNarrativeSchema = Field(default_factory=AiNarrativeSchema)
    methodology: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = ""


class ValidationListResponse(BaseModel):
    """Paginated list of validations."""

    total: int
    limit: int
    offset: int
    validations: list[ValidationSummarySchema]


class ExceptionListResponse(BaseModel):
    """Paginated, filtered list of exceptions for one validation."""

    validation_id: str
    total: int
    limit: int
    offset: int
    exceptions: list[ExceptionSchema]


class RuleInfoSchema(BaseModel):
    """One configured validation rule, for the methodology view."""

    rule_id: str
    name: str
    category: str
    enabled: bool
    base_severity: Severity
    confidence: float = Field(ge=0.0, le=1.0, description="A 0.0-1.0 confidence score.")
    recommended_action: str
    params: dict[str, Any] = Field(default_factory=dict)


class RuleCatalogueSchema(BaseModel):
    """The rule catalogue plus the active tolerances and tax/freight policy."""

    config_version: str
    engine_version: str
    base_currency: str
    tolerances: dict[str, Any]
    expected_tax_rate: float
    freight_policy: dict[str, Any]
    closed_po_status_values: list[str]
    rules: list[RuleInfoSchema]


class SampleDataInfo(BaseModel):
    """Description of the bundled demo invoice datasets."""

    available: bool
    invoice_count: int | None = None
    goods_receipt_count: int | None = None
    purchase_order_line_count: int | None = None
    scenario_count: int | None = None
    data_origin: OutputOrigin = OutputOrigin.DEMO_DATA
