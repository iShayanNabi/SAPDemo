"""Request and response schemas for the Supplier Recommendation Engine.

These types *are* the API contract. A future React front end can be generated
from the OpenAPI schema they produce, which is why every field is typed and
described rather than passed around as a loose dictionary.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import OutputOrigin


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


class SupplierFieldDefinitionSchema(BaseModel):
    """One canonical supplier field, for building a mapping UI."""

    name: str
    label: str
    field_type: str
    required: bool
    description: str
    aliases: list[str]
    is_list_field: bool = False


class SupplierUploadResponse(BaseModel):
    """Result of uploading a supplier master file into a catalogue."""

    catalog_id: str
    upload_id: str
    original_filename: str
    file_extension: str
    size_bytes: int
    supplier_count: int
    detected_columns: list[str]
    preview_rows: list[dict[str, Any]]
    applied_mapping: dict[str, str]
    mapping_suggestions: list[ColumnSuggestionSchema]
    unmapped_columns: list[str]
    missing_required_fields: list[str]
    data_quality_issues: list[dict[str, Any]] = Field(default_factory=list)
    parser_notes: list[str] = Field(default_factory=list)


class WeightsSchema(BaseModel):
    """The nine scoring weights (percentages that must sum to 100)."""

    model_config = ConfigDict(extra="forbid")

    cost: float = Field(ge=0.0, le=100.0)
    delivery: float = Field(ge=0.0, le=100.0)
    quality: float = Field(ge=0.0, le=100.0)
    capacity: float = Field(ge=0.0, le=100.0)
    risk: float = Field(ge=0.0, le=100.0)
    esg: float = Field(ge=0.0, le=100.0)
    contract: float = Field(ge=0.0, le=100.0)
    geographic: float = Field(ge=0.0, le=100.0)
    past_performance: float = Field(ge=0.0, le=100.0)


class RequirementSchema(BaseModel):
    """A purchasing requirement to source suppliers for."""

    model_config = ConfigDict(extra="forbid")

    material: str | None = Field(default=None, max_length=40)
    material_description: str | None = Field(default=None, max_length=255)
    material_group: str | None = Field(default=None, max_length=20)
    quantity: float | None = Field(default=None, ge=0)
    unit_of_measure: str | None = Field(default=None, max_length=10)
    plant: str | None = Field(default=None, max_length=10)
    company_code: str | None = Field(default=None, max_length=10)
    required_delivery_date: date | None = None
    order_date: date | None = Field(
        default=None,
        description="Planned order date. When given, the estimated delivery date is "
        "order_date + the supplier's lead time.",
    )
    target_price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    preferred_region: str | None = Field(default=None, max_length=80)
    risk_tolerance: Literal["low", "medium", "high"] = "medium"
    sustainability_requirement: float | None = Field(
        default=None, ge=0, le=100,
        description="Minimum acceptable ESG score. Suppliers below it are ineligible.",
    )
    contract_requirement: bool = False
    minimum_quality_score: float | None = Field(default=None, ge=0, le=100)
    minimum_available_capacity: float | None = Field(default=None, ge=0)


class RecommendRequest(BaseModel):
    """Request body for ``POST /supplier-recommendations/recommend``."""

    model_config = ConfigDict(extra="forbid")

    catalog_id: str | None = Field(
        default=None,
        description="Supplier catalogue to use. Defaults to the most recently uploaded catalogue.",
    )
    requirement: RequirementSchema
    weights: WeightsSchema | None = Field(
        default=None, description="Custom scoring weights. Defaults to the configured weights."
    )
    top_n: int | None = Field(default=None, ge=1, le=200)
    generate_ai_summary: bool = True
    include_ineligible: bool = True


class RecommendationEntrySchema(BaseModel):
    """One supplier's ranked, scored place in a recommendation."""

    supplier_id: str
    supplier_name: str | None = None
    rank: int | None = None
    eligibility_status: str
    is_eligible: bool
    overall_score: float
    cost_score: float
    delivery_score: float
    quality_score: float
    capacity_score: float
    risk_score: float
    esg_score: float
    contract_score: float
    geographic_score: float
    past_performance_score: float
    estimated_unit_price_base: float | None = None
    estimated_total_cost_base: float | None = None
    estimated_delivery_date: date | None = None
    lead_time_days: int | None = None
    contract_status: str | None = None
    contract_classification: str | None = None
    advantages: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    explanation: str | None = None
    ineligibility_reasons: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class SupplierRecoAiNarrativeSchema(BaseModel):
    """Optional AI commentary. Never the source of any figure or ranking."""

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


