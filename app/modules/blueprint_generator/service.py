"""Orchestration and persistence for the SAP Blueprint Generator.

This is the only layer that knows about the database. It wires the pure pieces
together in one direction:

    project request -> deterministic skeleton -> optional AI draft -> repair
    -> persist blueprint and sections -> read, edit, regenerate, approve,
       add, delete, version, compare, export

Four rules run through everything below, and each exists because a blueprint is
a *working document* that people review, argue about and forward:

* **Content and review are different operations.** Editing or regenerating a
  section's wording never writes an approval, and approving a section never
  rewrites its wording. Any change to the content clears the approval, because
  an approval belongs to the words that were read.
* **A section identifier points at one section forever.** Custom section numbers
  are read back out of the existing identifiers rather than counted from the
  number of sections, so deleting ``BP-CUS-002`` leaves a gap instead of handing
  that name to a different section somebody has already commented on.
* **The factual sections always agree with the project request.** Change the
  request and the organisational structure, module list, integration register,
  interface list, migration sources and roles are rebuilt from it.
* **A saved version never moves.** Snapshots are stored as data, so editing the
  document tomorrow cannot change what version 1 says today.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.blueprint import Blueprint, BlueprintSection, BlueprintVersion
from app.modules.blueprint_generator.builder import (
    build_needs_input_section,
    build_template_section,
    derived_to_item,
    items_from_input,
    renumber_items,
)
from app.modules.blueprint_generator.engine import (
    ENGINE_VERSION,
    generate_blueprint,
    redraft_section,
    stale_dependencies,
    summarise_sections,
)
from app.modules.blueprint_generator.planning import (
    DerivedItem,
    SectionSlot,
    custom_section_slot,
    derived_items_for,
    field_label,
    missing_inputs_for,
    next_custom_number,
)
from app.modules.blueprint_generator.thresholds import (
    BlueprintConfig,
    get_blueprint_config,
)
from app.modules.blueprint_generator.versioning import (
    build_snapshot,
    compare_snapshots,
    snapshot_counts,
)
from app.schemas.blueprint import (
    SECTION_ORDER,
    ApproveSectionRequest,
    BlueprintAiInfoSchema,
    BlueprintCatalogueSchema,
    BlueprintItemSchema,
    BlueprintListItemSchema,
    BlueprintProjectSchema,
    BlueprintSampleInfo,
    BlueprintSchema,
    BlueprintSectionSchema,
    BlueprintVersionSchema,
    ContentKind,
    CreateSectionRequest,
    CreateVersionRequest,
    DeleteSectionResponse,
    ExportFormat,
    GenerateBlueprintRequest,
    GenerationIssueSchema,
    ItemSource,
    RegenerateSectionRequest,
    SectionInfoSchema,
    SectionKey,
    SectionSource,
    SectionStatus,
    UpdateBlueprintRequest,
    UpdateSectionRequest,
    VersionComparisonSchema,
    VersionListResponse,
)
from app.schemas.common import OutputOrigin

logger = get_logger(__name__)

SAMPLE_PROJECT_FILE = "sample_blueprint_projects.json"

#: Version number that means "the blueprint as it stands now, unsaved".
WORKING_COPY_VERSION = 0


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex[:32]


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


def generate(db: Session, request: GenerateBlueprintRequest) -> BlueprintSchema:
    """Generate a complete blueprint and persist it."""
    config = get_blueprint_config()

    result = generate_blueprint(
        request.project,
        request.sections,
        config,
        use_ai=request.use_ai,
    )
    if not result.sections:
        raise ValidationError(
            "No blueprint section could be planned for this request. Choose at least one "
            "section, or omit the section filter to generate the complete document.",
            details={"requested_sections": [item.value for item in request.sections]},
        )

    project = request.project
    blueprint = Blueprint(
        id=_new_id(),
        name=(request.blueprint_name or f"{project.company} - {project.sap_product}")[:200],
        owner=request.owner or "",
        company=project.company,
        industry=project.industry,
        sap_product=project.sap_product,
        modules=list(project.modules),
        business_objectives=list(project.business_objectives),
        current_process=project.current_process,
        desired_process=project.desired_process,
        countries=list(project.countries),
        locations=list(project.locations),
        company_codes=list(project.company_codes),
        plants=list(project.plants),
        purchasing_organizations=list(project.purchasing_organizations),
        systems_involved=list(project.systems_involved),
        integrations=list(project.integrations),
        data_sources=list(project.data_sources),
        user_groups=list(project.user_groups),
        timeline=project.timeline,
        constraints=list(project.constraints),
        assumptions=list(project.assumptions),
        requested_sections=[item.value for item in request.sections],
        excluded_sections=[item.value for item in result.plan.excluded_sections],
        current_version=0,
        custom_sections_issued=0,
        notes=list(result.notes),
        generation_issues=[issue.model_dump() for issue in result.issues],
        injection_detected=result.injection_detected,
        injection_markers=list(result.injection_markers),
        config_version=config.config_version,
        engine_version=ENGINE_VERSION,
        duration_ms=result.duration_ms,
        ai_requested=result.ai.requested,
        ai_used=result.ai.used,
        ai_provider=result.ai.provider,
        ai_model=result.ai.model,
        ai_output_origin=result.ai.origin.value if result.ai.origin else None,
        ai_prompt_version=result.ai.prompt_version,
        ai_input_tokens=result.ai.input_tokens,
        ai_output_tokens=result.ai.output_tokens,
        ai_estimated_cost_usd=result.ai.estimated_cost_usd,
        ai_error=result.ai.error,
    )
    db.add(blueprint)
    db.flush()

    present = {section.slot.section_key for section in result.sections}
    for section in result.sections:
        slot = section.slot
        # Every section is written in the same pass, so each dependency that
        # exists is at revision 1. Recording that now is what lets a later edit
        # be spotted as one.
        dependencies = {key: 1 for key in slot.depends_on if key in present}
        db.add(
            BlueprintSection(
                id=_new_id(),
                blueprint_id=blueprint.id,
                section_id=slot.section_id,
                section_key=slot.section_key,
                position=slot.position,
                title=slot.title,
                is_custom=slot.is_custom,
                content_kind=slot.content_kind.value,
                description=slot.description,
                narrative=section.narrative,
                items=[item.model_dump(mode="json") for item in section.items],
                status=section.status.value,
                source=section.source.value,
                output_origin=section.output_origin.value,
                missing_inputs=list(slot.missing_inputs),
                validation_notes=list(section.validation_notes),
                content_revision=1,
                depends_on=list(slot.depends_on),
                dependency_revisions=dependencies,
                ai_provider=(
                    result.ai.provider
                    if section.source is SectionSource.AI_GENERATED
                    else None
                ),
                ai_prompt_version=(
                    result.ai.prompt_version
                    if section.source is SectionSource.AI_GENERATED
                    else None
                ),
            )
        )

    db.commit()
    db.refresh(blueprint)
    logger.info(
        "Generated blueprint %s with %d section(s)", blueprint.id, len(result.sections)
    )
    return _blueprint_schema(db, blueprint, config)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_blueprint(db: Session, blueprint_id: str) -> BlueprintSchema:
    """Return one blueprint with its sections."""
    return _blueprint_schema(db, _require_blueprint(db, blueprint_id), get_blueprint_config())


def list_blueprints(
    db: Session, *, limit: int = 20, offset: int = 0
) -> tuple[int, list[BlueprintListItemSchema]]:
    """Return blueprints, newest first."""
    total = int(db.execute(select(func.count(Blueprint.id))).scalar_one())
    rows = (
        db.execute(
            select(Blueprint)
            .order_by(Blueprint.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    items: list[BlueprintListItemSchema] = []
    for blueprint in rows:
        sections = _rows_for(db, blueprint.id)
        items.append(
            BlueprintListItemSchema(
                blueprint_id=blueprint.id,
                name=blueprint.name,
                company=blueprint.company,
                industry=blueprint.industry,
                sap_product=blueprint.sap_product,
                section_count=len(sections),
                approved_count=sum(1 for row in sections if row.approved_at is not None),
                needs_input_count=sum(
                    1 for row in sections if row.status == SectionStatus.NEEDS_INPUT.value
                ),
                version_count=_version_count(db, blueprint.id),
                current_version=blueprint.current_version,
                created_at=blueprint.created_at,
            )
        )
    return total, items


def get_section(db: Session, blueprint_id: str, section_id: str) -> BlueprintSectionSchema:
    """Return one section of a blueprint."""
    blueprint = _require_blueprint(db, blueprint_id)
    row = _require_section(db, blueprint.id, section_id)
    return _section_schema(row, _revisions(db, blueprint.id))


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def update_blueprint(
    db: Session, blueprint_id: str, request: UpdateBlueprintRequest
) -> BlueprintSchema:
    """Edit the blueprint's own fields, and optionally its project request."""
    config = get_blueprint_config()
    blueprint = _require_blueprint(db, blueprint_id)
    provided = request.model_dump(exclude_unset=True)
    if not provided:
        raise ValidationError("The update request contained no field to change.")

    if request.name is not None:
        blueprint.name = request.name
    if request.owner is not None:
        blueprint.owner = request.owner
    if request.notes is not None:
        blueprint.notes = list(request.notes)

    if request.project is not None:
        changed = _apply_project(db, blueprint, request.project, config)
        if changed:
            notes = list(blueprint.notes or [])
            notes.append(
                "The project request was updated. These sections were rebuilt from the new "
                "values, and any approval they carried was cleared: " + ", ".join(changed) + "."
            )
            blueprint.notes = notes[-40:]

    db.commit()
    db.refresh(blueprint)
    logger.info("Updated blueprint %s", blueprint.id)
    return _blueprint_schema(db, blueprint, config)


