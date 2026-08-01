"""The optional AI drafting layer for the Blueprint Generator.

This module and the Test Case Generator are the two places in the lab where the
AI output *is* the deliverable rather than a commentary on one, so the guard
rails sit in a different place than they do elsewhere - but they are just as
hard:

* the **skeleton** reaches the provider already decided (which sections exist,
  what they are called, which facts they already hold, whether they accept
  drafted items at all). The response is matched back to it by ``section_key``;
* the response is validated against a Pydantic schema **before** anything is
  saved, and the schema is deliberately permissive about *content* so that one
  badly written section cannot cost the caller the other twenty-nine - content
  is repaired afterwards, field by field, by ``builder.py``;
* every failure mode ends the same way: the configured template fills the
  section and the problem is reported. A provider outage costs the blueprint its
  prose, never its structure.
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
    BLUEPRINT_SECTIONS_PER_REQUEST,
    build_blueprint_generation_request,
    build_blueprint_section_request,
)

logger = get_logger(__name__)

__all__ = [
    "BlueprintDraftResult",
    "BlueprintDraftingService",
    "BlueprintGenerationPayload",
    "DraftedSectionPayload",
]


class DraftedItemPayload(BaseModel):
    """One drafted item, as it arrives from a provider."""

    model_config = ConfigDict(extra="ignore")

    title: str = ""
    detail: str = ""
    category: str = ""
    reference: str = ""
    owner: str = ""
    rating: str = ""

    @field_validator("title", "detail", "category", "reference", "owner", "rating", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> Any:
        """Accept a number or a list where a sentence was asked for."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            return " ".join(str(item) for item in value)
        return str(value)


