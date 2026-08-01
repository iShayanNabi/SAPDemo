"""ORM models for the Supplier Recommendation Engine.

Four tables, reusing the shared ``uploaded_files`` table from module 1 for the
supplier-master upload itself:

``supplier_catalogs``
    One row per uploaded supplier master file. A catalogue groups the suppliers
    a recommendation can choose from.
``suppliers``
    One row per supplier in a catalogue - the normalised supplier master data.
``supplier_recommendations``
    One row per recommendation run: the requirement, the weights, the eligibility
    summary and the optional AI narrative.
``supplier_recommendation_entries``
    One row per supplier in a recommendation, with its rank, nine sub-scores,
    estimated cost/delivery, advantages, risks and explanation.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UtcDateTime


class SupplierCatalog(Base, TimestampMixin):
    """One uploaded supplier master file."""

    __tablename__ = "supplier_catalogs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("uploaded_files.id", ondelete="CASCADE"), index=True
    )
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    config_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR")

    applied_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unmapped_columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_quality_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    supplier_count: Mapped[int] = mapped_column(Integer, default=0)

    suppliers: Mapped[list[Supplier]] = relationship(
        back_populates="catalog", cascade="all, delete-orphan", passive_deletes=True
    )
    recommendations: Mapped[list[SupplierRecommendation]] = relationship(
        back_populates="catalog", cascade="all, delete-orphan", passive_deletes=True
    )


class Supplier(Base):
    """One supplier belonging to a catalogue (normalised supplier master data)."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalog_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("supplier_catalogs.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, default=0)

    supplier_id: Mapped[str] = mapped_column(String(20), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(120))
    materials_supplied: Mapped[list[str]] = mapped_column(JSON, default=list)
    plants_served: Mapped[list[str]] = mapped_column(JSON, default=list)
    regions_served: Mapped[list[str]] = mapped_column(JSON, default=list)

    unit_price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(3))
    unit_price_base: Mapped[float | None] = mapped_column(Float)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    available_capacity: Mapped[float | None] = mapped_column(Float)
    on_time_delivery_rate: Mapped[float | None] = mapped_column(Float)
    quality_score: Mapped[float | None] = mapped_column(Float)
    defect_rate: Mapped[float | None] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    esg_score: Mapped[float | None] = mapped_column(Float)
    contract_status: Mapped[str | None] = mapped_column(String(40))
    contract_expiration: Mapped[date | None] = mapped_column(Date)
    payment_terms: Mapped[str | None] = mapped_column(String(20))
    historical_order_count: Mapped[int | None] = mapped_column(Integer)
    historical_spend: Mapped[float | None] = mapped_column(Float)
    historical_spend_base: Mapped[float | None] = mapped_column(Float)

    catalog: Mapped[SupplierCatalog] = relationship(back_populates="suppliers")

    __table_args__ = (
        Index("ix_suppliers_catalog_supplier", "catalog_id", "supplier_id"),
    )


class SupplierRecommendation(Base, TimestampMixin):
    """One recommendation run."""

    __tablename__ = "supplier_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    catalog_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("supplier_catalogs.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    config_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")
    scoring_engine_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")

    requirement: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    weights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR")

    total_supplier_count: Mapped[int] = mapped_column(Integer, default=0)
    eligible_count: Mapped[int] = mapped_column(Integer, default=0)
    ineligible_count: Mapped[int] = mapped_column(Integer, default=0)
    top_supplier_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    top_supplier_score: Mapped[float | None] = mapped_column(Float, nullable=True)

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
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)

    catalog: Mapped[SupplierCatalog] = relationship(back_populates="recommendations")
    entries: Mapped[list[SupplierRecommendationEntry]] = relationship(
        back_populates="recommendation", cascade="all, delete-orphan", passive_deletes=True
    )


class SupplierRecommendationEntry(Base):
    """One supplier's place in a recommendation."""

    __tablename__ = "supplier_recommendation_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("supplier_recommendations.id", ondelete="CASCADE"), index=True
    )
    supplier_id: Mapped[str] = mapped_column(String(20), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(120))

    rank: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    eligibility_status: Mapped[str] = mapped_column(String(20), default="eligible")
    is_eligible: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    cost_score: Mapped[float] = mapped_column(Float, default=0.0)
    delivery_score: Mapped[float] = mapped_column(Float, default=0.0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    capacity_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    esg_score: Mapped[float] = mapped_column(Float, default=0.0)
    contract_score: Mapped[float] = mapped_column(Float, default=0.0)
    geographic_score: Mapped[float] = mapped_column(Float, default=0.0)
    past_performance_score: Mapped[float] = mapped_column(Float, default=0.0)

    estimated_unit_price_base: Mapped[float | None] = mapped_column(Float)
    estimated_total_cost_base: Mapped[float | None] = mapped_column(Numeric(18, 2))
    estimated_delivery_date: Mapped[date | None] = mapped_column(Date)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    contract_status: Mapped[str | None] = mapped_column(String(40))
    contract_classification: Mapped[str | None] = mapped_column(String(20))

    advantages: Mapped[list[str]] = mapped_column(JSON, default=list)
    risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    explanation: Mapped[str | None] = mapped_column(Text)
    ineligibility_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    recommendation: Mapped[SupplierRecommendation] = relationship(back_populates="entries")

    __table_args__ = (
        Index("ix_reco_entry_reco_rank", "recommendation_id", "rank"),
    )
