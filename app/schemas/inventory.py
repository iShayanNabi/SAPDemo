"""Request and response schemas for the Inventory Predictor.

These are the module's API contract. A future React or Next.js front end can
build the whole inventory page - the chart, the confidence band, the shortage
alerts, the reorder table, the accuracy panel - from these shapes without
knowing anything about the Python engine behind them.

Every user-facing schema carries an ``output_origin``. For this module the
figures are labelled ``forecast`` rather than ``rule_based``: they are
statistical estimates about the future, not deterministic findings about a file,
and the label is what keeps that distinction visible in the UI. The AI narrative
keeps its own ``ai_generated``/``mock_ai`` label in a separate field.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import AnalysisStatus, DataQualityIssueSchema, IssueSeverity, OutputOrigin


class ExportFormat(str, Enum):
    """Formats a forecast run can be downloaded in."""

    XLSX = "xlsx"
    CSV = "csv"
    JSON = "json"


class ForecastModelName(str, Enum):
    """The five explainable methods, plus automatic selection."""

    AUTO = "auto"
    SIMPLE_MOVING_AVERAGE = "simple_moving_average"
    WEIGHTED_MOVING_AVERAGE = "weighted_moving_average"
    SIMPLE_EXPONENTIAL_SMOOTHING = "simple_exponential_smoothing"
    HOLT_LINEAR_TREND = "holt_linear_trend"
    HOLT_WINTERS_SEASONAL = "holt_winters_seasonal"


class ItemSort(str, Enum):
    """Orders the item list can be returned in."""

    SHORTAGE = "shortage"
    REORDER = "reorder"
    DEMAND = "demand"
    ACCURACY = "accuracy"
    MATERIAL = "material"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


class ColumnSuggestionSchema(BaseModel):
    """One suggested source-column -> canonical-field mapping."""

    source_column: str
    canonical_field: str
    confidence: float = Field(ge=0.0, le=1.0, description="A 0.0-1.0 confidence score.")
    strategy: str


class InventoryFieldDefinitionSchema(BaseModel):
    """One canonical field and the column names that map to it."""

    name: str
    label: str
    field_type: str
    required: bool
    description: str
    aliases: list[str] = Field(default_factory=list)
    is_series_key: bool = False


class SeriesSummarySchema(BaseModel):
    """One material/plant/storage location found in an uploaded file."""

    series_key: str
    material: str
    material_description: str | None = None
    plant: str
    storage_location: str | None = None
    supplier_id: str | None = None
    frequency: str
    period_count: int
    observed_period_count: int
    missing_period_count: int
    history_start: date | None = None
    history_end: date | None = None
    total_demand: float | None = None
    closing_inventory: float | None = None


class InventoryUploadResponse(BaseModel):
    """The result of uploading an inventory history file."""

    dataset_id: str | None = None
    upload_id: str
    filename: str
    file_extension: str = ""
    size_bytes: int = 0
    row_count: int
    series_count: int = 0
    material_count: int = 0
    plant_count: int = 0
    frequency: str | None = None
    history_start: date | None = None
    history_end: date | None = None
    detected_columns: list[str] = Field(default_factory=list)
    suggested_mapping: dict[str, str] = Field(default_factory=dict)
    suggestions: list[ColumnSuggestionSchema] = Field(default_factory=list)
    unmapped_columns: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)
    is_analyzable: bool = False
    data_quality_issues: list[DataQualityIssueSchema] = Field(default_factory=list)
    series: list[SeriesSummarySchema] = Field(default_factory=list)
    preview: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class InventoryDatasetSchema(BaseModel):
    """One uploaded inventory dataset."""

    id: str
    source_filename: str
    row_count: int
    series_count: int
    material_count: int
    plant_count: int
    frequency: str | None = None
    history_start: date | None = None
    history_end: date | None = None
    config_version: str
    created_at: datetime | None = None
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class InventoryDatasetListResponse(BaseModel):
    """Every uploaded dataset, newest first."""

    total: int
    datasets: list[InventoryDatasetSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Forecast request
# ---------------------------------------------------------------------------


class ForecastRequest(BaseModel):
    """Run the predictor over a loaded dataset."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str | None = Field(
        default=None,
        max_length=64,
        description="Dataset to forecast. Defaults to the most recently uploaded one.",
    )
    horizon_periods: int | None = Field(
        default=None,
        ge=1,
        le=36,
        description="How many periods ahead to forecast. Defaults to the configured horizon.",
    )
    confidence_level: float | None = Field(
        default=None,
        gt=0.0,
        lt=1.0,
        description=(
            "Confidence level for the prediction interval. Must be one of the levels that "
            "has a configured z-score (see GET /inventory/methods)."
        ),
    )
    model: ForecastModelName = Field(
        default=ForecastModelName.AUTO,
        description=(
            "Force one forecasting method, or 'auto' to select it per material by "
            "backtesting. A forced method that cannot be applied to a material falls back "
            "to automatic selection for that material, and says so."
        ),
    )
    as_of_date: date | None = Field(
        default=None,
        description=(
            "Reference date the projection starts from. Defaults to the end of each "
            "material's own history, so a historical file is analysed as at its own end "
            "rather than as at today."
        ),
    )
    materials: list[str] | None = Field(
        default=None,
        max_length=500,
        description="Restrict the run to these material numbers.",
    )
    plants: list[str] | None = Field(
        default=None,
        max_length=200,
        description="Restrict the run to these plants.",
    )
    generate_ai_summary: bool = Field(
        default=False,
        description="Also produce an optional AI narrative. Never changes a computed figure.",
    )


