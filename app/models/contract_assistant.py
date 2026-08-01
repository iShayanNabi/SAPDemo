"""ORM models for the Contract Assistant.

Five tables, reusing the shared ``uploaded_files`` table from module 1 for the
upload itself:

``contracts``
    One row per uploaded contract document: how its text was extracted, the
    document facts, the key dates, the analysis summary and the optional AI
    narrative.
``contract_pages``
    The extracted text, one row per page. Persisting it is what lets the API
    answer a question, re-run the analysis or show a citation without going
    back to the original file - and it is what keeps a page number meaningful
    after the upload directory is cleaned out.
``contract_clauses``
    One row per extracted clause, with its page, heading, excerpt and
    confidence.
``contract_risks``
    One row per risk finding.
``contract_obligations``
    One row per duty sentence.
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
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UtcDateTime


class Contract(Base, TimestampMixin):
    """One uploaded contract document and its analysis."""

    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("uploaded_files.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_extension: Mapped[str] = mapped_column(String(10), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded", index=True)

    # -- extraction -----------------------------------------------------
    extractor: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    page_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    section_count: Mapped[int] = mapped_column(Integer, default=0)
    needs_ocr: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    extraction_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # -- document facts -------------------------------------------------
    contract_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title_reference: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    parties: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # -- key dates ------------------------------------------------------
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    renewal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_deadline: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    auto_renewal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notice_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The full key-date payload, including every ``*_basis`` and excerpt.
    key_dates: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # -- analysis summary -----------------------------------------------
    clauses_found: Mapped[int] = mapped_column(Integer, default=0)
    clauses_expected: Mapped[int] = mapped_column(Integer, default=0)
    missing_clause_count: Mapped[int] = mapped_column(Integer, default=0)
    obligation_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_count: Mapped[int] = mapped_column(Integer, default=0)
    severity_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    risk_band: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    missing_clauses: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    injection_detected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    injection_markers: Mapped[list[str]] = mapped_column(JSON, default=list)
    rule_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    config_version: Mapped[str] = mapped_column(String(20), default="0.0.0")
    engine_version: Mapped[str] = mapped_column(String(20), default="0.0.0")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)

    # -- optional AI narrative ------------------------------------------
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

    pages: Mapped[list[ContractPage]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", passive_deletes=True
    )
    clauses: Mapped[list[ContractClause]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", passive_deletes=True
    )
    risks: Mapped[list[ContractRisk]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", passive_deletes=True
    )
    obligations: Mapped[list[ContractObligation]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", passive_deletes=True
    )


class ContractPage(Base):
    """The extracted text of one page."""

    __tablename__ = "contract_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")

    contract: Mapped[Contract] = relationship(back_populates="pages")

    __table_args__ = (Index("ix_contract_pages_contract_page", "contract_id", "page_number"),)


class ContractClause(Base):
    """One extracted clause with its source reference."""

    __tablename__ = "contract_clauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    clause_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    present: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    importance: Mapped[str] = mapped_column(String(20), default="medium")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    heading_matched: Mapped[bool] = mapped_column(Boolean, default=False)

    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_heading: Mapped[str | None] = mapped_column(String(200), nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, default="")

    matched_terms: Mapped[list[str]] = mapped_column(JSON, default=list)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    references: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    #: AI text lives in its own columns and never overwrites ``excerpt``.
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    output_origin: Mapped[str] = mapped_column(String(20), default="rule_based")

    contract: Mapped[Contract] = relationship(back_populates="clauses")

    __table_args__ = (Index("ix_contract_clauses_contract_type", "contract_id", "clause_type"),)


class ContractRisk(Base):
    """One deterministic risk finding about a contract."""

    __tablename__ = "contract_risks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="")
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    clause_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_heading: Mapped[str | None] = mapped_column(String(200), nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    references: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    output_origin: Mapped[str] = mapped_column(String(20), default="rule_based")

    contract: Mapped[Contract] = relationship(back_populates="risks")

    __table_args__ = (Index("ix_contract_risks_contract_severity", "contract_id", "severity"),)


class ContractObligation(Base):
    """One duty sentence found in a contract."""

    __tablename__ = "contract_obligations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contracts.id", ondelete="CASCADE"), index=True
    )
    obligation_id: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    party: Mapped[str | None] = mapped_column(String(120), nullable=True)
    party_role: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    duty_type: Mapped[str] = mapped_column(String(30), default="general", index=True)
    is_prohibition: Mapped[bool] = mapped_column(Boolean, default=False)
    clause_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_heading: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reference: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_origin: Mapped[str] = mapped_column(String(20), default="rule_based")

    contract: Mapped[Contract] = relationship(back_populates="obligations")

    __table_args__ = (
        Index("ix_contract_obligations_contract_party", "contract_id", "party_role"),
    )
