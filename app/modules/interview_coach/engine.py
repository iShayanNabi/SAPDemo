"""Orchestration for one interview answer.

The engine wires the pure pieces together in one direction and one order, and
the order is the whole point:

    score against the rubric  ->  build the template feedback
                              ->  optionally ask a provider for better prose
                              ->  repair that prose against the same limits

The score is finished before a provider is contacted, and nothing a provider
returns can reach it. That is what lets this module promise the same numbers
with a real model, with the mock and with ``use_ai=false`` - the promise is
structural rather than a matter of prompt wording.

The engine also owns the honest reporting of two things the caller cannot see
for itself: that an answer contained text written as an instruction to an
automated system, and that the clock ran over. Neither changes a score.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.core.security import contains_injection_markers
from app.modules.interview_coach.ai_feedback import (
    InterviewCoachingService,
    InterviewFeedbackResult,
)
from app.modules.interview_coach.builder import (
    build_template_feedback,
    repair_drafted_feedback,
)
from app.modules.interview_coach.scoring import score_answer
from app.modules.interview_coach.thresholds import InterviewCoachConfig
from app.schemas.common import OutputOrigin
from app.schemas.interview_coach import (
    AnswerFeedbackSchema,
    AnswerScoreSchema,
    BankQuestionSchema,
    InterviewMode,
)

logger = get_logger(__name__)

#: Bump when the marking or orchestration behaviour changes. Stored on every
#: session so an old result can always be read against the engine that produced
#: it.
ENGINE_VERSION = "1.0.0"

__all__ = ["ENGINE_VERSION", "AnswerEvaluation", "evaluate_answer", "timing_for"]


@dataclass
class AnswerEvaluation:
    """Everything produced by marking one answer."""

    score: AnswerScoreSchema
    feedback: AnswerFeedbackSchema
    injection_detected: bool = False
    injection_markers: list[str] = field(default_factory=list)
    ai_requested: bool = False
    ai_used: bool = False
    ai_error: str | None = None
    ai_input_tokens: int | None = None
    ai_output_tokens: int | None = None
    ai_estimated_cost_usd: float | None = None
    duration_ms: int = 0


def timing_for(
    seconds_spent: int, time_limit_seconds: int | None
) -> tuple[bool, int]:
    """Return ``(within_time_limit, over_by_seconds)`` for one answer.

    Time is *reported*, never scored. A rubric marks what was said; a stopwatch
    measures something else, and mixing the two would make the same answer worth
    different marks on two different afternoons.
    """
    if time_limit_seconds is None:
        return True, 0
    over = max(0, seconds_spent - time_limit_seconds)
    return over == 0, over


def _rubric_result_payload(score: AnswerScoreSchema) -> dict[str, object]:
    """Describe the finished verdict for the provider, with no room to move it.

    The provider is shown *labels*, never the marking scheme: it learns that a
    concept was missing, not which keywords would have matched it. A model that
    knows the keyword list can write a sample answer that games it.
    """
    return {
        "band": score.overall_band.value,
        "passed": score.passed,
        "non_answer": score.non_answer,
        "covered_concepts": [
            match.label for match in score.concept_matches if match.matched
        ],
        "missing_concepts": [
            match.label for match in score.concept_matches if not match.matched
        ],
        "incorrect_statements": [
            {"label": item.label, "correction": item.correction}
            for item in score.incorrect_statement_matches
        ],
        "dimensions_scored": [
            item.dimension.value for item in score.dimensions if item.applicable
        ],
        "clarity_observations": {
            "word_count": score.clarity.word_count,
            "sentence_count": score.clarity.sentence_count,
            "signposting_markers": score.clarity.structure_markers,
            "filler_phrases_used": score.clarity.filler_hits,
        },
    }


def _question_payload(question: BankQuestionSchema) -> dict[str, object]:
    """Describe the question for the provider."""
    return {
        "question_id": question.question_id,
        "track": question.track.value,
        "topic": question.topic,
        "difficulty": question.difficulty.value,
        "question": question.question,
        "reference_answer": question.reference_answer,
        "study_topics": list(question.study_topics),
    }


def evaluate_answer(
    question: BankQuestionSchema,
    answer_text: str,
    config: InterviewCoachConfig,
    *,
    mode: InterviewMode,
    use_ai: bool = True,
    coaching_service: InterviewCoachingService | None = None,
) -> AnswerEvaluation:
    """Mark one answer and produce its feedback.

    ``use_ai`` only decides who writes the prose. The returned
    :class:`AnswerScoreSchema` is byte-for-byte identical either way.
    """
    started = time.perf_counter()

    score = score_answer(question, answer_text, config, mode=mode)
    feedback = build_template_feedback(question, score, config)

    injection = contains_injection_markers(answer_text)
    markers = ["answer_text"] if injection else []

    draft = InterviewFeedbackResult()
    if use_ai:
        service = coaching_service or InterviewCoachingService()
        draft = service.draft_feedback(
            _question_payload(question), _rubric_result_payload(score), answer_text
        )
        if draft.available and draft.draft is not None:
            feedback = repair_drafted_feedback(
                draft.draft,
                question,
                score,
                config,
                origin=draft.origin or OutputOrigin.AI_GENERATED,
                provider=draft.provider,
                model=draft.model,
                prompt_version=draft.prompt_version,
            )
        else:
            feedback.ai_error = draft.error or "No usable feedback came back from the provider."
            feedback.validation_notes = [
                "The feedback below was written by the deterministic templates because the "
                "AI provider returned nothing usable. The score is unaffected."
            ]

    if injection:
        feedback.validation_notes = [
            *feedback.validation_notes,
            "This answer contained text written as an instruction to an automated system. "
            "It was filtered before any provider was called and was never acted on. The "
            "answer itself was still marked normally.",
        ]

    duration = int((time.perf_counter() - started) * 1000)
    logger.info(
        "Marked %s: %.2f (%s), %d of %d concept(s) covered, feedback by %s",
        question.question_id,
        score.overall_score,
        score.overall_band.value,
        sum(1 for match in score.concept_matches if match.matched),
        len(score.concept_matches),
        feedback.source.value,
    )

    return AnswerEvaluation(
        score=score,
        feedback=feedback,
        injection_detected=injection,
        injection_markers=markers,
        ai_requested=use_ai,
        ai_used=draft.available,
        ai_error=draft.error,
        ai_input_tokens=draft.input_tokens,
        ai_output_tokens=draft.output_tokens,
        ai_estimated_cost_usd=draft.estimated_cost_usd,
        duration_ms=duration,
    )
