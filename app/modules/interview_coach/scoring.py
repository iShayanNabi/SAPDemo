"""Deterministic rubric scoring of one interview answer.

This is the module's whole argument. Every number a candidate is shown comes
from here: whether each expected concept was covered, which keyword covered it,
what that is worth on each dimension, what a known-wrong statement costs, how
clear the answer reads, and what all of that adds up to. No provider is involved
and none can be - the scores are identical with a real model, with the mock and
with ``use_ai=false``.

Four decisions are worth reading before changing anything here:

* **Vocabulary is matched case-insensitively; nothing else is.** ``re.IGNORECASE``
  is right for keyword lists and wrong for structure, which is the lesson module
  6 learned the hard way. Matching runs against the *original* text rather than
  a lowercased copy, so every reported excerpt offset is true even when a
  character changes length under ``str.lower()``.
* **A phrase inside a negation is not the phrase.** "The goods receipt does not
  update stock" contains "goods receipt updates stock" as vocabulary and asserts
  its opposite. A keyword hit is vetoed when a configured negation cue precedes
  it *in the same clause* - clause, not sentence, because "we do not use a
  contract, we use a scheduling agreement" should credit the scheduling
  agreement.
* **Clarity is measured from shape, never from vocabulary.** A candidate who
  says all the right things in one unreadable 90-word sentence keeps every
  technical point they earned and loses clarity marks. The four components -
  length, sentence length, signposting, filler - are all in the configuration.
* **A wrong statement costs technical accuracy, and only technical accuracy.**
  Saying something incorrect does not make an answer less complete or less
  clear; it makes it less accurate. Mixing the penalty across dimensions would
  make the same mistake cost different amounts on different questions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from app.core.logging import get_logger
from app.core.rounding import round_half_up
from app.modules.interview_coach.thresholds import (
    ClaritySettings,
    InterviewCoachConfig,
    ScoringSettings,
)
from app.schemas.common import OutputOrigin
from app.schemas.interview_coach import (
    AnswerScoreSchema,
    BankQuestionSchema,
    ClarityBreakdownSchema,
    ConceptDimension,
    ConceptMatchSchema,
    DimensionScoreSchema,
    ExpectedConceptSchema,
    IncorrectStatementMatchSchema,
    InterviewMode,
    ScoreDimension,
)

logger = get_logger(__name__)

__all__ = ["ConceptFinding", "score_answer"]

#: Where one clause ends and the next begins. Punctuation plus the contrastive
#: conjunctions, because "not a contract but a scheduling agreement" is two
#: assertions and only the first one is negated.
_CLAUSE_BOUNDARY = re.compile(
    r"[.!?;:,\n]+|\b(?:but|although|whereas|however|though|nevertheless)\b",
    re.IGNORECASE,
)

_SENTENCE_BOUNDARY = re.compile(r"[.!?]+[\s\"')\]]*|\n{2,}")

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'/&.-]*")


@dataclass
class ConceptFinding:
    """Where a concept was found in an answer, before it becomes a schema."""

    concept: ExpectedConceptSchema
    matched: bool
    keyword: str | None = None
    start: int = -1
    end: int = -1
    negated: bool = False


@lru_cache(maxsize=4096)
def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Compile one keyword phrase into a whitespace-tolerant, bounded pattern.

    Three things the pattern does deliberately:

    * the phrase is **escaped**, so a keyword is always a literal - nobody
      writing a question bank should have to think about regular expression
      syntax;
    * internal whitespace matches any run of whitespace, which is what makes a
      keyword survive a line break. A wrapped answer is still the same answer,
      which is module 6's lesson in a different shape;
    * a trailing ``s`` on the last word is optional, so ``release code`` credits
      "release codes" and ``category manager`` credits "category managers". A
      rubric that marks somebody down for the plural is marking grammar.
    """
    parts = [re.escape(part) for part in phrase.strip().split()]
    if not parts:
        return re.compile(rf"(?<!\w){re.escape(phrase.strip())}(?!\w)", re.IGNORECASE)
    body = r"\s+".join(parts)
    return re.compile(rf"(?<!\w){body}s?(?!\w)", re.IGNORECASE)


