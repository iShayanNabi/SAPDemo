"""Blueprint generation, staleness and summary arithmetic.

The engine wires the deterministic pieces together in one direction and knows
nothing about the database:

    plan the sections -> (optionally) draft them -> repair every draft
    -> summarise

The ordering is the design. Because the skeleton exists before the provider is
called, a blueprint generated with no API key has the same sections in the same
order, the same organisational structure, the same interface register and the
same "waiting for input" headings as one generated with a real model. Only the
wording differs, and the wording is labelled with where it came from.

One piece of arithmetic here is specific to this module and worth naming.
A blueprint is not thirty independent sections: the executive summary describes
the scope, the SIT scenarios describe the process steps, the cutover plan
describes the migration. When one of those changes, the section that described
it is now describing something that no longer exists. Every section therefore
carries a ``content_revision``, and a dependent section records the revisions it
was written against. Comparing the two is what turns "this document looks
complete" into "the executive summary was written against an earlier scope".
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.core.rounding import round_half_up
from app.core.security import contains_injection_markers
from app.modules.blueprint_generator.ai_generator import (
    BlueprintDraftingService,
    BlueprintDraftResult,
)
from app.modules.blueprint_generator.builder import (
    BuiltSection,
    build_needs_input_section,
    build_template_section,
    normalise_drafted_section,
)
from app.modules.blueprint_generator.planning import (
    BlueprintPlan,
    SectionSlot,
    build_plan,
    field_label,
)
from app.modules.blueprint_generator.thresholds import BlueprintConfig
from app.schemas.blueprint import (
    BlueprintAiInfoSchema,
    BlueprintProjectSchema,
    BlueprintSectionSchema,
    BlueprintSummarySchema,
    GenerationIssueSchema,
    ItemSource,
    SectionKey,
    SectionSource,
    SectionStatus,
)
from app.schemas.common import OutputOrigin

logger = get_logger(__name__)

ENGINE_VERSION = "1.0.0"

__all__ = [
    "ENGINE_VERSION",
    "BlueprintGenerationResult",
    "detect_injection",
    "generate_blueprint",
    "project_payload",
    "redraft_section",
    "stale_dependencies",
    "summarise_sections",
]


@dataclass
class BlueprintGenerationResult:
    """Everything one generation run produced."""

    plan: BlueprintPlan
    sections: list[BuiltSection] = field(default_factory=list)
    issues: list[GenerationIssueSchema] = field(default_factory=list)
    ai: BlueprintAiInfoSchema = field(default_factory=BlueprintAiInfoSchema)
    injection_detected: bool = False
    injection_markers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    duration_ms: int = 0


def project_payload(project: BlueprintProjectSchema) -> dict[str, Any]:
    """The project request in the shape the prompt builder expects."""
    return project.model_dump()


# ---------------------------------------------------------------------------
# Injection reporting
# ---------------------------------------------------------------------------

_INJECTION_FIELDS = (
    "company",
    "industry",
    "sap_product",
    "modules",
    "business_objectives",
    "current_process",
    "desired_process",
    "systems_involved",
    "integrations",
    "data_sources",
    "user_groups",
    "timeline",
    "constraints",
    "assumptions",
)


def detect_injection(project: BlueprintProjectSchema) -> list[str]:
    """Return the project fields that contain instruction-like text.

    The process descriptions are typed by a person, but they can just as easily
    be pasted out of a document somebody else wrote. They are filtered before
    they can reach a provider; this reports *that it happened*, so a reviewer
    knows the blueprint was drafted from text that tried to give instructions.
    """
    flagged: list[str] = []
    for name in _INJECTION_FIELDS:
        value = getattr(project, name)
        text = " ".join(value) if isinstance(value, list) else str(value)
        if contains_injection_markers(text):
            flagged.append(name)
    return flagged


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate_blueprint(
    project: BlueprintProjectSchema,
    sections: list[SectionKey],
    config: BlueprintConfig,
    *,
    use_ai: bool = True,
    drafting_service: BlueprintDraftingService | None = None,
) -> BlueprintGenerationResult:
    """Plan, draft and repair a full blueprint."""
    started = time.perf_counter()

    plan = build_plan(project, sections, config)
    markers = detect_injection(project)
    issues: list[GenerationIssueSchema] = []
    ai_info = BlueprintAiInfoSchema(requested=use_ai)

    # A section waiting for a project input is never sent to a provider: there
    # is nothing to draft it from, and asking would invite exactly the invention
    # the section exists to prevent.
    draftable = [slot for slot in plan.slots if not slot.needs_input]

    draft_result = BlueprintDraftResult()
    if use_ai and draftable:
        service = drafting_service or BlueprintDraftingService()
        draft_result = service.draft_blueprint(
            project_payload(project), [slot.to_prompt_dict() for slot in draftable]
        )
        ai_info = _ai_info(draft_result, requested=True)
        issues.extend(_draft_issues(draft_result))

    built = [
        _section_for_slot(slot, draft_result, project, config, issues) for slot in plan.slots
    ]

    notes = list(plan.notes)
    if markers:
        notes.append(
            "The project request contained text written as an instruction to an automated "
            "system (in: " + ", ".join(field_label(name) for name in markers) + "). It was "
            "filtered before drafting and was never acted on."
        )
    if use_ai and draftable and not draft_result.available:
        notes.append(
            "No usable draft came back from the AI provider, so every section below was "
            "written from the configured templates. The blueprint is complete and usable."
        )

    duration = int((time.perf_counter() - started) * 1000)
    logger.info(
        "Generated %d blueprint section(s) in %d ms (%d drafted, %d templated, %d awaiting input)",
        len(built),
        duration,
        sum(1 for item in built if item.source is SectionSource.AI_GENERATED),
        sum(
            1
            for item in built
            if item.source in (SectionSource.TEMPLATE, SectionSource.DERIVED)
            and item.status is not SectionStatus.NEEDS_INPUT
        ),
        sum(1 for item in built if item.status is SectionStatus.NEEDS_INPUT),
    )

    return BlueprintGenerationResult(
        plan=plan,
        sections=built,
        issues=issues,
        ai=ai_info,
        injection_detected=bool(markers),
        injection_markers=markers,
        notes=notes,
        duration_ms=duration,
    )


def redraft_section(
    slot: SectionSlot,
    project: BlueprintProjectSchema,
    config: BlueprintConfig,
    *,
    use_ai: bool = True,
    instruction: str | None = None,
    previous_narrative: str | None = None,
    drafting_service: BlueprintDraftingService | None = None,
) -> tuple[BuiltSection, list[GenerationIssueSchema], BlueprintAiInfoSchema]:
    """Redraft one section, falling back to the template as generation does."""
    issues: list[GenerationIssueSchema] = []
    ai_info = BlueprintAiInfoSchema(requested=use_ai)
    draft_result = BlueprintDraftResult()

    if slot.needs_input:
        return build_needs_input_section(slot, project, config), issues, ai_info

    if use_ai:
        service = drafting_service or BlueprintDraftingService()
        draft_result = service.redraft_section(
            project_payload(project),
            slot.to_prompt_dict(),
            instruction=instruction,
            previous_narrative=previous_narrative,
        )
        ai_info = _ai_info(draft_result, requested=True)
        issues.extend(_draft_issues(draft_result))

    section = _section_for_slot(slot, draft_result, project, config, issues)
    return section, issues, ai_info


def _section_for_slot(
    slot: SectionSlot,
    draft_result: BlueprintDraftResult,
    project: BlueprintProjectSchema,
    config: BlueprintConfig,
    issues: list[GenerationIssueSchema],
) -> BuiltSection:
    """Repair the draft for one section, or build it from the template."""
    if slot.needs_input:
        return build_needs_input_section(slot, project, config)

    drafted = draft_result.drafts.get(slot.section_key)
    if drafted is None:
        if draft_result.available:
            issues.append(
                GenerationIssueSchema(
                    section_key=slot.section_key,
                    stage="payload",
                    message=(
                        "The AI response contained no wording for this section; the "
                        "configured template wrote it."
                    ),
                )
            )
        return build_template_section(slot, project, config)

    section = normalise_drafted_section(
        slot,
        drafted,
        project,
        config,
        origin=draft_result.origin or OutputOrigin.AI_GENERATED,
    )
    for note in section.validation_notes:
        issues.append(
            GenerationIssueSchema(
                section_key=slot.section_key, stage="content", message=note
            )
        )
    return section


def _draft_issues(result: BlueprintDraftResult) -> list[GenerationIssueSchema]:
    """Turn provider-level and payload-level problems into reported issues."""
    issues: list[GenerationIssueSchema] = []
    if result.error and not result.available:
        issues.append(
            GenerationIssueSchema(
                stage="provider",
                message=(
                    f"{result.error} Every section was written from the configured "
                    "templates instead."
                ),
            )
        )
    for key in result.unmatched_section_keys:
        issues.append(
            GenerationIssueSchema(
                section_key=key,
                stage="payload",
                message=(
                    "The AI response contained a section that matches no planned section; "
                    "it was discarded."
                ),
            )
        )
    return issues


def _ai_info(result: BlueprintDraftResult, *, requested: bool) -> BlueprintAiInfoSchema:
    """Describe the provider call without ever including a credential."""
    return BlueprintAiInfoSchema(
        requested=requested,
        used=result.available,
        provider=result.provider,
        model=result.model,
        origin=result.origin,
        prompt_version=result.prompt_version,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        estimated_cost_usd=result.estimated_cost_usd,
        error=result.error,
    )


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def stale_dependencies(
    depends_on: list[str],
    recorded: Mapping[str, Any] | None,
    current_revisions: Mapping[str, int],
) -> list[str]:
    """Return the dependencies that have changed since this section was written.

    ``recorded`` is the ``{section_key: content_revision}`` map stored when the
    section was last written; ``current_revisions`` is the same map read from the
    document as it stands now. A dependency is stale when its revision has moved.

    A dependency the blueprint does not contain - because the request generated
    a subset, or because the section was never produced - is not stale. There is
    nothing for the text to disagree with.
    """
    if not depends_on:
        return []
    stored = dict(recorded or {})
    stale: list[str] = []
    for key in depends_on:
        if key not in current_revisions:
            continue
        if int(stored.get(key, -1)) != int(current_revisions[key]):
            stale.append(key)
    return stale


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def summarise_sections(
    sections: list[BlueprintSectionSchema],
    config: BlueprintConfig,
    *,
    version_count: int = 0,
) -> BlueprintSummarySchema:
    """Count a blueprint: sections, items, sources, approvals and readiness."""
    summary = BlueprintSummarySchema(section_count=len(sections))
    summary.status_counts = {item.value: 0 for item in SectionStatus}
    summary.source_counts = {item.value: 0 for item in SectionSource}
    summary.version_count = version_count

    missing: list[str] = []
    complete = 0
    for section in sections:
        summary.item_count += len(section.items)
        summary.status_counts[section.status.value] += 1
        summary.source_counts[section.source.value] += 1
        if section.is_custom:
            summary.custom_section_count += 1
        else:
            summary.canonical_section_count += 1
        if section.source is SectionSource.AI_GENERATED:
            summary.ai_drafted_count += 1
        elif section.source is SectionSource.DERIVED:
            summary.derived_count += 1
        elif section.source is SectionSource.MANUAL:
            summary.manual_count += 1
        else:
            summary.template_count += 1
        if section.approved_at is not None:
            summary.approved_count += 1
        if section.status is SectionStatus.NEEDS_INPUT:
            summary.needs_input_count += 1
            for name in section.missing_inputs:
                if name not in missing:
                    missing.append(name)
            if config.readiness.count_needs_input_as_complete:
                complete += 1
        elif section.narrative.strip():
            complete += 1
        if section.stale_dependencies:
            summary.stale_section_count += 1
            if section.approved_at is not None:
                summary.stale_approved_count += 1

    summary.missing_inputs = missing
    decimals = config.readiness.decimals
    if sections:
        summary.completeness_pct = round_half_up(complete * 100 / len(sections), decimals)
        summary.approval_pct = round_half_up(
            summary.approved_count * 100 / len(sections), decimals
        )
    return summary


def item_source_counts(sections: list[BlueprintSectionSchema]) -> dict[str, int]:
    """Count items by how they came to exist, across the whole blueprint."""
    counts = {item.value: 0 for item in ItemSource}
    for section in sections:
        for item in section.items:
            counts[item.source.value] += 1
    return counts
