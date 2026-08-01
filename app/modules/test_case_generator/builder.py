"""Turning a planned slot into a complete, usable test case.

Two jobs live here, and they share one code path on purpose:

**The template build.** Every slot can be filled from the configured templates
alone, with no language model involved at all. That is what makes mock mode -
and "the provider is down" - produce a real suite rather than an apology.

**The repair of a drafted case.** A model returns prose. Prose can be blank, it
can be a hundred steps long, it can renumber its own steps wrongly, it can drop
a field entirely. Everything that comes back is measured against the configured
limits, repaired field by field from the template, and every repair is recorded
on the case as a ``validation_note``. A drafted case that cannot be repaired is
replaced wholesale by the template one - the slot is never lost, and the reader
is always told what happened.

The rule the whole module rests on: **a missing field is filled from the
template, never left blank and never invented.**
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from string import Formatter
from typing import Any

from app.core.logging import get_logger
from app.modules.test_case_generator.planning import TestCaseSlot
from app.modules.test_case_generator.thresholds import TestCaseGeneratorConfig
from app.schemas.common import OutputOrigin
from app.schemas.test_case_generator import (
    ProcessContextSchema,
    TestCaseSource,
    TestStepSchema,
)

logger = get_logger(__name__)

__all__ = [
    "DraftedCase",
    "build_template_case",
    "normalise_drafted_case",
    "render",
    "template_values",
]

#: Control characters that must never reach an export or a PDF.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class _DefaultingMap(dict):
    """A mapping that renders an unknown placeholder as a readable fallback.

    ``str.format`` raises ``KeyError`` for an unknown field, which would turn a
    typo in a configured template into a 500 at request time. Returning the
    placeholder's own name instead keeps the failure visible in the text and the
    suite intact.
    """

    def __missing__(self, key: str) -> str:  # pragma: no cover - defensive
        logger.warning("Unknown placeholder '%s' in a test case template", key)
        return key.replace("_", " ")


def render(template: str, values: Mapping[str, Any]) -> str:
    """Render one configured template, collapsing whitespace."""
    try:
        rendered = Formatter().vformat(template or "", (), _DefaultingMap(values))
    except (IndexError, ValueError) as exc:  # pragma: no cover - defensive
        logger.warning("Unusable template %r: %s", template, exc)
        rendered = template or ""
    return re.sub(r"\s+", " ", rendered).strip()


def template_values(
    context: ProcessContextSchema, slot: TestCaseSlot, config: TestCaseGeneratorConfig
) -> dict[str, str]:
    """Build the placeholder values for one slot.

    Where the user supplied nothing, the configured placeholder default is used
    so a rendered step never contains a hole.
    """
    defaults = config.generation.placeholder_defaults
    return {
        "sap_product": context.sap_product,
        "sap_module": context.sap_module,
        "business_process": context.business_process,
        "process": context.business_process,
        "focus": slot.focus,
        "test_type_label": slot.test_type_label,
        "test_case_id": slot.slot_id,
        "role": _first(context.user_roles, defaults.role),
        "primary_system": _first(context.systems_involved, defaults.primary_system),
        "integration": _first(context.integrations, defaults.integration),
        "test_data_requirement": _first(
            context.test_data_requirements, defaults.test_data_requirement
        ),
    }


def _first(items: list[str], fallback: str) -> str:
    """Return the first non-empty entry of ``items`` or ``fallback``."""
    for item in items:
        if item and item.strip():
            return item.strip()
    return fallback


def _clean(text: Any, limit: int) -> str:
    """Strip control characters, collapse whitespace and enforce a length."""
    if text is None:
        return ""
    value = _CONTROL_CHARS.sub(" ", str(text))
    value = re.sub(r"[ \t]+", " ", value).strip()
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value


def _clean_list(items: Any, limit: int, item_limit: int) -> list[str]:
    """Clean a list of short strings, dropping blanks and duplicates."""
    if isinstance(items, str):
        items = items.splitlines()
    if not isinstance(items, (list, tuple)):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = _clean(item, item_limit)
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
        if len(cleaned) >= limit:
            break
    return cleaned


@dataclass
class DraftedCase:
    """One test case's content, ready to be persisted."""

    slot: TestCaseSlot
    title: str
    objective: str
    preconditions: list[str]
    test_data: list[str]
    steps: list[TestStepSchema]
    expected_result: str
    comments: str = ""
    source: TestCaseSource = TestCaseSource.TEMPLATE
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED
    validation_notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The template build
# ---------------------------------------------------------------------------


