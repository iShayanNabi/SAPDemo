"""Suite generation, coverage and summary arithmetic.

The engine wires the three deterministic pieces together in one direction and
knows nothing about the database:

    plan the slots -> (optionally) draft them -> repair every draft -> summarise

The ordering is the design. Because the plan exists before the provider is
called, a suite generated with no API key has the same identifiers, the same
type coverage and the same priorities as one generated with a real model. Only
the wording differs, and the wording is labelled with where it came from.

Every summary and coverage figure in the module is computed here, including the
ones shown after a user edits or deletes a row - so the number on the dashboard
is produced by the same code whether the suite is one second or one week old.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.core.security import contains_injection_markers
from app.modules.test_case_generator.ai_generator import (
    TestCaseDraftingService,
    TestCaseDraftResult,
)
from app.modules.test_case_generator.builder import (
    DraftedCase,
    build_template_case,
    normalise_drafted_case,
)
from app.modules.test_case_generator.planning import TestCaseSlot, TestPlan, build_plan
from app.modules.test_case_generator.thresholds import TestCaseGeneratorConfig
from app.schemas.common import OutputOrigin
from app.schemas.test_case_generator import (
    TEST_TYPE_ORDER,
    ExecutionResult,
    GenerationIssueSchema,
    ProcessContextSchema,
    SuiteAiInfoSchema,
    SuiteSummarySchema,
    TestCaseSchema,
    TestCaseSource,
    TestCaseStatus,
    TestPriority,
    TestType,
    TypeCoverageSchema,
)

logger = get_logger(__name__)

ENGINE_VERSION = "1.0.0"

__all__ = [
    "ENGINE_VERSION",
    "SuiteGenerationResult",
    "build_coverage",
    "context_payload",
    "generate_suite",
    "redraft_case",
    "summarise_cases",
]


@dataclass
class SuiteGenerationResult:
    """Everything one generation run produced."""

    plan: TestPlan
    cases: list[DraftedCase] = field(default_factory=list)
    issues: list[GenerationIssueSchema] = field(default_factory=list)
    ai: SuiteAiInfoSchema = field(default_factory=SuiteAiInfoSchema)
    injection_detected: bool = False
    injection_markers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    duration_ms: int = 0


def context_payload(context: ProcessContextSchema) -> dict[str, Any]:
    """The process context in the shape the prompt builder expects."""
    return context.model_dump()


# ---------------------------------------------------------------------------
# Injection reporting
# ---------------------------------------------------------------------------

_INJECTION_FIELDS = (
    "business_process",
    "process_description",
    "preconditions",
    "business_rules",
    "systems_involved",
    "integrations",
    "user_roles",
    "test_data_requirements",
)


def detect_injection(context: ProcessContextSchema) -> list[str]:
    """Return the context fields that contain instruction-like text.

    The process description is typed by a person, but it can just as easily be
    pasted out of a document somebody else wrote. It is filtered before it can
    reach a provider; this reports *that it happened*, so a reviewer knows the
    suite was drafted from text that tried to give instructions.
    """
    flagged: list[str] = []
    for name in _INJECTION_FIELDS:
        value = getattr(context, name)
        text = " ".join(value) if isinstance(value, list) else str(value)
        if contains_injection_markers(text):
            flagged.append(name)
    return flagged


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate_suite(
    context: ProcessContextSchema,
    test_types: list[TestType],
    count: int,
    config: TestCaseGeneratorConfig,
    *,
    default_owner: str | None = None,
    use_ai: bool = True,
    drafting_service: TestCaseDraftingService | None = None,
) -> SuiteGenerationResult:
    """Plan, draft and repair a full suite of test cases."""
    started = time.perf_counter()

    plan = build_plan(context, test_types, count, config, default_owner=default_owner)
    markers = detect_injection(context)
    issues: list[GenerationIssueSchema] = []
    ai_info = SuiteAiInfoSchema(requested=use_ai)

    draft_result = TestCaseDraftResult()
    if use_ai and plan.slots:
        service = drafting_service or TestCaseDraftingService()
        draft_result = service.draft_suite(
            context_payload(context), [slot.to_prompt_dict() for slot in plan.slots]
        )
        ai_info = _ai_info(draft_result, requested=True)
        issues.extend(_draft_issues(draft_result))

    cases = [
        _case_for_slot(slot, draft_result, context, config, issues)
        for slot in plan.slots
    ]

    notes = list(plan.notes)
    if markers:
        notes.append(
            "The process context contained text written as an instruction to an automated "
            "system (in: " + ", ".join(markers) + "). It was filtered before drafting and "
            "was never acted on."
        )
    if use_ai and not draft_result.available:
        notes.append(
            "No usable draft came back from the AI provider, so every test case below was "
            "built from the deterministic templates. The suite is complete and usable."
        )

    duration = int((time.perf_counter() - started) * 1000)
    logger.info(
        "Generated %d test case(s) in %d ms (%d drafted, %d from template)",
        len(cases),
        duration,
        sum(1 for case in cases if case.source is TestCaseSource.AI_GENERATED),
        sum(1 for case in cases if case.source is TestCaseSource.TEMPLATE),
    )

    return SuiteGenerationResult(
        plan=plan,
        cases=cases,
        issues=issues,
        ai=ai_info,
        injection_detected=bool(markers),
        injection_markers=markers,
        notes=notes,
        duration_ms=duration,
    )


def redraft_case(
    slot: TestCaseSlot,
    context: ProcessContextSchema,
    config: TestCaseGeneratorConfig,
    *,
    use_ai: bool = True,
    instruction: str | None = None,
    previous_title: str | None = None,
    drafting_service: TestCaseDraftingService | None = None,
) -> tuple[DraftedCase, list[GenerationIssueSchema], SuiteAiInfoSchema]:
    """Redraft one test case, falling back to the template as generation does."""
    issues: list[GenerationIssueSchema] = []
    ai_info = SuiteAiInfoSchema(requested=use_ai)
    draft_result = TestCaseDraftResult()

    if use_ai:
        service = drafting_service or TestCaseDraftingService()
        draft_result = service.redraft_case(
            context_payload(context),
            slot.to_prompt_dict(),
            instruction=instruction,
            previous_title=previous_title,
        )
        ai_info = _ai_info(draft_result, requested=True)
        issues.extend(_draft_issues(draft_result))

    case = _case_for_slot(slot, draft_result, context, config, issues)
    return case, issues, ai_info


def _case_for_slot(
    slot: TestCaseSlot,
    draft_result: TestCaseDraftResult,
    context: ProcessContextSchema,
    config: TestCaseGeneratorConfig,
    issues: list[GenerationIssueSchema],
) -> DraftedCase:
    """Repair the draft for one slot, or build it from the template."""
    drafted = draft_result.drafts.get(slot.slot_id)
    if drafted is None:
        if draft_result.available:
            issues.append(
                GenerationIssueSchema(
                    slot_id=slot.slot_id,
                    stage="payload",
                    message=(
                        "The AI response contained no test case for this slot; the "
                        "deterministic template built it."
                    ),
                )
            )
        return build_template_case(slot, context, config)

    case = normalise_drafted_case(
        slot,
        drafted,
        context,
        config,
        origin=draft_result.origin or OutputOrigin.AI_GENERATED,
    )
    for note in case.validation_notes:
        issues.append(
            GenerationIssueSchema(slot_id=slot.slot_id, stage="content", message=note)
        )
    return case


def _draft_issues(result: TestCaseDraftResult) -> list[GenerationIssueSchema]:
    """Turn provider-level and payload-level problems into reported issues."""
    issues: list[GenerationIssueSchema] = []
    if result.error and not result.available:
        issues.append(
            GenerationIssueSchema(
                stage="provider",
                message=(
                    f"{result.error} Every test case was built from the deterministic "
                    "templates instead."
                ),
            )
        )
    for slot_id in result.unmatched_slot_ids:
        issues.append(
            GenerationIssueSchema(
                slot_id=slot_id,
                stage="payload",
                message=(
                    "The AI response contained a test case that matches no planned slot; "
                    "it was discarded."
                ),
            )
        )
    return issues


def _ai_info(result: TestCaseDraftResult, *, requested: bool) -> SuiteAiInfoSchema:
    """Describe the provider call without ever including a credential."""
    return SuiteAiInfoSchema(
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
# Summary and coverage
# ---------------------------------------------------------------------------


def summarise_cases(cases: list[TestCaseSchema]) -> SuiteSummarySchema:
    """Count a suite: sources, priorities, statuses and execution outcomes."""
    summary = SuiteSummarySchema(test_case_count=len(cases))
    summary.priority_counts = {item.value: 0 for item in TestPriority}
    summary.status_counts = {item.value: 0 for item in TestCaseStatus}
    summary.execution_counts = {item.value: 0 for item in ExecutionResult}

    for case in cases:
        summary.step_count += len(case.steps)
        summary.priority_counts[case.priority.value] += 1
        summary.status_counts[case.status.value] += 1
        summary.execution_counts[case.execution_result.value] += 1
        if case.source is TestCaseSource.AI_GENERATED:
            summary.ai_drafted_count += 1
        elif case.source is TestCaseSource.TEMPLATE:
            summary.template_built_count += 1
        else:
            summary.manual_count += 1
        if case.approved_at is not None:
            summary.approved_count += 1
        if case.execution_is_stale and case.execution_result is not ExecutionResult.NOT_RUN:
            summary.stale_execution_count += 1

    summary.passed_count = summary.execution_counts[ExecutionResult.PASSED.value]
    summary.failed_count = summary.execution_counts[ExecutionResult.FAILED.value]
    summary.executed_count = (
        summary.passed_count
        + summary.failed_count
        + summary.execution_counts[ExecutionResult.BLOCKED.value]
    )
    decided = summary.passed_count + summary.failed_count
    # The pass rate is over *decided* executions only: a blocked test has no
    # verdict, and counting it as a failure would misreport a test that never
    # ran as one that ran and failed.
    summary.pass_rate_pct = (
        round(summary.passed_count * 100 / decided, 1) if decided else None
    )
    return summary


def build_coverage(
    requested_types: list[TestType],
    cases: list[TestCaseSchema],
    planned: dict[str, int] | None = None,
    config: TestCaseGeneratorConfig | None = None,
) -> list[TypeCoverageSchema]:
    """Report how each test type is covered by the suite as it stands now.

    ``planned`` is what the original plan allocated; the counts are what the
    suite holds after any editing. The two are reported side by side so a suite
    that has lost its only security test says so, instead of quietly reporting
    "1 type covered" because a row was deleted.
    """
    planned = planned or {}
    present_types = {case.test_type for case in cases}
    # Requested types first, in the order they were asked for; then anything
    # else the suite has picked up since (a type added by hand), in the
    # canonical order.
    ordered: list[TestType] = []
    for item in list(requested_types) + list(TEST_TYPE_ORDER):
        if item in ordered:
            continue
        if item in requested_types or item in present_types or item.value in planned:
            ordered.append(item)

    coverage: list[TypeCoverageSchema] = []
    for test_type in ordered:
        rows = [case for case in cases if case.test_type is test_type]
        coverage.append(
            TypeCoverageSchema(
                test_type=test_type,
                label=config.label(test_type) if config else test_type.value,
                planned=int(planned.get(test_type.value, 0)),
                generated=len(rows),
                ai_drafted=sum(
                    1 for row in rows if row.source is TestCaseSource.AI_GENERATED
                ),
                template_built=sum(
                    1 for row in rows if row.source is TestCaseSource.TEMPLATE
                ),
                manual=sum(
                    1
                    for row in rows
                    if row.source in (TestCaseSource.MANUAL, TestCaseSource.DUPLICATED)
                ),
            )
        )
    return coverage