class RecommendationDetailSchema(BaseModel):
    """The full recommendation payload."""

    recommendation_id: str
    catalog_id: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: int

    config_version: str
    scoring_engine_version: str
    base_currency: str

    requirement: RequirementSchema
    weights: WeightsSchema
    total_supplier_count: int
    eligible_count: int
    ineligible_count: int
    top_supplier_id: str | None = None
    top_supplier_score: float | None = None

    results: list[RecommendationEntrySchema] = Field(default_factory=list)
    ai_narrative: SupplierRecoAiNarrativeSchema = Field(default_factory=SupplierRecoAiNarrativeSchema)
    methodology: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = ""


class RecommendationSummarySchema(BaseModel):
    """Compact recommendation record used by the list endpoint."""

    recommendation_id: str
    catalog_id: str
    status: str
    base_currency: str
    material: str | None = None
    total_supplier_count: int
    eligible_count: int
    top_supplier_id: str | None = None
    top_supplier_score: float | None = None
    created_at: datetime


class RecommendationListResponse(BaseModel):
    """Paginated list of recommendations."""

    total: int
    limit: int
    offset: int
    recommendations: list[RecommendationSummarySchema]


class SupplierSchema(BaseModel):
    """One supplier from the catalogue, as returned by the suppliers endpoints."""

    supplier_id: str
    supplier_name: str | None = None
    catalog_id: str
    materials_supplied: list[str] = Field(default_factory=list)
    plants_served: list[str] = Field(default_factory=list)
    regions_served: list[str] = Field(default_factory=list)
    unit_price: float | None = None
    currency: str | None = None
    unit_price_base: float | None = None
    lead_time_days: int | None = None
    available_capacity: float | None = None
    on_time_delivery_rate: float | None = None
    quality_score: float | None = None
    defect_rate: float | None = None
    risk_score: float | None = None
    esg_score: float | None = None
    contract_status: str | None = None
    contract_expiration: date | None = None
    payment_terms: str | None = None
    historical_order_count: int | None = None
    historical_spend: float | None = None
    historical_spend_base: float | None = None
    data_origin: OutputOrigin = OutputOrigin.RULE_BASED


class SupplierListResponse(BaseModel):
    """Paginated, filtered supplier list."""

    catalog_id: str | None = None
    total: int
    limit: int
    offset: int
    suppliers: list[SupplierSchema]


class SupplierCatalogInfoSchema(BaseModel):
    """A supplier catalogue and its size."""

    catalog_id: str
    source_filename: str
    supplier_count: int
    base_currency: str
    created_at: datetime


class SupplierCatalogListResponse(BaseModel):
    """Available supplier catalogues, newest first."""

    total: int
    catalogs: list[SupplierCatalogInfoSchema]


class ScoringDimensionInfo(BaseModel):
    """Documentation for one scoring dimension."""

    dimension: str
    label: str
    default_weight: float
    formula: str


class ScoringInfoSchema(BaseModel):
    """The documented scoring model: weights and formulas."""

    config_version: str
    scoring_engine_version: str
    base_currency: str
    weight_total: float
    default_weights: dict[str, float]
    dimensions: list[ScoringDimensionInfo]
    eligibility_filters: list[str]
    normalization: str
    disclaimer: str


class SupplierSampleDataInfo(BaseModel):
    """Description of the bundled demo supplier catalogue."""

    available: bool
    filename: str | None = None
    supplier_count: int | None = None
    scenario_count: int | None = None
    data_origin: OutputOrigin = OutputOrigin.DEMO_DATA