def update_section(
    db: Session, blueprint_id: str, section_id: str, request: UpdateSectionRequest
) -> BlueprintSectionSchema:
    """Apply a partial edit to one section.

    Only the fields present in the request are written, so a UI that sends one
    changed paragraph cannot blank the rest of the section.

    Editing the **content** - the title, the narrative or the items - clears the
    approval and returns the section to draft, exactly as regenerating does. An
    approval belongs to the words that were read and approved; carrying it
    across to rewritten ones would leave a section reading "approved by Ingrid"
    above a scope Ingrid never saw. Editing only the review fields - the status
    or the comments - leaves the approval alone.
    """
    config = get_blueprint_config()
    blueprint = _require_blueprint(db, blueprint_id)
    row = _require_section(db, blueprint.id, section_id)
    provided = request.model_dump(exclude_unset=True)
    if not provided:
        raise ValidationError("The update request contained no field to change.")

    content_changed = False

    if request.title is not None and request.title != row.title:
        row.title = request.title
        content_changed = True

    if request.narrative is not None:
        narrative = request.narrative.strip()
        if narrative != row.narrative:
            row.narrative = narrative
            content_changed = True

    if request.items is not None:
        if len(request.items) > config.generation.max_items_per_section:
            raise ValidationError(
                f"A section may hold at most {config.generation.max_items_per_section} items.",
                details={"submitted": len(request.items)},
            )
        item_code = _item_code_for(row, config)
        row.items = [
            item.model_dump(mode="json")
            for item in items_from_input(request.items, item_code, config)
        ]
        content_changed = True

    if request.comments is not None:
        row.comments = request.comments
    if request.status is not None:
        # Two statuses are not a person's to set by hand, because each of them
        # is one half of a pair the rest of the module reads together.
        if request.status is SectionStatus.NEEDS_INPUT and not row.missing_inputs:
            raise ValidationError(
                "A section can only be marked 'needs input' by the generator, and only while "
                "a required project field is empty. Update the project request instead.",
                details={"section_key": row.section_key},
            )
        if request.status is SectionStatus.APPROVED and row.approved_at is None:
            raise ValidationError(
                "A section cannot be set to 'approved' without an approval. Use the approve "
                "endpoint, which records who approved it and when - a status saying approved "
                "with nobody's name against it is worse than a draft.",
                details={"section_key": row.section_key},
            )
        row.status = request.status.value

    if content_changed:
        row.source = SectionSource.MANUAL.value
        row.output_origin = OutputOrigin.RULE_BASED.value
        row.edited_by_user = True
        _record_content_change(db, blueprint.id, row, request.status)

    db.commit()
    db.refresh(row)
    logger.info("Updated blueprint section %s (%s)", row.section_id, blueprint.id)
    return _section_schema(row, _revisions(db, blueprint.id))


