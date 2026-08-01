"""The deterministic blueprint skeleton.

This module answers every question about a blueprint that a language model must
not be allowed to answer:

* which sections the document contains, and in what order;
* what each section is called and what it is for;
* which project inputs a section needs, and whether they were supplied;
* which items a section holds **because the project request named them** - the
  company codes, the plants, the integrations, the migration sources, the roles;
* which other sections a section describes, so a later edit can be reported.

Only after that is settled does anything get drafted. Run the same request
twice, with a model or without one, and you get the same sections, the same
order, the same organisational structure and the same interface register. Only
the prose can differ.

The rule the whole module rests on: **a section whose inputs are empty is
reported, not invented.** A blueprint that lists three interfaces for a project
that named none is worse than a blueprint with a heading that says "no
integration was supplied" - the first one gets built, the second one gets fixed.

Nothing here touches the database or the AI layer, so the whole plan is testable
on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.modules.blueprint_generator.rendering import (
    project_values,
    render,
    safe_project_text,
)
from app.modules.blueprint_generator.thresholds import BlueprintConfig, SectionSpec
from app.schemas.blueprint import (
    SECTION_ORDER,
    BlueprintProjectSchema,
    ContentKind,
    SectionKey,
)

logger = get_logger(__name__)

__all__ = [
    "BlueprintPlan",
    "DerivedItem",
    "SectionSlot",
    "build_plan",
    "custom_section_slot",
    "derived_items_for",
    "field_label",
    "missing_inputs_for",
    "next_custom_number",
]

#: Matches the numeric tail of a custom section identifier such as ``BP-CUS-007``.
_TRAILING_NUMBER = re.compile(r"(\d+)\s*$")


def field_label(name: str) -> str:
    """Return a readable label for a project field name.

    ``purchasing_organizations`` becomes "purchasing organizations", which is
    what a user needs to see when a section tells them what is missing.
    """
    return str(name).replace("_", " ").strip()


@dataclass(frozen=True)
class DerivedItem:
    """One item computed from the project request rather than drafted.

    ``source_field`` records which project field produced it, so a reader - and
    an export - can say *why* this row is in the document.
    """

    title: str
    detail: str = ""
    category: str = ""
    reference: str = ""
    owner: str = ""
    rating: str = ""
    source_field: str = ""


@dataclass(frozen=True)
class SectionSlot:
    """One planned section, before anything has written its words."""

    section_key: str
    section_id: str
    position: int
    title: str
    content_kind: ContentKind
    description: str = ""
    guidance: str = ""
    depends_on: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()
    #: Required project fields the request left empty. While this is non-empty
    #: the section is written as "needs input" and nothing is drafted for it.
    missing_inputs: tuple[str, ...] = ()
    derived_items: tuple[DerivedItem, ...] = ()
    allow_ai_items: bool = True
    min_items: int = 0
    max_items: int = 25
    item_code: str = "ITM"
    is_custom: bool = False

    @property
    def needs_input(self) -> bool:
        return bool(self.missing_inputs)

    def to_prompt_dict(self) -> dict[str, object]:
        """The compact description of this section that travels to a provider.

        The derived items travel too, but as *context*: they tell the model what
        the project actually named so the narrative can refer to it, and the
        response is never allowed to change them.
        """
        return {
            "section_key": self.section_key,
            "title": self.title,
            "content_kind": self.content_kind.value,
            "purpose": self.description,
            "guidance": self.guidance,
            "wants_items": self.allow_ai_items,
            "min_items": self.min_items if self.allow_ai_items else 0,
            "max_items": self.max_items if self.allow_ai_items else 0,
            "facts_already_recorded": [
                {
                    "title": item.title,
                    "category": item.category,
                    "detail": item.detail,
                }
                for item in self.derived_items[:20]
            ],
        }


@dataclass
class BlueprintPlan:
    """The complete plan for one blueprint."""

    slots: list[SectionSlot] = field(default_factory=list)
    #: Canonical sections the request excluded. Reported, never hidden.
    excluded_sections: list[SectionKey] = field(default_factory=list)
    #: Every project field that would unlock at least one section if supplied.
    missing_inputs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.slots)


def _is_empty(value: object) -> bool:
    """True when a project field holds nothing usable."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def missing_inputs_for(
    project: BlueprintProjectSchema, spec: SectionSpec
) -> tuple[str, ...]:
    """Return the required project fields that this request left empty."""
    return tuple(
        name for name in spec.required_inputs if _is_empty(getattr(project, name, None))
    )


