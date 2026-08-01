"""Turning a planned section into a complete, usable blueprint section.

Three jobs live here, and they share one code path on purpose:

**The "needs input" build.** When a section's required project fields are empty,
the section is written as a heading that says which field to fill in. It is not
drafted, not templated and not left blank - the reader is told exactly what the
document is waiting for.

**The template build.** Every section that has its inputs can be filled from the
configured templates alone, with no language model involved. That is what makes
mock mode - and "the provider is down" - produce a real blueprint rather than an
apology.

**The repair of a drafted section.** A model returns prose. Prose can be blank,
it can be a hundred items long, it can drop a field entirely, and it can try to
add an eleventh company code to an organisational structure the project defined.
Everything that comes back is measured against the configured limits, repaired
field by field from the template, and every repair is recorded on the section as
a ``validation_note``.

Two rules the module rests on:

* **A missing field is filled from the template, never left blank and never
  invented.**
* **Derived items are not negotiable.** In a section whose items come from the
  project request, the model writes the narrative and nothing else; items it
  returns anyway are discarded and the attempt is reported. An organisational
  structure a model can add a plant to is not an organisational structure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.modules.blueprint_generator.planning import DerivedItem, SectionSlot, field_label
from app.modules.blueprint_generator.rendering import (
    clean_line,
    clean_text,
    project_values,
    render,
)
from app.modules.blueprint_generator.thresholds import BlueprintConfig
from app.schemas.blueprint import (
    BlueprintItemInput,
    BlueprintItemSchema,
    BlueprintProjectSchema,
    ItemSource,
    SectionSource,
    SectionStatus,
)
from app.schemas.common import OutputOrigin

logger = get_logger(__name__)

__all__ = [
    "BuiltSection",
    "build_needs_input_section",
    "derived_to_item",
    "build_template_section",
    "items_from_input",
    "normalise_drafted_section",
    "renumber_items",
]


@dataclass
class BuiltSection:
    """One section's content, ready to be persisted."""

    slot: SectionSlot
    narrative: str
    items: list[BlueprintItemSchema]
    source: SectionSource = SectionSource.TEMPLATE
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED
    status: SectionStatus = SectionStatus.DRAFT
    validation_notes: list[str] = field(default_factory=list)


def renumber_items(
    items: list[BlueprintItemSchema], item_code: str, config: BlueprintConfig
) -> list[BlueprintItemSchema]:
    """Return ``items`` numbered 1..n, whatever identifiers they arrived with.

    An item has no identity outside its section: it is never queried, filtered
    or reported on alone, and every edit replaces the whole ordered list. So the
    order the items arrive in is trusted and the identifiers they carry are not
    - exactly the opposite of a *section* identifier, which has to keep meaning
    the same thing for the life of the document because people write review
    comments against it.
    """
    start = config.generation.id_number_start
    return [
        item.model_copy(
            update={"item_id": config.generation.build_item_id(item_code, start + index)}
        )
        for index, item in enumerate(items)
    ]


def derived_to_item(item: DerivedItem, config: BlueprintConfig) -> BlueprintItemSchema:
    limits = config.generation
    return BlueprintItemSchema(
        item_id="",
        title=clean_line(item.title, limits.max_title_chars),
        detail=clean_line(item.detail, limits.max_detail_chars),
        category=clean_line(item.category, 120),
        reference=clean_line(item.reference or field_label(item.source_field), 300),
        owner=clean_line(item.owner, 120),
        rating=clean_line(item.rating, 60),
        source=ItemSource.DERIVED,
        output_origin=OutputOrigin.RULE_BASED,
    )


def _template_items(
    slot: SectionSlot, values: Mapping[str, Any], config: BlueprintConfig
) -> list[BlueprintItemSchema]:
    limits = config.generation
    spec = None if slot.is_custom else config.spec(slot.section_key)
    templates = list(spec.template_items) if spec else []
    built: list[BlueprintItemSchema] = []
    for template in templates:
        built.append(
            BlueprintItemSchema(
                item_id="",
                title=clean_line(render(template.title, values, single_line=True), limits.max_title_chars),
                detail=clean_line(
                    render(template.detail, values, single_line=True), limits.max_detail_chars
                ),
                category=clean_line(render(template.category, values, single_line=True), 120),
                reference=clean_line(render(template.reference, values, single_line=True), 300),
                owner=clean_line(render(template.owner, values, single_line=True), 120),
                rating=clean_line(render(template.rating, values, single_line=True), 60),
                source=ItemSource.TEMPLATE,
                output_origin=OutputOrigin.RULE_BASED,
            )
        )
    return built