def regenerate_section(
    db: Session, blueprint_id: str, section_id: str, request: RegenerateSectionRequest
) -> BlueprintSectionSchema:
    """Redraft one section's wording, keeping its place in the document.

    The identifier, the position and the section's factual items are kept - the
    items come from the project request and no redraft can change them. The
    **approval is always cleared**, because it belonged to the wording that was
    replaced.
    """
    config = get_blueprint_config()
    blueprint = _require_blueprint(db, blueprint_id)
    row = _require_section(db, blueprint.id, section_id)
    project = _project_from_blueprint(blueprint)
    slot = _slot_for_row(row, project, config)

    section, issues, ai_info = redraft_section(
        slot,
        project,
        config,
        use_ai=request.use_ai,
        instruction=request.instruction,
        previous_narrative=row.narrative,
    )

    row.narrative = section.narrative
    row.items = [item.model_dump(mode="json") for item in section.items]
    row.status = section.status.value
    row.source = section.source.value
    row.output_origin = section.output_origin.value
    row.missing_inputs = list(slot.missing_inputs)
    row.validation_notes = list(section.validation_notes)
    row.edited_by_user = False
    row.regenerated_count = int(row.regenerated_count or 0) + 1
    row.ai_provider = (
        ai_info.provider if section.source is SectionSource.AI_GENERATED else None
    )
    row.ai_prompt_version = (
        ai_info.prompt_version if section.source is SectionSource.AI_GENERATED else None
    )

    _record_content_change(db, blueprint.id, row, None)
    _record_issues(blueprint, issues)
    db.commit()
    db.refresh(row)
    logger.info(
        "Regenerated blueprint section %s (attempt %d)", row.section_id, row.regenerated_count
    )
    return _section_schema(row, _revisions(db, blueprint.id))


def approve_section(
    db: Session, blueprint_id: str, section_id: str, request: ApproveSectionRequest
) -> BlueprintSectionSchema:
    """Approve or un-approve one section.

    A section waiting for a project input cannot be approved: approving a
    heading that says "nothing was written here" would make the completeness
    figures describe a document that does not exist.
    """
    blueprint = _require_blueprint(db, blueprint_id)
    row = _require_section(db, blueprint.id, section_id)

    if request.approved and row.status == SectionStatus.NEEDS_INPUT.value:
        raise ValidationError(
            "This section is waiting for project input and holds no content, so it cannot be "
            "approved. Supply "
            + ", ".join(field_label(name) for name in (row.missing_inputs or []))
            + " in the project request and regenerate the section first.",
            details={"section_key": row.section_key, "missing_inputs": list(row.missing_inputs or [])},
        )

    if request.approved:
        row.approved_by = request.approved_by
        row.approved_at = _now()
        row.status = SectionStatus.APPROVED.value
    else:
        row.approved_by = None
        row.approved_at = None
        row.status = SectionStatus.DRAFT.value
    if request.comments:
        row.comments = request.comments

    db.commit()
    db.refresh(row)
    logger.info(
        "Section %s of blueprint %s %s",
        row.section_id,
        blueprint.id,
        "approved" if request.approved else "approval cleared",
    )
    return _section_schema(row, _revisions(db, blueprint.id))