# ---------------------------------------------------------------------------
# Forecast output
# ---------------------------------------------------------------------------


class ForecastPointSchema(BaseModel):
    """One forecast period: the quantity and the range around it."""

    index: int
    period_date: date
    period_end_date: date
    period_days: int
    demand: float
    lower: float | None = None
    upper: float | None = None
    output_origin: OutputOrigin = OutputOrigin.FORECAST


class HistoryPointSchema(BaseModel):
    """One historical period of a series."""

    index: int
    period_date: date
    demand: float
    observed: bool = True
    starting_inventory: float | None = None
    ending_inventory: float | None = None
    receipts: float | None = None
    issues: float | None = None


class AccuracyMetricsSchema(BaseModel):
    """How far the forecasts fell from what actually happened."""

    observations: int = 0
    mae: float | None = None
    rmse: float | None = None
    mape: float | None = None
    mape_available: bool = False
    mape_unavailable_reason: str | None = None
    zero_demand_periods: int = 0
    smape: float | None = None
    mase: float | None = None
    bias: float | None = None
    bias_pct: float | None = None
    basis: str = ""
    notes: list[str] = Field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.FORECAST


class ModelCandidateSchema(BaseModel):
    """One method that was considered, and how it scored."""

    model_config = ConfigDict(protected_namespaces=())

    model: str
    label: str
    eligible: bool
    ineligible_reason: str | None = None
    evaluated: bool = False
    folds: int = 0
    holdout_periods: int = 0
    score: float | None = None
    metrics: AccuracyMetricsSchema | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    selected: bool = False


class DemandProfileSchema(BaseModel):
    """What kind of demand a series has."""

    observation_count: int = 0
    zero_period_count: int = 0
    zero_period_pct: float = 0.0
    mean_demand: float | None = None
    std_demand: float | None = None
    coefficient_of_variation: float | None = None
    cv_squared: float | None = None
    average_demand_interval: float | None = None
    pattern: str = "unknown"
    is_intermittent: bool = False
    total_demand: float = 0.0


class ModelSelectionSchema(BaseModel):
    """The chosen model, the runners-up and the reasoning."""

    model_config = ConfigDict(protected_namespaces=())

    selected_model: str | None = None
    selection_basis: str = "backtest"
    metric: str = "rmse"
    metric_label: str = ""
    candidates: list[ModelCandidateSchema] = Field(default_factory=list)
    demand_profile: DemandProfileSchema = Field(default_factory=DemandProfileSchema)
    notes: list[str] = Field(default_factory=list)


class ProjectedPeriodSchema(BaseModel):
    """The projected stock position at the end of one future period."""

    index: int
    period_date: date
    period_end_date: date
    opening_inventory: float
    forecast_demand: float
    scheduled_receipts: float
    projected_ending: float
    projected_ending_low: float
    projected_ending_high: float
    inventory_position: float
    below_safety_stock: bool = False
    stockout: bool = False
    days_of_cover: float | None = None
    output_origin: OutputOrigin = OutputOrigin.FORECAST