@lru_cache(maxsize=512)
def _cue_pattern(cue: str) -> re.Pattern[str]:
    """Compile one negation cue as a bounded, case-insensitive phrase."""
    return _phrase_pattern(cue)


def _clause_spans(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` spans for every clause in ``text``."""
    spans: list[tuple[int, int]] = []
    cursor = 0
    for boundary in _CLAUSE_BOUNDARY.finditer(text):
        if boundary.start() > cursor:
            spans.append((cursor, boundary.start()))
        cursor = boundary.end()
    if cursor < len(text):
        spans.append((cursor, len(text)))
    return spans or [(0, len(text))]


def _clause_for(spans: list[tuple[int, int]], position: int) -> tuple[int, int]:
    """Return the clause span containing ``position``."""
    for start, end in spans:
        if start <= position < end:
            return start, end
    return 0, len(spans[-1]) if spans else 0


def _sentence_for(text: str, position: int) -> str:
    """Return the sentence containing ``position``."""
    start = 0
    for boundary in _SENTENCE_BOUNDARY.finditer(text):
        if boundary.end() > position:
            return text[start : boundary.start()]
        start = boundary.end()
    return text[start:]


def _is_negated(
    text: str,
    spans: list[tuple[int, int]],
    position: int,
    cues: list[str],
    window: int,
) -> bool:
    """Return ``True`` when a negation cue governs the phrase at ``position``.

    Two limits keep this heuristic from doing more harm than good:

    * the cue has to be in the **same clause**, so "we do not use a contract, we
      use a scheduling agreement" still credits the scheduling agreement;
    * the cue has to be within ``window`` words *immediately* before the phrase.
      A cue at the far end of a long clause is usually negating something else -
      "what it does not do is reach the long tail" is a statement about the long
      tail, not a denial of it - and vetoing on that would quietly cost a
      candidate marks for a sentence that says exactly the right thing.

    Where the opposite assertion is a real risk rather than a grammatical
    accident, a concept declares its own ``negation_patterns`` and a question
    declares the wrong statement outright. Those are precise; this is the net
    that catches "the goods receipt does not update stock".
    """
    start, _end = _clause_for(spans, position)
    preceding_words = _WORD.findall(text[start:position])
    if not preceding_words:
        return False
    nearby = " ".join(preceding_words[-window:])
    return any(_cue_pattern(cue).search(nearby) for cue in cues)


def _excerpt(text: str, start: int, end: int, width: int) -> str:
    """Return a short window of the answer around a match."""
    half = max(10, (width - (end - start)) // 2)
    left = max(0, start - half)
    right = min(len(text), end + half)
    snippet = " ".join(text[left:right].split())
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def find_concept(
    concept: ExpectedConceptSchema, answer: str, cues: list[str], window: int = 4
) -> ConceptFinding:
    """Look for one expected concept in an answer.

    A concept is credited when one of its keywords appears outside a negation
    and outside any of its own ``negation_patterns``. When every hit is vetoed
    the finding records ``negated=True``, so the feedback can say "you mentioned
    this, but you said the opposite" rather than "you did not mention this".
    """
    spans = _clause_spans(answer)
    negated_hit = False

    for keyword in concept.keywords:
        for match in _phrase_pattern(keyword).finditer(answer):
            if _is_negated(answer, spans, match.start(), cues, window):
                negated_hit = True
                continue
            if concept.negation_patterns:
                sentence = _sentence_for(answer, match.start())
                if any(
                    _phrase_pattern(pattern).search(sentence)
                    for pattern in concept.negation_patterns
                ):
                    negated_hit = True
                    continue
            return ConceptFinding(
                concept=concept,
                matched=True,
                keyword=keyword,
                start=match.start(),
                end=match.end(),
            )

    return ConceptFinding(concept=concept, matched=False, negated=negated_hit)


def _is_non_answer(answer: str, scoring: ScoringSettings) -> bool:
    """Return ``True`` when the answer is one of the configured non-answers."""
    collapsed = " ".join(answer.split()).strip().lower()
    if not collapsed:
        return True
    return any(
        re.search(pattern, collapsed, re.IGNORECASE) for pattern in scoring.non_answer_patterns
    )


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def _sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_BOUNDARY.split(text)]
    return [part for part in parts if part]


def _count_structure_markers(text: str, markers: list[str]) -> int:
    """Count the configured signposting markers in an answer."""
    found = 0
    for marker in markers:
        if marker and marker[0].isalnum():
            found += len(_phrase_pattern(marker).findall(text))
        else:
            found += text.count(marker)
    return found


def score_clarity(answer: str, clarity: ClaritySettings) -> tuple[float, ClarityBreakdownSchema]:
    """Measure how clearly an answer reads, from its shape alone."""
    words = _words(answer)
    sentences = _sentences(answer)
    word_count = len(words)
    sentence_count = len(sentences)
    average_sentence_words = word_count / sentence_count if sentence_count else float(word_count)

    # -- length ---------------------------------------------------------
    if word_count <= clarity.min_words:
        length_score = 0.0
    elif word_count < clarity.ideal_min_words:
        span = clarity.ideal_min_words - clarity.min_words
        length_score = 100.0 * (word_count - clarity.min_words) / span if span else 100.0
    elif word_count <= clarity.ideal_max_words:
        length_score = 100.0
    elif word_count < clarity.max_words:
        span = clarity.max_words - clarity.ideal_max_words
        length_score = 100.0 * (clarity.max_words - word_count) / span if span else 0.0
    else:
        length_score = 0.0

    # -- sentence length -------------------------------------------------
    if average_sentence_words <= clarity.max_average_sentence_words:
        sentence_score = 100.0
    elif average_sentence_words >= clarity.hard_average_sentence_words:
        sentence_score = 0.0
    else:
        span = clarity.hard_average_sentence_words - clarity.max_average_sentence_words
        sentence_score = 100.0 * (
            clarity.hard_average_sentence_words - average_sentence_words
        ) / span

    # -- signposting -----------------------------------------------------
    markers = _count_structure_markers(answer, clarity.structure_markers)
    reach = min(1.0, markers / clarity.structure_marker_target)
    structure_score = clarity.structure_base_score + reach * (
        100.0 - clarity.structure_base_score
    )

    # -- filler ----------------------------------------------------------
    filler_hits: list[str] = []
    for phrase in clarity.filler_phrases:
        hits = len(_phrase_pattern(phrase).findall(answer))
        filler_hits.extend([phrase] * hits)
    filler_penalty = min(
        len(filler_hits) * clarity.filler_penalty_points, clarity.max_filler_penalty
    )

    weights = clarity.component_weights.normalised()
    combined = (
        length_score * weights["length"]
        + sentence_score * weights["sentences"]
        + structure_score * weights["structure"]
    ) - filler_penalty
    score = max(0.0, min(100.0, combined))

    breakdown = ClarityBreakdownSchema(
        word_count=word_count,
        sentence_count=sentence_count,
        average_sentence_words=round_half_up(average_sentence_words),
        structure_markers=markers,
        filler_hits=sorted(set(filler_hits)),
        length_score=round_half_up(length_score),
        sentence_score=round_half_up(sentence_score),
        structure_score=round_half_up(structure_score),
        filler_penalty=round_half_up(filler_penalty),
    )
    return score, breakdown


def _coverage(findings: list[ConceptFinding]) -> tuple[float | None, int, int]:
    """Return the weighted coverage of a group of concepts, 0-100."""
    if not findings:
        return None, 0, 0
    total = sum(finding.concept.weight for finding in findings)
    matched = sum(finding.concept.weight for finding in findings if finding.matched)
    matched_count = sum(1 for finding in findings if finding.matched)
    if total <= 0:  # pragma: no cover - weights are validated as positive
        return None, len(findings), matched_count
    return 100.0 * matched / total, len(findings), matched_count


def _find_incorrect_statements(
    question: BankQuestionSchema, answer: str, scoring: ScoringSettings
) -> list[IncorrectStatementMatchSchema]:
    """Detect the known-wrong statements this question warns about."""
    matches: list[IncorrectStatementMatchSchema] = []
    for statement in question.incorrect_statements:
        for pattern in statement.patterns:
            hit = _phrase_pattern(pattern).search(answer)
            if hit is None:
                continue
            matches.append(
                IncorrectStatementMatchSchema(
                    statement_id=statement.statement_id,
                    label=statement.label,
                    correction=statement.correction,
                    penalty_points=statement.penalty_points,
                    excerpt=_excerpt(answer, hit.start(), hit.end(), scoring.excerpt_chars),
                )
            )
            break
    return matches


def score_answer(
    question: BankQuestionSchema,
    answer_text: str,
    config: InterviewCoachConfig,
    *,
    mode: InterviewMode,
) -> AnswerScoreSchema:
    """Score one answer against one question's rubric.

    Deterministic in every input: the same question, the same answer text, the
    same mode and the same configuration always produce the same numbers.
    """
    scoring = config.scoring
    answer = answer_text or ""
    notes: list[str] = []

    findings = [
        find_concept(
            concept, answer, scoring.negation_cues, scoring.negation_window_words
        )
        for concept in question.expected_concepts
    ]
    incorrect = _find_incorrect_statements(question, answer, scoring)
    clarity_settings = config.clarity_for(mode)
    clarity_score, clarity_breakdown = score_clarity(answer, clarity_settings)

    non_answer = _is_non_answer(answer, scoring)
    if non_answer:
        notes.append(
            "The answer was recorded as a non-answer, so no concept could be credited. "
            "This is reported rather than scored as a very low answer."
        )
        findings = [
            ConceptFinding(concept=finding.concept, matched=False) for finding in findings
        ]
        clarity_score = 0.0
        incorrect = []

    by_dimension = {
        ConceptDimension.TECHNICAL: [
            f for f in findings if f.concept.dimension is ConceptDimension.TECHNICAL
        ],
        ConceptDimension.BUSINESS: [
            f for f in findings if f.concept.dimension is ConceptDimension.BUSINESS
        ],
        ConceptDimension.ARCHITECTURE: [
            f for f in findings if f.concept.dimension is ConceptDimension.ARCHITECTURE
        ],
    }

    # -- completeness: every concept, minus the required ones that are absent
    completeness, completeness_expected, completeness_matched = _coverage(findings)
    missed_required = [
        finding for finding in findings if finding.concept.required and not finding.matched
    ]
    required_penalty = 0.0
    if completeness is not None and missed_required and not non_answer:
        required_penalty = min(
            len(missed_required) * scoring.required_concept_miss_penalty,
            scoring.max_required_concept_penalty,
        )
        completeness = max(0.0, completeness - required_penalty)
        notes.append(
            f"{len(missed_required)} required concept(s) were missing, costing "
            f"{round_half_up(required_penalty)} completeness points."
        )

    # -- technical accuracy: technical concepts, minus wrong statements
    technical, technical_expected, technical_matched = _coverage(
        by_dimension[ConceptDimension.TECHNICAL]
    )
    incorrect_penalty = min(
        sum(item.penalty_points for item in incorrect),
        scoring.max_incorrect_statement_penalty,
    )
    if technical is not None and incorrect_penalty:
        technical = max(0.0, technical - incorrect_penalty)
        notes.append(
            f"{len(incorrect)} statement(s) known to be incorrect were detected, costing "
            f"{round_half_up(incorrect_penalty)} technical accuracy points."
        )

    business, business_expected, business_matched = _coverage(
        by_dimension[ConceptDimension.BUSINESS]
    )
    architecture, architecture_expected, architecture_matched = _coverage(
        by_dimension[ConceptDimension.ARCHITECTURE]
    )

    raw: dict[ScoreDimension, tuple[float | None, int, int]] = {
        ScoreDimension.TECHNICAL_ACCURACY: (technical, technical_expected, technical_matched),
        ScoreDimension.COMPLETENESS: (
            completeness,
            completeness_expected,
            completeness_matched,
        ),
        ScoreDimension.CLARITY: (clarity_score, 0, 0),
        ScoreDimension.BUSINESS_UNDERSTANDING: (business, business_expected, business_matched),
        ScoreDimension.ARCHITECTURE: (
            architecture,
            architecture_expected,
            architecture_matched,
        ),
    }

    applicable = [dimension for dimension, (score, _e, _m) in raw.items() if score is not None]
    weights = config.weights_for(
        mode, applicable, question_weights=question.rubric.weights or None
    )

    dimensions: list[DimensionScoreSchema] = []
    for dimension in ScoreDimension:
        score, expected_count, matched_count = raw[dimension]
        dimensions.append(
            DimensionScoreSchema(
                dimension=dimension,
                score=round_half_up(score) if score is not None else None,
                weight=round_half_up(weights.get(dimension, 0.0), 4),
                applicable=score is not None,
                band=scoring.band_for(score),
                explanation=_explain(
                    dimension,
                    score,
                    expected_count,
                    matched_count,
                    clarity_breakdown,
                    incorrect_penalty,
                    required_penalty,
                ),
                concepts_expected=expected_count,
                concepts_matched=matched_count,
            )
        )

    overall = sum(
        (raw[dimension][0] or 0.0) * weight for dimension, weight in weights.items()
    )
    overall_score = round_half_up(max(0.0, min(100.0, overall)))
    pass_score = (
        question.rubric.pass_score
        if question.rubric.pass_score is not None
        else scoring.pass_score
    )

    matches = [
        ConceptMatchSchema(
            concept_id=finding.concept.concept_id,
            label=finding.concept.label,
            dimension=finding.concept.dimension,
            weight=finding.concept.weight,
            required=finding.concept.required,
            matched=finding.matched,
            matched_keyword=finding.keyword,
            excerpt=(
                _excerpt(answer, finding.start, finding.end, scoring.excerpt_chars)
                if finding.matched
                else None
            ),
            negated=finding.negated,
            study_hint=finding.concept.study_hint,
        )
        for finding in findings
    ]
    if any(match.negated and not match.matched for match in matches):
        notes.append(
            "One or more expected concepts were mentioned inside a negation, so they were "
            "not credited. Check whether you meant to say the opposite."
        )

    return AnswerScoreSchema(
        overall_score=overall_score,
        overall_band=scoring.band_for(overall_score) or scoring.band_for(0.0),
        passed=overall_score >= pass_score,
        pass_score=round_half_up(pass_score),
        dimensions=dimensions,
        concept_matches=matches,
        incorrect_statement_matches=incorrect,
        clarity=clarity_breakdown,
        non_answer=non_answer,
        scoring_notes=notes,
        output_origin=OutputOrigin.RULE_BASED,
    )


def _explain(
    dimension: ScoreDimension,
    score: float | None,
    expected: int,
    matched: int,
    clarity: ClarityBreakdownSchema,
    incorrect_penalty: float,
    required_penalty: float,
) -> str:
    """Return one sentence a candidate can check the dimension score against."""
    if score is None:
        return (
            "This question carries no concept for this dimension, so it is not scored. "
            "A blank is reported rather than a zero."
        )
    if dimension is ScoreDimension.CLARITY:
        return (
            f"{clarity.word_count} words in {clarity.sentence_count} sentence(s), "
            f"averaging {clarity.average_sentence_words} words, with "
            f"{clarity.structure_markers} signposting marker(s)"
            + (f" and a {clarity.filler_penalty} point filler penalty" if clarity.filler_penalty else "")
            + "."
        )
    base = f"{matched} of {expected} expected concept(s) covered."
    if dimension is ScoreDimension.TECHNICAL_ACCURACY and incorrect_penalty:
        base += f" {round_half_up(incorrect_penalty)} points deducted for incorrect statements."
    if dimension is ScoreDimension.COMPLETENESS and required_penalty:
        base += f" {round_half_up(required_penalty)} points deducted for missing required concepts."
    return base