def add_section(
    db: Session, blueprint_id: str, request: CreateSectionRequest
) -> BlueprintSectionSchema:
    """Add one custom section to a blueprint."""
    config = get_blueprint_config()
    blueprint = _require_blueprint(db, blueprint_id)
    rows = _rows_for(db, blueprint.id)

    custom_rows = [row for row in rows if row.is_custom]
    if len(custom_rows) >= config.generation.max_custom_sections:
        raise ValidationError(
            f"This blueprint already holds the configured maximum of "
            f"{config.generation.max_custom_sections} custom sections.",
            details={"custom_sections": len(custom_rows)},
        )

    number = next_custom_number(
        [row.section_id for row in custom_rows],
        config,
        issued=blueprint.custom_sections_issued,
    )
    position = _position_after(rows, request.after_section)
    slot = custom_section_slot(
        title=request.title,
        content_kind=request.content_kind,
        position=position,
        number=number,
        config=config,
    )

    items = items_from_input(request.items, slot.item_code, config)
    row = BlueprintSection(
        id=_new_id(),
        blueprint_id=blueprint.id,
        section_id=slot.section_id,
        section_key=slot.section_key,
        position=position,
        title=slot.title,
        is_custom=True,
        content_kind=slot.content_kind.value,
        description=slot.description,
        narrative=request.narrative.strip(),
        items=[item.model_dump(mode="json") for item in items],
        status=SectionStatus.DRAFT.value,
        source=SectionSource.MANUAL.value,
        output_origin=OutputOrigin.RULE_BASED.value,
        comments=request.comments or "",
        missing_inputs=[],
        validation_notes=[],
        content_revision=1,
        depends_on=[],
        dependency_revisions={},
        edited_by_user=True,
    )
    # Everything at or below the insertion point moves down one place, so the
    # document keeps a gap-free reading order.
    for existing in rows:
        if existing.position >= position:
            existing.position += 1
    db.add(row)
    blueprint.custom_sections_issued = number
    db.commit()
    db.refresh(row)
    logger.info("Added custom section %s to blueprint %s", row.section_id, blueprint.id)
    return _section_schema(row, _revisions(db, blueprint.id))


def delete_section(
    db: Session, blueprint_id: str, section_id: str
) -> DeleteSectionResponse:
    """Delete one custom section and report what the blueprint lost.

    Only custom sections can be deleted. A canonical section is part of the
    blueprint standard: a reader who finds twenty-nine headings cannot tell
    whether the thirtieth was considered and dropped or never written, so the
    standard set stays whole. A canonical section that does not apply is left
    with its content saying so.
    """
    config = get_blueprint_config()
    blueprint = _require_blueprint(db, blueprint_id)
    row = _require_section(db, blueprint.id, section_id)

    if not row.is_custom:
        raise ValidationError(
            f"'{row.title}' is one of the {len(SECTION_ORDER)} standard blueprint sections and "
            "cannot be deleted. Only custom sections can be removed. Edit the section to record "
            "that it does not apply to this project instead.",
            details={"section_key": row.section_key, "section_id": row.section_id},
        )

    deleted_key = row.section_key
    identifier = row.section_id
    affected = [
        other.section_key
        for other in _rows_for(db, blueprint.id)
        if other.id != row.id and deleted_key in (other.depends_on or [])
    ]

    db.delete(row)
    db.flush()

    remaining = _rows_for(db, blueprint.id)
    for index, item in enumerate(remaining, start=1):
        item.position = index
    # ``custom_sections_issued`` is deliberately NOT decremented: the identifier
    # this section held is retired with it.

    db.commit()
    logger.info("Deleted custom section %s from blueprint %s", identifier, blueprint.id)

    sections = _sections_for(db, blueprint.id)
    return DeleteSectionResponse(
        deleted=True,
        section_id=identifier,
        section_key=deleted_key,
        blueprint_id=blueprint.id,
        remaining_count=len(sections),
        summary=summarise_sections(
            sections, config, version_count=_version_count(db, blueprint.id)
        ),
        affected_sections=affected,
    )


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


def create_version(
    db: Session, blueprint_id: str, request: CreateVersionRequest
) -> BlueprintVersionSchema:
    """Save the blueprint's current state as an immutable version."""
    blueprint = _require_blueprint(db, blueprint_id)
    sections = _sections_for(db, blueprint.id)
    if not sections:
        raise ValidationError(
            "This blueprint holds no section, so there is nothing to save as a version.",
            details={"blueprint_id": blueprint.id},
        )

    snapshot = build_snapshot(sections)
    counts = snapshot_counts(snapshot)
    number = int(blueprint.current_version or 0) + 1

    version = BlueprintVersion(
        id=_new_id(),
        blueprint_id=blueprint.id,
        version_number=number,
        label=request.label or f"Version {number}",
        created_by=request.created_by or blueprint.owner or "",
        note=request.note,
        sections=snapshot,
        section_count=counts["section_count"],
        item_count=counts["item_count"],
        approved_count=counts["approved_count"],
        needs_input_count=counts["needs_input_count"],
    )
    db.add(version)
    blueprint.current_version = number
    db.commit()
    db.refresh(version)
    logger.info("Saved blueprint %s as version %d", blueprint.id, number)
    return _version_schema(version, include_sections=False)


def list_versions(db: Session, blueprint_id: str) -> VersionListResponse:
    """Return the version history, newest first."""
    blueprint = _require_blueprint(db, blueprint_id)
    rows = _version_rows(db, blueprint.id)
    return VersionListResponse(
        blueprint_id=blueprint.id,
        current_version=blueprint.current_version,
        total=len(rows),
        versions=[
            _version_schema(row, include_sections=False) for row in reversed(rows)
        ],
    )


