"""ORM models for the SAP Blueprint Generator.

Three tables. Like the Test Case Generator this module has no upload, so it does
not touch the shared ``uploaded_files`` table: its input is a form, and the form
is stored on the blueprint itself.

``blueprints``
    One row per generation run: the project request exactly as it was entered,
    the provenance of the drafting call, and everything that went wrong on the
    way.
``blueprint_sections``
    One row per section - the live, editable document. The **content** fields
    (title, narrative, items) and the **review** fields (status, approval,
    comments) live in the same row but are never written by the same operation:
    regenerating a section's wording must not carry across an approval that was
    given to the wording it replaced.
``blueprint_versions``
    One row per saved version, holding a complete, self-contained snapshot of the
    sections. The snapshot is stored as data rather than as foreign keys on
    purpose: a version whose text changes when somebody edits the live document
    afterwards is not a version.

The items are stored as a JSON list rather than in their own table. An item has
no identity outside its section - it is never queried, filtered or reported on
alone, and every edit replaces the whole ordered list - so a child table would
buy nothing but a join. The item *numbering* is always rewritten by the builder,
so the stored order is the truth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UtcDateTime


class Blueprint(Base, TimestampMixin):
    """One generated SAP implementation blueprint."""

    __tablename__ = "blueprints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner: Mapped[str] = mapped_column(String(120), default="")

    # -- the project request, exactly as it was entered ---------------------
    company: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    industry: Mapped[str] = mapped_column(String(120), nullable=False)
    sap_product: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    modules: Mapped[list[str]] = mapped_column(JSON, default=list)
    business_objectives: Mapped[list[str]] = mapped_column(JSON, default=list)
    current_process: Mapped[str] = mapped_column(Text, default="")
    desired_process: Mapped[str] = mapped_column(Text, default="")
    countries: Mapped[list[str]] = mapped_column(JSON, default=list)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    company_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    plants: Mapped[list[str]] = mapped_column(JSON, default=list)
    purchasing_organizations: Mapped[list[str]] = mapped_column(JSON, default=list)
    systems_involved: Mapped[list[str]] = mapped_column(JSON, default=list)
    integrations: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    user_groups: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeline: Mapped[str] = mapped_column(Text, default="")
    constraints: Mapped[list[str]] = mapped_column(JSON, default=list)
    assumptions: Mapped[list[str]] = mapped_column(JSON, default=list)

    # -- the deterministic plan ---------------------------------------------
    requested_sections: Mapped[list[str]] = mapped_column(JSON, default=list)
    excluded_sections: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: The highest version number saved so far. Zero means "never saved".
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    #: The highest custom section number this blueprint has ever handed out.
    #: It only ever increases: deleting ``BP-CUS-001`` must not let the next
    #: added section claim that identifier, because a review comment written
    #: against it has to keep meaning what it meant. The *current* number of
    #: custom sections is counted from the rows, never from here.
    custom_sections_issued: Mapped[int] = mapped_column(Integer, default=0)

    # -- what happened while generating -------------------------------------
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    generation_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    injection_detected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    injection_markers: Mapped[list[str]] = mapped_column(JSON, default=list)

    config_version: Mapped[str] = mapped_column(String(20), default="0.0.0")
    engine_version: Mapped[str] = mapped_column(String(20), default="0.0.0")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    # -- provenance of the drafting call (never the API key) ----------------
    ai_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_used: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ai_output_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    sections: Mapped[list[BlueprintSection]] = relationship(
        back_populates="blueprint",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BlueprintSection.position",
    )
    versions: Mapped[list[BlueprintVersion]] = relationship(
        back_populates="blueprint",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BlueprintVersion.version_number",
    )


class BlueprintSection(Base, TimestampMixin):
    """One section of the live, editable blueprint."""

    __tablename__ = "blueprint_sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    blueprint_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("blueprints.id", ondelete="CASCADE"), index=True
    )
    #: The human-readable identifier, e.g. ``BP-SCOPE`` or ``BP-CUS-001``.
    #: Stable for the life of the document: review comments are written against
    #: it, so it must never be handed to a different section.
    section_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    section_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    content_kind: Mapped[str] = mapped_column(String(20), default="list")
    description: Mapped[str] = mapped_column(Text, default="")

    # -- the content --------------------------------------------------------
    narrative: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # -- the review record --------------------------------------------------
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    source: Mapped[str] = mapped_column(String(20), default="template", index=True)
    output_origin: Mapped[str] = mapped_column(String(20), default="rule_based")
    comments: Mapped[str] = mapped_column(Text, default="")
    approved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime(), nullable=True
    )

    #: Required project fields the request left empty. Non-empty means the
    #: section is deliberately unwritten rather than missing.
    missing_inputs: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: What the deterministic repair had to fix in the drafted text.
    validation_notes: Mapped[list[str]] = mapped_column(JSON, default=list)

    #: Bumped on every content change. Dependent sections record the revision
    #: they were written against, which is what makes staleness detectable.
    content_revision: Mapped[int] = mapped_column(Integer, default=1)
    #: Section keys whose content this section describes.
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    #: ``{section_key: content_revision}`` at the moment this section was
    #: written. Compared against the live revisions to report staleness.
    dependency_revisions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    regenerated_count: Mapped[int] = mapped_column(Integer, default=0)
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    blueprint: Mapped[Blueprint] = relationship(back_populates="sections")

    __table_args__ = (
        Index("ix_blueprint_sections_bp_position", "blueprint_id", "position"),
        Index("uq_blueprint_sections_bp_key", "blueprint_id", "section_key", unique=True),
        Index("uq_blueprint_sections_bp_identifier", "blueprint_id", "section_id", unique=True),
    )


class BlueprintVersion(Base, TimestampMixin):
    """An immutable snapshot of a blueprint's sections at a point in time."""

    __tablename__ = "blueprint_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    blueprint_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("blueprints.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    created_by: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(Text, default="")

    #: The complete section list as it stood. Self-contained by design.
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    section_count: Mapped[int] = mapped_column(Integer, default=0)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    needs_input_count: Mapped[int] = mapped_column(Integer, default=0)

    blueprint: Mapped[Blueprint] = relationship(back_populates="versions")

    __table_args__ = (
        Index("uq_blueprint_versions_bp_number", "blueprint_id", "version_number", unique=True),
    )
