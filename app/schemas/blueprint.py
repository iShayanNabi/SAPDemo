"""Request and response schemas for the SAP Blueprint Generator.

These are the module's API contract. A future React or Next.js front end can
build the whole page - the project form, the section navigator, the editable
section body, the approval controls, the version history and the export buttons
- from these shapes alone.

Four conventions carry through every schema, and each one exists because a
blueprint is a *document under review* rather than a report produced once:

* **A section is a skeleton before it is prose.** Which sections exist, what
  they are called, in what order they appear, which project inputs feed them and
  which items they must contain are decided by deterministic Python. A language
  model writes the wording inside that skeleton and nothing else.
* **A section with no input is not a section to invent.** When the project
  request names no integration, the Integrations section comes back
  ``needs_input`` and says which field to fill in - it never invents an
  interface that nobody asked for.
* **A section that summarises other sections records which version it read.**
  Every section carries a ``content_revision``; a dependent section records the
  revisions it was written against. When one of those moves, the dependent
  section is reported stale rather than quietly describing a scope that has
  since changed.
* **Everything a reviewer records** (status, approval, comments) lives in its
  own fields and is never overwritten by a regeneration of the text.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import OutputOrigin


class ExportFormat(str, Enum):
    """Formats a blueprint can be downloaded in."""

    MARKDOWN = "markdown"
    JSON = "json"
    DOCX = "docx"
    PDF = "pdf"


class SectionKey(str, Enum):
    """The thirty canonical blueprint sections.

    The declaration order below is the order the document is written in, the
    order the navigator lists, and the order every export prints. It is the
    blueprint's table of contents, so it lives in code rather than in a
    configuration file a typo could reorder.
    """

    EXECUTIVE_SUMMARY = "executive_summary"
    BUSINESS_OBJECTIVES = "business_objectives"
    SCOPE = "scope"
    OUT_OF_SCOPE = "out_of_scope"
    ASSUMPTIONS = "assumptions"
    CURRENT_STATE_PROCESS = "current_state_process"
    FUTURE_STATE_PROCESS = "future_state_process"
    PROCESS_STEPS = "process_steps"
    SAP_PRODUCTS_MODULES = "sap_products_modules"
    BEST_PRACTICE_ALIGNMENT = "best_practice_alignment"
    ORGANIZATIONAL_STRUCTURE = "organizational_structure"
    MASTER_DATA = "master_data"
    CONFIGURATION_REQUIREMENTS = "configuration_requirements"
    FUNCTIONAL_REQUIREMENTS = "functional_requirements"
    NONFUNCTIONAL_REQUIREMENTS = "nonfunctional_requirements"
    INTEGRATIONS = "integrations"
    INTERFACES_APIS = "interfaces_apis"
    DATA_MIGRATION = "data_migration"
    SECURITY_ROLES = "security_roles"
    CONTROLS = "controls"
    REPORTING_REQUIREMENTS = "reporting_requirements"
    TEST_STRATEGY = "test_strategy"
    SIT_SCENARIOS = "sit_scenarios"
    UAT_SCENARIOS = "uat_scenarios"
    TRAINING = "training"
    CUTOVER_ACTIVITIES = "cutover_activities"
    HYPERCARE = "hypercare"
    RISKS = "risks"
    DEPENDENCIES = "dependencies"
    OPEN_DECISIONS = "open_decisions"


#: The canonical order, used everywhere a list of sections is produced.
SECTION_ORDER: tuple[SectionKey, ...] = tuple(SectionKey)


class ContentKind(str, Enum):
    """What shape a section's body takes.

    The kind decides how a section is rendered, exported and repaired - a
    ``narrative`` section with no prose is empty, a ``list`` section with no
    items is empty, and the two failures are reported differently.
    """

    #: Prose only: the executive summary, the current/future state descriptions.
    NARRATIVE = "narrative"
    #: A short lead-in paragraph plus a list of items.
    LIST = "list"
    #: A short lead-in paragraph plus rows that carry a category and a reference
    #: (organisational structure, interfaces, process steps).
    TABLE = "table"


class SectionStatus(str, Enum):
    """Where a section sits in its review lifecycle."""

    #: A required project input is missing, so nothing was written. Reported,
    #: never filled with invention.
    NEEDS_INPUT = "needs_input"
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"


class SectionSource(str, Enum):
    """How a section's content came to exist.

    Deliberately separate from :class:`OutputOrigin`: the origin says *what
    produced the words*, the source says *how the content entered the document*.
    """

    AI_GENERATED = "ai_generated"
    #: Computed from the project request by deterministic Python - the
    #: organisational structure, the module list, the integration register.
    DERIVED = "derived"
    #: The configured template built it, because AI was off or unusable.
    TEMPLATE = "template"
    #: A person wrote or edited it through the API or the UI.
    MANUAL = "manual"


class ItemSource(str, Enum):
    """How one item inside a section came to exist."""

    AI_GENERATED = "ai_generated"
    DERIVED = "derived"
    TEMPLATE = "template"
    MANUAL = "manual"


# ---------------------------------------------------------------------------
# Project request
# ---------------------------------------------------------------------------


class BlueprintProjectSchema(BaseModel):
    """What the user tells the generator about the implementation project.

    Everything here is free text supplied by a person, so it is treated as
    untrusted data: it is injection-filtered before it can reach a provider and
    it is never executed or interpreted as an instruction.

    The list fields are what makes a blueprint specific rather than generic. A
    section whose inputs are empty is reported as needing input; it is never
    filled with a plausible-sounding SAP organisational structure the project
    never described.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    company: str = Field(min_length=2, max_length=160, description="e.g. Nordwind Logistics GmbH")
    industry: str = Field(min_length=2, max_length=120, description="e.g. Wholesale distribution")
    sap_product: str = Field(
        min_length=2, max_length=160, description="e.g. SAP S/4HANA 2023 Private Cloud"
    )
    modules: list[str] = Field(default_factory=list, max_length=30, description="e.g. MM, SD, FI")
    business_objectives: list[str] = Field(default_factory=list, max_length=30)
    current_process: str = Field(
        min_length=10, max_length=6000, description="How the process runs today"
    )
    desired_process: str = Field(
        min_length=10, max_length=6000, description="How the process should run after go-live"
    )
    countries: list[str] = Field(default_factory=list, max_length=40)
    locations: list[str] = Field(default_factory=list, max_length=60)
    company_codes: list[str] = Field(default_factory=list, max_length=60)
    plants: list[str] = Field(default_factory=list, max_length=60)
    purchasing_organizations: list[str] = Field(default_factory=list, max_length=60)
    systems_involved: list[str] = Field(default_factory=list, max_length=40)
    integrations: list[str] = Field(default_factory=list, max_length=40)
    data_sources: list[str] = Field(default_factory=list, max_length=40)
    user_groups: list[str] = Field(default_factory=list, max_length=40)
    timeline: str = Field(default="", max_length=2000)
    constraints: list[str] = Field(default_factory=list, max_length=30)
    assumptions: list[str] = Field(default_factory=list, max_length=30)

    @field_validator(
        "modules",
        "business_objectives",
        "countries",
        "locations",
        "company_codes",
        "plants",
        "purchasing_organizations",
        "systems_involved",
        "integrations",
        "data_sources",
        "user_groups",
        "constraints",
        "assumptions",
        mode="before",
    )
    @classmethod
    def _clean_list(cls, value: Any) -> Any:
        """Accept a newline- or comma-separated block as well as a real list.

        The Streamlit form collects these as text areas and a future web form
        will do the same. Splitting here keeps that convenience out of the UI
        layer, where business logic is not allowed to live.
        """
        if isinstance(value, str):
            value = value.splitlines()
        if isinstance(value, list):
            return [
                str(item).strip()[:300]
                for item in value
                if item is not None and str(item).strip()
            ]
        return value