class ReorderRecommendationSchema(BaseModel):
    """What to order, when, and the policy behind it."""

    lead_time_days: int = 0
    lead_time_source: str = "file"
    review_period_days: int = 0
    service_level: float = 0.0
    service_level_z: float = 0.0
    safety_stock_basis: str = ""
    demand_sigma_per_period: float | None = None
    expected_lead_time_demand: float | None = None
    recommended_safety_stock: float | None = None
    calculated_reorder_point: float | None = None
    reorder_point_at_trigger: float | None = None
    master_safety_stock: float | None = None
    master_reorder_point: float | None = None
    effective_safety_stock: float | None = None
    safety_stock_gap: float | None = None
    reorder_point_gap: float | None = None
    recommended_reorder_date: date | None = None
    recommended_reorder_quantity: float | None = None
    order_urgency: str = "not_required"
    expedite_recommended: bool = False
    expedite_reason: str | None = None
    target_stock_level: float | None = None
    inventory_position_at_reorder: float | None = None
    rationale: list[str] = Field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.FORECAST


class StockHealthSchema(BaseModel):
    """Whether the stock is moving, over-held or dead."""

    days_of_cover: float | None = None
    annual_turnover: float | None = None
    average_inventory: float | None = None
    movement_class: str = "unknown"
    is_slow_moving: bool = False
    is_dead_stock: bool = False
    trailing_zero_demand_periods: int = 0
    zero_demand_period_pct: float = 0.0
    overstock_risk: str = "none"
    overstock_excess_quantity: float | None = None
    overstock_threshold_days: float = 0.0
    classification_basis: list[str] = Field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.FORECAST


class ProjectionSchema(BaseModel):
    """The projected stock path and everything derived from it."""

    opening_inventory: float | None = None
    opening_inventory_date: date | None = None
    periods: list[ProjectedPeriodSchema] = Field(default_factory=list)
    predicted_shortage_date: date | None = None
    days_to_shortage: int | None = None
    predicted_below_safety_stock_date: date | None = None
    shortage_within_horizon: bool = False
    minimum_projected_inventory: float | None = None
    minimum_projected_inventory_date: date | None = None
    ending_projected_inventory: float | None = None
    scheduled_receipt_total: float = 0.0
    unscheduled_open_quantity: float = 0.0
    reorder: ReorderRecommendationSchema = Field(default_factory=ReorderRecommendationSchema)
    health: StockHealthSchema = Field(default_factory=StockHealthSchema)
    available: bool = True
    unavailable_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


class SeriesWarningSchema(BaseModel):
    """One data-quality warning about a single material."""

    code: str
    message: str
    severity: IssueSeverity = IssueSeverity.WARNING


class ForecastItemSummarySchema(BaseModel):
    """One material as it appears in a list."""

    model_config = ConfigDict(protected_namespaces=())

    series_key: str
    material: str
    material_description: str | None = None
    plant: str
    storage_location: str | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None
    status: str = "forecast"
    frequency: str = "monthly"
    model: str | None = None
    model_label: str | None = None
    selection_basis: str | None = None
    history_period_count: int = 0
    missing_period_count: int = 0
    history_end: date | None = None
    total_forecast_demand: float | None = None
    opening_inventory: float | None = None
    ending_projected_inventory: float | None = None
    minimum_projected_inventory: float | None = None
    predicted_shortage_date: date | None = None
    days_to_shortage: int | None = None
    recommended_reorder_date: date | None = None
    recommended_reorder_quantity: float | None = None
    recommended_safety_stock: float | None = None
    calculated_reorder_point: float | None = None
    order_urgency: str | None = None
    expedite_recommended: bool = False
    movement_class: str | None = None
    is_slow_moving: bool = False
    is_dead_stock: bool = False
    overstock_risk: str | None = None
    days_of_cover: float | None = None
    annual_turnover: float | None = None
    accuracy_basis: str | None = None
    mae: float | None = None
    rmse: float | None = None
    mape: float | None = None
    smape: float | None = None
    mase: float | None = None
    warning_count: int = 0
    output_origin: OutputOrigin = OutputOrigin.FORECAST


