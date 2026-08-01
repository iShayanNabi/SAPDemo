"""The deterministic feedback a candidate always gets, and the repair of the
optional drafted feedback.

Two jobs live here, and the split is the same one modules 8 and 9 use:

* :func:`build_template_feedback` writes the complete feedback from the rubric
  result alone - strengths, missing concepts, corrections, an improved sample
  answer assembled from the bank's reference answer, a follow-up question chosen
  for what the candidate actually missed, and the topics to study. This is what
  a candidate gets with no API key, with a provider outage, or with
  ``use_ai=false``, and it is a complete answer rather than a stub.
* :func:`repair_drafted_feedback` takes prose a provider returned - already
  shape-validated at the provider boundary - and repairs its *content* field by
  field against the configured limits, recording every repair. Rejecting a whole
  piece of feedback because the coaching note came back empty is a worse outcome
  than filling that one field from the template and saying so.

The follow-up question is the small piece worth keeping: it is chosen for the
highest-weighted concept the candidate missed, which is why questions in the
bank tag their follow-ups with the concept they chase. A follow-up picked off
the top of a list is a list; a follow-up aimed at the gap is coaching.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.modules.interview_coach.thresholds import InterviewCoachConfig
from app.schemas.common import OutputOrigin
from app.schemas.interview_coach import (
    AnswerFeedbackSchema,
    AnswerScoreSchema,
    BankQuestionSchema,
    ConceptMatchSchema,
    FeedbackSource,
    PerformanceBand,
)

logger = get_logger(__name__)

__all__ = ["build_template_feedback", "choose_follow_up", "repair_drafted_feedback"]


def _missing(score: AnswerScoreSchema) -> list[ConceptMatchSchema]:
    """Return the unmatched concepts, most valuable first."""
    return sorted(
        (match for match in score.concept_matches if not match.matched),
        key=lambda match: (-match.weight, match.concept_id),
    )


def _matched(score: AnswerScoreSchema) -> list[ConceptMatchSchema]:
    """Return the matched concepts, most valuable first."""
    return sorted(
        (match for match in score.concept_matches if match.matched),
        key=lambda match: (-match.weight, match.concept_id),
    )


def choose_follow_up(
    question: BankQuestionSchema, score: AnswerScoreSchema, config: InterviewCoachConfig
) -> str:
    """Pick the follow-up question this answer earned.

    The follow-up that targets the highest-weighted missing concept wins. When
    every concept was covered - or no follow-up targets a missing one - the
    first untargeted follow-up is used, and failing that the configured default.
    """
    follow_ups = question.follow_up_questions
    if not follow_ups:
        return config.feedback.templates.follow_up_default

    missing_ids = [match.concept_id for match in _missing(score)]
    for concept_id in missing_ids:
        for follow_up in follow_ups:
            if follow_up.targets_concept_id == concept_id:
                return follow_up.text

    untargeted = [item for item in follow_ups if not item.targets_concept_id]
    if untargeted:
        return untargeted[0].text
    return follow_ups[0].text


def _improved_answer(
    question: BankQuestionSchema, score: AnswerScoreSchema, config: InterviewCoachConfig
) -> str:
    """Assemble the improved sample answer from the bank's reference answer."""
    templates = config.feedback.templates
    parts = [templates.improved_answer_intro, "", question.reference_answer.strip()]

    missing = _missing(score)[: config.feedback.max_missing_concepts]
    if missing:
        parts.extend(["", templates.improved_answer_missing_intro])
        parts.extend(f"- {match.label}" for match in missing)

    corrections = score.incorrect_statement_matches[: config.feedback.max_incorrect_statements]
    if corrections:
        parts.extend(["", "Corrections:"])
        parts.extend(f"- {item.correction}" for item in corrections)

    text = "\n".join(parts).strip()
    return text[: config.feedback.max_improved_answer_chars]


def _coaching_note(score: AnswerScoreSchema, config: InterviewCoachConfig) -> str:
    """Return the note that frames the result, from the configured wording."""
    templates = config.feedback.templates
    if score.non_answer:
        return templates.coaching_note_non_answer
    if score.passed:
        return templates.coaching_note_pass
    if score.overall_score >= score.pass_score - 15:
        return templates.coaching_note_borderline
    return templates.coaching_note_fail


def _topics_to_study(
    question: BankQuestionSchema, score: AnswerScoreSchema, config: InterviewCoachConfig
) -> list[str]:
    """Return the topics worth studying after this answer.

    An answer that covered everything and said nothing wrong produces an empty
    list. "Study this anyway" after a full-marks answer trains a candidate to
    ignore the study list.
    """
    if not _missing(score) and not score.incorrect_statement_matches and not score.non_answer:
        return []
    topics = [question.topic, *question.study_topics]
    seen: set[str] = set()
    ordered = [
        topic
        for topic in topics
        if topic and not (topic.lower() in seen or seen.add(topic.lower()))
    ]
    return ordered[: config.feedback.max_topics_to_study]