# ---------------------------------------------------------------------------
# The "needs input" build
# ---------------------------------------------------------------------------


def build_needs_input_section(
    slot: SectionSlot, project: BlueprintProjectSchema, config: BlueprintConfig
) -> BuiltSection:
    """Write a section that is waiting for a project input.

    The heading stays in the document - a blueprint missing its Integrations
    heading reads as a project with no integrations, which is a different claim
    from "nobody told us". The body says which field to fill in and what will
    happen when it is.
    """
    labels = ", ".join(field_label(name) for name in slot.missing_inputs)
    plural = "s" if len(slot.missing_inputs) > 1 else ""
    narrative = (
        f"This section is waiting for project input. The project request left the "
        f"following field{plural} empty: {labels}. Nothing has been written here, because "
        f"the content of this section has to come from what {project.company} actually "
        f"has - inventing it would produce a blueprint that reads convincingly and "
        f"describes a system nobody asked for. Add the missing detail to the project "
        f"request and regenerate this section."
    )
    return BuiltSection(
        slot=slot,
        narrative=narrative,
        items=[],
        source=SectionSource.TEMPLATE,
        output_origin=OutputOrigin.RULE_BASED,
        status=SectionStatus.NEEDS_INPUT,
    )


# ---------------------------------------------------------------------------
# The template build
# ---------------------------------------------------------------------------


def build_template_section(
    slot: SectionSlot, project: BlueprintProjectSchema, config: BlueprintConfig
) -> BuiltSection:
    """Build a complete section for ``slot`` from the configured templates.

    This is a real section, not a placeholder: it names the company, the
    product, the modules and the organisational units, and its items are the
    ones the project request supplied. It is what a mock-mode blueprint falls
    back to and what an unusable draft is replaced with.
    """
    if slot.needs_input:
        return build_needs_input_section(slot, project, config)

    limits = config.generation
    values = project_values(project, limits.placeholder_defaults)
    spec = None if slot.is_custom else config.spec(slot.section_key)

    narrative = clean_text(
        render(spec.template_narrative, values) if spec else "",
        limits.max_narrative_chars,
    )

    items = [derived_to_item(item, config) for item in slot.derived_items]
    if len(items) < slot.max_items:
        for item in _template_items(slot, values, config):
            if len(items) >= slot.max_items:
                break
            items.append(item)

    source = SectionSource.DERIVED if slot.derived_items else SectionSource.TEMPLATE
    return BuiltSection(
        slot=slot,
        narrative=narrative,
        items=renumber_items(items[: slot.max_items], slot.item_code, config),
        source=source,
        output_origin=OutputOrigin.RULE_BASED,
        status=SectionStatus.DRAFT,
    )


# ---------------------------------------------------------------------------
# The repair of a drafted section
# ---------------------------------------------------------------------------


