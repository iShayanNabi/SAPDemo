"""Orchestration and persistence for the SAP Test Case Generator.

This is the only layer that knows about the database. It wires the pure pieces
together in one direction:

    process context -> deterministic plan -> optional AI draft -> repair
    -> persist suite and cases -> read, edit, regenerate, execute, export

Two rules run through everything below, and both exist because a test suite is
a *working document* rather than a report that is generated once:

* **A script edit and an execution record are different operations.** Editing,
  regenerating or duplicating a test case never writes an actual result, a
  pass/fail verdict or an evidence reference, and recording an execution never
  rewrites the script.
* **An identifier points at one test forever.** Numbers are read back out of the
  existing identifiers rather than counted from the row count, so deleting
  ``TC-SIT-002`` leaves a gap instead of handing that name to a different test.
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
from app.models.test_case_generator import TestCase, TestSuite
from app.modules.test_case_generator.builder import build_template_case, renumber
from app.modules.test_case_generator.engine import (
    ENGINE_VERSION,
    build_coverage,
    generate_suite,
    redraft_case,
    summarise_cases,
)
from app.modules.test_case_generator.planning import (
    TestCaseSlot,
    next_identifier,
    read_signals,
)
from app.modules.test_case_generator.thresholds import (
    TestCaseGeneratorConfig,
    get_test_case_config,
)
from app.schemas.common import OutputOrigin
from app.schemas.test_case_generator import (
    TEST_TYPE_ORDER,
    ApproveTestCaseRequest,
    CreateTestCaseRequest,
    DeleteTestCaseResponse,
    ExecutionResult,
    GenerateTestCasesRequest,
    GenerationIssueSchema,
    ProcessContextSchema,
    RecordExecutionRequest,
    RegenerateTestCaseRequest,
    SuiteAiInfoSchema,
    SuiteListItemSchema,
    TestCaseCatalogueSchema,
    TestCaseSampleInfo,
    TestCaseSchema,
    TestCaseSource,
    TestCaseStatus,
    TestPriority,
    TestStepSchema,
    TestSuiteSchema,
    TestType,
    TestTypeInfoSchema,
    TypeCoverageSchema,
    UpdateTestCaseRequest,
)

logger = get_logger(__name__)

SAMPLE_PROCESS_FILE = "sample_test_case_processes.json"
SAMPLE_MANIFEST_FILE = "test_case_scenario_manifest.json"


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex[:32]


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


def generate(db: Session, request: GenerateTestCasesRequest) -> TestSuiteSchema:
    """Generate a suite of test cases and persist it."""
    config = get_test_case_config()

    result = generate_suite(
        request.context,
        request.test_types,
        request.test_case_count,
        config,
        default_owner=request.default_owner,
        use_ai=request.use_ai,
    )
    if not result.cases:
        raise ValidationError(
            "No test case could be planned for this request. Choose at least one test type "
            "and a test-case count of one or more.",
            details={"requested_count": request.test_case_count},
        )

    context = request.context
    suite = TestSuite(
        id=_new_id(),
        name=(request.suite_name or f"{context.business_process} - {context.sap_module}")[:200],
        sap_product=context.sap_product,
        sap_module=context.sap_module,
        business_process=context.business_process,
        process_description=context.process_description,
        preconditions=list(context.preconditions),
        business_rules=list(context.business_rules),
        systems_involved=list(context.systems_involved),
        integrations=list(context.integrations),
        user_roles=list(context.user_roles),
        test_data_requirements=list(context.test_data_requirements),
        requested_test_types=[item.value for item in request.test_types],
        requested_count=request.test_case_count,
        allocation={
            test_type.value: count for test_type, count in result.plan.allocation.items()
        },
        uncovered_test_types=[item.value for item in result.plan.uncovered_types],
        default_owner=request.default_owner or "",
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
    db.add(suite)
    db.flush()

    default_status = _status_from_config(config)
    for case in result.cases:
        db.add(
            TestCase(
                id=_new_id(),
                suite_id=suite.id,
                test_case_id=case.slot.slot_id,
                sequence=case.slot.sequence,
                test_type=case.slot.test_type.value,
                focus=case.slot.focus,
                title=case.title,
                objective=case.objective,
                priority=case.slot.priority.value,
                preconditions=list(case.preconditions),
                test_data=list(case.test_data),
                steps=[step.model_dump() for step in case.steps],
                expected_result=case.expected_result,
                owner=case.slot.owner,
                status=default_status.value,
                comments=case.comments,
                source=case.source.value,
                output_origin=case.output_origin.value,
                ai_provider=result.ai.provider if case.source is TestCaseSource.AI_GENERATED else None,
                ai_prompt_version=(
                    result.ai.prompt_version if case.source is TestCaseSource.AI_GENERATED else None
                ),
                validation_notes=list(case.validation_notes),
            )
        )

    db.commit()
    db.refresh(suite)
    logger.info("Generated suite %s with %d test case(s)", suite.id, len(result.cases))
    return _suite_schema(db, suite, config)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_suite(db: Session, suite_id: str) -> TestSuiteSchema:
    """Return one suite with its test cases."""
    return _suite_schema(db, _require_suite(db, suite_id), get_test_case_config())


def list_suites(
    db: Session, *, limit: int = 20, offset: int = 0
) -> tuple[int, list[SuiteListItemSchema]]:
    """Return suites, newest first."""
    total = int(db.execute(select(func.count(TestSuite.id))).scalar_one())
    rows = (
        db.execute(
            select(TestSuite)
            .order_by(TestSuite.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    items: list[SuiteListItemSchema] = []
    for suite in rows:
        cases = _cases_for(db, suite.id)
        summary = summarise_cases(cases)
        items.append(
            SuiteListItemSchema(
                suite_id=suite.id,
                name=suite.name,
                sap_product=suite.sap_product,
                sap_module=suite.sap_module,
                business_process=suite.business_process,
                test_case_count=summary.test_case_count,
                approved_count=summary.approved_count,
                executed_count=summary.executed_count,
                passed_count=summary.passed_count,
                failed_count=summary.failed_count,
                created_at=suite.created_at,
            )
        )
    return total, items


def get_test_case(db: Session, test_case_id: str) -> TestCaseSchema:
    """Return one test case."""
    return _case_schema(_require_case(db, test_case_id), get_test_case_config())


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def add_test_case(
    db: Session, suite_id: str, request: CreateTestCaseRequest
) -> TestCaseSchema:
    """Add one test case to an existing suite by hand.

    Steps are optional: when none are supplied the configured template steps for
    the chosen test type are used, so an added row is a usable test rather than
    an empty shell somebody has to remember to finish.
    """
    config = get_test_case_config()
    suite = _require_suite(db, suite_id)
    context = _context_from_suite(suite)

    identifier = next_identifier(_identifiers(db, suite.id), request.test_type, config)
    priority = request.priority or _derive_priority(request.test_type, context, config)
    spec = config.spec(request.test_type)
    sequence = _next_sequence(db, suite.id)

    slot = TestCaseSlot(
        slot_id=identifier,
        sequence=sequence,
        test_type=request.test_type,
        test_type_label=spec.label,
        focus=spec.focus_for(_type_count(db, suite.id, request.test_type)),
        priority=priority,
        owner=request.owner or suite.default_owner or spec.default_owner_role,
    )
    template = build_template_case(slot, context, config)

    steps = renumber(list(request.steps)) if request.steps else template.steps
    row = TestCase(
        id=_new_id(),
        suite_id=suite.id,
        test_case_id=identifier,
        sequence=sequence,
        test_type=request.test_type.value,
        focus=slot.focus,
        title=request.title,
        objective=request.objective or template.objective,
        priority=priority.value,
        preconditions=list(request.preconditions) or list(template.preconditions),
        test_data=list(request.test_data) or list(template.test_data),
        steps=[step.model_dump() for step in steps],
        expected_result=request.expected_result or template.expected_result,
        owner=slot.owner,
        status=_status_from_config(config).value,
        comments=request.comments or "",
        source=TestCaseSource.MANUAL.value,
        output_origin=OutputOrigin.RULE_BASED.value,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Added test case %s to suite %s", identifier, suite.id)
    return _case_schema(row, config)


def update_test_case(
    db: Session, test_case_id: str, request: UpdateTestCaseRequest
) -> TestCaseSchema:
    """Apply a partial edit to one test case.

    Only the fields present in the request are written, so a UI that sends one
    changed cell cannot blank the rest of the row.

    Changing the **test type** does two extra things, because the type is part
    of the identifier and part of the priority derivation: the case is given the
    next free identifier of its new type, and its priority is re-derived unless
    the request supplies one. Leaving ``TC-SIT-004`` on a security test would
    make the identifier lie about what the test is.

    Editing the **script** - the type, title, objective, preconditions, test
    data, steps or expected result - clears the approval and returns the case to
    draft, exactly as regenerating does. An approval belongs to the script that
    was read and approved; carrying it across to a rewritten one would leave a
    test case reading "approved by Ingrid" above steps Ingrid never saw.
    Editing only the administrative fields - owner, status, priority, actual
    result, pass/fail, evidence or comments - leaves the approval alone.
    """
    config = get_test_case_config()
    row = _require_case(db, test_case_id)
    provided = request.model_dump(exclude_unset=True)
    if not provided:
        raise ValidationError("The update request contained no field to change.")

    script_fields = {
        "test_type",
        "title",
        "objective",
        "preconditions",
        "test_data",
        "steps",
        "expected_result",
    }
    script_changed = any(
        name in provided and provided[name] is not None for name in script_fields
    )

    if "test_type" in provided and request.test_type is not None:
        new_type = request.test_type
        if new_type.value != row.test_type:
            suite = _require_suite(db, row.suite_id)
            context = _context_from_suite(suite)
            spec = config.spec(new_type)
            row.test_type = new_type.value
            row.test_case_id = next_identifier(
                _identifiers(db, row.suite_id, exclude_id=row.id), new_type, config
            )
            row.focus = row.focus or spec.focus_for(0)
            if request.priority is None:
                row.priority = _derive_priority(new_type, context, config).value

    for name in (
        "title",
        "objective",
        "expected_result",
        "owner",
        "actual_result",
        "evidence_reference",
        "comments",
    ):
        if name in provided and provided[name] is not None:
            setattr(row, name, provided[name])

    if "priority" in provided and request.priority is not None:
        row.priority = request.priority.value
    if "status" in provided and request.status is not None:
        row.status = request.status.value
    if "execution_result" in provided and request.execution_result is not None:
        row.execution_result = request.execution_result.value
    if "preconditions" in provided and request.preconditions is not None:
        row.preconditions = list(request.preconditions)
    if "test_data" in provided and request.test_data is not None:
        row.test_data = list(request.test_data)
    if "steps" in provided and request.steps is not None:
        if not request.steps:
            raise ValidationError(
                "A test case must keep at least one step. Send the steps you want to keep, "
                "or delete the test case."
            )
        row.steps = [step.model_dump() for step in renumber(list(request.steps))]

    if script_changed:
        if row.approved_at is not None:
            row.approved_by = None
            row.approved_at = None
            if request.status is None:
                row.status = _status_from_config(config).value
            logger.info(
                "Cleared the approval on %s: its script was edited after approval",
                row.test_case_id,
            )
        if row.execution_result != ExecutionResult.NOT_RUN.value:
            # The verdict was reached against steps that have just changed. It
            # is kept, because a tester recorded it - but it is flagged, so the
            # suite cannot report a failure against a test nobody can find.
            row.execution_is_stale = True

    db.commit()
    db.refresh(row)
    logger.info("Updated test case %s (%s)", row.test_case_id, row.id)
    return _case_schema(row, config)


def delete_test_case(db: Session, test_case_id: str) -> DeleteTestCaseResponse:
    """Delete one test case and report what the suite lost.

    The response names any test type that had a case before the deletion and has
    none afterwards. Silently dropping a suite's only security test is exactly
    the kind of coverage loss a test lead needs told, not discovered later.
    """
    config = get_test_case_config()
    row = _require_case(db, test_case_id)
    suite_id = row.suite_id
    identifier = row.test_case_id

    before = {case.test_type for case in _cases_for(db, suite_id)}
    db.delete(row)
    db.commit()

    suite = _require_suite(db, suite_id)
    cases = _cases_for(db, suite_id)
    after = {case.test_type for case in cases}
    lost = [item for item in TEST_TYPE_ORDER if item in before and item not in after]

    logger.info("Deleted test case %s from suite %s", identifier, suite_id)
    return DeleteTestCaseResponse(
        deleted=True,
        test_case_id=identifier,
        suite_id=suite_id,
        remaining_count=len(cases),
        summary=summarise_cases(cases),
        coverage=_coverage(suite, cases, config),
        lost_test_types=lost,
    )


def duplicate_test_case(db: Session, test_case_id: str) -> TestCaseSchema:
    """Copy one test case into a new row with its own identifier.

    The script is copied; the execution record and the approval are not. A copy
    of a passed test has not itself passed.
    """
    config = get_test_case_config()
    row = _require_case(db, test_case_id)
    test_type = TestType(row.test_type)
    identifier = next_identifier(_identifiers(db, row.suite_id), test_type, config)

    copy = TestCase(
        id=_new_id(),
        suite_id=row.suite_id,
        test_case_id=identifier,
        sequence=_next_sequence(db, row.suite_id),
        test_type=row.test_type,
        focus=row.focus,
        title=row.title,
        objective=row.objective,
        priority=row.priority,
        preconditions=list(row.preconditions or []),
        test_data=list(row.test_data or []),
        steps=[dict(step) for step in (row.steps or [])],
        expected_result=row.expected_result,
        owner=row.owner,
        status=_status_from_config(config).value,
        comments=f"Duplicated from {row.test_case_id}." + (
            f" {row.comments}" if row.comments else ""
        ),
        source=TestCaseSource.DUPLICATED.value,
        output_origin=row.output_origin,
        execution_is_stale=False,
        ai_provider=row.ai_provider,
        ai_prompt_version=row.ai_prompt_version,
        validation_notes=list(row.validation_notes or []),
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    logger.info("Duplicated %s as %s", row.test_case_id, identifier)
    return _case_schema(copy, config)


def regenerate_test_case(
    db: Session, test_case_id: str, request: RegenerateTestCaseRequest
) -> TestCaseSchema:
    """Redraft one test case's script, keeping its place in the suite.

    The identifier, the sequence and the owner are kept. The **approval is
    always cleared** - an approval belongs to the script that was approved, and
    that script no longer exists. The execution record is kept by default, so a
    tester's recorded result is not lost when somebody improves the wording;
    ``keep_execution_record=false`` clears it deliberately.
    """
    config = get_test_case_config()
    row = _require_case(db, test_case_id)
    suite = _require_suite(db, row.suite_id)
    context = _context_from_suite(suite)

    test_type = request.test_type or TestType(row.test_type)
    spec = config.spec(test_type)
    identifier = row.test_case_id
    if test_type.value != row.test_type:
        identifier = next_identifier(
            _identifiers(db, row.suite_id, exclude_id=row.id), test_type, config
        )

    slot = TestCaseSlot(
        slot_id=identifier,
        sequence=row.sequence,
        test_type=test_type,
        test_type_label=spec.label,
        focus=row.focus or spec.focus_for(0),
        priority=_derive_priority(test_type, context, config),
        owner=row.owner or spec.default_owner_role,
        guidance=spec.guidance,
    )

    case, issues, ai_info = redraft_case(
        slot,
        context,
        config,
        use_ai=request.use_ai,
        instruction=request.instruction,
        previous_title=row.title,
    )

    row.test_case_id = identifier
    row.test_type = test_type.value
    row.focus = slot.focus
    row.title = case.title
    row.objective = case.objective
    row.priority = slot.priority.value
    row.preconditions = list(case.preconditions)
    row.test_data = list(case.test_data)
    row.steps = [step.model_dump() for step in case.steps]
    row.expected_result = case.expected_result
    row.comments = case.comments or row.comments
    row.source = case.source.value
    row.output_origin = case.output_origin.value
    row.ai_provider = ai_info.provider if case.source is TestCaseSource.AI_GENERATED else None
    row.ai_prompt_version = (
        ai_info.prompt_version if case.source is TestCaseSource.AI_GENERATED else None
    )
    row.validation_notes = list(case.validation_notes)
    row.regenerated_count = int(row.regenerated_count or 0) + 1

    # An approval describes a script that has just been replaced.
    row.approved_by = None
    row.approved_at = None
    row.status = _status_from_config(config).value

    if request.keep_execution_record:
        # The kept verdict was reached against the script just replaced.
        row.execution_is_stale = row.execution_result != ExecutionResult.NOT_RUN.value
    else:
        row.actual_result = ""
        row.execution_result = ExecutionResult.NOT_RUN.value
        row.evidence_reference = ""
        row.executed_by = None
        row.executed_at = None
        row.execution_is_stale = False

    _record_issues(suite, issues)
    db.commit()
    db.refresh(row)
    logger.info("Regenerated test case %s (attempt %d)", identifier, row.regenerated_count)
    return _case_schema(row, config)


def approve_test_case(
    db: Session, test_case_id: str, request: ApproveTestCaseRequest
) -> TestCaseSchema:
    """Approve or un-approve one test case."""
    config = get_test_case_config()
    row = _require_case(db, test_case_id)

    if request.approved:
        row.approved_by = request.approved_by
        row.approved_at = _now()
        row.status = TestCaseStatus.APPROVED.value
    else:
        row.approved_by = None
        row.approved_at = None
        row.status = TestCaseStatus.DRAFT.value
    if request.comments:
        row.comments = request.comments

    db.commit()
    db.refresh(row)
    return _case_schema(row, config)


def record_execution(
    db: Session, test_case_id: str, request: RecordExecutionRequest
) -> TestCaseSchema:
    """Record the outcome of running one test case.

    The status follows the verdict deterministically: a blocked run leaves the
    case blocked, anything else marks it executed. Recording an execution never
    touches the script.
    """
    config = get_test_case_config()
    row = _require_case(db, test_case_id)

    row.execution_result = request.execution_result.value
    row.actual_result = request.actual_result
    # This verdict was reached against the script as it stands now.
    row.execution_is_stale = False
    row.executed_by = request.executed_by or row.executed_by
    row.executed_at = request.executed_at or _now()
    if request.evidence_reference is not None:
        row.evidence_reference = request.evidence_reference
    if request.comments is not None:
        row.comments = request.comments

    if request.execution_result is ExecutionResult.BLOCKED:
        row.status = TestCaseStatus.BLOCKED.value
    elif request.execution_result is ExecutionResult.NOT_RUN:
        row.status = (
            TestCaseStatus.APPROVED.value
            if row.approved_at is not None
            else TestCaseStatus.DRAFT.value
        )
        row.executed_at = request.executed_at
        row.executed_by = request.executed_by
    else:
        row.status = TestCaseStatus.EXECUTED.value

    db.commit()
    db.refresh(row)
    logger.info(
        "Recorded execution of %s: %s", row.test_case_id, request.execution_result.value
    )
    return _case_schema(row, config)


# ---------------------------------------------------------------------------
# Catalogue, samples and export payload
# ---------------------------------------------------------------------------


def get_catalogue() -> TestCaseCatalogueSchema:
    """Describe the test types, the limits and the deterministic rules."""
    config = get_test_case_config()
    return TestCaseCatalogueSchema(
        config_version=config.config_version,
        engine_version=ENGINE_VERSION,
        test_types=[
            TestTypeInfoSchema(
                test_type=test_type,
                label=config.spec(test_type).label,
                description=config.spec(test_type).description,
                id_code=config.spec(test_type).id_code,
                default_priority=config.spec(test_type).default_priority,
                default_owner_role=config.spec(test_type).default_owner_role,
                focus_areas=list(config.spec(test_type).focus_areas),
            )
            for test_type in TEST_TYPE_ORDER
        ],
        priorities=list(TestPriority),
        statuses=list(TestCaseStatus),
        execution_results=list(ExecutionResult),
        max_test_cases=config.generation.max_test_cases,
        max_steps_per_case=config.generation.max_steps_per_case,
        id_template=config.generation.id_template,
        priority_rules=config.methodology()["priority_rules"],
        methodology=config.methodology(),
        disclaimer=config.reporting.disclaimer,
    )


def sample_info() -> TestCaseSampleInfo:
    """Describe the bundled fictional process definitions."""
    path = settings.sample_dir / SAMPLE_PROCESS_FILE
    if not path.is_file():
        return TestCaseSampleInfo(available=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    processes = payload.get("processes", [])
    return TestCaseSampleInfo(
        available=True,
        process_count=len(processes),
        processes=[
            {
                "name": item.get("name"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "sap_product": item.get("context", {}).get("sap_product"),
                "sap_module": item.get("context", {}).get("sap_module"),
                "suggested_test_types": item.get("suggested_test_types", []),
                "suggested_test_case_count": item.get("suggested_test_case_count"),
            }
            for item in processes
        ],
        manifest=payload.get("manifest"),
    )


def load_sample_process(name: str) -> dict[str, Any]:
    """Return one bundled fictional process definition."""
    path = settings.sample_dir / SAMPLE_PROCESS_FILE
    if not path.is_file():
        raise NotFoundError(
            "The demo process definitions have not been generated yet. "
            "Run: python scripts/generate_test_case_sample_data.py"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload.get("processes", []):
        if item.get("name") == name:
            return item
    raise NotFoundError(
        "That demo process does not exist.", details={"requested": name}
    )


def build_export_payload(db: Session, suite_id: str) -> dict[str, Any]:
    """Assemble everything the export builders need."""
    config = get_test_case_config()
    suite = _require_suite(db, suite_id)
    schema = _suite_schema(db, suite, config)
    return {
        "suite": schema.model_dump(mode="json", exclude={"test_cases", "coverage", "summary"}),
        "summary": schema.summary.model_dump(mode="json"),
        "coverage": [item.model_dump(mode="json") for item in schema.coverage],
        "test_cases": [item.model_dump(mode="json") for item in schema.test_cases],
        "methodology": config.methodology(),
        "disclaimer": config.reporting.disclaimer,
        "ai_note": config.reporting.ai_note,
        "coverage_note": config.reporting.coverage_note,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _require_suite(db: Session, suite_id: str) -> TestSuite:
    suite = db.get(TestSuite, suite_id)
    if suite is None:
        raise NotFoundError("Test suite not found.", details={"suite_id": suite_id})
    return suite


def _require_case(db: Session, test_case_id: str) -> TestCase:
    """Find a test case by its internal id, or by its identifier if unique.

    Accepting ``TC-SIT-001`` as well as the internal id is a convenience the API
    documents: it is what a person reading an exported report has in front of
    them. It is only honoured when the identifier resolves to exactly one row,
    because the same identifier legitimately exists in every suite.
    """
    row = db.get(TestCase, test_case_id)
    if row is not None:
        return row

    matches = (
        db.execute(select(TestCase).where(TestCase.test_case_id == test_case_id))
        .scalars()
        .all()
    )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValidationError(
            f"'{test_case_id}' identifies a test case in {len(matches)} suites. "
            "Use the test case's own id, which is unique across suites.",
            details={"suite_ids": [item.suite_id for item in matches]},
        )
    raise NotFoundError("Test case not found.", details={"test_case_id": test_case_id})


def _rows_for(db: Session, suite_id: str) -> list[TestCase]:
    return list(
        db.execute(
            select(TestCase)
            .where(TestCase.suite_id == suite_id)
            .order_by(TestCase.sequence, TestCase.test_case_id)
        )
        .scalars()
        .all()
    )


def _cases_for(db: Session, suite_id: str) -> list[TestCaseSchema]:
    config = get_test_case_config()
    return [_case_schema(row, config) for row in _rows_for(db, suite_id)]


def _identifiers(db: Session, suite_id: str, *, exclude_id: str | None = None) -> list[str]:
    return [
        row.test_case_id
        for row in _rows_for(db, suite_id)
        if exclude_id is None or row.id != exclude_id
    ]


def _next_sequence(db: Session, suite_id: str) -> int:
    highest = db.execute(
        select(func.max(TestCase.sequence)).where(TestCase.suite_id == suite_id)
    ).scalar()
    return int(highest or 0) + 1


def _type_count(db: Session, suite_id: str, test_type: TestType) -> int:
    return int(
        db.execute(
            select(func.count(TestCase.id)).where(
                TestCase.suite_id == suite_id, TestCase.test_type == test_type.value
            )
        ).scalar_one()
    )


def _status_from_config(config: TestCaseGeneratorConfig) -> TestCaseStatus:
    """Resolve the configured default status, falling back to ``draft``."""
    try:
        return TestCaseStatus(config.generation.default_status)
    except ValueError:  # pragma: no cover - guarded by config validation in practice
        logger.warning(
            "Unknown default_status '%s' in the configuration; using 'draft'.",
            config.generation.default_status,
        )
        return TestCaseStatus.DRAFT


def _derive_priority(
    test_type: TestType, context: ProcessContextSchema, config: TestCaseGeneratorConfig
) -> TestPriority:
    """Apply the configured priority rules to one test type."""
    signals = read_signals(context, config)
    priority, _reasons = config.priority.derive(
        test_type,
        config.spec(test_type).default_priority,
        keyword_hits=list(signals.keyword_hits),
        integration_count=signals.integration_count,
        role_count=signals.role_count,
    )
    return priority


def _context_from_suite(suite: TestSuite) -> ProcessContextSchema:
    """Rebuild the process context that produced a suite."""
    return ProcessContextSchema(
        sap_product=suite.sap_product,
        sap_module=suite.sap_module,
        business_process=suite.business_process,
        process_description=suite.process_description,
        preconditions=list(suite.preconditions or []),
        business_rules=list(suite.business_rules or []),
        systems_involved=list(suite.systems_involved or []),
        integrations=list(suite.integrations or []),
        user_roles=list(suite.user_roles or []),
        test_data_requirements=list(suite.test_data_requirements or []),
    )


def _record_issues(suite: TestSuite, issues: list[GenerationIssueSchema]) -> None:
    """Append regeneration issues to the suite's record, newest last."""
    if not issues:
        return
    existing = list(suite.generation_issues or [])
    existing.extend(issue.model_dump() for issue in issues)
    suite.generation_issues = existing[-100:]


