"""Request and response schemas for the SAP Test Case Generator.

These are the module's API contract. A future React or Next.js front end can
build the whole page - the process form, the test-type picker, the editable
test-case table, the step editor, the execution tracker and the export controls
- from these shapes alone.

Three conventions carry through every schema:

* every test case carries an ``output_origin`` and a ``source``, so a reader can
  tell an AI-drafted case (``ai_generated`` / ``mock_ai``) from one the
  deterministic template built (``rule_based``) and from one a person typed
  (``manual``);
* the *plan* - which test types exist, how many cases each gets, what their
  identifiers are and what priority they carry - is computed by ordinary Python
  and is never something the model decides;
* everything a tester later records (status, actual result, pass/fail, evidence,
  comments) lives in its own fields and is never overwritten by a regeneration.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import OutputOrigin


class ExportFormat(str, Enum):
    """Formats a test suite can be downloaded in."""

    XLSX = "xlsx"
    CSV = "csv"
    JSON = "json"
    PDF = "pdf"


class TestType(str, Enum):
    """The eight test types the generator supports.

    The order below is the canonical one: it decides the order slots are laid
    out in, the order the coverage report is printed in and the order the UI
    shows the types in.
    """

    SIT = "sit"
    UAT = "uat"
    NEGATIVE = "negative"
    INTEGRATION = "integration"
    REGRESSION = "regression"
    SECURITY = "security"
    AUTHORIZATION = "authorization"
    DATA_MIGRATION = "data_migration"


#: The canonical order, used everywhere a list of types is produced.
TEST_TYPE_ORDER: tuple[TestType, ...] = tuple(TestType)


class TestPriority(str, Enum):
    """How urgent a test case is, ordered from least to most urgent."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Numeric rank used for sorting and for escalation arithmetic."""
        return {"low": 0, "medium": 1, "high": 2, "critical": 3}[self.value]


class TestCaseStatus(str, Enum):
    """Where a test case sits in its lifecycle."""

    DRAFT = "draft"
    READY = "ready"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    EXECUTED = "executed"
    BLOCKED = "blocked"
    OBSOLETE = "obsolete"


class ExecutionResult(str, Enum):
    """The pass-or-fail outcome of one execution."""

    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TestCaseSource(str, Enum):
    """How a test case came to exist.

    This is deliberately separate from :class:`OutputOrigin`: the origin says
    *what produced the words*, the source says *how the row entered the suite*.
    A duplicated AI case is still ``mock_ai``/``ai_generated`` text, but it was
    not drafted for its own slot.
    """

    AI_GENERATED = "ai_generated"
    #: The deterministic template built it, because AI was off or unusable.
    TEMPLATE = "template"
    #: A person added the row through the API or the UI.
    MANUAL = "manual"
    DUPLICATED = "duplicated"


# ---------------------------------------------------------------------------
# Process input
# ---------------------------------------------------------------------------