def normalise_drafted_section(
    slot: SectionSlot,
    drafted: Mapping[str, Any],
    project: BlueprintProjectSchema,
    config: BlueprintConfig,
    *,
    origin: OutputOrigin,
) -> BuiltSection:
    """Repair one drafted section against the configured limits.

    Every field is checked; anything unusable is replaced from the template and
    recorded in ``validation_notes``. When neither a usable narrative nor a
    usable item survives, the whole section falls back to the template one -
    reported, not silently accepted as an empty heading.
    """
    if slot.needs_input:
        # A section waiting for input is never drafted, so a draft for one can
        # only come from a provider answering a question it was not asked.
        section = build_needs_input_section(slot, project, config)
        section.validation_notes = [
            "The AI response contained content for a section that is waiting for project "
            "input. It was discarded: the missing project fields have to be supplied first."
        ]
        return section

    limits = config.generation
    template = build_template_section(slot, project, config)
    notes: list[str] = []

    narrative = clean_text(drafted.get("narrative"), limits.max_narrative_chars)
    drafted_items = _normalise_items(drafted.get("items"), slot, config)

    if not slot.allow_ai_items and drafted_items:
        # The organisational structure, the integration register, the interface
        # list, the migration sources and the role list exist because the
        # project named them. A model may describe them; it may not extend them.
        notes.append(
            f"The AI response returned {len(drafted_items)} item(s) for a section whose "
            f"content is computed from the project request. They were discarded; the "
            f"{len(template.items)} item(s) below come from the project request."
        )
        drafted_items = []

    if not narrative and not drafted_items:
        template.validation_notes = [
            "The drafted section held neither a usable narrative nor a usable item, so the "
            "configured template wrote this section instead."
        ]
        return template

    if len(narrative) < limits.min_narrative_chars:
        if narrative:
            notes.append(
                f"The drafted narrative was {len(narrative)} character(s), below the "
                f"configured minimum of {limits.min_narrative_chars}; the template "
                f"narrative was used."
            )
        else:
            notes.append("The drafted narrative was empty; the template narrative was used.")
        narrative = template.narrative

    items = [derived_to_item(item, config) for item in slot.derived_items]
    if slot.allow_ai_items:
        # A short draft is topped up from the template rather than replaced by
        # it. One well-drafted risk plus two template ones is more use to a
        # reader than three template ones, and the top-up is reported either
        # way. Duplicate titles are never added twice.
        chosen = list(drafted_items)
        shortfall = slot.min_items - len(items) - len(chosen)
        if shortfall > 0:
            seen = {item.title.lower() for item in items + chosen}
            filler = [
                item
                for item in template.items
                if item.source is ItemSource.TEMPLATE and item.title.lower() not in seen
            ][:shortfall]
            if filler:
                notes.append(
                    f"The draft held {len(drafted_items)} item(s), fewer than the configured "
                    f"minimum of {slot.min_items}; {len(filler)} item(s) from the configured "
                    f"template were added."
                )
                chosen.extend(filler)
            elif not chosen:
                notes.append("The draft listed no usable item and the template holds none.")
        for item in chosen:
            if len(items) >= slot.max_items:
                notes.append(
                    f"The draft held more items than the configured maximum of "
                    f"{slot.max_items}; the surplus was dropped."
                )
                break
            items.append(item)

    return BuiltSection(
        slot=slot,
        narrative=narrative,
        items=renumber_items(items, slot.item_code, config),
        source=SectionSource.AI_GENERATED,
        output_origin=origin,
        status=SectionStatus.DRAFT,
        validation_notes=notes,
    )


def _normalise_items(
    raw: Any, slot: SectionSlot, config: BlueprintConfig
) -> list[BlueprintItemSchema]:
    """Clean and cap the drafted items of one section."""
    if isinstance(raw, str):
        raw = [{"title": line} for line in raw.splitlines()]
    if not isinstance(raw, (list, tuple)):
        return []

    limits = config.generation
    ceiling = min(slot.max_items, limits.max_items_per_ai_section)
    items: list[BlueprintItemSchema] = []
    seen: set[str] = set()

    for entry in raw:
        if isinstance(entry, str):
            entry = {"title": entry}
        if not isinstance(entry, Mapping):
            continue
        title = clean_line(entry.get("title") or entry.get("name") or "", limits.max_title_chars)
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            BlueprintItemSchema(
                item_id="",
                title=title,
                detail=clean_line(entry.get("detail"), limits.max_detail_chars),
                category=clean_line(entry.get("category"), 120),
                reference=clean_line(entry.get("reference"), 300),
                owner=clean_line(entry.get("owner"), 120),
                rating=clean_line(entry.get("rating"), 60),
                source=ItemSource.AI_GENERATED,
                output_origin=OutputOrigin.AI_GENERATED,
            )
        )
        if len(items) >= ceiling:
            break
    return items


def items_from_input(
    inputs: list[BlueprintItemInput], slot_item_code: str, config: BlueprintConfig
) -> list[BlueprintItemSchema]:
    """Turn the items a person typed into stored items.

    Everything a user writes is theirs: it is cleaned and length-checked, never
    replaced from a template, and it is labelled ``manual`` so a later reader can
    see which rows a person wrote and which a model drafted.
    """
    limits = config.generation
    items = [
        BlueprintItemSchema(
            item_id="",
            title=clean_line(entry.title, limits.max_title_chars),
            detail=clean_line(entry.detail, limits.max_detail_chars),
            category=clean_line(entry.category, 120),
            reference=clean_line(entry.reference, 300),
            owner=clean_line(entry.owner, 120),
            rating=clean_line(entry.rating, 60),
            source=ItemSource.MANUAL,
            output_origin=OutputOrigin.RULE_BASED,
        )
        for entry in inputs
        if clean_line(entry.title)
    ]
    return renumber_items(items[: limits.max_items_per_section], slot_item_code, config)
