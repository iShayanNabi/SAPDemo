"""ORM models for the Spend Analytics Dashboard.

Three tables, reusing the shared ``uploaded_files`` table from module 1 for the
upload itself:

``spend_analyses``
    One row per analysis run: the filter that was applied, every headline
    metric, the analytics breakdowns and the optional AI narrative.
``spend_transactions``
    The normalised transactions that were analysed. Persisting them is what
    makes drill-down possible without re-reading the source file, and it keeps
    an analysis reproducible after the upload is cleaned up.
``spend_opportunities``
    One row per modelled savings opportunity, with the evidence and the
    arithmetic that produced it.
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
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class SpendAnalysis(Base, TimestampMixin):
    """One spend analysis run."""

    __tablename__ = "spend_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("uploaded_files.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provenance
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    config_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")
    metrics_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")
    savings_engine_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")
    applied_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unmapped_columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_quality_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    applied_filter: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Headline metrics (columns so they can be listed and sorted without JSON parsing)
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR")
    total_spend: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    filtered_record_count: Mapped[int] = mapped_column(Integer, default=0)
    purchase_order_count: Mapped[int] = mapped_column(Integer, default=0)
    supplier_count: Mapped[int] = mapped_column(Integer, default=0)
    contracted_spend: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    maverick_spend: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    tail_spend: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    spend_under_management_pct: Mapped[float] = mapped_column(Float, default=0.0)
    supplier_concentration_hhi: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_savings: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    opportunity_count: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Full payloads
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    analytics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    supplier_spend: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    savings_executions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    savings_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    filter_options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Optional AI narrative
    ai_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_output_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_key_findings: Mapped[list[str]] = mapped_column(JSON, default=list)
    ai_recommended_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    ai_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    transactions: Mapped[list["SpendTransaction"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", passive_deletes=True
    )
    opportunities: Mapped[list["SpendOpportunity"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", passive_deletes=True
    )


class SpendTransaction(Base):
    """One normalised spend transaction line belonging to an analysis."""

    __tablename__ = "spend_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("spend_analyses.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, default=0)

    po_number: Mapped[str | None] = mapped_column(String(20), index=True)
    po_item: Mapped[str | None] = mapped_column(String(10))
    supplier_id: Mapped[str | None] = mapped_column(String(20), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(120))
    material: Mapped[str | None] = mapped_column(String(40), index=True)
    material_description: Mapped[str | None] = mapped_column(String(255))
    material_group: Mapped[str | None] = mapped_column(String(20), index=True)
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(80))
    company_code: Mapped[str | None] = mapped_column(String(10))
    purchasing_org: Mapped[str | None] = mapped_column(String(10))
    purchasing_group: Mapped[str | None] = mapped_column(String(10))
    plant: Mapped[str | None] = mapped_column(String(10))

    quantity: Mapped[float | None] = mapped_column(Float)
    unit_of_measure: Mapped[str | None] = mapped_column(String(10))
    unit_price: Mapped[float | None] = mapped_column(Float)
    baseline_price: Mapped[float | None] = mapped_column(Float)
    current_price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(3))
    total_value: Mapped[float | None] = mapped_column(Numeric(18, 2))
    spend_base: Mapped[float] = mapped_column(Numeric(18, 2), default=0)

    effective_date: Mapped[date | None] = mapped_column(Date, index=True)
    spend_month: Mapped[str | None] = mapped_column(String(7), index=True)
    contract_number: Mapped[str | None] = mapped_column(String(20))
    contract_status: Mapped[str | None] = mapped_column(String(40))
    preferred_supplier_status: Mapped[str | None] = mapped_column(String(40))
    payment_status: Mapped[str | None] = mapped_column(String(40))

    is_contracted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_preferred_supplier: Mapped[bool] = mapped_column(Boolean, default=False)
    is_maverick: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_under_management: Mapped[bool] = mapped_column(Boolean, default=False)
    price_variance_base: Mapped[float | None] = mapped_column(Float)
    price_variance_pct: Mapped[float | None] = mapped_column(Float)

    analysis: Mapped[SpendAnalysis] = relationship(back_populates="transactions")

    __table_args__ = (
        Index("ix_spend_tx_analysis_supplier", "analysis_id", "supplier_id"),
        Index("ix_spend_tx_analysis_month", "analysis_id", "spend_month"),
        Index("ix_spend_tx_analysis_category", "analysis_id", "category"),
    )


class SpendOpportunity(Base, TimestampMixin):
    """One modelled savings opportunity.

    ``is_estimate`` is stored explicitly and defaults to ``True``: every row in
    this table is a modelled figure, never a booked or committed saving.
    """

    __tablename__ = "spend_opportunities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("spend_analyses.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(20), index=True)
    rule_name: Mapped[str] = mapped_column(String(120))
    opportunity_type: Mapped[str] = mapped_column(String(60), index=True)
    scope: Mapped[str] = mapped_column(String(30))
    scope_value: Mapped[str] = mapped_column(String(120), index=True)
    scope_label: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)

    addressable_spend_base: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    gross_saving_base: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    realization_factor: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_saving_base: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    transaction_count: Mapped[int] = mapped_column(Integer, default=0)
    supplier_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=True)

    analysis: Mapped[SpendAnalysis] = relationship(back_populates="opportunities")