def build_template_feedback(
    question: BankQuestionSchema, score: AnswerScoreSchema, config: InterviewCoachConfig
) -> AnswerFeedbackSchema:
    """Build the complete deterministic feedback for one scored answer."""
    templates = config.feedback.templates
    limits = config.feedback

    strengths: list[str] = [
        templates.strength_concept.format(label=match.label)
        for match in _matched(score)[: limits.max_strengths]
    ]
    clarity_band = next(
        (item.band for item in score.dimensions if item.dimension.value == "clarity"), None
    )
    if not score.non_answer and clarity_band in (
        PerformanceBand.PROFICIENT,
        PerformanceBand.STRONG,
    ):
        strengths.append(templates.strength_clarity)
    if not score.non_answer and score.clarity.length_score >= 100:
        strengths.append(templates.strength_length)
    if not strengths:
        strengths = [templates.strength_none]
    strengths = strengths[: limits.max_strengths]

    missing = [
        templates.missing_concept.format(
            label=match.label,
            hint=f" - {match.study_hint}" if match.study_hint else "",
        )
        for match in _missing(score)[: limits.max_missing_concepts]
    ]
    incorrect = [
        f"{item.label} {item.correction}".strip()
        for item in score.incorrect_statement_matches[: limits.max_incorrect_statements]
    ]

    return AnswerFeedbackSchema(
        strengths=strengths,
        missing_concepts=missing,
        incorrect_statements=incorrect,
        improved_sample_answer=_improved_answer(question, score, config),
        follow_up_question=choose_follow_up(question, score, config),
        topics_to_study=_topics_to_study(question, score, config),
        coaching_note=_coaching_note(score, config)[: limits.max_coaching_note_chars],
        source=FeedbackSource.TEMPLATE,
        output_origin=OutputOrigin.RULE_BASED,
    )


def repair_drafted_feedback(
    draft: dict[str, Any],
    question: BankQuestionSchema,
    score: AnswerScoreSchema,
    config: InterviewCoachConfig,
    *,
    origin: OutputOrigin,
    provider: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
) -> AnswerFeedbackSchema:
    """Repair one drafted piece of feedback field by field.

    The provider is trusted with wording and with nothing else. Every list it
    returns is capped, every string is trimmed, and three fields are *never*
    taken from it at all:

    * the **strengths**, **missing concepts** and **incorrect statements**,
      which are statements of fact about what the rubric found. A model that
      congratulates a candidate on a concept they did not mention is worse than
      no model;
    * the **follow-up question**, which is chosen for the missed concept;
    * every number, which never leaves :mod:`scoring`.

    What the provider may supply is the coaching note, the improved sample
    answer and the topics to study - and each of those falls back to the
    template when it comes back empty or unusably short.
    """
    template = build_template_feedback(question, score, config)
    limits = config.feedback
    notes: list[str] = []

    coaching = str(draft.get("coaching_note") or "").strip()
    if not coaching:
        coaching = template.coaching_note
        notes.append("The drafted coaching note was empty; the template note was used.")
    elif len(coaching) > limits.max_coaching_note_chars:
        coaching = coaching[: limits.max_coaching_note_chars].rstrip()
        notes.append(
            f"The drafted coaching note was trimmed to {limits.max_coaching_note_chars} characters."
        )

    improved = str(draft.get("improved_sample_answer") or "").strip()
    if len(improved) < limits.min_improved_answer_chars:
        improved = template.improved_sample_answer
        notes.append(
            "The drafted sample answer was too short to be useful; the reference answer "
            "from the question bank was used instead."
        )
    elif len(improved) > limits.max_improved_answer_chars:
        improved = improved[: limits.max_improved_answer_chars].rstrip()
        notes.append(
            f"The drafted sample answer was trimmed to "
            f"{limits.max_improved_answer_chars} characters."
        )

    drafted_topics = [
        str(item).strip()[:120]
        for item in (draft.get("topics_to_study") or [])
        if str(item).strip()
    ]
    if not template.topics_to_study:
        # Nothing was missed, so there is nothing to study. A model that invents
        # study topics for a full-marks answer is inventing work.
        topics = []
        if drafted_topics:
            notes.append(
                "The drafted study topics were discarded: this answer covered every "
                "expected concept."
            )
    elif drafted_topics:
        topics = drafted_topics[: limits.max_topics_to_study]
    else:
        topics = template.topics_to_study
        notes.append("No study topics were drafted; the question's own topics were used.")

    return AnswerFeedbackSchema(
        strengths=template.strengths,
        missing_concepts=template.missing_concepts,
        incorrect_statements=template.incorrect_statements,
        improved_sample_answer=improved,
        follow_up_question=template.follow_up_question,
        topics_to_study=topics,
        coaching_note=coaching,
        source=FeedbackSource.AI_GENERATED,
        output_origin=origin,
        ai_provider=provider,
        ai_model=model,
        ai_prompt_version=prompt_version,
        validation_notes=notes,
    )