class ForecastItemDetailSchema(BaseModel):
    """Everything the engine produced for one material."""

    model_config = ConfigDict(protected_namespaces=())

    series_key: str
    material: str
    material_description: str | None = None
    plant: str
    storage_location: str | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None

    status: str = "forecast"
    frequency: str = "monthly"
    season_length: int = 12
    history_period_count: int = 0
    observed_period_count: int = 0
    missing_period_count: int = 0
    history_start: date | None = None
    history_end: date | None = None

    model: str | None = None
    model_label: str | None = None
    model_parameters: dict[str, Any] = Field(default_factory=dict)
    model_assumptions: list[str] = Field(default_factory=list)
    model_notes: list[str] = Field(default_factory=list)
    selection: ModelSelectionSchema | None = None

    horizon_periods: int = 0
    horizon_end_date: date | None = None
    confidence_level: float = 0.95
    forecast: list[ForecastPointSchema] = Field(default_factory=list)
    total_forecast_demand: float | None = None

    accuracy_in_sample: AccuracyMetricsSchema | None = None
    accuracy_backtest: AccuracyMetricsSchema | None = None
    accuracy_headline: AccuracyMetricsSchema | None = None

    projection: ProjectionSchema = Field(default_factory=ProjectionSchema)
    history: list[HistoryPointSchema] = Field(default_factory=list)
    warnings: list[SeriesWarningSchema] = Field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.FORECAST


class ForecastItemListResponse(BaseModel):
    """A page of materials inside one forecast run."""

    forecast_id: str
    total: int
    limit: int
    offset: int
    items: list[ForecastItemSummarySchema] = Field(default_factory=list)


class InventoryAiNarrativeSchema(BaseModel):
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


class ForecastSummarySchema(BaseModel):
    """Portfolio level results of one forecast run."""

    series_count: int = 0
    forecast_count: int = 0
    insufficient_data_count: int = 0
    shortage_count: int = 0
    reorder_now_count: int = 0
    overstock_count: int = 0
    slow_moving_count: int = 0
    dead_stock_count: int = 0
    total_forecast_demand: float | None = None
    model_usage: dict[str, int] = Field(default_factory=dict)
    accuracy_summary: dict[str, float | None] = Field(default_factory=dict)
    frequency_counts: dict[str, int] = Field(default_factory=dict)
    warning_counts: dict[str, int] = Field(default_factory=dict)


class ForecastDetailSchema(BaseModel):
    """One complete forecast run."""

    model_config = ConfigDict(protected_namespaces=())

    forecast_id: str
    dataset_id: str
    status: AnalysisStatus
    source_filename: str | None = None
    config_version: str
    engine_version: str
    as_of_date: date | None = None
    horizon_periods: int = 0
    confidence_level: float = 0.95
    service_level: float = 0.95
    requested_model: str | None = None
    selection_metric: str | None = None
    summary: ForecastSummarySchema = Field(default_factory=ForecastSummarySchema)
    items: list[ForecastItemSummarySchema] = Field(default_factory=list)
    data_quality_issues: list[DataQualityIssueSchema] = Field(default_factory=list)
    series_errors: list[dict[str, Any]] = Field(default_factory=list)
    ai_narrative: InventoryAiNarrativeSchema = Field(default_factory=InventoryAiNarrativeSchema)
    duration_ms: int = 0
    created_at: datetime | None = None
    disclaimer: str = ""
    output_origin: OutputOrigin = OutputOrigin.FORECAST


class ForecastListResponse(BaseModel):
    """Previous forecast runs, newest first."""

    total: int
    limit: int
    offset: int
    forecasts: list[ForecastDetailSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Model documentation and sample data
# ---------------------------------------------------------------------------


class ForecastMethodInfoSchema(BaseModel):
    """One documented forecasting method."""

    model_config = ConfigDict(protected_namespaces=())

    model: str
    label: str
    enabled: bool
    min_observations: int
    parameters: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)


class MethodologySchema(BaseModel):
    """The documented forecasting and planning method."""

    config_version: str
    engine_version: str
    methods: list[ForecastMethodInfoSchema] = Field(default_factory=list)
    selection: dict[str, Any] = Field(default_factory=dict)
    intermittent: dict[str, Any] = Field(default_factory=dict)
    forecast: dict[str, Any] = Field(default_factory=dict)
    reorder: dict[str, Any] = Field(default_factory=dict)
    stock_health: dict[str, Any] = Field(default_factory=dict)
    period: dict[str, Any] = Field(default_factory=dict)
    accuracy_metrics: dict[str, str] = Field(default_factory=dict)
    disclaimer: str = ""
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class InventorySampleDataInfo(BaseModel):
    """Describes the bundled fictional demo dataset."""

    available: bool = False
    filename: str | None = None
    row_count: int | None = None
    material_count: int | None = None
    plant_count: int | None = None
    series_count: int | None = None
    period_count: int | None = None
    history_start: str | None = None
    history_end: str | None = None
    scenario_count: int | None = None
    as_of_date: str | None = None
    data_origin: OutputOrigin = OutputOrigin.DEMO_DATA