def get_version(
    db: Session, blueprint_id: str, version_number: int
) -> BlueprintVersionSchema:
    """Return one saved version, including its full section snapshot."""
    blueprint = _require_blueprint(db, blueprint_id)
    if version_number == WORKING_COPY_VERSION:
        return _working_copy(db, blueprint)
    return _version_schema(
        _require_version(db, blueprint.id, version_number), include_sections=True
    )


def compare_versions(
    db: Session, blueprint_id: str, from_version: int, to_version: int
) -> VersionComparisonSchema:
    """Compare two saved versions, or a saved version against the live document.

    Version ``0`` means "the blueprint as it stands now", which is what a
    reviewer wants most often: *what have I changed since I last saved?*
    """
    blueprint = _require_blueprint(db, blueprint_id)
    if from_version == to_version:
        raise ValidationError(
            "Choose two different versions to compare.",
            details={"from_version": from_version, "to_version": to_version},
        )

    before, before_label = _snapshot_for(db, blueprint, from_version)
    after, after_label = _snapshot_for(db, blueprint, to_version)
    return compare_snapshots(
        blueprint.id,
        from_version,
        to_version,
        before,
        after,
        from_label=before_label,
        to_label=after_label,
    )


# ---------------------------------------------------------------------------
# Catalogue, samples and export payload
# ---------------------------------------------------------------------------


def get_catalogue() -> BlueprintCatalogueSchema:
    """Describe the sections, the project fields and the deterministic rules."""
    config = get_blueprint_config()
    return BlueprintCatalogueSchema(
        config_version=config.config_version,
        engine_version=ENGINE_VERSION,
        sections=[
            SectionInfoSchema(
                section_key=section,
                title=config.spec(section).title,
                section_code=config.spec(section).section_code,
                description=config.spec(section).description,
                content_kind=config.spec(section).content_kind,
                guidance=config.spec(section).guidance,
                required_inputs=list(config.spec(section).required_inputs),
                derives_from=list(config.spec(section).derived_fields),
                depends_on=list(config.spec(section).depends_on),
                min_items=config.spec(section).min_items,
                max_items=config.spec(section).max_items,
                is_derived=config.spec(section).is_derived,
            )
            for section in SECTION_ORDER
        ],
        statuses=list(SectionStatus),
        content_kinds=list(ContentKind),
        export_formats=list(ExportFormat),
        project_fields=[
            {
                "name": name,
                "label": field_label(name),
                "kind": "list" if _is_list_field(name) else "text",
                "required": _is_required_field(name),
                "used_by": sorted(
                    section.value
                    for section in SECTION_ORDER
                    if name in config.spec(section).required_inputs
                    or name in config.spec(section).derived_fields
                ),
            }
            for name in BlueprintProjectSchema.model_fields
        ],
        max_custom_sections=config.generation.max_custom_sections,
        max_items_per_section=config.generation.max_items_per_section,
        methodology=config.methodology(),
        disclaimer=config.reporting.disclaimer,
    )