class GenerateBlueprintRequest(BaseModel):
    """Ask the generator for a complete blueprint."""

    project: BlueprintProjectSchema
    blueprint_name: str | None = Field(default=None, max_length=200)
    #: Restrict the document to a subset of the canonical sections. The order is
    #: always the canonical one - a blueprint whose sections come back shuffled
    #: is not a blueprint.
    sections: list[SectionKey] = Field(default_factory=list, max_length=len(SECTION_ORDER))
    owner: str | None = Field(default=None, max_length=120)
    #: When false the configured templates write every section and no provider
    #: is called at all. The blueprint is still complete and usable.
    use_ai: bool = True

    @field_validator("sections")
    @classmethod
    def _dedupe_sections(cls, value: list[SectionKey]) -> list[SectionKey]:
        """Remove duplicates and restore the canonical document order."""
        chosen = set(value)
        return [item for item in SECTION_ORDER if item in chosen]


class UpdateBlueprintRequest(BaseModel):
    """Edit the blueprint's own fields. Only fields present are changed.

    Sending ``project`` replaces the whole project request, which is how a
    section that was waiting for an input gets unblocked. The consequence is
    deliberate and reported: the sections whose items are computed from the
    request are rebuilt from the new values, because a blueprint whose
    organisational structure disagrees with its own project request is worse
    than one that is out of date.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=2, max_length=200)
    owner: str | None = Field(default=None, max_length=120)
    notes: list[str] | None = Field(default=None, max_length=40)
    project: "BlueprintProjectSchema | None" = None


class BlueprintItemInput(BaseModel):
    """One item as a client sends it. Identifiers are always assigned by code."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=300)
    detail: str = Field(default="", max_length=3000)
    category: str = Field(default="", max_length=120)
    reference: str = Field(default="", max_length=300)
    owner: str = Field(default="", max_length=120)
    rating: str = Field(default="", max_length=60)


