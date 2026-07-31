"""ORM models for the Inventory Predictor.

Three tables, reusing the shared ``uploaded_files`` table from module 1 for the
upload itself:

``inventory_datasets``
    One row per uploaded inventory history file. A dataset holds the normalised
    movement rows and can be forecast repeatedly with different horizons,
    confidence levels or models without re-uploading the file.
``inventory_records``
    One row per movement row of a dataset - the normalised, typed history.
``inventory_forecasts``
    One row per forecast run: the settings it used, the portfolio summary and
    the optional AI narrative.
``inventory_forecast_items``
    One row per material/plant/storage location inside a run, with the chosen
    model, the horizon totals, the shortage and reorder figures, the stock
    classification, the headline accuracy and the complete engine payload.

The columns lifted out of the payload onto ``inventory_forecast_items`` are the
ones a planner filters and sorts by - shortage date, reorder date, movement
class, dead stock, overstock risk - so a warehouse-sized run can be paged
through in SQL rather than by deserialising every payload.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class InventoryDatasetRow(Base, TimestampMixin):
    """One uploaded inventory history file."""

    __tablename__ = "inventory_datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("uploaded_files.id", ondelete="CASCADE"), index=True
    )
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    config_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")

    applied_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unmapped_columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_quality_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    row_count: Mapped[int] = mapped_column(Integer, default=0)
    series_count: Mapped[int] = mapped_column(Integer, default=0)
    material_count: Mapped[int] = mapped_column(Integer, default=0)
    plant_count: Mapped[int] = mapped_column(Integer, default=0)
    history_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    history_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(20), nullable=True)

    records: Mapped[list["InventoryRecord"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )
    forecasts: Mapped[list["InventoryForecast"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )


class InventoryRecord(Base):
    """One normalised movement row inside a dataset."""

    __tablename__ = "inventory_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_datasets.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, default=0)

    material: Mapped[str] = mapped_column(String(40), index=True)
    plant: Mapped[str] = mapped_column(String(10), index=True)
    storage_location: Mapped[str | None] = mapped_column(String(20), nullable=True)
    period_date: Mapped[date] = mapped_column(Date, index=True)

    #: The full normalised row, so a run can be repeated without the file.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    dataset: Mapped[InventoryDatasetRow] = relationship(back_populates="records")

    __table_args__ = (
        Index("ix_inventory_records_dataset_series", "dataset_id", "material", "plant"),
        Index("ix_inventory_records_dataset_period", "dataset_id", "period_date"),
    )


class InventoryForecast(Base, TimestampMixin):
    """One forecast run over a dataset."""

    __tablename__ = "inventory_forecasts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_datasets.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    config_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")

    as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    horizon_periods: Mapped[int] = mapped_column(Integer, default=0)
    confidence_level: Mapped[float] = mapped_column(Float, default=0.95)
    service_level: Mapped[float] = mapped_column(Float, default=0.95)
    requested_model: Mapped[str | None] = mapped_column(String(40), nullable=True)
    selection_metric: Mapped[str | None] = mapped_column(String(20), nullable=True)

    series_count: Mapped[int] = mapped_column(Integer, default=0)
    forecast_count: Mapped[int] = mapped_column(Integer, default=0)
    insufficient_data_count: Mapped[int] = mapped_column(Integer, default=0)
    shortage_count: Mapped[int] = mapped_column(Integer, default=0)
    reorder_now_count: Mapped[int] = mapped_column(Integer, default=0)
    overstock_count: Mapped[int] = mapped_column(Integer, default=0)
    slow_moving_count: Mapped[int] = mapped_column(Integer, default=0)
    dead_stock_count: Mapped[int] = mapped_column(Integer, default=0)
    total_forecast_demand: Mapped[float | None] = mapped_column(Float, nullable=True)

    model_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    accuracy_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    frequency_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    warning_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    series_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # Optional AI narrative - never a source of any number above.
    ai_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_output_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_key_findings: Mapped[list[str]] = mapped_column(JSON, default=list)
    ai_recommended_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    ai_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    dataset: Mapped[InventoryDatasetRow] = relationship(back_populates="forecasts")
    items: Mapped[list["InventoryForecastItem"]] = relationship(
        back_populates="forecast", cascade="all, delete-orphan", passive_deletes=True
    )


class InventoryForecastItem(Base):
    """One material / plant / storage location inside a forecast run."""

    __tablename__ = "inventory_forecast_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_forecasts.id", ondelete="CASCADE"), index=True
    )
    series_key: Mapped[str] = mapped_column(String(80), index=True)
    material: Mapped[str] = mapped_column(String(40), index=True)
    material_description: Mapped[str | None] = mapped_column(String(120), nullable=True)
    plant: Mapped[str] = mapped_column(String(10), index=True)
    storage_location: Mapped[str | None] = mapped_column(String(20), nullable=True)
    supplier_id: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="forecast", index=True)
    frequency: Mapped[str] = mapped_column(String(20), default="monthly")
    model: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    model_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    selection_basis: Mapped[str | None] = mapped_column(String(30), nullable=True)

    history_period_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_period_count: Mapped[int] = mapped_column(Integer, default=0)
    history_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    total_forecast_demand: Mapped[float | None] = mapped_column(Float, nullable=True)
    opening_inventory: Mapped[float | None] = mapped_column(Float, nullable=True)
    ending_projected_inventory: Mapped[float | None] = mapped_column(Float, nullable=True)
    minimum_projected_inventory: Mapped[float | None] = mapped_column(Float, nullable=True)

    predicted_shortage_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    days_to_shortage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommended_reorder_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    recommended_reorder_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommended_safety_stock: Mapped[float | None] = mapped_column(Float, nullable=True)
    calculated_reorder_point: Mapped[float | None] = mapped_column(Float, nullable=True)
    order_urgency: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    expedite_recommended: Mapped[bool] = mapped_column(Boolean, default=False)

    movement_class: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    is_slow_moving: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_dead_stock: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    overstock_risk: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    days_of_cover: Mapped[float | None] = mapped_column(Float, nullable=True)
    annual_turnover: Mapped[float | None] = mapped_column(Float, nullable=True)

    accuracy_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    mape: Mapped[float | None] = mapped_column(Float, nullable=True)
    smape: Mapped[float | None] = mapped_column(Float, nullable=True)
    mase: Mapped[float | None] = mapped_column(Float, nullable=True)

    warning_count: Mapped[int] = mapped_column(Integer, default=0)

    #: The complete engine output for this series: history, forecast points with
    #: their interval, every model candidate and its backtest score, the
    #: projected stock path, the reorder rationale and the warnings.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_origin: Mapped[str] = mapped_column(String(20), default="forecast")

    forecast: Mapped[InventoryForecast] = relationship(back_populates="items")

    __table_args__ = (
        Index("ix_inventory_items_forecast_series", "forecast_id", "series_key"),
        Index("ix_inventory_items_forecast_material", "forecast_id", "material", "plant"),
        Index("ix_inventory_items_forecast_shortage", "forecast_id", "predicted_shortage_date"),
    )