def sample_info() -> BlueprintSampleInfo:
    """Describe the bundled fictional project definitions."""
    path = settings.sample_dir / SAMPLE_PROJECT_FILE
    if not path.is_file():
        return BlueprintSampleInfo(available=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    projects = payload.get("projects", [])
    return BlueprintSampleInfo(
        available=True,
        project_count=len(projects),
        projects=[
            {
                "name": item.get("name"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "company": item.get("project", {}).get("company"),
                "industry": item.get("project", {}).get("industry"),
                "sap_product": item.get("project", {}).get("sap_product"),
                "suggested_sections": item.get("suggested_sections", []),
            }
            for item in projects
        ],
        manifest=payload.get("manifest"),
    )


def load_sample_project(name: str) -> dict[str, Any]:
    """Return one bundled fictional project definition."""
    path = settings.sample_dir / SAMPLE_PROJECT_FILE
    if not path.is_file():
        raise NotFoundError(
            "The demo project definitions have not been generated yet. "
            "Run: python scripts/generate_blueprint_sample_data.py"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload.get("projects", []):
        if item.get("name") == name:
            return item
    raise NotFoundError("That demo project does not exist.", details={"requested": name})


def build_export_payload(db: Session, blueprint_id: str) -> dict[str, Any]:
    """Assemble everything the export builders need."""
    config = get_blueprint_config()
    blueprint = _require_blueprint(db, blueprint_id)
    schema = _blueprint_schema(db, blueprint, config)
    return {
        "blueprint": schema.model_dump(mode="json", exclude={"sections", "summary"}),
        "summary": schema.summary.model_dump(mode="json"),
        "sections": [item.model_dump(mode="json") for item in schema.sections],
        "versions": [
            _version_schema(row, include_sections=False).model_dump(mode="json")
            for row in reversed(_version_rows(db, blueprint.id))
        ],
        "methodology": config.methodology(),
        "disclaimer": config.reporting.disclaimer,
        "ai_note": config.reporting.ai_note,
        "review_note": config.reporting.review_note,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _is_list_field(name: str) -> bool:
    annotation = BlueprintProjectSchema.model_fields[name].annotation
    return getattr(annotation, "__origin__", None) is list


def _is_required_field(name: str) -> bool:
    return BlueprintProjectSchema.model_fields[name].is_required()


def _require_blueprint(db: Session, blueprint_id: str) -> Blueprint:
    blueprint = db.get(Blueprint, blueprint_id)
    if blueprint is None:
        raise NotFoundError("Blueprint not found.", details={"blueprint_id": blueprint_id})
    return blueprint


def _require_section(db: Session, blueprint_id: str, section_id: str) -> BlueprintSection:
    """Find a section by its identifier, its key or its internal id.

    Accepting ``BP-SCOPE`` and ``scope`` as well as the internal id is a
    convenience the API documents: those are what a person reading an exported
    blueprint has in front of them. All three are unique inside one blueprint.
    """
    rows = _rows_for(db, blueprint_id)
    needle = str(section_id).strip()
    for row in rows:
        if needle in (row.id, row.section_id, row.section_key):
            return row
    lowered = needle.lower()
    for row in rows:
        if lowered in (row.section_id.lower(), row.section_key.lower()):
            return row
    raise NotFoundError(
        "Blueprint section not found.",
        details={"blueprint_id": blueprint_id, "section_id": section_id},
    )


def _require_version(
    db: Session, blueprint_id: str, version_number: int
) -> BlueprintVersion:
    version = db.execute(
        select(BlueprintVersion).where(
            BlueprintVersion.blueprint_id == blueprint_id,
            BlueprintVersion.version_number == version_number,
        )
    ).scalar_one_or_none()
    if version is None:
        raise NotFoundError(
            "That blueprint version does not exist.",
            details={"blueprint_id": blueprint_id, "version_number": version_number},
        )
    return version


def _rows_for(db: Session, blueprint_id: str) -> list[BlueprintSection]:
    return list(
        db.execute(
            select(BlueprintSection)
            .where(BlueprintSection.blueprint_id == blueprint_id)
            .order_by(BlueprintSection.position, BlueprintSection.section_id)
        )
        .scalars()
        .all()
    )


def _version_rows(db: Session, blueprint_id: str) -> list[BlueprintVersion]:
    return list(
        db.execute(
            select(BlueprintVersion)
            .where(BlueprintVersion.blueprint_id == blueprint_id)
            .order_by(BlueprintVersion.version_number)
        )
        .scalars()
        .all()
    )


def _version_count(db: Session, blueprint_id: str) -> int:
    return int(
        db.execute(
            select(func.count(BlueprintVersion.id)).where(
                BlueprintVersion.blueprint_id == blueprint_id
            )
        ).scalar_one()
    )


def _revisions(db: Session, blueprint_id: str) -> dict[str, int]:
    """The live ``{section_key: content_revision}`` map of one blueprint."""
    return {
        row.section_key: int(row.content_revision or 0) for row in _rows_for(db, blueprint_id)
    }


def _sections_for(db: Session, blueprint_id: str) -> list[BlueprintSectionSchema]:
    revisions = _revisions(db, blueprint_id)
    return [_section_schema(row, revisions) for row in _rows_for(db, blueprint_id)]


def _position_after(rows: list[BlueprintSection], after_section: str | None) -> int:
    """Return the position a new section takes.

    An unknown or omitted anchor appends to the end, which is the least
    surprising thing to do with a heading nobody placed.
    """
    if after_section:
        needle = str(after_section).strip().lower()
        for row in rows:
            if needle in (row.id.lower(), row.section_id.lower(), row.section_key.lower()):
                return row.position + 1
    return (max((row.position for row in rows), default=0)) + 1


def _item_code_for(row: BlueprintSection, config: BlueprintConfig) -> str:
    if row.is_custom:
        return "CUS"
    return config.spec(row.section_key).item_code.upper()


def _record_content_change(
    db: Session,
    blueprint_id: str,
    row: BlueprintSection,
    requested_status: SectionStatus | None,
) -> None:
    """Bump the revision, clear the approval and re-record the dependencies.

    The three belong together. Bumping the revision without clearing the
    approval leaves a signature on words nobody signed; clearing the approval
    without re-recording the dependencies leaves the section permanently stale
    against sections it has just been written from.
    """
    row.content_revision = int(row.content_revision or 0) + 1
    if row.approved_at is not None:
        row.approved_by = None
        row.approved_at = None
        logger.info(
            "Cleared the approval on %s: its content changed after approval", row.section_id
        )
        if requested_status is None and row.status != SectionStatus.NEEDS_INPUT.value:
            row.status = SectionStatus.DRAFT.value
    elif requested_status is None and row.status == SectionStatus.APPROVED.value:
        row.status = SectionStatus.DRAFT.value

    live = _revisions(db, blueprint_id)
    row.dependency_revisions = {
        key: live[key] for key in (row.depends_on or []) if key in live
    }


def _record_issues(blueprint: Blueprint, issues: list[GenerationIssueSchema]) -> None:
    """Append regeneration issues to the blueprint's record, newest last."""
    if not issues:
        return
    existing = list(blueprint.generation_issues or [])
    existing.extend(issue.model_dump() for issue in issues)
    blueprint.generation_issues = existing[-100:]


def _project_from_blueprint(blueprint: Blueprint) -> BlueprintProjectSchema:
    """Rebuild the project request that produced a blueprint."""
    return BlueprintProjectSchema(
        company=blueprint.company,
        industry=blueprint.industry,
        sap_product=blueprint.sap_product,
        modules=list(blueprint.modules or []),
        business_objectives=list(blueprint.business_objectives or []),
        current_process=blueprint.current_process,
        desired_process=blueprint.desired_process,
        countries=list(blueprint.countries or []),
        locations=list(blueprint.locations or []),
        company_codes=list(blueprint.company_codes or []),
        plants=list(blueprint.plants or []),
        purchasing_organizations=list(blueprint.purchasing_organizations or []),
        systems_involved=list(blueprint.systems_involved or []),
        integrations=list(blueprint.integrations or []),
        data_sources=list(blueprint.data_sources or []),
        user_groups=list(blueprint.user_groups or []),
        timeline=blueprint.timeline or "",
        constraints=list(blueprint.constraints or []),
        assumptions=list(blueprint.assumptions or []),
    )


def _slot_for_row(
    row: BlueprintSection, project: BlueprintProjectSchema, config: BlueprintConfig
) -> SectionSlot:
    """Rebuild the planned slot behind a stored section row.

    The slot is recomputed from the configuration and the *current* project
    request rather than read back from the row, which is what makes a
    regeneration pick up a project field the user has since filled in.
    """
    if row.is_custom:
        return SectionSlot(
            section_key=row.section_key,
            section_id=row.section_id,
            position=row.position,
            title=row.title,
            content_kind=ContentKind(row.content_kind),
            description=row.description or "",
            guidance="",
            allow_ai_items=True,
            min_items=0,
            max_items=config.generation.max_items_per_section,
            item_code="CUS",
            is_custom=True,
        )

    spec = config.spec(row.section_key)
    gaps = missing_inputs_for(project, spec)
    return SectionSlot(
        section_key=row.section_key,
        section_id=row.section_id,
        position=row.position,
        title=row.title or spec.title,
        content_kind=spec.content_kind,
        description=spec.description,
        guidance=spec.guidance,
        depends_on=tuple(spec.depends_on),
        required_inputs=tuple(spec.required_inputs),
        missing_inputs=gaps,
        derived_items=() if gaps else derived_items_for(project, spec, config),
        allow_ai_items=spec.allow_ai_items,
        min_items=spec.min_items,
        max_items=min(spec.max_items, config.generation.max_items_per_section),
        item_code=spec.item_code.upper(),
    )


def _apply_project(
    db: Session,
    blueprint: Blueprint,
    project: BlueprintProjectSchema,
    config: BlueprintConfig,
) -> list[str]:
    """Store a new project request and resync the sections that depend on it.

    Returns the section keys whose content was rebuilt. Three cases:

    * a section that was waiting for an input and now has it is rebuilt from the
      templates, so the heading stops saying "nothing was written here";
    * a section that had its inputs and has lost them goes back to waiting,
      rather than keeping items describing units the project no longer contains;
    * a section whose derived items have changed keeps its narrative and its
      drafted items, and has its factual rows replaced. The organisational
      structure has to equal the project request; there is no version of this
      where the two are allowed to disagree.
    """
    for name in BlueprintProjectSchema.model_fields:
        setattr(blueprint, name, getattr(project, name))

    changed: list[str] = []
    for row in _rows_for(db, blueprint.id):
        if row.is_custom:
            continue
        slot = _slot_for_row(row, project, config)
        was_needs_input = row.status == SectionStatus.NEEDS_INPUT.value

        if slot.needs_input:
            if not was_needs_input or list(row.missing_inputs or []) != list(slot.missing_inputs):
                section = build_needs_input_section(slot, project, config)
                row.narrative = section.narrative
                row.items = []
                row.status = SectionStatus.NEEDS_INPUT.value
                row.source = SectionSource.TEMPLATE.value
                row.output_origin = OutputOrigin.RULE_BASED.value
                row.missing_inputs = list(slot.missing_inputs)
                _record_content_change(db, blueprint.id, row, None)
                changed.append(row.section_key)
            continue

        if was_needs_input:
            section = build_template_section(slot, project, config)
            row.narrative = section.narrative
            row.items = [item.model_dump(mode="json") for item in section.items]
            row.status = SectionStatus.DRAFT.value
            row.source = section.source.value
            row.output_origin = section.output_origin.value
            row.missing_inputs = []
            _record_content_change(db, blueprint.id, row, None)
            changed.append(row.section_key)
            continue

        row.missing_inputs = []
        if not slot.derived_items and not _stored_derived(row):
            continue
        refreshed = _refresh_derived_items(row, slot.derived_items, config)
        if refreshed is not None:
            row.items = refreshed
            _record_content_change(db, blueprint.id, row, None)
            changed.append(row.section_key)

    return changed


def _stored_derived(row: BlueprintSection) -> list[dict[str, Any]]:
    return [
        item
        for item in (row.items or [])
        if str(item.get("source")) == ItemSource.DERIVED.value
    ]


def _refresh_derived_items(
    row: BlueprintSection, derived: tuple[DerivedItem, ...], config: BlueprintConfig
) -> list[dict[str, Any]] | None:
    """Replace a section's derived items, keeping everything a person wrote.

    Returns ``None`` when nothing changed, so an unrelated project edit does not
    bump every section's revision and mark the whole document stale.
    """
    fresh = [derived_to_item(item, config) for item in derived]
    kept = [
        BlueprintItemSchema.model_validate(item)
        for item in (row.items or [])
        if str(item.get("source")) != ItemSource.DERIVED.value
    ]
    combined = renumber_items(fresh + kept, _item_code_for(row, config), config)
    payload = [item.model_dump(mode="json") for item in combined]
    if payload == list(row.items or []):
        return None
    return payload


def _snapshot_for(
    db: Session, blueprint: Blueprint, version_number: int
) -> tuple[list[dict[str, Any]], str]:
    """Return the sections of one version, or of the live document for ``0``."""
    if version_number == WORKING_COPY_VERSION:
        return build_snapshot(_sections_for(db, blueprint.id)), "current (unsaved)"
    version = _require_version(db, blueprint.id, version_number)
    return list(version.sections or []), version.label


def _working_copy(db: Session, blueprint: Blueprint) -> BlueprintVersionSchema:
    """Present the live document in the shape of a version, without saving it."""
    sections = _sections_for(db, blueprint.id)
    counts = snapshot_counts(build_snapshot(sections))
    return BlueprintVersionSchema(
        blueprint_id=blueprint.id,
        version_number=WORKING_COPY_VERSION,
        label="current (unsaved)",
        created_by=blueprint.owner or "",
        note="The blueprint as it stands now. It has not been saved as a version.",
        section_count=counts["section_count"],
        item_count=counts["item_count"],
        approved_count=counts["approved_count"],
        needs_input_count=counts["needs_input_count"],
        created_at=blueprint.updated_at,
        sections=sections,
    )


def _version_schema(
    version: BlueprintVersion, *, include_sections: bool
) -> BlueprintVersionSchema:
    return BlueprintVersionSchema(
        blueprint_id=version.blueprint_id,
        version_number=version.version_number,
        label=version.label,
        created_by=version.created_by,
        note=version.note,
        section_count=version.section_count,
        item_count=version.item_count,
        approved_count=version.approved_count,
        needs_input_count=version.needs_input_count,
        created_at=version.created_at,
        sections=(
            [
                BlueprintSectionSchema.model_validate(item)
                for item in (version.sections or [])
            ]
            if include_sections
            else []
        ),
    )


def _section_schema(
    row: BlueprintSection, revisions: dict[str, int]
) -> BlueprintSectionSchema:
    """Validate one stored row back into the API shape.

    The items are renumbered on the way out as well as on the way in: a row
    written before a numbering fix, or edited directly in the database, still
    presents 1..n to every reader.
    """
    items = [BlueprintItemSchema.model_validate(item) for item in (row.items or [])]
    for index, item in enumerate(items, start=1):
        if not item.item_id:
            item.item_id = f"{row.section_id}-{index:03d}"
    stale = stale_dependencies(
        list(row.depends_on or []), row.dependency_revisions, revisions
    )
    return BlueprintSectionSchema(
        id=row.id,
        blueprint_id=row.blueprint_id,
        section_id=row.section_id,
        section_key=row.section_key,
        position=row.position,
        title=row.title,
        is_custom=bool(row.is_custom),
        content_kind=ContentKind(row.content_kind),
        description=row.description or "",
        narrative=row.narrative or "",
        items=items,
        status=SectionStatus(row.status),
        source=SectionSource(row.source),
        output_origin=OutputOrigin(row.output_origin),
        comments=row.comments or "",
        missing_inputs=list(row.missing_inputs or []),
        validation_notes=list(row.validation_notes or []),
        content_revision=int(row.content_revision or 0),
        depends_on=list(row.depends_on or []),
        stale_dependencies=stale,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        # The approval and the staleness are one statement, not two. Reporting
        # them separately leaves every reader - and every export - to join them,
        # and the one that forgets prints "Approved" over a superseded scope.
        approval_is_stale=bool(stale) and row.approved_at is not None,
        regenerated_count=row.regenerated_count or 0,
        edited_by_user=bool(row.edited_by_user),
        ai_provider=row.ai_provider,
        ai_prompt_version=row.ai_prompt_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _blueprint_schema(
    db: Session, blueprint: Blueprint, config: BlueprintConfig
) -> BlueprintSchema:
    sections = _sections_for(db, blueprint.id)
    summary = summarise_sections(
        sections, config, version_count=_version_count(db, blueprint.id)
    )
    origin = (
        OutputOrigin(blueprint.ai_output_origin)
        if blueprint.ai_output_origin
        else OutputOrigin.RULE_BASED
    )
    return BlueprintSchema(
        blueprint_id=blueprint.id,
        name=blueprint.name,
        owner=blueprint.owner or "",
        project=_project_from_blueprint(blueprint),
        summary=summary,
        sections=sections,
        excluded_sections=[
            SectionKey(name) for name in (blueprint.excluded_sections or [])
        ],
        ai=BlueprintAiInfoSchema(
            requested=blueprint.ai_requested,
            used=blueprint.ai_used,
            provider=blueprint.ai_provider,
            model=blueprint.ai_model,
            origin=(
                OutputOrigin(blueprint.ai_output_origin)
                if blueprint.ai_output_origin
                else None
            ),
            prompt_version=blueprint.ai_prompt_version,
            input_tokens=blueprint.ai_input_tokens,
            output_tokens=blueprint.ai_output_tokens,
            estimated_cost_usd=blueprint.ai_estimated_cost_usd,
            error=blueprint.ai_error,
        ),
        generation_issues=[
            GenerationIssueSchema.model_validate(item)
            for item in (blueprint.generation_issues or [])
        ],
        injection_detected=blueprint.injection_detected,
        injection_markers=list(blueprint.injection_markers or []),
        current_version=blueprint.current_version,
        config_version=blueprint.config_version,
        engine_version=blueprint.engine_version,
        duration_ms=blueprint.duration_ms,
        notes=list(blueprint.notes or []),
        output_origin=origin,
        disclaimer=config.reporting.disclaimer,
        created_at=blueprint.created_at,
        updated_at=blueprint.updated_at,
    )
