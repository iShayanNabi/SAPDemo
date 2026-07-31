"""The optional AI drafting layer for the Test Case Generator.

This is the one module in the lab where the AI output *is* the deliverable
rather than a commentary on one, so the guard rails sit in a different place
than they do elsewhere - but they are just as hard:

* the **plan** reaches the provider already decided (identifiers, types, focus
  areas, priorities). The response is matched back to it by ``slot_id``;
* the response is validated against a Pydantic schema **before** anything is
  saved, and the schema is deliberately permissive about *content* so that one
  badly written step cannot cost the caller the other nineteen test cases -
  content is repaired afterwards, field by field, by ``builder.py``;
* every failure mode ends the same way: the deterministic template fills the
  slot and the problem is reported. A provider outage costs the suite its prose,
  never its test cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.schemas.common import OutputOrigin
from app.services.ai.base import AIProvider, AIRequest
from app.services.ai.factory import get_ai_provider
from app.services.ai.prompts import (
    build_test_case_generation_request,
    build_test_case_regeneration_request,
)

logger = get_logger(__name__)

__all__ = [
    "DraftedTestCasePayload",
    "TestCaseDraftResult",
    "TestCaseDraftingService",
    "TestCaseGenerationPayload",
]


class DraftedStepPayload(BaseModel):
    """One drafted step, as it arrives from a provider."""

    model_config = ConfigDict(extra="ignore")

    step_number: int | None = None
    action: str = ""
    test_data: str | None = None
    expected_result: str | None = None

    @field_validator("action", "test_data", "expected_result", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> Any:
        """Accept a number or a list where a sentence was asked for."""
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            return " ".join(str(item) for item in value)
        return str(value)


class DraftedTestCasePayload(BaseModel):
    """One drafted test case, as it arrives from a provider.

    Permissive on purpose: shape is enforced here, quality is enforced in
    ``builder.normalise_drafted_case``. Rejecting the whole suite because one
    case came back with an empty objective would be a worse outcome than
    repairing that objective from the template and saying so.
    """

    model_config = ConfigDict(extra="ignore")

    slot_id: str = ""
    title: str = ""
    objective: str = ""
    preconditions: list[str] = Field(default_factory=list)
    test_data: list[str] = Field(default_factory=list)
    steps: list[DraftedStepPayload] = Field(default_factory=list)
    expected_result: str = ""
    comments: str = ""

    @field_validator("preconditions", "test_data", mode="before")
    @classmethod
    def _as_string_list(cls, value: Any) -> Any:
        """Accept a paragraph where a list was asked for."""
        if value is None:
            return []
        if isinstance(value, str):
            return [line.strip("-• ") for line in value.splitlines() if line.strip()]
        if isinstance(value, (list, tuple)):
            return [
                (" ".join(str(part) for part in item) if isinstance(item, (list, tuple))
                 else str(item))
                for item in value
                if item is not None
            ]
        return value

    @field_validator("steps", mode="before")
    @classmethod
    def _as_step_list(cls, value: Any) -> Any:
        """Accept plain sentences where step objects were asked for."""
        if value is None:
            return []
        if isinstance(value, str):
            return [{"action": line.strip("-• ")} for line in value.splitlines() if line.strip()]
        if isinstance(value, (list, tuple)):
            return [
                {"action": item} if isinstance(item, str) else item
                for item in value
                if item is not None
            ]
        return value

    @field_validator("slot_id", "title", "objective", "expected_result", "comments", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> Any:
        if value is None:
            return ""
        return value if isinstance(value, str) else str(value)


class TestCaseGenerationPayload(BaseModel):
    """The JSON shape a provider must return, validated before anything is saved."""

    model_config = ConfigDict(extra="ignore")

    test_cases: list[DraftedTestCasePayload] = Field(default_factory=list)


@dataclass
class TestCaseDraftResult:
    """The outcome of asking a provider to draft a set of test cases."""

    #: ``slot_id`` -> the drafted content, ready for the builder to repair.
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Entries the provider returned whose ``slot_id`` matches no planned slot.
    unmatched_slot_ids: list[str] = field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    origin: OutputOrigin | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    error: str | None = None

    @property
    def available(self) -> bool:
        """True when at least one usable draft came back."""
        return bool(self.drafts)


class TestCaseDraftingService:
    """Ask the active provider to draft test cases for planned slots."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_ai_provider()

    def draft_suite(
        self, context: dict[str, Any], slots: list[dict[str, Any]]
    ) -> TestCaseDraftResult:
        """Draft one test case per planned slot."""
        if not slots:
            return TestCaseDraftResult(provider=self.provider.name)
        request = build_test_case_generation_request(context=context, slots=slots)
        return self._run(request, {str(slot["slot_id"]) for slot in slots})

    def redraft_case(
        self,
        context: dict[str, Any],
        slot: dict[str, Any],
        *,
        instruction: str | None = None,
        previous_title: str | None = None,
    ) -> TestCaseDraftResult:
        """Redraft one existing test case, keeping its slot identity."""
        request = build_test_case_regeneration_request(
            context=context,
            slot=slot,
            instruction=instruction,
            previous_title=previous_title,
        )
        return self._run(request, {str(slot["slot_id"])})

    # ------------------------------------------------------------------
    def _run(self, request: AIRequest, known_slot_ids: set[str]) -> TestCaseDraftResult:
        """Run one request, converting every failure into a reported result."""
        try:
            payload, response = self.provider.complete_structured(
                request, TestCaseGenerationPayload
            )
        except AIProviderError as exc:
            logger.warning("Test case drafting unavailable: %s", exc)
            return TestCaseDraftResult(error=str(exc), provider=self.provider.name)
        except Exception as exc:  # noqa: BLE001 - an AI failure never fails a suite
            logger.warning("Test case drafting failed unexpectedly: %s", type(exc).__name__)
            return TestCaseDraftResult(
                error=f"The AI provider failed: {type(exc).__name__}.",
                provider=self.provider.name,
            )

        drafts: dict[str, dict[str, Any]] = {}
        unmatched: list[str] = []
        for index, case in enumerate(payload.test_cases):
            slot_id = case.slot_id.strip()
            # A provider that returns one unlabelled case for a one-slot request
            # is answering correctly, just untidily; accept it. Anything else
            # with no usable slot_id is reported rather than guessed at.
            if not slot_id and len(known_slot_ids) == 1 and index == 0:
                slot_id = next(iter(known_slot_ids))
            if slot_id not in known_slot_ids:
                unmatched.append(slot_id or f"<entry {index + 1} with no slot_id>")
                continue
            if slot_id in drafts:
                unmatched.append(f"{slot_id} (returned more than once)")
                continue
            drafts[slot_id] = case.model_dump()

        if not drafts:
            logger.warning(
                "The provider returned %d case(s), none matching a planned slot",
                len(payload.test_cases),
            )

        return TestCaseDraftResult(
            drafts=drafts,
            unmatched_slot_ids=unmatched,
            provider=response.provider,
            model=response.model,
            origin=response.origin,
            prompt_version=response.prompt_version,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            estimated_cost_usd=response.estimated_cost_usd,
            error=None if drafts else "The AI response contained no usable test case.",
        )


# These are classes about tests, not test suites; pytest would otherwise try to
# collect them whenever a test module imports them.
for _class in (DraftedTestCasePayload, TestCaseGenerationPayload, TestCaseDraftingService):
    _class.__test__ = False
