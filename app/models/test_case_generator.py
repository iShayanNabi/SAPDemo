"""ORM models for the SAP Test Case Generator.

Two tables. Unlike modules 1-7 this module has no upload, so it does not touch
the shared ``uploaded_files`` table: its input is a form, and the form is stored
on the suite itself.

``test_suites``
    One row per generation run: the process context exactly as it was entered,
    the plan that was derived from it, the provenance of the drafting call and
    everything that went wrong on the way.
``test_cases``
    One row per test case. The **script** fields (title, objective,
    preconditions, test data, steps, expected result) and the **execution**
    fields (status, actual result, pass/fail, evidence, comments, approval) live
    in the same row but are never written by the same operation: regenerating a
    script must not silently erase what a tester recorded when they ran it.

The steps are stored as a JSON list rather than in their own table. A step has
no identity outside its test case - it is never queried, filtered or reported on
alone, and every edit replaces the whole ordered list - so a child table would
buy nothing but a join. The step *numbering* is always rewritten by the engine,
so the stored order is the truth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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


class TestSuite(Base, TimestampMixin):
    """One generated suite of SAP test cases."""

    __tablename__ = "test_suites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # -- the process context, exactly as it was entered -------------------
    sap_product: Mapped[str] = mapped_column(String(120), nullable=False)
    sap_module: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    business_process: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    process_description: Mapped[str] = mapped_column(Text, default="")
    preconditions: Mapped[list[str]] = mapped_column(JSON, default=list)
    business_rules: Mapped[list[str]] = mapped_column(JSON, default=list)
    systems_involved: Mapped[list[str]] = mapped_column(JSON, default=list)
    integrations: Mapped[list[str]] = mapped_column(JSON, default=list)
    user_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    test_data_requirements: Mapped[list[str]] = mapped_column(JSON, default=list)

    # -- the deterministic plan -------------------------------------------
    requested_test_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    requested_count: Mapped[int] = mapped_column(Integer, default=0)
    #: ``{test_type: planned_case_count}`` - kept so coverage can still be
    #: reported against the original plan after rows are edited or deleted.
    allocation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    uncovered_test_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_owner: Mapped[str] = mapped_column(String(120), default="")

    # -- what happened while generating ------------------------------------
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    generation_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    injection_detected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    injection_markers: Mapped[list[str]] = mapped_column(JSON, default=list)

    config_version: Mapped[str] = mapped_column(String(20), default="0.0.0")
    engine_version: Mapped[str] = mapped_column(String(20), default="0.0.0")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    # -- provenance of the drafting call (never the API key) ---------------
    ai_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_used: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ai_output_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    test_cases: Mapped[list["TestCase"]] = relationship(
        back_populates="suite",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TestCase.sequence",
    )


class TestCase(Base, TimestampMixin):
    """One test case inside a suite."""

    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    suite_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("test_suites.id", ondelete="CASCADE"), index=True
    )
    #: The human-readable identifier, e.g. ``TC-SIT-001``. Unique inside a suite.
    test_case_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)

    # -- the script --------------------------------------------------------
    test_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    #: The aspect of the process this case covers, chosen by the planner from
    #: the configured focus areas. Stored so a regeneration redrafts the same
    #: test rather than a different one that happens to share an identifier.
    focus: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    preconditions: Mapped[list[str]] = mapped_column(JSON, default=list)
    test_data: Mapped[list[str]] = mapped_column(JSON, default=list)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    expected_result: Mapped[str] = mapped_column(Text, default="")

    # -- the execution record ---------------------------------------------
    owner: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    actual_result: Mapped[str] = mapped_column(Text, default="")
    execution_result: Mapped[str] = mapped_column(String(20), default="not_run", index=True)
    evidence_reference: Mapped[str] = mapped_column(String(500), default="")
    comments: Mapped[str] = mapped_column(Text, default="")
    #: True when the script was edited or redrafted *after* this result was
    #: recorded, so the verdict describes steps that no longer exist. Without
    #: it a suite can report "1 failed" against a test case nobody can find.
    execution_is_stale: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # -- provenance --------------------------------------------------------
    source: Mapped[str] = mapped_column(String(20), default="template", index=True)
    output_origin: Mapped[str] = mapped_column(String(20), default="rule_based")
    ai_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: What the deterministic repair had to fix in the drafted text.
    validation_notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    regenerated_count: Mapped[int] = mapped_column(Integer, default=0)

    suite: Mapped[TestSuite] = relationship(back_populates="test_cases")

    __table_args__ = (
        Index("ix_test_cases_suite_sequence", "suite_id", "sequence"),
        Index("uq_test_cases_suite_identifier", "suite_id", "test_case_id", unique=True),
    )
