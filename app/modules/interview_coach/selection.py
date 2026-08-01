"""Deterministic question selection.

Choosing the questions is the first half of this module's deterministic
skeleton: which questions an interview asks, in which order, at which
difficulties, is decided here from the request, the mode configuration and a
seed - never by a language model, and never by anything that changes between
two runs of the same request.

Three rules do the work, and two of them are borrowed from earlier modules
because they turned out not to be specific to those modules at all:

* **The seed is a hash, not** :func:`hash`. Python salts ``hash()`` per process,
  so a "seeded" shuffle built on it reproduces within one run and never between
  two. Ordering by ``sha256(seed:question_id)`` is stable across processes,
  machines and Python versions, which is what makes a demo repeatable and a
  recorded baseline meaningful.
* **The caller's order is information** (module 8). When fewer questions are
  asked for than tracks are requested, the tracks listed *first* keep their
  questions. Somebody who lists ``sap_integration`` first and asks for three
  questions is telling the coach what the interview is about.
* **A difficulty that yields nothing is relaxed, not dropped.** A track with no
  question at the requested difficulty falls back to its other questions and
  says so in the notes. A four-question interview where five were asked for is
  a worse outcome than one slightly easier question.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from itertools import cycle, islice

from app.core.logging import get_logger
from app.modules.interview_coach.question_bank import QuestionBank
from app.modules.interview_coach.thresholds import InterviewCoachConfig
from app.schemas.interview_coach import (
    BankQuestionSchema,
    InterviewMode,
    InterviewTrack,
    QuestionDifficulty,
)

logger = get_logger(__name__)

__all__ = ["SelectionPlan", "allocate_questions", "plan_questions", "shuffle_key"]


def shuffle_key(seed: int, question_id: str) -> str:
    """Return the stable ordering key for one question under one seed."""
    digest = hashlib.sha256(f"{seed}:{question_id}".encode("utf-8"))
    return digest.hexdigest()


@dataclass
class SelectionPlan:
    """The chosen questions plus everything that had to be relaxed to get them."""

    questions: list[BankQuestionSchema] = field(default_factory=list)
    allocation: dict[InterviewTrack, int] = field(default_factory=dict)
    #: Tracks that were asked for and that no question could be drawn for.
    uncovered_tracks: list[InterviewTrack] = field(default_factory=list)
    effective_difficulties: list[QuestionDifficulty] = field(default_factory=list)
    seed: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def question_count(self) -> int:
        return len(self.questions)


def allocate_questions(
    total: int, tracks: list[InterviewTrack], capacities: dict[InterviewTrack, int]
) -> dict[InterviewTrack, int]:
    """Share ``total`` questions across ``tracks`` in the caller's order.

    Two different questions get two different answers, exactly as in module 8:

    * *Which tracks survive when there are fewer questions than tracks?* The
      order the caller listed them in.
    * *Who gets the remainder when the count does not divide evenly?* The same
      order - there is no project-wide weighting of one SAP track over another,
      so the only honest tie-break is what the caller asked for first.

    A track never receives more questions than it has, and any surplus is
    offered back to the other tracks in caller order.
    """
    eligible = [track for track in tracks if capacities.get(track, 0) > 0]
    if total <= 0 or not eligible:
        return {}

    allocation: dict[InterviewTrack, int] = {track: 0 for track in eligible}
    remaining = total
    # Round-robin in caller order. This handles "fewer questions than tracks"
    # (the first `total` tracks get one each) and the remainder in one loop.
    while remaining > 0:
        progressed = False
        for track in eligible:
            if remaining == 0:
                break
            if allocation[track] >= capacities[track]:
                continue
            allocation[track] += 1
            remaining -= 1
            progressed = True
        if not progressed:
            # Every track is at capacity; the interview is simply shorter.
            break

    return {track: count for track, count in allocation.items() if count > 0}


def _ordered_pool(
    pool: list[BankQuestionSchema], seed: int
) -> list[BankQuestionSchema]:
    """Return the pool in a stable, seed-dependent order."""
    return sorted(pool, key=lambda question: shuffle_key(seed, question.question_id))


def _draw_for_track(
    pool: list[BankQuestionSchema],
    count: int,
    difficulties: list[QuestionDifficulty],
    *,
    used_topics: set[str],
    prefer_distinct_topics: bool,
) -> list[BankQuestionSchema]:
    """Draw ``count`` questions from one track's ordered pool.

    The difficulties are walked as a cycle so a five-question interview across
    three difficulties gets 2/2/1 rather than five of whichever difficulty
    happens to sort first. Within a difficulty, a topic that has not been asked
    about yet wins, so a session does not spend five questions on release
    strategies while never mentioning the rest of the track.
    """
    chosen: list[BankQuestionSchema] = []
    remaining = list(pool)
    wanted = list(islice(cycle(difficulties), count)) if difficulties else [None] * count

    for target in wanted:
        if not remaining:
            break
        candidate = _pick(remaining, target, used_topics, prefer_distinct_topics)
        if candidate is None:
            candidate = remaining[0]
        remaining.remove(candidate)
        used_topics.add(candidate.topic.strip().lower())
        chosen.append(candidate)
    return chosen


def _pick(
    remaining: list[BankQuestionSchema],
    difficulty: QuestionDifficulty | None,
    used_topics: set[str],
    prefer_distinct_topics: bool,
) -> BankQuestionSchema | None:
    """Return the best candidate for one slot, relaxing constraints in order."""
    at_difficulty = (
        [item for item in remaining if item.difficulty is difficulty]
        if difficulty is not None
        else list(remaining)
    )
    if prefer_distinct_topics:
        fresh = [
            item for item in at_difficulty if item.topic.strip().lower() not in used_topics
        ]
        if fresh:
            return fresh[0]
    if at_difficulty:
        return at_difficulty[0]
    if prefer_distinct_topics:
        fresh_any = [
            item for item in remaining if item.topic.strip().lower() not in used_topics
        ]
        if fresh_any:
            return fresh_any[0]
    return remaining[0] if remaining else None


def plan_questions(
    bank: QuestionBank,
    config: InterviewCoachConfig,
    *,
    tracks: list[InterviewTrack],
    mode: InterviewMode,
    difficulties: list[QuestionDifficulty] | None = None,
    question_count: int | None = None,
    topics: list[str] | None = None,
    seed: int | None = None,
) -> SelectionPlan:
    """Choose the questions for one interview session.

    The same arguments always produce the same list, in the same order.
    """
    mode_settings = config.mode(mode)
    effective_seed = seed if seed is not None else config.selection.default_seed
    effective_difficulties = list(difficulties) if difficulties else list(
        mode_settings.difficulty_mix
    )
    total = question_count or mode_settings.default_question_count
    total = max(1, min(total, config.selection.max_questions_per_session))

    notes: list[str] = []
    pools: dict[InterviewTrack, list[BankQuestionSchema]] = {}

    for track in tracks:
        pool = bank.matching(
            tracks=[track],
            mode=mode,
            difficulties=effective_difficulties,
            topics=topics,
        )
        if not pool and config.selection.allow_difficulty_fallback:
            pool = bank.matching(tracks=[track], mode=mode, topics=topics)
            if pool:
                notes.append(
                    f"No {mode_settings.label.lower()} question exists for "
                    f"'{track.value}' at the requested difficulty, so its other "
                    f"questions were used instead."
                )
        if pool:
            pools[track] = _ordered_pool(pool, effective_seed)

    capacities = {track: len(pool) for track, pool in pools.items()}
    allocation = allocate_questions(total, tracks, capacities)

    uncovered = [track for track in tracks if allocation.get(track, 0) == 0]
    if uncovered:
        without_questions = [track for track in uncovered if not capacities.get(track)]
        squeezed = [track for track in uncovered if capacities.get(track)]
        if without_questions:
            notes.append(
                "The question bank has nothing for these tracks in this mode: "
                + ", ".join(track.value for track in without_questions)
                + "."
            )
        if squeezed:
            notes.append(
                f"Only {total} question(s) were asked for, so the tracks listed last "
                "went without one: " + ", ".join(track.value for track in squeezed) + "."
            )

    used_topics: set[str] = set()
    drawn: dict[InterviewTrack, list[BankQuestionSchema]] = {}
    for track in tracks:
        count = allocation.get(track, 0)
        if not count:
            continue
        drawn[track] = _draw_for_track(
            pools[track],
            count,
            effective_difficulties,
            used_topics=used_topics,
            prefer_distinct_topics=config.selection.prefer_distinct_topics,
        )

    # Interleave the tracks in caller order, so a two-track interview alternates
    # rather than asking every MM question before the first Ariba one.
    ordered: list[BankQuestionSchema] = []
    position = 0
    while len(ordered) < sum(len(items) for items in drawn.values()):
        for track in tracks:
            items = drawn.get(track, [])
            if position < len(items):
                ordered.append(items[position])
        position += 1

    if len(ordered) < total:
        notes.append(
            f"{len(ordered)} of the {total} question(s) asked for could be drawn from the "
            "bundled question bank with these filters."
        )

    logger.info(
        "Planned %d question(s) for mode '%s' across %d track(s), seed %d",
        len(ordered),
        mode.value,
        len(allocation),
        effective_seed,
    )
    return SelectionPlan(
        questions=ordered,
        allocation=allocation,
        uncovered_tracks=uncovered,
        effective_difficulties=effective_difficulties,
        seed=effective_seed,
        notes=notes,
    )