def build_template_case(
    slot: TestCaseSlot,
    context: ProcessContextSchema,
    config: TestCaseGeneratorConfig,
) -> DraftedCase:
    """Build a complete test case for ``slot`` from the configured templates.

    This is a real test case, not a placeholder: it names the process, the
    module, the role and the focus area, and its steps are the ones a tester
    would actually walk. It is what a mock-mode suite falls back to and what an
    unusable draft is replaced with.
    """
    spec = config.spec(slot.test_type)
    values = template_values(context, slot, config)
    limits = config.generation

    title = _clean(
        f"{slot.test_type_label}: {context.business_process} - {slot.focus}",
        limits.max_title_chars,
    )

    preconditions = _clean_list(
        list(context.preconditions)
        + [render(item, values) for item in spec.precondition_templates],
        limits.max_preconditions,
        500,
    )
    test_data = _clean_list(
        [render(item, values) for item in spec.test_data_templates]
        + list(context.test_data_requirements),
        limits.max_test_data_items,
        500,
    )

    steps: list[TestStepSchema] = []
    for index, template in enumerate(spec.step_templates[: limits.max_steps_per_case], start=1):
        steps.append(
            TestStepSchema(
                step_number=index,
                action=_clean(render(template.action, values), limits.max_step_chars),
                test_data=_clean(render(template.test_data or "", values), limits.max_step_chars)
                or None,
                expected_result=_clean(
                    render(template.expected_result, values), limits.max_step_chars
                )
                or None,
            )
        )

    return DraftedCase(
        slot=slot,
        title=title,
        objective=_clean(render(spec.objective_template, values), limits.max_objective_chars),
        preconditions=preconditions,
        test_data=test_data,
        steps=steps,
        expected_result=_clean(
            render(spec.expected_result_template, values), limits.max_expected_result_chars
        ),
        source=TestCaseSource.TEMPLATE,
        output_origin=OutputOrigin.RULE_BASED,
    )


# ---------------------------------------------------------------------------
# The repair of a drafted case
# ---------------------------------------------------------------------------


def normalise_drafted_case(
    slot: TestCaseSlot,
    drafted: Mapping[str, Any],
    context: ProcessContextSchema,
    config: TestCaseGeneratorConfig,
    *,
    origin: OutputOrigin,
) -> DraftedCase:
    """Repair one drafted case against the configured limits.

    Every field is checked; anything unusable is replaced from the template and
    recorded in ``validation_notes``. When neither a title nor a single usable
    step survives, the whole case falls back to the template one - reported, not
    silently accepted as an empty test.
    """
    template = build_template_case(slot, context, config)
    limits = config.generation
    notes: list[str] = []

    title = _clean(drafted.get("title"), limits.max_title_chars)
    steps = _normalise_steps(drafted.get("steps"), limits)

    if not title and not steps:
        template.validation_notes = [
            "The drafted case held neither a usable title nor a usable step, so the "
            "deterministic template built this case instead."
        ]
        return template

    if not title:
        title = template.title
        notes.append("The drafted title was empty; the template title was used.")
    if not steps:
        steps = template.steps
        notes.append("The drafted case had no usable step; the template steps were used.")
    elif len(steps) < limits.min_steps_per_case:
        notes.append(
            f"The draft held {len(steps)} step(s), fewer than the configured minimum of "
            f"{limits.min_steps_per_case}; the template steps were used instead."
        )
        steps = template.steps

    objective = _clean(drafted.get("objective"), limits.max_objective_chars)
    if not objective:
        objective = template.objective
        notes.append("The drafted objective was empty; the template objective was used.")

    preconditions = _clean_list(drafted.get("preconditions"), limits.max_preconditions, 500)
    if not preconditions:
        preconditions = template.preconditions
        notes.append("The draft listed no precondition; the template preconditions were used.")

    test_data = _clean_list(drafted.get("test_data"), limits.max_test_data_items, 500)
    if not test_data:
        test_data = template.test_data
        notes.append("The draft listed no test data; the template test data was used.")

    expected_result = _clean(drafted.get("expected_result"), limits.max_expected_result_chars)
    if not expected_result:
        trailing = next(
            (step.expected_result for step in reversed(steps) if step.expected_result), ""
        )
        expected_result = trailing or template.expected_result
        notes.append(
            "The draft stated no overall expected result; it was taken from the final step."
            if trailing
            else "The draft stated no overall expected result; the template one was used."
        )

    return DraftedCase(
        slot=slot,
        title=title,
        objective=objective,
        preconditions=preconditions,
        test_data=test_data,
        steps=steps,
        expected_result=expected_result,
        comments=_clean(drafted.get("comments"), 2000),
        source=TestCaseSource.AI_GENERATED,
        output_origin=origin,
        validation_notes=notes,
    )


def _normalise_steps(raw: Any, limits: Any) -> list[TestStepSchema]:
    """Clean, cap and **renumber** the drafted steps.

    Renumbering is not cosmetic. A model that returns steps numbered 1, 2, 2, 4
    produces a script a tester cannot follow and an export whose rows do not
    line up. The order the steps arrive in is trusted; the numbers they carry
    are not.
    """
    if isinstance(raw, str):
        raw = [{"action": line} for line in raw.splitlines()]
    if not isinstance(raw, (list, tuple)):
        return []

    steps: list[TestStepSchema] = []
    for entry in raw:
        if isinstance(entry, str):
            entry = {"action": entry}
        if not isinstance(entry, Mapping):
            continue
        action = _clean(entry.get("action") or entry.get("step") or "", limits.max_step_chars)
        if not action:
            continue
        steps.append(
            TestStepSchema(
                step_number=len(steps) + 1,
                action=action,
                test_data=_clean(entry.get("test_data"), limits.max_step_chars) or None,
                expected_result=_clean(entry.get("expected_result"), limits.max_step_chars)
                or None,
            )
        )
        if len(steps) >= limits.max_steps_per_case:
            break
    return steps


def renumber(steps: list[TestStepSchema]) -> list[TestStepSchema]:
    """Return ``steps`` numbered 1..n, whatever numbers they arrived with."""
    return [
        step.model_copy(update={"step_number": index})
        for index, step in enumerate(steps, start=1)
    ]
