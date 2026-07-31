"""Typed, validated access to the Test Case Generator configuration.

Every value the generator decides for itself - the identifier scheme, how many
cases each test type receives, the base priority of a type, the escalation
rules, the size limits and the templates a test case falls back to - lives in
``config/test_case_rules.json`` and is validated here at load time.

That separation is what makes this module honest about the deterministic/AI
boundary. A language model may write the *prose* of a test case; it never
decides how many cases exist, what they are called, which type they belong to
or how urgent they are. Those come from this file, so "add a test type focus"
or "make security tests critical" is a JSON edit, not a code change.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.schemas.test_case_generator import TEST_TYPE_ORDER, TestPriority, TestType

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "test_case_rules.json"

#: Priority levels ordered from least to most urgent, used for escalation.
PRIORITY_LADDER: tuple[TestPriority, ...] = (
    TestPriority.LOW,
    TestPriority.MEDIUM,
    TestPriority.HIGH,
    TestPriority.CRITICAL,
)


class PlaceholderDefaults(BaseModel):
    """What a template placeholder becomes when the user supplied nothing.

    A template that renders ``Log on as {role}`` when no role was entered must
    not print ``Log on as`` - a test step with a hole in it is worse than a
    generic one, because a tester cannot tell whether something was lost.
    """

    role: str = "the assigned business user"
    primary_system: str = "the SAP test client"
    integration: str = "the connected external system"
    test_data_requirement: str = "the test data recorded for this suite"


class GenerationSettings(BaseModel):
    """Identifier scheme, size limits and the defaults a new case starts from."""

    description: str = ""
    id_prefix: str = Field(default="TC", min_length=1, max_length=10)
    id_template: str = "{prefix}-{code}-{number:03d}"
    id_number_start: int = Field(default=1, ge=0)
    max_test_cases: int = Field(default=50, ge=1, le=200)
    default_test_case_count: int = Field(default=8, ge=1)
    min_steps_per_case: int = Field(default=3, ge=1)
    max_steps_per_case: int = Field(default=20, ge=1)
    max_preconditions: int = Field(default=12, ge=1)
    max_test_data_items: int = Field(default=12, ge=1)
    max_title_chars: int = Field(default=200, ge=20)
    max_objective_chars: int = Field(default=2000, ge=20)
    max_step_chars: int = Field(default=1000, ge=20)
    max_expected_result_chars: int = Field(default=2000, ge=20)
    default_owner: str = "Unassigned"
    default_status: str = "draft"
    placeholder_defaults: PlaceholderDefaults = Field(default_factory=PlaceholderDefaults)

    def model_post_init(self, _context: object) -> None:
        if self.min_steps_per_case > self.max_steps_per_case:
            raise ValueError(
                "generation.min_steps_per_case is greater than generation.max_steps_per_case"
            )
        if self.default_test_case_count > self.max_test_cases:
            raise ValueError(
                "generation.default_test_case_count exceeds generation.max_test_cases"
            )
        try:
            self.id_template.format(prefix="TC", code="SIT", number=1)
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(
                f"generation.id_template is not a usable format string: {exc}"
            ) from exc

    def build_id(self, code: str, number: int) -> str:
        """Render one human-readable test-case identifier."""
        return self.id_template.format(prefix=self.id_prefix, code=code, number=number)


class AllocationSettings(BaseModel):
    """How the requested case count is shared out across the requested types."""

    description: str = ""
    weights: dict[str, float] = Field(default_factory=dict)

    def model_post_init(self, _context: object) -> None:
        known = {item.value for item in TEST_TYPE_ORDER}
        unknown = sorted(set(self.weights) - known)
        if unknown:
            raise ValueError(f"allocation.weights names unknown test types: {unknown}")
        for name, weight in self.weights.items():
            if weight <= 0:
                raise ValueError(f"allocation.weights['{name}'] must be greater than zero")

    def weight_for(self, test_type: TestType) -> float:
        """Return the allocation weight of one test type (default 1.0)."""
        return float(self.weights.get(test_type.value, 1.0))


class PrioritySettings(BaseModel):
    """The documented, deterministic priority rules.

    Priority is derived from the test type plus signals the *user* supplied in
    the process context. It is never asked of a language model, because a
    priority that changes between two runs of the same input is not a priority.
    """

    description: str = ""
    default: TestPriority = TestPriority.MEDIUM
    max_escalation_steps: int = Field(default=1, ge=0, le=3)
    escalate_keywords: list[str] = Field(default_factory=list)
    escalate_keyword_types: list[TestType] = Field(default_factory=list)
    integration_escalation_threshold: int = Field(default=3, ge=0)
    integration_escalation_types: list[TestType] = Field(default_factory=list)
    role_escalation_threshold: int = Field(default=4, ge=0)
    role_escalation_types: list[TestType] = Field(default_factory=list)

    def matched_keywords(self, text: str) -> list[str]:
        """Return the configured escalation keywords present in ``text``."""
        lowered = (text or "").lower()
        return [keyword for keyword in self.escalate_keywords if keyword.lower() in lowered]

    def derive(
        self,
        test_type: TestType,
        base: TestPriority,
        *,
        keyword_hits: list[str],
        integration_count: int,
        role_count: int,
    ) -> tuple[TestPriority, list[str]]:
        """Return the derived priority and the reasons it was raised.

        Escalation is capped at ``max_escalation_steps`` levels no matter how
        many signals fire, so a description mentioning both "payment" and
        "audit" does not push a medium test straight to critical.
        """
        reasons: list[str] = []
        steps = 0

        if keyword_hits and test_type in self.escalate_keyword_types:
            steps += 1
            reasons.append(
                "the process description mentions "
                + ", ".join(sorted(set(keyword_hits))[:3])
            )
        if (
            test_type in self.integration_escalation_types
            and self.integration_escalation_threshold
            and integration_count >= self.integration_escalation_threshold
        ):
            steps += 1
            reasons.append(f"{integration_count} integrations are involved")
        if (
            test_type in self.role_escalation_types
            and self.role_escalation_threshold
            and role_count >= self.role_escalation_threshold
        ):
            steps += 1
            reasons.append(f"{role_count} user roles are involved")

        if not steps:
            return base, []

        steps = min(steps, self.max_escalation_steps)
        if steps == 0:
            return base, []
        index = min(PRIORITY_LADDER.index(base) + steps, len(PRIORITY_LADDER) - 1)
        raised = PRIORITY_LADDER[index]
        if raised is base:
            return base, []
        return raised, reasons


class StepTemplate(BaseModel):
    """One template step used when no model drafted the case."""

    action: str = Field(min_length=3)
    expected_result: str = ""
    test_data: str | None = None


class TestTypeSpec(BaseModel):
    """One test type: how it is labelled, prioritised and templated."""

    label: str = Field(min_length=2, max_length=80)
    id_code: str = Field(min_length=2, max_length=8)
    description: str = ""
    default_priority: TestPriority = TestPriority.MEDIUM
    default_owner_role: str = ""
    guidance: str = ""
    focus_areas: list[str] = Field(min_length=1)
    objective_template: str = Field(min_length=5)
    precondition_templates: list[str] = Field(default_factory=list)
    test_data_templates: list[str] = Field(default_factory=list)
    step_templates: list[StepTemplate] = Field(min_length=1)
    expected_result_template: str = Field(min_length=5)

    def focus_for(self, index: int) -> str:
        """Return the focus area for the ``index``-th case of this type.

        Rotating through the configured focus areas is what stops a suite of
        five SIT cases from being five copies of the same test.
        """
        return self.focus_areas[index % len(self.focus_areas)]


class ReportingSettings(BaseModel):
    """The standing disclaimers printed on every export."""

    disclaimer: str = ""
    ai_note: str = ""
    coverage_note: str = ""


class TestCaseGeneratorConfig(BaseModel):
    """The complete, validated Test Case Generator configuration."""

    config_version: str
    description: str = ""
    generation: GenerationSettings = Field(default_factory=GenerationSettings)
    allocation: AllocationSettings = Field(default_factory=AllocationSettings)
    priority: PrioritySettings = Field(default_factory=PrioritySettings)
    test_types: dict[str, TestTypeSpec]
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)

    def model_post_init(self, _context: object) -> None:
        expected = [item.value for item in TEST_TYPE_ORDER]
        missing = [name for name in expected if name not in self.test_types]
        if missing:
            raise ValueError(f"configuration is missing test types: {missing}")
        unknown = [name for name in self.test_types if name not in expected]
        if unknown:
            raise ValueError(
                f"configuration declares test types the engine does not know: {unknown}. "
                f"Add them to TestType in app/schemas/test_case_generator.py first."
            )
        codes = {name: spec.id_code.upper() for name, spec in self.test_types.items()}
        if len(set(codes.values())) != len(codes):
            raise ValueError(
                f"two test types share an id_code, which would collide in the identifiers: {codes}"
            )

    # -- helpers ---------------------------------------------------------
    def spec(self, test_type: TestType | str) -> TestTypeSpec:
        """Return one test type specification."""
        name = test_type.value if isinstance(test_type, TestType) else str(test_type)
        if name not in self.test_types:
            raise ConfigurationError(f"Unknown test type: {name}")
        return self.test_types[name]

    def label(self, test_type: TestType | str) -> str:
        """Return the human label of a test type."""
        return self.spec(test_type).label

    def methodology(self) -> dict[str, Any]:
        """Describe, in plain language, how a suite is produced."""
        return {
            "deterministic": [
                "How many test cases each requested type receives (allocation weights).",
                "The test-case identifiers and their numbering.",
                "The priority of each case (test-type base priority plus the escalation rules).",
                "The step numbering, the size limits and every field length check.",
                "Every status, approval and execution record.",
                "The fallback test case used whenever a drafted one is unusable.",
            ],
            "ai_generated": [
                "The title, objective, preconditions, test data, step wording and expected "
                "result of each drafted case.",
            ],
            "allocation_weights": dict(self.allocation.weights),
            "priority_rules": {
                "default": self.priority.default.value,
                "base_by_test_type": {
                    name: spec.default_priority.value
                    for name, spec in self.test_types.items()
                },
                "max_escalation_steps": self.priority.max_escalation_steps,
                "escalate_keywords": list(self.priority.escalate_keywords),
                "escalate_keyword_types": [
                    item.value for item in self.priority.escalate_keyword_types
                ],
                "integration_escalation_threshold": self.priority.integration_escalation_threshold,
                "role_escalation_threshold": self.priority.role_escalation_threshold,
            },
            "identifier_template": self.generation.id_template,
            "coverage_note": self.reporting.coverage_note,
        }


def load_test_case_config(path: Path | str | None = None) -> TestCaseGeneratorConfig:
    """Load and validate the Test Case Generator configuration from ``path``."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigurationError(
            f"Test Case Generator configuration file is missing: {config_path.name}"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Test Case Generator configuration is not valid JSON: {exc.msg} (line {exc.lineno})"
        ) from exc
    try:
        config = TestCaseGeneratorConfig.model_validate(raw)
    except PydanticValidationError as exc:
        raise ConfigurationError(
            f"Test Case Generator configuration failed validation: {exc.error_count()} problem(s).",
            details={"errors": exc.errors(include_url=False)[:10]},
        ) from exc

    logger.info(
        "Loaded test case generator configuration v%s (%d test types)",
        config.config_version,
        len(config.test_types),
    )
    return config


@lru_cache(maxsize=1)
def get_test_case_config() -> TestCaseGeneratorConfig:
    """Return the cached default configuration."""
    return load_test_case_config()