def _coverage(
    suite: TestSuite, cases: list[TestCaseSchema], config: TestCaseGeneratorConfig
) -> list[TypeCoverageSchema]:
    requested = [TestType(name) for name in (suite.requested_test_types or [])]
    return build_coverage(requested, cases, dict(suite.allocation or {}), config)


def _case_schema(row: TestCase, config: TestCaseGeneratorConfig) -> TestCaseSchema:
    """Validate one stored row back into the API shape.

    The steps are renumbered on the way out as well as on the way in: a row
    written before a numbering fix, or edited directly in the database, still
    presents 1..n to every reader.
    """
    steps = renumber([TestStepSchema.model_validate(step) for step in (row.steps or [])])
    test_type = TestType(row.test_type)
    return TestCaseSchema(
        id=row.id,
        suite_id=row.suite_id,
        test_case_id=row.test_case_id,
        sequence=row.sequence,
        test_type=test_type,
        test_type_label=config.label(test_type),
        title=row.title,
        objective=row.objective or "",
        priority=TestPriority(row.priority),
        preconditions=list(row.preconditions or []),
        test_data=list(row.test_data or []),
        steps=steps,
        expected_result=row.expected_result or "",
        owner=row.owner or "",
        status=TestCaseStatus(row.status),
        actual_result=row.actual_result or "",
        execution_result=ExecutionResult(row.execution_result),
        evidence_reference=row.evidence_reference or "",
        comments=row.comments or "",
        execution_is_stale=bool(row.execution_is_stale),
        source=TestCaseSource(row.source),
        output_origin=OutputOrigin(row.output_origin),
        ai_provider=row.ai_provider,
        ai_prompt_version=row.ai_prompt_version,
        validation_notes=list(row.validation_notes or []),
        regenerated_count=row.regenerated_count or 0,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        executed_by=row.executed_by,
        executed_at=row.executed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _suite_schema(
    db: Session, suite: TestSuite, config: TestCaseGeneratorConfig
) -> TestSuiteSchema:
    cases = _cases_for(db, suite.id)
    summary = summarise_cases(cases)
    # How many cases were *asked* for is a property of the request, not of the
    # rows, so it is filled in here rather than counted: a suite the user has
    # since added rows to must still show what was originally requested.
    summary.requested_count = suite.requested_count
    origin = (
        OutputOrigin(suite.ai_output_origin)
        if suite.ai_output_origin
        else OutputOrigin.RULE_BASED
    )
    return TestSuiteSchema(
        suite_id=suite.id,
        name=suite.name,
        context=_context_from_suite(suite),
        requested_test_types=[TestType(name) for name in (suite.requested_test_types or [])],
        requested_count=suite.requested_count,
        default_owner=suite.default_owner or "",
        summary=summary,
        coverage=_coverage(suite, cases, config),
        uncovered_test_types=[
            TestType(name) for name in (suite.uncovered_test_types or [])
        ],
        test_cases=cases,
        ai=SuiteAiInfoSchema(
            requested=suite.ai_requested,
            used=suite.ai_used,
            provider=suite.ai_provider,
            model=suite.ai_model,
            origin=OutputOrigin(suite.ai_output_origin) if suite.ai_output_origin else None,
            prompt_version=suite.ai_prompt_version,
            input_tokens=suite.ai_input_tokens,
            output_tokens=suite.ai_output_tokens,
            estimated_cost_usd=suite.ai_estimated_cost_usd,
            error=suite.ai_error,
        ),
        generation_issues=[
            GenerationIssueSchema.model_validate(item)
            for item in (suite.generation_issues or [])
        ],
        injection_detected=suite.injection_detected,
        injection_markers=list(suite.injection_markers or []),
        config_version=suite.config_version,
        engine_version=suite.engine_version,
        duration_ms=suite.duration_ms,
        notes=list(suite.notes or []),
        output_origin=origin,
        created_at=suite.created_at,
        updated_at=suite.updated_at,
    )
