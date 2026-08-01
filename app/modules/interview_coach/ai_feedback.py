"""The optional AI coaching layer for the SAP Interview Coach.

This module sits in a different place from the AI layers in modules 8 and 9.
There, the model's output *was* the deliverable. Here the deliverable is a
**score**, and the score is finished before this file is reached: the rubric has
already decided the overall mark, every dimension, every covered concept, every
missing one and every incorrect statement. What a provider adds is the wording
around that verdict.

That ordering is what makes the guarantee in the module specification true -
*mock mode must produce deterministic scoring for test answers* - without
qualification. Mock mode does, and so does a real model, and so does
``use_ai=false``, because none of them is asked for a number. Only the prose
moves.

Every failure mode ends the same way: the deterministic template writes the
feedback and the problem is reported on the answer. No key, provider down,
non-JSON, wrong shape, empty coaching note, a sample answer two words long -
each of them costs the candidate some prose and never costs them their result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.schemas.common import OutputOrigin
from app.services.ai.base import AIProvider, AIRequest
from app.services.ai.factory import get_ai_provider
from app.services.ai.prompts import build_interview_feedback_request

logger = get_logger(__name__)

__all__ = [
    "InterviewCoachingService",
    "InterviewFeedbackPayload",
    "InterviewFeedbackResult",
]


class InterviewFeedbackPayload(BaseModel):
    """The JSON shape a provider must return, validated before anything is used.

    Permissive on purpose, exactly as in module 8: shape is enforced here and
    quality is enforced by :func:`builder.repair_drafted_feedback`. Rejecting a
    whole piece of feedback because the study-topic list came back as one comma
    separated string would be a worse outcome than splitting it and saying so.
    """

    model_config = ConfigDict(extra="ignore")

    coaching_note: str = ""
    improved_sample_answer: str = ""
    topics_to_study: list[str] = Field(default_factory=list)

    @field_validator("coaching_note", "improved_sample_answer", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return " ".join(str(item) for item in value)
        return value if isinstance(value, str) else str(value)

    @field_validator("topics_to_study", mode="before")
    @classmethod
    def _as_string_list(cls, value: Any) -> Any:
        """Accept a paragraph or a comma separated string where a list was asked for."""
        if value is None:
            return []
        if isinstance(value, str):
            lines = [line.strip("-• ") for line in value.splitlines() if line.strip()]
            if len(lines) == 1 and "," in lines[0]:
                lines = [part.strip() for part in lines[0].split(",") if part.strip()]
            return lines
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if item is not None and str(item).strip()]
        return value


@dataclass
class InterviewFeedbackResult:
    """The outcome of asking a provider for coaching prose."""

    draft: dict[str, Any] | None = None
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
        """True when a usable draft came back."""
        return self.draft is not None


class InterviewCoachingService:
    """Ask the active provider to write feedback around a finished score."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self.provider = provider or get_ai_provider()

    def draft_feedback(
        self,
        question: dict[str, Any],
        rubric_result: dict[str, Any],
        candidate_answer: str,
    ) -> InterviewFeedbackResult:
        """Draft the coaching note, sample answer and study topics for one answer."""
        request = build_interview_feedback_request(
            question=question,
            rubric_result=rubric_result,
            candidate_answer=candidate_answer,
        )
        return self._run(request)

    # ------------------------------------------------------------------
    def _run(self, request: AIRequest) -> InterviewFeedbackResult:
        """Run one request, converting every failure into a reported result."""
        try:
            payload, response = self.provider.complete_structured(
                request, InterviewFeedbackPayload
            )
        except AIProviderError as exc:
            logger.warning("Interview coaching unavailable: %s", exc)
            return InterviewFeedbackResult(error=str(exc), provider=self.provider.name)
        except Exception as exc:  # noqa: BLE001 - an AI failure never fails a score
            logger.warning("Interview coaching failed unexpectedly: %s", type(exc).__name__)
            return InterviewFeedbackResult(
                error=f"The AI provider failed: {type(exc).__name__}.",
                provider=self.provider.name,
            )

        return InterviewFeedbackResult(
            draft=payload.model_dump(),
            provider=response.provider,
            model=response.model,
            origin=response.origin,
            prompt_version=response.prompt_version,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            estimated_cost_usd=response.estimated_cost_usd,
        )