class ProcessContextSchema(BaseModel):
    """What the user tells the generator about the process under test.

    Everything here is free text supplied by a person, so it is treated as
    untrusted data: it is injection-filtered before it can reach a provider and
    it is never executed or interpreted as an instruction.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    sap_product: str = Field(
        min_length=2, max_length=120, description="e.g. SAP S/4HANA 2023, SAP ECC 6.0"
    )
    sap_module: str = Field(
        min_length=2, max_length=120, description="e.g. MM, SD, FI, Ariba Buying"
    )
    business_process: str = Field(
        min_length=3, max_length=200, description="e.g. Procure to Pay - Standard PO"
    )
    process_description: str = Field(
        min_length=10,
        max_length=4000,
        description="What the process does, in the tester's own words",
    )
    preconditions: list[str] = Field(default_factory=list, max_length=40)
    business_rules: list[str] = Field(default_factory=list, max_length=40)
    systems_involved: list[str] = Field(default_factory=list, max_length=30)
    integrations: list[str] = Field(default_factory=list, max_length=30)
    user_roles: list[str] = Field(default_factory=list, max_length=30)
    test_data_requirements: list[str] = Field(default_factory=list, max_length=40)

    @field_validator(
        "preconditions",
        "business_rules",
        "systems_involved",
        "integrations",
        "user_roles",
        "test_data_requirements",
        mode="before",
    )
    @classmethod
    def _clean_list(cls, value: Any) -> Any:
        """Accept a newline-separated block as well as a real list.

        The Streamlit form collects these as text areas, and a future web form
        will do the same. Splitting here keeps that convenience out of the UI
        layer, where business logic is not allowed to live.
        """
        if isinstance(value, str):
            value = value.splitlines()
        if isinstance(value, list):
            return [
                str(item).strip()[:500]
                for item in value
                if item is not None and str(item).strip()
            ]
        return value


class GenerateTestCasesRequest(BaseModel):
    """Ask the generator for a suite of test cases."""

    context: ProcessContextSchema
    test_case_count: int = Field(default=8, ge=1, le=50)
    test_types: list[TestType] = Field(
        default_factory=lambda: [TestType.SIT, TestType.UAT, TestType.NEGATIVE],
        min_length=1,
        max_length=len(TEST_TYPE_ORDER),
    )
    suite_name: str | None = Field(default=None, max_length=200)
    default_owner: str | None = Field(default=None, max_length=120)
    #: When false the deterministic templates build every case and no provider
    #: is called at all. The suite is still complete and usable.
    use_ai: bool = True

    @field_validator("test_types")
    @classmethod
    def _dedupe_types(cls, value: list[TestType]) -> list[TestType]:
        """Remove duplicates while keeping **the order the caller asked in**.

        The order is not cosmetic. When the requested case count is smaller than
        the number of requested types, the types listed last are the ones that
        go without a case - so a migration process that lists ``data_migration``
        first keeps its migration tests, whatever the configured weights say.
        """
        seen: set[TestType] = set()
        ordered: list[TestType] = []
        for item in value:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered


class CreateTestCaseRequest(BaseModel):
    """Add one row to an existing suite by hand."""

    model_config = ConfigDict(str_strip_whitespace=True)

    test_type: TestType
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(default="", max_length=2000)
    priority: TestPriority | None = None
    preconditions: list[str] = Field(default_factory=list, max_length=40)
    test_data: list[str] = Field(default_factory=list, max_length=40)
    steps: list[TestStepSchema] = Field(default_factory=list, max_length=60)
    expected_result: str = Field(default="", max_length=2000)
    owner: str | None = Field(default=None, max_length=120)
    comments: str | None = Field(default=None, max_length=2000)


class UpdateTestCaseRequest(BaseModel):
    """Edit one test case. Only the fields present in the request are changed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    test_type: TestType | None = None
    title: str | None = Field(default=None, min_length=3, max_length=200)
    objective: str | None = Field(default=None, max_length=2000)
    priority: TestPriority | None = None
    preconditions: list[str] | None = Field(default=None, max_length=40)
    test_data: list[str] | None = Field(default=None, max_length=40)
    steps: list[TestStepSchema] | None = Field(default=None, max_length=60)
    expected_result: str | None = Field(default=None, max_length=2000)
    owner: str | None = Field(default=None, max_length=120)
    status: TestCaseStatus | None = None
    actual_result: str | None = Field(default=None, max_length=4000)
    execution_result: ExecutionResult | None = None
    evidence_reference: str | None = Field(default=None, max_length=500)
    comments: str | None = Field(default=None, max_length=2000)


class RegenerateTestCaseRequest(BaseModel):
    """Redraft one test case, optionally steering the redraft."""

    model_config = ConfigDict(str_strip_whitespace=True)

    #: Extra direction for the redraft ("focus on the tolerance check").
    instruction: str | None = Field(default=None, max_length=1000)
    test_type: TestType | None = Field(
        default=None, description="Redraft as a different test type"
    )
    use_ai: bool = True
    #: Execution fields (actual result, evidence, comments) are preserved by
    #: default: a redraft of the *script* must not silently erase what a tester
    #: recorded when they ran the old one.
    keep_execution_record: bool = True


