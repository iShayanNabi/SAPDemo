"""ORM models for the Supplier Risk Copilot.

Four tables, reusing the shared ``uploaded_files`` table from module 1 for the
uploads themselves:

``supplier_risk_datasets``
    One row per uploaded supplier risk profile file. A dataset groups the
    suppliers an assessment can score, and optionally carries a second upload
    holding the dated risk events.
``supplier_risk_records``
    One row per supplier in a dataset - the normalised risk facts.
``supplier_risk_assessments``
    One row per calculation run: the weights, the as-of date, the portfolio
    summary and the optional AI narrative.
``supplier_risk_profiles``
    One row per supplier in an assessment, with the ten category scores, the
    overall score and band, the trend, the supporting metrics, the recommended
    actions and the full scoring breakdown.
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


class SupplierRiskDataset(Base, TimestampMixin):
    """One uploaded supplier risk profile file (plus an optional events file)."""

    __tablename__ = "supplier_risk_datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("uploaded_files.id", ondelete="CASCADE"), index=True
    )
    event_upload_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    event_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR")

    applied_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    applied_event_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unmapped_columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_quality_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    supplier_count: Mapped[int] = mapped_column(Integer, default=0)
    event_count: Mapped[int] = mapped_column(Integer, default=0)

    records: Mapped[list[SupplierRiskRecord]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )
    assessments: Mapped[list[SupplierRiskAssessment]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )


class SupplierRiskRecord(Base):
    """One supplier's normalised risk facts inside a dataset."""

    __tablename__ = "supplier_risk_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("supplier_risk_datasets.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, default=0)

    supplier_id: Mapped[str] = mapped_column(String(20), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(40))
    spend_category: Mapped[str | None] = mapped_column(String(80))

    #: The full normalised record, so an assessment can be re-run without the file.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: The supplier's dated internal records, as normalised event dicts.
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    dataset: Mapped[SupplierRiskDataset] = relationship(back_populates="records")

    __table_args__ = (Index("ix_risk_records_dataset_supplier", "dataset_id", "supplier_id"),)


class SupplierRiskAssessment(Base, TimestampMixin):
    """One risk calculation run."""

    __tablename__ = "supplier_risk_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("supplier_risk_datasets.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    config_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")

    weights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR")

    supplier_count: Mapped[int] = mapped_column(Integer, default=0)
    scored_count: Mapped[int] = mapped_column(Integer, default=0)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    band_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    category_averages: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    average_overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    highest_risk_supplier_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    highest_risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    contracts_expiring_count: Mapped[int] = mapped_column(Integer, default=0)
    limited_data_count: Mapped[int] = mapped_column(Integer, default=0)
    rule_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

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

    dataset: Mapped[SupplierRiskDataset] = relationship(back_populates="assessments")
    profiles: Mapped[list[SupplierRiskProfileRow]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", passive_deletes=True
    )


class SupplierRiskProfileRow(Base):
    """One supplier's scored risk profile inside an assessment."""

    __tablename__ = "supplier_risk_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("supplier_risk_assessments.id", ondelete="CASCADE"), index=True
    )
    supplier_id: Mapped[str] = mapped_column(String(20), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(40))
    spend_category: Mapped[str | None] = mapped_column(String(80))

    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    overall_band: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    delivery_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    financial_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    spend_concentration_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    contract_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    invoice_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    compliance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    esg_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    geographic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    operational_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    trend_direction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trend_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    data_completeness_pct: Mapped[float] = mapped_column(Float, default=0.0)
    limited_data: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    total_spend_base: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    purchase_order_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_contract_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contract_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contract_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_expiring_soon: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    on_time_delivery_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    late_delivery_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invoice_exception_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: The complete engine output for this supplier: category breakdown with
    #: every metric's weight, normalised score and contribution, plus the
    #: supporting internal records and the recommended actions.
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_origin: Mapped[str] = mapped_column(String(20), default="rule_based")

    assessment: Mapped[SupplierRiskAssessment] = relationship(back_populates="profiles")

    __table_args__ = (
        Index("ix_risk_profiles_assessment_supplier", "assessment_id", "supplier_id"),
        Index("ix_risk_profiles_assessment_rank", "assessment_id", "rank"),
    )