class UpdateSectionRequest(BaseModel):
    """Edit one section. Only the fields present in the request are changed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=2, max_length=200)
    narrative: str | None = Field(default=None, max_length=20000)
    items: list[BlueprintItemInput] | None = Field(default=None, max_length=60)
    status: SectionStatus | None = None
    comments: str | None = Field(default=None, max_length=4000)


class RegenerateSectionRequest(BaseModel):
    """Redraft one section, optionally steering the redraft."""

    model_config = ConfigDict(str_strip_whitespace=True)

    #: Extra direction for the redraft ("say more about the tax determination").
    instruction: str | None = Field(default=None, max_length=1000)
    use_ai: bool = True


class ApproveSectionRequest(BaseModel):
    """Approve (or un-approve) one section."""

    model_config = ConfigDict(str_strip_whitespace=True)

    approved_by: str = Field(min_length=1, max_length=120)
    approved: bool = True
    comments: str | None = Field(default=None, max_length=4000)


class CreateSectionRequest(BaseModel):
    """Add one custom section to a blueprint.

    Custom sections are the only ones that can be deleted. A canonical section
    is part of the blueprint standard: a reader who finds twenty-nine headings
    cannot tell whether the thirtieth was considered and dropped or never
    written, so the standard set stays whole.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=2, max_length=200)
    content_kind: ContentKind = ContentKind.LIST
    narrative: str = Field(default="", max_length=20000)
    items: list[BlueprintItemInput] = Field(default_factory=list, max_length=60)
    #: Place the new section directly after this one. Unknown or omitted puts it
    #: at the end of the document.
    after_section: str | None = Field(default=None, max_length=80)
    comments: str | None = Field(default=None, max_length=4000)