class ApproveTestCaseRequest(BaseModel):
    """Approve (or un-approve) one test case."""

    model_config = ConfigDict(str_strip_whitespace=True)

    approved_by: str = Field(min_length=1, max_length=120)
    approved: bool = True
    comments: str | None = Field(default=None, max_length=2000)


class RecordExecutionRequest(BaseModel):
    """Record the outcome of running one test case."""

    model_config = ConfigDict(str_strip_whitespace=True)

    execution_result: ExecutionResult
    actual_result: str = Field(default="", max_length=4000)
    executed_by: str | None = Field(default=None, max_length=120)
    executed_at: datetime | None = None
    evidence_reference: str | None = Field(default=None, max_length=500)
    comments: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# Test case
# ---------------------------------------------------------------------------


class TestStepSchema(BaseModel):
    """One numbered step of a test case.

    ``step_number`` is always renumbered by the engine, so a client can send
    steps in order without maintaining the numbering itself, and a step can
    never claim a position it does not hold.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    step_number: int = Field(default=0, ge=0)
    action: str = Field(min_length=1, max_length=1000)
    test_data: str | None = Field(default=None, max_length=1000)
    expected_result: str | None = Field(default=None, max_length=1000)


class TestCaseSchema(BaseModel):
    """One complete test case, with every field the module is specified around."""

    id: str
    suite_id: str
    test_case_id: str = Field(description="Human-readable identifier, e.g. TC-SIT-001")
    sequence: int

    test_type: TestType
    test_type_label: str = ""
    title: str
    objective: str = ""
    priority: TestPriority = TestPriority.MEDIUM
    preconditions: list[str] = Field(default_factory=list)
    test_data: list[str] = Field(default_factory=list)
    steps: list[TestStepSchema] = Field(default_factory=list)
    expected_result: str = ""

    owner: str = ""
    status: TestCaseStatus = TestCaseStatus.DRAFT
    actual_result: str = ""
    execution_result: ExecutionResult = ExecutionResult.NOT_RUN
    evidence_reference: str = ""
    comments: str = ""
    #: True when the script was edited or redrafted after this result was
    #: recorded: the verdict describes steps that are no longer in the case.
    execution_is_stale: bool = False

    source: TestCaseSource = TestCaseSource.TEMPLATE
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED
    ai_provider: str | None = None
    ai_prompt_version: str | None = None
    #: What the deterministic post-processing had to repair in the drafted text.
    validation_notes: list[str] = Field(default_factory=list)
    regenerated_count: int = 0

    approved_by: str | None = None
    approved_at: datetime | None = None
    executed_by: str | None = None
    executed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


class TypeCoverageSchema(BaseModel):
    """How one requested test type is covered by the generated suite."""

    test_type: TestType
    label: str = ""
    planned: int = 0
    generated: int = 0
    ai_drafted: int = 0
    template_built: int = 0
    manual: int = 0

    @property
    def covered(self) -> bool:
        return self.generated > 0


class SuiteSummarySchema(BaseModel):
    """Counts a dashboard shows without walking the whole test-case list."""

    test_case_count: int = 0
    requested_count: int = 0
    ai_drafted_count: int = 0
    template_built_count: int = 0
    manual_count: int = 0
    step_count: int = 0
    priority_counts: dict[str, int] = Field(default_factory=dict)
    status_counts: dict[str, int] = Field(default_factory=dict)
    execution_counts: dict[str, int] = Field(default_factory=dict)
    approved_count: int = 0
    executed_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    #: Recorded results whose script has since changed. A suite reporting a
    #: failure against steps that no longer exist has to say so.
    stale_execution_count: int = 0
    pass_rate_pct: float | None = None


class GenerationIssueSchema(BaseModel):
    """One thing that went wrong while drafting, reported instead of hidden.

    A drafting failure for a single slot never costs the suite that slot: the
    deterministic template fills it and the problem is recorded here.
    """

    slot_id: str | None = None
    stage: str = Field(description="provider, payload or content")
    message: str
    recovered: bool = True


class SuiteAiInfoSchema(BaseModel):
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


class TestSuiteSchema(BaseModel):
    """A generated test suite with its process context and its test cases."""

    suite_id: str
    name: str
    context: ProcessContextSchema
    requested_test_types: list[TestType] = Field(default_factory=list)
    requested_count: int = 0
    default_owner: str = ""

    summary: SuiteSummarySchema = Field(default_factory=SuiteSummarySchema)
    coverage: list[TypeCoverageSchema] = Field(default_factory=list)
    #: Types the user asked for that no slot could be allocated to, because the
    #: requested case count was smaller than the number of requested types.
    uncovered_test_types: list[TestType] = Field(default_factory=list)
    test_cases: list[TestCaseSchema] = Field(default_factory=list)

    ai: SuiteAiInfoSchema = Field(default_factory=SuiteAiInfoSchema)
    generation_issues: list[GenerationIssueSchema] = Field(default_factory=list)
    injection_detected: bool = False
    injection_markers: list[str] = Field(default_factory=list)

    config_version: str = "0.0.0"
    engine_version: str = "0.0.0"
    duration_ms: int = 0
    notes: list[str] = Field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SuiteListItemSchema(BaseModel):
    """One row of the suite list."""

    suite_id: str
    name: str
    sap_product: str
    sap_module: str
    business_process: str
    test_case_count: int = 0
    approved_count: int = 0
    executed_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    created_at: datetime | None = None


class SuiteListResponse(BaseModel):
    """Paginated suite list."""

    total: int
    limit: int
    offset: int
    suites: list[SuiteListItemSchema] = Field(default_factory=list)


class DeleteTestCaseResponse(BaseModel):
    """What was removed, and what the suite looks like afterwards."""

    deleted: bool = True
    test_case_id: str
    suite_id: str
    remaining_count: int = 0
    summary: SuiteSummarySchema = Field(default_factory=SuiteSummarySchema)
    coverage: list[TypeCoverageSchema] = Field(default_factory=list)
    #: Types that had a case before the deletion and have none now.
    lost_test_types: list[TestType] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


class TestTypeInfoSchema(BaseModel):
    """One supported test type, as the UI should describe it."""

    test_type: TestType
    label: str
    description: str = ""
    id_code: str = ""
    default_priority: TestPriority = TestPriority.MEDIUM
    default_owner_role: str = ""
    focus_areas: list[str] = Field(default_factory=list)


class TestCaseCatalogueSchema(BaseModel):
    """Everything a client needs to render the form and the table."""

    config_version: str
    engine_version: str
    test_types: list[TestTypeInfoSchema] = Field(default_factory=list)
    priorities: list[TestPriority] = Field(default_factory=list)
    statuses: list[TestCaseStatus] = Field(default_factory=list)
    execution_results: list[ExecutionResult] = Field(default_factory=list)
    max_test_cases: int = 50
    max_steps_per_case: int = 20
    id_template: str = ""
    priority_rules: dict[str, Any] = Field(default_factory=dict)
    methodology: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = ""


class TestCaseSampleInfo(BaseModel):
    """Describes the bundled fictional process definitions."""

    available: bool = False
    process_count: int = 0
    processes: list[dict[str, Any]] = Field(default_factory=list)
    manifest: str | None = None


CreateTestCaseRequest.model_rebuild()
UpdateTestCaseRequest.model_rebuild()


# pytest collects any class whose name begins with "Test". These are schemas
# about tests, not test suites, so a test module that imports them would
# otherwise fill the run with collection warnings. The marker below is pytest's
# documented opt-out and costs nothing at runtime.
for _schema in (
    TestType,
    TestPriority,
    TestCaseStatus,
    TestCaseSource,
    TestStepSchema,
    TestCaseSchema,
    TestSuiteSchema,
    TestTypeInfoSchema,
    TestCaseCatalogueSchema,
    TestCaseSampleInfo,
):
    _schema.__test__ = False
