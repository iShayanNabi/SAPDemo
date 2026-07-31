"""The deterministic test plan.

This module answers every question about a suite that a language model must not
be allowed to answer:

* how many test cases each requested type receives;
* what each case is called;
* which aspect of the process it focuses on;
* how urgent it is.

Only after that is settled does anything get drafted. The consequence is worth
stating plainly: run the same request twice, with a model or without one, and
you get the same identifiers, the same type coverage and the same priorities.
Only the prose can differ.

Nothing here touches the database or the AI layer, so the whole plan is testable
on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.schemas.test_case_generator import (
    TEST_TYPE_ORDER,
    ProcessContextSchema,
    TestPriority,
    TestType,
)
from app.modules.test_case_generator.thresholds import TestCaseGeneratorConfig

logger = get_logger(__name__)

__all__ = [
    "ContextSignals",
    "TestCaseSlot",
    "TestPlan",
    "allocate",
    "build_plan",
    "next_identifier",
    "read_signals",
]

#: Matches the numeric tail of an identifier such as ``TC-SIT-007``.
_TRAILING_NUMBER = re.compile(r"(\d+)\s*$")


@dataclass(frozen=True)
class ContextSignals:
    """The facts the priority rules read out of the user's process context."""

    keyword_hits: tuple[str, ...] = ()
    integration_count: int = 0
    role_count: int = 0
    system_count: int = 0
    rule_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "keyword_hits": list(self.keyword_hits),
            "integration_count": self.integration_count,
            "role_count": self.role_count,
            "system_count": self.system_count,
            "rule_count": self.rule_count,
        }


@dataclass(frozen=True)
class TestCaseSlot:
    """One planned test case, before anything has written its words."""

    slot_id: str
    sequence: int
    test_type: TestType
    test_type_label: str
    focus: str
    priority: TestPriority
    owner: str
    guidance: str = ""
    priority_reasons: tuple[str, ...] = ()

    def to_prompt_dict(self) -> dict[str, object]:
        """The compact description of this slot that travels to a provider."""
        return {
            "slot_id": self.slot_id,
            "test_type": self.test_type.value,
            "test_type_label": self.test_type_label,
            "focus": self.focus,
            "priority": self.priority.value,
            "guidance": self.guidance,
        }


@dataclass
class TestPlan:
    """The complete plan for one suite."""

    slots: list[TestCaseSlot] = field(default_factory=list)
    allocation: dict[TestType, int] = field(default_factory=dict)
    #: Requested types that received no slot, because the requested case count
    #: was smaller than the number of requested types. Reported, never hidden.
    uncovered_types: list[TestType] = field(default_factory=list)
    signals: ContextSignals = field(default_factory=ContextSignals)
    notes: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.slots)


def read_signals(
    context: ProcessContextSchema, config: TestCaseGeneratorConfig
) -> ContextSignals:
    """Extract the priority signals from the process context."""
    haystack = " ".join(
        [
            context.business_process,
            context.process_description,
            " ".join(context.business_rules),
        ]
    )
    return ContextSignals(
        keyword_hits=tuple(config.priority.matched_keywords(haystack)),
        integration_count=len(context.integrations),
        role_count=len(context.user_roles),
        system_count=len(context.systems_involved),
        rule_count=len(context.business_rules),
    )


def allocate(
    count: int, test_types: list[TestType], config: TestCaseGeneratorConfig
) -> tuple[dict[TestType, int], list[TestType]]:
    """Share ``count`` cases across ``test_types``.

    Two different questions get two different answers, and both are worth
    stating because they are the ones a user notices:

    * **Which types survive when there are not enough cases to go round?** The
      order the caller listed them in. Their first choice is their first choice;
      a configured weight is a project-wide default and has no business
      overruling it. The types that miss out are returned, never dropped
      silently.
    * **Who gets the remainder when the count does not divide evenly?** The
      configured ``allocation.weights``, heaviest first - that is exactly what
      a project-wide emphasis setting is for.

    Returns:
        ``(allocation, uncovered_types)`` - the allocation keeps the requested
        order, which is the order the suite is laid out in.
    """
    ordered: list[TestType] = []
    for item in test_types:
        if item not in ordered:
            ordered.append(item)
    if not ordered:
        return {}, []

    if count < len(ordered):
        return {item: 1 for item in ordered[:count]}, ordered[count:]

    by_weight = sorted(
        ordered,
        key=lambda item: (-config.allocation.weight_for(item), ordered.index(item)),
    )
    base, remainder = divmod(count, len(ordered))
    allocation = {item: base for item in ordered}
    for index in range(remainder):
        allocation[by_weight[index % len(by_weight)]] += 1
    return allocation, []


def build_plan(
    context: ProcessContextSchema,
    test_types: list[TestType],
    count: int,
    config: TestCaseGeneratorConfig,
    *,
    default_owner: str | None = None,
) -> TestPlan:
    """Build the full deterministic plan for one generation request."""
    capped = min(count, config.generation.max_test_cases)
    notes: list[str] = []
    if capped != count:
        notes.append(
            f"The request asked for {count} test cases; the configured maximum is "
            f"{config.generation.max_test_cases}, so {capped} were planned."
        )

    signals = read_signals(context, config)
    allocation, uncovered = allocate(capped, test_types, config)
    if uncovered:
        notes.append(
            "The requested test-case count is smaller than the number of requested test "
            "types, so these types received no case: "
            + ", ".join(item.value for item in uncovered)
            + ". Raise the count to cover them."
        )

    # The suite is laid out in the order the caller asked for its types, which
    # is the order a test plan document reads in.
    slots: list[TestCaseSlot] = []
    sequence = 0
    for test_type, planned in allocation.items():
        if not planned:
            continue
        spec = config.spec(test_type)
        priority, reasons = config.priority.derive(
            test_type,
            spec.default_priority,
            keyword_hits=list(signals.keyword_hits),
            integration_count=signals.integration_count,
            role_count=signals.role_count,
        )
        owner = default_owner or spec.default_owner_role or config.generation.default_owner
        for index in range(planned):
            sequence += 1
            number = config.generation.id_number_start + index
            slots.append(
                TestCaseSlot(
                    slot_id=config.generation.build_id(spec.id_code.upper(), number),
                    sequence=sequence,
                    test_type=test_type,
                    test_type_label=spec.label,
                    focus=spec.focus_for(index),
                    priority=priority,
                    owner=owner,
                    guidance=spec.guidance,
                    priority_reasons=tuple(reasons),
                )
            )

    logger.info(
        "Planned %d test case(s) across %d type(s)", len(slots), len(allocation)
    )
    return TestPlan(
        slots=slots,
        allocation=allocation,
        uncovered_types=uncovered,
        signals=signals,
        notes=notes,
    )


def next_identifier(
    existing_ids: list[str], test_type: TestType, config: TestCaseGeneratorConfig
) -> str:
    """Return the next free identifier of ``test_type`` for a suite.

    Used when a row is added or duplicated after generation. The number is read
    back out of the existing identifiers rather than counted from the number of
    rows, because deleting ``TC-SIT-002`` must not make the next added case
    reuse that identifier - a test-case identifier that points at two different
    tests over time is worse than a gap in the numbering.
    """
    spec = config.spec(test_type)
    code = spec.id_code.upper()
    highest = config.generation.id_number_start - 1
    for identifier in existing_ids:
        if not identifier:
            continue
        parts = str(identifier).upper().split("-")
        if code not in parts:
            continue
        match = _TRAILING_NUMBER.search(str(identifier))
        if match:
            highest = max(highest, int(match.group(1)))
    return config.generation.build_id(code, highest + 1)