class CreateVersionRequest(BaseModel):
    """Save the blueprint's current state as an immutable version."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(default="", max_length=120)
    created_by: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=2000)


# ---------------------------------------------------------------------------
# Section content
# ---------------------------------------------------------------------------


class BlueprintItemSchema(BaseModel):
    """One item inside a section.

    The same shape carries an organisational-structure row, a functional
    requirement, a risk and a cutover task. What differs is which fields are
    populated, and the section configuration declares that - so a new section
    type is a JSON edit rather than a new schema.
    """

    item_id: str = Field(description="Human-readable identifier, e.g. BP-ORG-003")
    title: str
    detail: str = ""
    category: str = ""
    #: What this item was derived from, or the section it cross-references.
    reference: str = ""
    owner: str = ""
    #: A short qualifier the section gives meaning to: a risk severity, a
    #: requirement priority, a cutover window.
    rating: str = ""
    source: ItemSource = ItemSource.TEMPLATE
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED


class BlueprintSectionSchema(BaseModel):
    """One complete blueprint section."""

    id: str
    blueprint_id: str
    section_id: str = Field(description="Human-readable identifier, e.g. BP-SCOPE")
    section_key: str = Field(description="Canonical key, or a generated key for a custom section")
    position: int
    title: str
    is_custom: bool = False
    content_kind: ContentKind = ContentKind.LIST
    description: str = ""

    narrative: str = ""
    items: list[BlueprintItemSchema] = Field(default_factory=list)

    status: SectionStatus = SectionStatus.DRAFT
    source: SectionSource = SectionSource.TEMPLATE
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED
    comments: str = ""

    #: Project fields this section needs that the request left empty. While this
    #: is non-empty the section is ``needs_input`` and says so in its narrative.
    missing_inputs: list[str] = Field(default_factory=list)
    #: What the deterministic repair had to fix in the drafted text.
    validation_notes: list[str] = Field(default_factory=list)

    #: Bumped on every content change. A dependent section records the revision
    #: it was written against, which is what makes staleness detectable.
    content_revision: int = 0
    #: Section keys whose content this section describes.
    depends_on: list[str] = Field(default_factory=list)
    #: Dependencies that have changed since this section was written, so this
    #: text describes a scope, a process or a risk register that has moved on.
    stale_dependencies: list[str] = Field(default_factory=list)

    approved_by: str | None = None
    approved_at: datetime | None = None
    #: True when this section carries an approval **and** describes a section
    #: that has changed since. The approval is real - somebody gave it - but it
    #: was given to a description of something that has moved on, so it is
    #: reported rather than either kept silently or thrown away.
    approval_is_stale: bool = False
    regenerated_count: int = 0
    edited_by_user: bool = False
    ai_provider: str | None = None
    ai_prompt_version: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_stale(self) -> bool:
        return bool(self.stale_dependencies)


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------


class BlueprintSummarySchema(BaseModel):
    """Counts a dashboard shows without walking the whole section list."""

    section_count: int = 0
    canonical_section_count: int = 0
    custom_section_count: int = 0
    item_count: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)
    approved_count: int = 0
    needs_input_count: int = 0
    ai_drafted_count: int = 0
    derived_count: int = 0
    template_count: int = 0
    manual_count: int = 0
    #: Sections whose text was written against a version of another section that
    #: has since changed. A blueprint reporting "complete" while its executive
    #: summary describes a superseded scope has to say so.
    stale_section_count: int = 0
    #: Of those, the ones that are also approved. An approval on a section that
    #: describes a superseded scope is the single most misleading state this
    #: document can be in, so it is counted on its own rather than left for a
    #: reader to work out by joining two fields.
    stale_approved_count: int = 0
    #: Sections holding real content (not ``needs_input``), as a percentage.
    completeness_pct: float = 0.0
    approval_pct: float = 0.0
    version_count: int = 0
    #: Project fields that would unlock at least one section if filled in.
    missing_inputs: list[str] = Field(default_factory=list)


class GenerationIssueSchema(BaseModel):
    """One thing that went wrong while drafting, reported instead of hidden.

    A drafting failure for a single section never costs the blueprint that
    section: the configured template fills it and the problem is recorded here.
    """

    section_key: str | None = None
    stage: str = Field(description="provider, payload or content")
    message: str
    recovered: bool = True


class BlueprintAiInfoSchema(BaseModel):
    """Provenance and cost of the drafting call, never the API key."""

    requested: bool = False
    used: bool = False
    provider: str | None = None
    model: str | None = None
    origin: OutputOrigin | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    error: str | None = None


class BlueprintSchema(BaseModel):
    """A generated blueprint with its project request and its sections."""

    blueprint_id: str
    name: str
    owner: str = ""
    project: BlueprintProjectSchema

    summary: BlueprintSummarySchema = Field(default_factory=BlueprintSummarySchema)
    sections: list[BlueprintSectionSchema] = Field(default_factory=list)
    #: Canonical sections the request excluded, reported so a reader knows the
    #: document is a subset by choice rather than by omission.
    excluded_sections: list[SectionKey] = Field(default_factory=list)

    ai: BlueprintAiInfoSchema = Field(default_factory=BlueprintAiInfoSchema)
    generation_issues: list[GenerationIssueSchema] = Field(default_factory=list)
    injection_detected: bool = False
    injection_markers: list[str] = Field(default_factory=list)

    current_version: int = 0
    config_version: str = "0.0.0"
    engine_version: str = "0.0.0"
    duration_ms: int = 0
    notes: list[str] = Field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED
    #: The standing statement that this is a proposal requiring review by
    #: qualified SAP professionals. It travels with every response and every
    #: export, because a blueprint is exactly the kind of document that gets
    #: forwarded away from the tool that produced it.
    disclaimer: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BlueprintListItemSchema(BaseModel):
    """One row of the blueprint list."""

    blueprint_id: str
    name: str
    company: str
    industry: str
    sap_product: str
    section_count: int = 0
    approved_count: int = 0
    needs_input_count: int = 0
    version_count: int = 0
    current_version: int = 0
    created_at: datetime | None = None


class BlueprintListResponse(BaseModel):
    """Paginated blueprint list."""

    total: int
    limit: int
    offset: int
    blueprints: list[BlueprintListItemSchema] = Field(default_factory=list)


class DeleteSectionResponse(BaseModel):
    """What was removed, and what the blueprint looks like afterwards."""

    deleted: bool = True
    section_id: str
    section_key: str
    blueprint_id: str
    remaining_count: int = 0
    summary: BlueprintSummarySchema = Field(default_factory=BlueprintSummarySchema)
    #: Sections that referred to the deleted one and are now reported stale.
    affected_sections: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


class BlueprintVersionSchema(BaseModel):
    """One saved version of a blueprint."""

    blueprint_id: str
    version_number: int
    label: str = ""
    created_by: str = ""
    note: str = ""
    section_count: int = 0
    item_count: int = 0
    approved_count: int = 0
    needs_input_count: int = 0
    created_at: datetime | None = None
    #: The full section snapshot. Only returned by the single-version endpoint;
    #: the list endpoint leaves it empty so a history page stays small.
    sections: list[BlueprintSectionSchema] = Field(default_factory=list)


class VersionListResponse(BaseModel):
    """The version history, newest first."""

    blueprint_id: str
    current_version: int = 0
    total: int = 0
    versions: list[BlueprintVersionSchema] = Field(default_factory=list)


class SectionChange(str, Enum):
    """How one section differs between two versions."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