class DraftedSectionPayload(BaseModel):
    """One drafted section, as it arrives from a provider.

    Permissive on purpose: shape is enforced here, quality is enforced in
    ``builder.normalise_drafted_section``. Rejecting a whole blueprint because
    one section came back with an empty narrative would be a worse outcome than
    repairing that narrative from the template and saying so.
    """

    model_config = ConfigDict(extra="ignore")

    section_key: str = ""
    narrative: str = ""
    items: list[DraftedItemPayload] = Field(default_factory=list)

    @field_validator("section_key", "narrative", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return "\n".join(str(item) for item in value)
        return value if isinstance(value, str) else str(value)

    @field_validator("items", mode="before")
    @classmethod
    def _as_item_list(cls, value: Any) -> Any:
        """Accept plain sentences where item objects were asked for."""
        if value is None:
            return []
        if isinstance(value, str):
            return [{"title": line.strip("-• ")} for line in value.splitlines() if line.strip()]
        if isinstance(value, (list, tuple)):
            return [
                {"title": item} if isinstance(item, str) else item
                for item in value
                if item is not None
            ]
        return value


class BlueprintGenerationPayload(BaseModel):
    """The JSON shape a provider must return, validated before anything is saved."""

    model_config = ConfigDict(extra="ignore")

    sections: list[DraftedSectionPayload] = Field(default_factory=list)


@dataclass
class BlueprintDraftResult:
    """The outcome of asking a provider to draft a set of blueprint sections."""

    #: ``section_key`` -> the drafted content, ready for the builder to repair.
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Entries the provider returned whose ``section_key`` matches no section.
    unmatched_section_keys: list[str] = field(default_factory=list)
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


class BlueprintDraftingService:
    """Ask the active provider to draft the wording of planned sections."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_ai_provider()

    def draft_blueprint(
        self, project: dict[str, Any], sections: list[dict[str, Any]]
    ) -> BlueprintDraftResult:
        """Draft the wording of every planned section, a batch at a time.

        Thirty sections asked for in one request is a payload large enough to be
        trimmed and a response long enough to be truncated - and both failures
        land on the sections at the *end* of the list, quietly. Batching keeps
        every payload and every response small, and makes the unit of recovery
        one batch: a failed batch costs its own sections their prose and nothing
        else, and the failure is reported.
        """
        if not sections:
            return BlueprintDraftResult(provider=self.provider.name)

        size = max(1, BLUEPRINT_SECTIONS_PER_REQUEST)
        batches = [sections[index : index + size] for index in range(0, len(sections), size)]
        results = [
            self._run(
                build_blueprint_generation_request(project=project, sections=batch),
                {str(section["section_key"]) for section in batch},
            )
            for batch in batches
        ]
        return _merge_results(results, provider=self.provider.name)

    def redraft_section(
        self,
        project: dict[str, Any],
        section: dict[str, Any],
        *,
        instruction: str | None = None,
        previous_narrative: str | None = None,
    ) -> BlueprintDraftResult:
        """Redraft one existing section, keeping its place in the document."""
        request = build_blueprint_section_request(
            project=project,
            section=section,
            instruction=instruction,
            previous_narrative=previous_narrative,
        )
        return self._run(request, {str(section["section_key"])})

    # ------------------------------------------------------------------
    def _run(self, request: AIRequest, known_keys: set[str]) -> BlueprintDraftResult:
        """Run one request, converting every failure into a reported result."""
        try:
            payload, response = self.provider.complete_structured(
                request, BlueprintGenerationPayload
            )
        except AIProviderError as exc:
            logger.warning("Blueprint drafting unavailable: %s", exc)
            return BlueprintDraftResult(error=str(exc), provider=self.provider.name)
        except Exception as exc:  # noqa: BLE001 - an AI failure never fails a blueprint
            logger.warning("Blueprint drafting failed unexpectedly: %s", type(exc).__name__)
            return BlueprintDraftResult(
                error=f"The AI provider failed: {type(exc).__name__}.",
                provider=self.provider.name,
            )

        drafts: dict[str, dict[str, Any]] = {}
        unmatched: list[str] = []
        for index, section in enumerate(payload.sections):
            key = section.section_key.strip()
            # A provider that returns one unlabelled section for a one-section
            # request is answering correctly, just untidily; accept it. Anything
            # else with no usable key is reported rather than guessed at.
            if not key and len(known_keys) == 1 and index == 0:
                key = next(iter(known_keys))
            if key not in known_keys:
                unmatched.append(key or f"<entry {index + 1} with no section_key>")
                continue
            if key in drafts:
                unmatched.append(f"{key} (returned more than once)")
                continue
            drafts[key] = section.model_dump()

        if not drafts:
            logger.warning(
                "The provider returned %d section(s), none matching a planned section",
                len(payload.sections),
            )

        return BlueprintDraftResult(
            drafts=drafts,
            unmatched_section_keys=unmatched,
            provider=response.provider,
            model=response.model,
            origin=response.origin,
            prompt_version=response.prompt_version,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            estimated_cost_usd=response.estimated_cost_usd,
            error=None if drafts else "The AI response contained no usable section.",
        )


def _sum_optional(values: list[int | float | None]) -> int | float | None:
    """Add token or cost figures, returning ``None`` when nothing reported one.

    ``None`` means "the provider did not tell us", which is a different
    statement from zero and must not be reported as one.
    """
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _merge_results(
    results: list[BlueprintDraftResult], *, provider: str
) -> BlueprintDraftResult:
    """Merge the results of several drafting batches into one.

    Token counts and costs are summed across the batches, because a caller
    reading "input_tokens" wants what the blueprint cost, not what its first
    batch cost. The error names how many batches failed, so "three sections came
    back from the template" has a visible reason next to it.
    """
    merged = BlueprintDraftResult(provider=provider)
    errors: list[str] = []

    for result in results:
        for key, draft in result.drafts.items():
            merged.drafts.setdefault(key, draft)
        merged.unmatched_section_keys.extend(result.unmatched_section_keys)
        if result.error:
            errors.append(result.error)
        if result.available and merged.model is None:
            merged.provider = result.provider or provider
            merged.model = result.model
            merged.origin = result.origin
            merged.prompt_version = result.prompt_version

    merged.input_tokens = _sum_optional([result.input_tokens for result in results])
    merged.output_tokens = _sum_optional([result.output_tokens for result in results])
    merged.estimated_cost_usd = _sum_optional(
        [result.estimated_cost_usd for result in results]
    )

    if errors:
        unique = list(dict.fromkeys(errors))
        merged.error = (
            f"{len(errors)} of {len(results)} drafting request(s) failed: "
            + " ".join(unique[:3])
        )
    return merged
