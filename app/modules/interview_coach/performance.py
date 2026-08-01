"""Session summaries and the performance dashboard.

Everything here is arithmetic over recorded answers. No provider is involved,
and the study plan in particular is derived from the data rather than written:
the topics it names are the topics with the lowest recorded averages, and the
concepts it tells somebody to focus on are the concepts those answers actually
missed, counted.

Three rules run through the aggregation:

* **Averages are computed with the decimal helpers.** A dashboard average of a
  hundred two-decimal scores is a published figure, and
  ``round(sum(xs) / len(xs), 2)`` on a published figure is the bug module 5
  shipped. ``decimal_mean`` sums exactly and rounds half away from zero, so the
  same answers give the same average on any machine.
* **"No data" and "zero" are different statements.** A topic nobody has
  answered has ``None`` for an average, not ``0.0``, and it is never called a
  weakness.
* **One answer is not a trend.** A topic needs
  ``performance.min_answers_for_topic`` answers before it can be called weak or
  strong. Topics below that threshold are still listed with their averages -
  hiding them would be its own kind of lie - and carry
  ``has_enough_answers=False`` so a reader knows which is which.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from app.core.logging import get_logger
from app.core.rounding import decimal_mean, round_half_up
from app.modules.interview_coach.thresholds import InterviewCoachConfig
from app.schemas.common import OutputOrigin
from app.schemas.interview_coach import (
    DIFFICULTY_ORDER,
    DIMENSION_ORDER,
    TRACK_ORDER,
    DifficultyPerformanceSchema,
    DimensionPerformanceSchema,
    InterviewMode,
    InterviewTrack,
    PerformanceBand,
    PerformanceDashboardSchema,
    QuestionDifficulty,
    ScoreOverTimePointSchema,
    SessionListItemSchema,
    SessionStatus,
    SessionSummarySchema,
    StudyPlanItemSchema,
    TopicPerformanceSchema,
    TrackPerformanceSchema,
)

logger = get_logger(__name__)

__all__ = [
    "AnswerRecord",
    "SessionRecord",
    "build_dashboard",
    "summarise_answers",
]


@dataclass
class AnswerRecord:
    """One marked answer, flattened into the fields the aggregates need.

    Deliberately not an ORM row: every function below is pure arithmetic over
    this shape, so the dashboard can be unit tested without a database and the
    same code can later aggregate answers that arrive from somewhere else.
    """

    session_id: str
    question_id: str
    track: InterviewTrack
    topic: str
    difficulty: QuestionDifficulty
    mode: InterviewMode
    overall_score: float
    dimension_scores: dict[str, float] = field(default_factory=dict)
    missed_concepts: list[str] = field(default_factory=list)
    seconds_spent: int = 0
    within_time_limit: bool = True
    scoring_is_stale: bool = False
    passed: bool = False
    answered_at: datetime | None = None


@dataclass
class SessionRecord:
    """One session, flattened for the dashboard."""

    session_id: str
    name: str
    candidate_name: str = ""
    tracks: list[InterviewTrack] = field(default_factory=list)
    mode: InterviewMode = InterviewMode.PRACTICE
    status: SessionStatus = SessionStatus.IN_PROGRESS
    question_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None


def _band(config: InterviewCoachConfig, score: float | None) -> PerformanceBand | None:
    return config.scoring.band_for(score)


def _average(scores: list[float]) -> float | None:
    return decimal_mean(scores)


def _most_missed(records: list[AnswerRecord], limit: int) -> list[str]:
    """Return the concept labels these answers missed most often."""
    counter: Counter[str] = Counter()
    for record in records:
        counter.update(record.missed_concepts)
    return [label for label, _count in counter.most_common(limit)]


# ---------------------------------------------------------------------------
# Session summary
# ---------------------------------------------------------------------------


def summarise_answers(
    records: list[AnswerRecord], question_count: int, config: InterviewCoachConfig
) -> SessionSummarySchema:
    """Summarise one session's answers."""
    answered = len(records)
    scores = [record.overall_score for record in records]
    average = _average(scores)

    by_dimension: dict[str, list[float]] = {}
    for record in records:
        for name, value in record.dimension_scores.items():
            if value is None:
                continue
            by_dimension.setdefault(name, []).append(float(value))

    by_topic: dict[str, list[float]] = {}
    by_difficulty: dict[str, list[float]] = {}
    for record in records:
        by_topic.setdefault(record.topic, []).append(record.overall_score)
        by_difficulty.setdefault(record.difficulty.value, []).append(record.overall_score)

    topic_averages = {
        topic: _average(values) for topic, values in by_topic.items()
    }
    ranked = sorted(
        ((topic, value) for topic, value in topic_averages.items() if value is not None),
        key=lambda pair: (pair[1], pair[0]),
    )
    weak = [
        topic
        for topic, value in ranked
        if value < config.performance.weak_area_threshold
    ][: config.performance.max_weak_areas]
    strong = [
        topic
        for topic, value in reversed(ranked)
        if value >= config.performance.strong_area_threshold
    ][: config.performance.max_strong_areas]

    total_seconds = sum(record.seconds_spent for record in records)
    missed = _most_missed(records, config.performance.max_most_missed_concepts)

    return SessionSummarySchema(
        question_count=question_count,
        answered_count=answered,
        pending_count=max(0, question_count - answered),
        average_score=average,
        best_score=round_half_up(max(scores)) if scores else None,
        lowest_score=round_half_up(min(scores)) if scores else None,
        passed_count=sum(1 for record in records if record.passed),
        average_by_dimension={
            name: value
            for name, value in (
                (name, _average(values)) for name, values in by_dimension.items()
            )
            if value is not None
        },
        average_by_topic={
            topic: value for topic, value in topic_averages.items() if value is not None
        },
        average_by_difficulty={
            name: value
            for name, value in (
                (name, _average(values)) for name, values in by_difficulty.items()
            )
            if value is not None
        },
        band=_band(config, average),
        total_seconds_spent=total_seconds,
        average_seconds_per_answer=(
            round_half_up(total_seconds / answered) if answered else None
        ),
        over_time_count=sum(1 for record in records if not record.within_time_limit),
        stale_score_count=sum(1 for record in records if record.scoring_is_stale),
        strong_topics=strong,
        weak_topics=weak,
        most_missed_concepts=missed,
        recommended_study_topics=weak or ([ranked[0][0]] if ranked and average is not None
                                          and average < config.scoring.pass_score else []),
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def _topic_performance(
    topic: str, records: list[AnswerRecord], config: InterviewCoachConfig
) -> TopicPerformanceSchema:
    scores = [record.overall_score for record in records]
    average = _average(scores) or 0.0
    tracks = {record.track for record in records}
    return TopicPerformanceSchema(
        topic=topic,
        track=next(iter(tracks)) if len(tracks) == 1 else None,
        answer_count=len(records),
        average_score=average,
        best_score=round_half_up(max(scores)) if scores else 0.0,
        lowest_score=round_half_up(min(scores)) if scores else 0.0,
        band=_band(config, average) or PerformanceBand.NEEDS_WORK,
        has_enough_answers=len(records) >= config.performance.min_answers_for_topic,
        most_missed_concepts=_most_missed(
            records, config.performance.max_most_missed_concepts
        ),
    )


def _suggested_difficulty(
    records: list[AnswerRecord], config: InterviewCoachConfig
) -> QuestionDifficulty | None:
    """Suggest the difficulty to practise a weak topic at.

    One step below the difficulty most of the weak answers were asked at. A
    candidate who is failing advanced questions on a topic is not helped by
    being sent more advanced questions.
    """
    if not records:
        return None
    counter = Counter(record.difficulty for record in records)
    # Ties resolve towards the harder difficulty, which is the one that is
    # actually causing trouble.
    highest = max(counter, key=lambda difficulty: (counter[difficulty], difficulty.rank))
    if not config.study_plan.step_down_difficulty or highest.rank == 0:
        return highest
    return DIFFICULTY_ORDER[highest.rank - 1]


def _study_plan(
    topics: list[TopicPerformanceSchema],
    records_by_topic: dict[str, list[AnswerRecord]],
    config: InterviewCoachConfig,
) -> list[StudyPlanItemSchema]:
    """Turn the weakest topics into a plan somebody can actually work through.

    Two rules, both learned by reading a real dashboard rather than a test:

    * **Only a topic below the threshold can be in the plan.** Ranking the
      topics and taking the lowest few looks right until somebody has only
      strong topics, at which point the plan tells a candidate scoring 98 to go
      and study it. An empty study plan is a legitimate, useful answer.
    * **The reason is derived from the topic, never from the list it arrived
      in.** The first version printed "average 98.5, below the 60.0 point
      threshold for a weak area" - every number correct, the sentence a lie.
      This is module 8's paired-field lesson in a new place: assert the
      relationship, not the fields.
    """
    threshold = config.performance.weak_area_threshold
    plan: list[StudyPlanItemSchema] = []

    for index, topic in enumerate(
        [item for item in topics if item.average_score < threshold][
            : config.study_plan.max_items
        ],
        start=1,
    ):
        records = records_by_topic.get(topic.topic, [])
        if topic.has_enough_answers:
            reason = (
                f"{topic.answer_count} answers on {topic.topic} average "
                f"{topic.average_score}, below the {threshold} "
                "point threshold for a weak area."
            )
        else:
            reason = (
                f"Only {topic.answer_count} answer(s) on {topic.topic} so far, averaging "
                f"{topic.average_score}, which is below the {threshold} point threshold. "
                "One answer is not a trend - answer a few more before drawing a conclusion."
            )
        plan.append(
            StudyPlanItemSchema(
                priority=index,
                topic=topic.topic,
                track=topic.track,
                average_score=topic.average_score,
                answer_count=topic.answer_count,
                reason=reason,
                actions=config.study_plan.actions_for(topic.track, topic.topic),
                focus_concepts=topic.most_missed_concepts,
                suggested_difficulty=_suggested_difficulty(records, config),
            )
        )
    return plan


def build_dashboard(
    sessions: list[SessionRecord],
    records: list[AnswerRecord],
    config: InterviewCoachConfig,
    *,
    filters: dict[str, object] | None = None,
) -> PerformanceDashboardSchema:
    """Build the complete performance dashboard from recorded answers."""
    notes: list[str] = []
    scores = [record.overall_score for record in records]
    average = _average(scores)

    if not records:
        notes.append(
            "No answers have been recorded yet with these filters. Start a session and answer "
            "a question to populate this dashboard."
        )

    # -- by dimension ----------------------------------------------------
    dimension_scores: dict[str, list[float]] = {}
    for record in records:
        for name, value in record.dimension_scores.items():
            if value is None:
                continue
            dimension_scores.setdefault(name, []).append(float(value))
    by_dimension: list[DimensionPerformanceSchema] = []
    for dimension in DIMENSION_ORDER:
        values = dimension_scores.get(dimension.value, [])
        if not values:
            continue
        dimension_average = _average(values) or 0.0
        by_dimension.append(
            DimensionPerformanceSchema(
                dimension=dimension,
                answer_count=len(values),
                average_score=dimension_average,
                band=_band(config, dimension_average) or PerformanceBand.NEEDS_WORK,
            )
        )

    # -- by topic --------------------------------------------------------
    records_by_topic: dict[str, list[AnswerRecord]] = {}
    for record in records:
        records_by_topic.setdefault(record.topic, []).append(record)
    topics = [
        _topic_performance(topic, topic_records, config)
        for topic, topic_records in records_by_topic.items()
    ]
    topics.sort(key=lambda item: (item.average_score, item.topic))
    by_topic = topics[: config.performance.max_topics_reported]

    weak = [
        item
        for item in topics
        if item.has_enough_answers
        and item.average_score < config.performance.weak_area_threshold
    ][: config.performance.max_weak_areas]
    strong = [
        item
        for item in reversed(topics)
        if item.has_enough_answers
        and item.average_score >= config.performance.strong_area_threshold
    ][: config.performance.max_strong_areas]

    # A dashboard with no *qualifying* weak area still owes the candidate a next
    # step, so topics below the threshold with too few answers are used - but
    # nothing above the threshold ever enters the plan. Telling somebody who
    # scored 98 to go and study that topic is worse than saying nothing.
    below_threshold = [
        item
        for item in topics
        if item.average_score < config.performance.weak_area_threshold
    ]
    plan_topics = weak or below_threshold
    if not weak and below_threshold:
        notes.append(
            f"No topic yet has {config.performance.min_answers_for_topic} or more answers "
            "below the weak-area threshold, so the study plan below is built from the "
            "lowest-scoring topics recorded so far and each item says how little it rests on."
        )
    if records and not below_threshold:
        notes.append(
            f"No topic is averaging below {config.performance.weak_area_threshold} points, "
            "so there is no study plan to give. Raise the difficulty or add a track to find "
            "the edge of what you know."
        )

    # -- by difficulty and track -----------------------------------------
    difficulty_scores: dict[QuestionDifficulty, list[float]] = {}
    track_scores: dict[InterviewTrack, list[float]] = {}
    for record in records:
        difficulty_scores.setdefault(record.difficulty, []).append(record.overall_score)
        track_scores.setdefault(record.track, []).append(record.overall_score)

    by_difficulty = []
    for difficulty in DIFFICULTY_ORDER:
        values = difficulty_scores.get(difficulty, [])
        if not values:
            continue
        difficulty_average = _average(values) or 0.0
        by_difficulty.append(
            DifficultyPerformanceSchema(
                difficulty=difficulty,
                answer_count=len(values),
                average_score=difficulty_average,
                band=_band(config, difficulty_average) or PerformanceBand.NEEDS_WORK,
            )
        )

    by_track = []
    for track in TRACK_ORDER:
        values = track_scores.get(track, [])
        if not values:
            continue
        track_average = _average(values) or 0.0
        by_track.append(
            TrackPerformanceSchema(
                track=track,
                answer_count=len(values),
                average_score=track_average,
                band=_band(config, track_average) or PerformanceBand.NEEDS_WORK,
            )
        )

    # -- over time -------------------------------------------------------
    records_by_session: dict[str, list[AnswerRecord]] = {}
    for record in records:
        records_by_session.setdefault(record.session_id, []).append(record)

    ordered_sessions = sorted(
        sessions,
        key=lambda item: (item.completed_at or item.started_at or datetime.min, item.session_id),
    )
    over_time: list[ScoreOverTimePointSchema] = []
    for session in ordered_sessions:
        session_records = records_by_session.get(session.session_id, [])
        if not session_records:
            continue
        session_average = _average(
            [record.overall_score for record in session_records]
        ) or 0.0
        over_time.append(
            ScoreOverTimePointSchema(
                session_id=session.session_id,
                session_name=session.name,
                mode=session.mode,
                tracks=list(session.tracks),
                answered_count=len(session_records),
                average_score=session_average,
                recorded_at=session.completed_at or session.started_at,
            )
        )
    over_time = over_time[-config.performance.max_score_over_time_points :]

    # -- recent sessions --------------------------------------------------
    recent: list[SessionListItemSchema] = []
    for session in reversed(ordered_sessions):
        if len(recent) >= config.performance.recent_session_limit:
            break
        session_records = records_by_session.get(session.session_id, [])
        recent.append(
            SessionListItemSchema(
                session_id=session.session_id,
                name=session.name,
                candidate_name=session.candidate_name,
                tracks=list(session.tracks),
                mode=session.mode,
                status=session.status,
                question_count=session.question_count,
                answered_count=len(session_records),
                average_score=_average(
                    [record.overall_score for record in session_records]
                ),
                started_at=session.started_at,
                completed_at=session.completed_at,
            )
        )

    stale = sum(1 for record in records if record.scoring_is_stale)
    if stale:
        notes.append(
            f"{stale} recorded score(s) were computed against a question rubric that has "
            "since changed. They are still included in every average above and are counted "
            "here so nothing disappears quietly."
        )

    return PerformanceDashboardSchema(
        session_count=len(sessions),
        completed_session_count=sum(
            1 for session in sessions if session.status is SessionStatus.COMPLETED
        ),
        answer_count=len(records),
        average_score=average,
        band=_band(config, average),
        total_seconds_spent=sum(record.seconds_spent for record in records),
        stale_score_count=stale,
        by_dimension=by_dimension,
        by_topic=by_topic,
        by_difficulty=by_difficulty,
        by_track=by_track,
        score_over_time=over_time,
        weak_areas=weak,
        strong_areas=strong,
        study_plan=_study_plan(plan_topics, records_by_topic, config),
        recent_sessions=recent,
        filters=dict(filters or {}),
        output_origin=OutputOrigin.RULE_BASED,
        notes=notes,
    )