class SectionDiffSchema(BaseModel):
    """The difference in one section between two versions.

    Sections are matched by ``section_key``, never by position. Matching by
    position would report every section after an inserted custom one as
    rewritten, which is both wrong and unreadable.
    """

    section_key: str
    title: str
    change: SectionChange
    narrative_changed: bool = False
    items_added: list[str] = Field(default_factory=list)
    items_removed: list[str] = Field(default_factory=list)
    items_changed: list[str] = Field(default_factory=list)
    status_from: str | None = None
    status_to: str | None = None
    approval_changed: bool = False
    position_from: int | None = None
    position_to: int | None = None
    #: A unified diff of the narrative, capped so a response stays readable.
    narrative_diff: list[str] = Field(default_factory=list)


class VersionComparisonSchema(BaseModel):
    """A deterministic comparison of two saved versions."""

    blueprint_id: str
    from_version: int
    to_version: int
    from_label: str = ""
    to_label: str = ""
    sections_added: int = 0
    sections_removed: int = 0
    sections_modified: int = 0
    sections_unchanged: int = 0
    reordered: bool = False
    section_diffs: list[SectionDiffSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


class SectionInfoSchema(BaseModel):
    """One supported section, as the UI should describe it."""

    section_key: SectionKey
    title: str
    section_code: str = ""
    description: str = ""
    content_kind: ContentKind = ContentKind.LIST
    guidance: str = ""
    required_inputs: list[str] = Field(default_factory=list)
    derives_from: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    min_items: int = 0
    max_items: int = 0
    is_derived: bool = False


class BlueprintCatalogueSchema(BaseModel):
    """Everything a client needs to render the form and the navigator."""

    config_version: str
    engine_version: str
    sections: list[SectionInfoSchema] = Field(default_factory=list)
    statuses: list[SectionStatus] = Field(default_factory=list)
    content_kinds: list[ContentKind] = Field(default_factory=list)
    export_formats: list[ExportFormat] = Field(default_factory=list)
    project_fields: list[dict[str, Any]] = Field(default_factory=list)
    max_custom_sections: int = 20
    max_items_per_section: int = 40
    methodology: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = ""


class BlueprintSampleInfo(BaseModel):
    """Describes the bundled fictional project definitions."""

    available: bool = False
    project_count: int = 0
    projects: list[dict[str, Any]] = Field(default_factory=list)
    manifest: str | None = None
