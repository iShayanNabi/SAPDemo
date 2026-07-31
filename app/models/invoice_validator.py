"""ORM models for the Invoice Validator.

Two tables, reusing the shared ``uploaded_files`` table from module 1 for the
three uploads (invoices, purchase orders, goods receipts):

``invoice_validations``
    One row per validation run: the three upload references, the tolerances
    used, the aggregate KPIs, the three-way-match comparison rows and the
    optional AI narrative.
``invoice_exceptions``
    One row per exception raised by the deterministic rules.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
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

from app.models.base import Base, TimestampMixin, utc_now


class InvoiceValidation(Base, TimestampMixin):
    """One execution of the invoice validator over three uploaded datasets."""

    __tablename__ = "invoice_validations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invoice_upload_id: Mapped[str] = mapped_column(
        ForeignKey("uploaded_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    po_upload_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    gr_upload_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    invoice_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    po_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gr_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    config_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.0.0")
    as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    tolerances: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    applied_invoice_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    applied_po_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    applied_gr_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    data_quality_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    kpis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    supplier_summary: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    three_way_matches: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    rule_executions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    rule_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    invoice_count: Mapped[int] = mapped_column(Integer, default=0)
    purchase_order_line_count: Mapped[int] = mapped_column(Integer, default=0)
    goods_receipt_count: Mapped[int] = mapped_column(Integer, default=0)
    supplier_count: Mapped[int] = mapped_column(Integer, default=0)
    total_invoice_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    base_currency: Mapped[str] = mapped_column(String(3), default="EUR")

    exceptions_count: Mapped[int] = mapped_column(Integer, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    high_count: Mapped[int] = mapped_column(Integer, default=0)
    medium_count: Mapped[int] = mapped_column(Integer, default=0)
    low_count: Mapped[int] = mapped_column(Integer, default=0)
    flagged_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    estimated_exposure: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    exception_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Optional AI enrichment - always labelled, never used for a validation decision.
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

    exceptions: Mapped[list["InvoiceException"]] = relationship(
        back_populates="validation", cascade="all, delete-orphan", passive_deletes=True
    )


class InvoiceException(Base):
    """One exception raised by the deterministic invoice validation engine."""

    __tablename__ = "invoice_exceptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    validation_id: Mapped[str] = mapped_column(
        ForeignKey("invoice_validations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    rule_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(120), nullable=False)
    exception_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    invoice_number: Mapped[str | None] = mapped_column(String(40), index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(20), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(120))
    po_number: Mapped[str | None] = mapped_column(String(20), index=True)
    po_item: Mapped[str | None] = mapped_column(String(10))
    gr_number: Mapped[str | None] = mapped_column(String(40))

    expected_value: Mapped[str | None] = mapped_column(Text)
    actual_value: Mapped[str | None] = mapped_column(Text)
    difference: Mapped[str | None] = mapped_column(Text)
    difference_amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")

    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    output_origin: Mapped[str] = mapped_column(String(20), default="rule_based")
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_output_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    validation: Mapped[InvoiceValidation] = relationship(back_populates="exceptions")

    __table_args__ = (
        Index("ix_invoice_exceptions_validation_severity", "validation_id", "severity"),
        Index("ix_invoice_exceptions_validation_rule", "validation_id", "rule_id"),
    )