def derived_items_for(
    project: BlueprintProjectSchema, spec: SectionSpec, config: BlueprintConfig
) -> tuple[DerivedItem, ...]:
    """Compute the items a section holds because the project request named them.

    One item per value, in the order the user entered them, with the configured
    category and detail. This is the whole of the module's factual content: no
    provider is involved, and for the factual sections no provider is allowed to
    add to it.
    """
    if not spec.derives_from:
        return ()

    values = project_values(project, config.generation.placeholder_defaults)
    items: list[DerivedItem] = []
    seen: set[tuple[str, str]] = set()

    for derivation in spec.derives_from:
        raw = getattr(project, derivation.field, None)
        entries = [raw] if isinstance(raw, str) else list(raw or [])
        for entry in entries:
            # The values become rows in the finished document, so they travel
            # through the same injection filter as every other quoted value.
            text = safe_project_text(entry, max_length=500).strip()
            if not text:
                continue
            key = (derivation.field, text.lower())
            if key in seen:
                continue
            seen.add(key)
            local = dict(values)
            local["value"] = text
            items.append(
                DerivedItem(
                    title=text,
                    detail=render(derivation.detail_template, local, single_line=True),
                    category=derivation.category,
                    reference=render(derivation.reference_template, local, single_line=True),
                    owner=derivation.owner,
                    rating=derivation.rating,
                    source_field=derivation.field,
                )
            )
            if len(items) >= config.generation.max_items_per_section:
                logger.info(
                    "Section '%s' reached the configured item ceiling of %d",
                    spec.title,
                    config.generation.max_items_per_section,
                )
                return tuple(items)
    return tuple(items)


def build_plan(
    project: BlueprintProjectSchema,
    sections: list[SectionKey],
    config: BlueprintConfig,
) -> BlueprintPlan:
    """Build the full deterministic plan for one generation request.

    ``sections`` restricts the document to a subset; an empty list means the
    whole canonical set. Either way the order is the canonical one - a blueprint
    whose headings arrive in the order the caller happened to type them is not a
    blueprint anybody can read alongside another.
    """
    chosen = set(sections) if sections else set(SECTION_ORDER)
    excluded = [item for item in SECTION_ORDER if item not in chosen]

    slots: list[SectionSlot] = []
    missing: list[str] = []
    position = 0

    for section in SECTION_ORDER:
        if section not in chosen:
            continue
        spec = config.spec(section)
        position += 1
        gaps = missing_inputs_for(project, spec)
        for name in gaps:
            if name not in missing:
                missing.append(name)
        slots.append(
            SectionSlot(
                section_key=section.value,
                section_id=config.generation.build_section_id(spec.section_code.upper()),
                position=position,
                title=spec.title,
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
        )

    notes: list[str] = []
    if excluded:
        notes.append(
            "The request asked for a subset of the blueprint: "
            + ", ".join(item.value for item in excluded)
            + " were not generated. Regenerate without a section filter to produce the "
            "complete document."
        )
    if missing:
        blocked = sorted({slot.section_key for slot in slots if slot.needs_input})
        notes.append(
            "These project fields were left empty, so the sections that depend on them were "
            "left unwritten rather than invented: "
            + ", ".join(field_label(name) for name in missing)
            + ". Sections waiting for input: "
            + ", ".join(blocked)
            + "."
        )

    logger.info(
        "Planned %d blueprint section(s), %d waiting for input",
        len(slots),
        sum(1 for slot in slots if slot.needs_input),
    )
    return BlueprintPlan(
        slots=slots,
        excluded_sections=excluded,
        missing_inputs=missing,
        notes=notes,
    )


def next_custom_number(
    existing_ids: list[str], config: BlueprintConfig, *, issued: int = 0
) -> int:
    """Return the next free custom section number for a blueprint.

    Two sources are consulted, and both are needed:

    * the numbers already in use, read back out of the existing identifiers
      rather than counted from the number of sections;
    * ``issued`` - the highest number this blueprint has **ever** handed out.

    The second one is what stops an identifier being reissued. Reading the
    existing identifiers alone is not enough: delete the only custom section and
    there is nothing left to read, so the next section would be handed
    ``BP-CUS-001`` again - the name a reviewer has already written a comment
    against. A section identifier that points at two different sections over the
    life of a document is worse than a gap in the numbering.
    """
    highest = max(config.generation.id_number_start - 1, int(issued or 0))
    for identifier in existing_ids:
        if not identifier:
            continue
        match = _TRAILING_NUMBER.search(str(identifier))
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def custom_section_slot(
    *,
    title: str,
    content_kind: ContentKind,
    position: int,
    number: int,
    config: BlueprintConfig,
) -> SectionSlot:
    """Build the slot for a user-added custom section.

    A custom section has no configured inputs, derives nothing and depends on
    nothing: it is the user's own heading, and the generator neither fills it nor
    reports it as incomplete.
    """
    return SectionSlot(
        section_key=f"custom_{number:03d}",
        section_id=config.generation.build_custom_section_id(number),
        position=position,
        title=title,
        content_kind=content_kind,
        description="Custom section added to this blueprint.",
        guidance="",
        allow_ai_items=True,
        min_items=0,
        max_items=config.generation.max_items_per_section,
        item_code="CUS",
        is_custom=True,
    )
