"""ORM models for the Purchase Order Risk Checker.

Four tables:

``uploaded_files``
    One row per accepted upload (metadata only - the bytes stay on disk).
``po_analyses``
    One row per analysis run, including aggregate KPIs and the optional AI
    executive summary.
``po_records``
    The normalised purchase order line items that were analysed. Persisting
    them makes findings reproducible and lets the API serve evidence without
    re-reading the source file.
``po_findings``
    One row per rule hit.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
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

from app.models.base import Base, TimestampMixin, UtcDateTime, utc_now


class UploadedFile(Base, TimestampMixin):
    """Metadata for a file that passed upload validation."""

    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False, default="po_risk")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    file_extension: Mapped[str] = mapped_column(String(10), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detected_columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    suggested_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    analyses: Mapped[list["PoAnalysis"]] = relationship(back_populates="upload")


class PoAnalysis(Base, TimestampMixin):
    """A single execution of the risk engine over one uploaded dataset."""

    __tablename__ = "po_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upload_id: Mapped[str] = mapped_column(
        ForeignKey("uploaded_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provenance
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    config_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")
    applied_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unmapped_columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_quality_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    kpis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    supplier_risk: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    rule_executions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    rule_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # Aggregates (all deterministic)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    purchase_order_count: Mapped[int] = mapped_column(Integer, default=0)
    supplier_count: Mapped[int] = mapped_column(Integer, default=0)
    total_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR")
    findings_count: Mapped[int] = mapped_column(Integer, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    high_count: Mapped[int] = mapped_column(Integer, default=0)
    medium_count: Mapped[int] = mapped_column(Integer, default=0)
    low_count: Mapped[int] = mapped_column(Integer, default=0)
    flagged_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    estimated_exposure: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Optional AI enrichment - always labelled, never used for the risk decision
    ai_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_output_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_key_risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    ai_recommended_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    ai_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)

    upload: Mapped[UploadedFile] = relationship(back_populates="analyses")
    findings: Mapped[list["PoFinding"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    records: Mapped[list["PoRecord"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class PoRecord(Base):
    """A normalised purchase order line item belonging to one analysis."""

    __tablename__ = "po_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("po_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)

    po_number: Mapped[str | None] = mapped_column(String(20), index=True)
    po_item: Mapped[str | None] = mapped_column(String(10))
    supplier_id: Mapped[str | None] = mapped_column(String(20), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(120))
    material: Mapped[str | None] = mapped_column(String(40), index=True)
    material_description: Mapped[str | None] = mapped_column(String(255))
    material_group: Mapped[str | None] = mapped_column(String(20))
    company_code: Mapped[str | None] = mapped_column(String(10))
    purchasing_org: Mapped[str | None] = mapped_column(String(10))
    purchasing_group: Mapped[str | None] = mapped_column(String(10))
    plant: Mapped[str | None] = mapped_column(String(10))
    quantity: Mapped[float | None] = mapped_column(Float)
    unit_of_measure: Mapped[str | None] = mapped_column(String(10))
    unit_price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(3))
    total_value: Mapped[float | None] = mapped_column(Float)
    total_value_base: Mapped[float | None] = mapped_column(Float)
    order_date: Mapped[date | None] = mapped_column(Date)
    requested_delivery_date: Mapped[date | None] = mapped_column(Date)
    actual_delivery_date: Mapped[date | None] = mapped_column(Date)
    contract_number: Mapped[str | None] = mapped_column(String(20))
    payment_terms: Mapped[str | None] = mapped_column(String(20))
    approval_status: Mapped[str | None] = mapped_column(String(30))
    created_by: Mapped[str | None] = mapped_column(String(30))
    changed_by: Mapped[str | None] = mapped_column(String(30))
    change_count: Mapped[int | None] = mapped_column(Integer)

    analysis: Mapped[PoAnalysis] = relationship(back_populates="records")

    __table_args__ = (Index("ix_po_records_analysis_po", "analysis_id", "po_number"),)


class PoFinding(Base):
    """One rule hit produced by the deterministic risk engine."""

    __tablename__ = "po_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("po_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )

    po_number: Mapped[str | None] = mapped_column(String(20), index=True)
    po_item: Mapped[str | None] = mapped_column(String(10))
    supplier_id: Mapped[str | None] = mapped_column(String(20), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(120))

    risk_category: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0)
    estimated_financial_exposure: Mapped[float] = mapped_column(Float, default=0.0)
    exposure_currency: Mapped[str] = mapped_column(String(3), default="EUR")

    output_origin: Mapped[str] = mapped_column(String(20), default="rule_based")
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_output_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=utc_now, nullable=False
    )

    analysis: Mapped[PoAnalysis] = relationship(back_populates="findings")

    __table_args__ = (Index("ix_po_findings_analysis_severity", "analysis_id", "severity"),)
