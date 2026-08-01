"""Unit tests for question selection and the performance aggregates.

Both layers are pure: selection takes a bank plus a request, the dashboard takes
a list of flat records. Neither touches a database, and neither ever consults a
provider.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.interview_coach.performance import (
    AnswerRecord,
    SessionRecord,
    build_dashboard,
    summarise_answers,
)
from app.modules.interview_coach.selection import (
    allocate_questions,
    plan_questions,
    shuffle_key,
)
from app.modules.interview_coach.thresholds import load_interview_config
from app.schemas.interview_coach import (
    InterviewMode,
    InterviewTrack,
    PerformanceBand,
    QuestionDifficulty,
    SessionStatus,
)

MM = InterviewTrack.SAP_MM
INT = InterviewTrack.SAP_INTEGRATION
ARCH = InterviewTrack.SAP_ARCHITECTURE
SC = InterviewTrack.SUPPLY_CHAIN


@pytest.fixture(scope="module")
def config():
    return load_interview_config()


class TestAllocation:
    def test_the_callers_order_decides_which_tracks_survive(self):
        """Module 8's lesson: the order the caller listed them in is information."""
        capacities = {MM: 5, INT: 5, ARCH: 5}

        allocation = allocate_questions(2, [INT, ARCH, MM], capacities)

        assert set(allocation) == {INT, ARCH}
        assert MM not in allocation

    def test_the_remainder_goes_in_caller_order(self):
        allocation = allocate_questions(5, [MM, INT], {MM: 5, INT: 5})

        assert allocation[MM] == 3
        assert allocation[INT] == 2

    def test_a_track_never_gets_more_questions_than_it_has(self):
        allocation = allocate_questions(6, [MM, INT], {MM: 2, INT: 10})

        assert allocation[MM] == 2
        assert allocation[INT] == 4

    def test_a_track_with_no_questions_is_left_out(self):
        allocation = allocate_questions(3, [MM, INT], {MM: 0, INT: 4})

        assert MM not in allocation
        assert allocation[INT] == 3


class TestShuffleKey:
    def test_the_key_is_stable_across_processes(self):
        """`hash()` is salted per process, so a seeded shuffle built on it is a lie."""
        assert shuffle_key(7, "IQ-MM-001") == shuffle_key(7, "IQ-MM-001")
        assert shuffle_key(7, "IQ-MM-001") != shuffle_key(8, "IQ-MM-001")


class TestPlanning:
    def test_the_same_seed_produces_the_same_interview(self, interview_bank, config):
        first = plan_questions(
            interview_bank, config, tracks=[MM, INT], mode=InterviewMode.TECHNICAL,
            question_count=6, seed=42,
        )
        second = plan_questions(
            interview_bank, config, tracks=[MM, INT], mode=InterviewMode.TECHNICAL,
            question_count=6, seed=42,
        )

        assert [item.question_id for item in first.questions] == [
            item.question_id for item in second.questions
        ]

    def test_a_different_seed_produces_a_different_interview(self, interview_bank, config):
        first = plan_questions(
            interview_bank, config, tracks=[MM, INT], mode=InterviewMode.TECHNICAL,
            question_count=6, seed=1,
        )
        second = plan_questions(
            interview_bank, config, tracks=[MM, INT], mode=InterviewMode.TECHNICAL,
            question_count=6, seed=2,
        )

        assert [item.question_id for item in first.questions] != [
            item.question_id for item in second.questions
        ]

    def test_only_questions_offered_in_the_mode_are_drawn(self, interview_bank, config):
        plan = plan_questions(
            interview_bank, config, tracks=list(InterviewTrack),
            mode=InterviewMode.ARCHITECTURE, question_count=5, seed=3,
        )

        assert plan.questions
        for question in plan.questions:
            assert InterviewMode.ARCHITECTURE in question.modes

    def test_the_requested_difficulties_are_respected(self, interview_bank, config):
        plan = plan_questions(
            interview_bank, config, tracks=[MM], mode=InterviewMode.PRACTICE,
            difficulties=[QuestionDifficulty.ADVANCED], question_count=3, seed=5,
        )

        assert plan.questions
        for question in plan.questions:
            assert question.difficulty is QuestionDifficulty.ADVANCED

    def test_the_difficulty_mix_is_spread_rather_than_clumped(self, interview_bank, config):
        plan = plan_questions(
            interview_bank, config, tracks=[MM], mode=InterviewMode.PRACTICE,
            difficulties=[
                QuestionDifficulty.FOUNDATIONAL,
                QuestionDifficulty.INTERMEDIATE,
                QuestionDifficulty.ADVANCED,
            ],
            question_count=3, seed=11,
        )

        assert len({question.difficulty for question in plan.questions}) == 3

    def test_distinct_topics_are_preferred(self, interview_bank, config):
        plan = plan_questions(
            interview_bank, config, tracks=[MM], mode=InterviewMode.PRACTICE,
            question_count=5, seed=13,
        )
        topics = [question.topic for question in plan.questions]

        assert len(set(topics)) == len(topics)

    def test_tracks_are_interleaved_in_caller_order(self, interview_bank, config):
        plan = plan_questions(
            interview_bank, config, tracks=[MM, INT], mode=InterviewMode.PRACTICE,
            question_count=4, seed=17,
        )
        tracks = [question.track for question in plan.questions]

        assert tracks == [MM, INT, MM, INT]

    def test_a_track_that_cannot_be_covered_is_named(self, interview_bank, config):
        plan = plan_questions(
            interview_bank, config, tracks=[INT, ARCH, MM],
            mode=InterviewMode.ARCHITECTURE, question_count=2, seed=19,
        )

        assert len(plan.questions) == 2
        assert plan.uncovered_tracks
        assert plan.notes

    def test_an_impossible_filter_yields_nothing_rather_than_something_wrong(
        self, interview_bank, config
    ):
        plan = plan_questions(
            interview_bank, config, tracks=[MM], mode=InterviewMode.PRACTICE,
            topics=["a topic that does not exist"], question_count=3, seed=23,
        )

        assert plan.questions == []


def _record(topic: str, score: float, *, difficulty="intermediate", track=MM,
            missed=(), session_id="s1", stale=False, seconds=60) -> AnswerRecord:
    return AnswerRecord(
        session_id=session_id,
        question_id=f"Q-{topic}-{score}",
        track=track,
        topic=topic,
        difficulty=QuestionDifficulty(difficulty),
        mode=InterviewMode.PRACTICE,
        overall_score=score,
        dimension_scores={"technical_accuracy": score, "clarity": score},
        missed_concepts=list(missed),
        seconds_spent=seconds,
        scoring_is_stale=stale,
        passed=score >= 60,
        answered_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


class TestSessionSummary:
    def test_an_unanswered_question_is_reported_rather_than_scored_as_zero(self, config):
        summary = summarise_answers([_record("A", 80.0)], question_count=3, config=config)

        assert summary.question_count == 3
        assert summary.answered_count == 1
        assert summary.pending_count == 2
        assert summary.average_score == 80.0

    def test_no_answers_means_no_average_rather_than_zero(self, config):
        summary = summarise_answers([], question_count=4, config=config)

        assert summary.average_score is None
        assert summary.band is None
        assert summary.average_seconds_per_answer is None

    def test_the_average_is_computed_with_the_decimal_helpers(self, config):
        summary = summarise_answers(
            [_record("A", 20.19), _record("B", 20.20)], question_count=2, config=config
        )

        assert summary.average_score == 20.20

    def test_stale_scores_are_counted_separately_and_still_included(self, config):
        summary = summarise_answers(
            [_record("A", 100.0, stale=True), _record("B", 0.0)],
            question_count=2,
            config=config,
        )

        assert summary.stale_score_count == 1
        assert summary.average_score == 50.0

    def test_most_missed_concepts_are_counted(self, config):
        summary = summarise_answers(
            [
                _record("A", 10.0, missed=["Tolerances", "GR/IR"]),
                _record("B", 20.0, missed=["GR/IR"]),
            ],
            question_count=2,
            config=config,
        )

        assert summary.most_missed_concepts[0] == "GR/IR"


class TestDashboard:
    def _sessions(self, count: int = 1) -> list[SessionRecord]:
        base = datetime(2026, 7, 1, tzinfo=UTC)
        return [
            SessionRecord(
                session_id=f"s{index + 1}",
                name=f"Session {index + 1}",
                mode=InterviewMode.PRACTICE,
                status=SessionStatus.COMPLETED,
                question_count=3,
                started_at=base + timedelta(days=index),
                completed_at=base + timedelta(days=index, hours=1),
            )
            for index in range(count)
        ]

    def test_an_empty_dashboard_says_so_rather_than_reporting_zeroes(self, config):
        dashboard = build_dashboard([], [], config)

        assert dashboard.average_score is None
        assert dashboard.band is None
        assert dashboard.study_plan == []
        assert dashboard.notes

    def test_a_topic_below_the_threshold_with_enough_answers_is_a_weak_area(self, config):
        records = [
            _record("Weak topic", 20.0, missed=["Concept A"]),
            _record("Weak topic", 30.0, missed=["Concept A"]),
            _record("Strong topic", 95.0),
            _record("Strong topic", 90.0),
        ]

        dashboard = build_dashboard(self._sessions(), records, config)

        assert [item.topic for item in dashboard.weak_areas] == ["Weak topic"]
        assert [item.topic for item in dashboard.strong_areas] == ["Strong topic"]

    def test_one_answer_is_not_a_trend(self, config):
        records = [_record("Only once", 10.0)]

        dashboard = build_dashboard(self._sessions(), records, config)

        assert dashboard.weak_areas == []
        topic = next(item for item in dashboard.by_topic if item.topic == "Only once")
        assert topic.has_enough_answers is False
        assert topic.average_score == 10.0

    def test_the_study_plan_never_recommends_a_topic_you_are_strong_at(self, config):
        """Every field was right and the sentence was a lie; found by reading a dashboard."""
        records = [_record("Strong topic", 98.0), _record("Strong topic", 97.0)]

        dashboard = build_dashboard(self._sessions(), records, config)

        assert dashboard.study_plan == []
        assert any("no study plan" in note.lower() for note in dashboard.notes)

    def test_every_study_plan_reason_matches_the_topics_real_state(self, config):
        records = [
            _record("Weak topic", 20.0, missed=["Concept A"]),
            _record("Weak topic", 30.0, missed=["Concept A"]),
            _record("Fine topic", 92.0),
            _record("Fine topic", 91.0),
        ]

        dashboard = build_dashboard(self._sessions(), records, config)

        for item in dashboard.study_plan:
            assert item.average_score < config.performance.weak_area_threshold
            assert str(item.average_score) in item.reason
            assert item.actions
            assert item.topic in item.actions[0]

    def test_the_study_plan_steps_the_difficulty_down(self, config):
        records = [
            _record("Weak topic", 20.0, difficulty="advanced"),
            _record("Weak topic", 25.0, difficulty="advanced"),
        ]

        dashboard = build_dashboard(self._sessions(), records, config)

        assert dashboard.study_plan[0].suggested_difficulty is QuestionDifficulty.INTERMEDIATE

    def test_score_over_time_follows_the_sessions_in_order(self, config):
        sessions = self._sessions(2)
        records = [
            _record("A", 40.0, session_id="s1"),
            _record("A", 80.0, session_id="s2"),
        ]

        dashboard = build_dashboard(sessions, records, config)

        assert [point.average_score for point in dashboard.score_over_time] == [40.0, 80.0]

    def test_breakdowns_cover_dimension_difficulty_and_track(self, config):
        records = [
            _record("A", 40.0, difficulty="foundational", track=MM),
            _record("B", 80.0, difficulty="expert", track=SC),
        ]

        dashboard = build_dashboard(self._sessions(), records, config)

        assert {item.dimension.value for item in dashboard.by_dimension} == {
            "technical_accuracy",
            "clarity",
        }
        assert {item.difficulty.value for item in dashboard.by_difficulty} == {
            "foundational",
            "expert",
        }
        assert {item.track for item in dashboard.by_track} == {MM, SC}
        assert dashboard.average_score == 60.0
        assert dashboard.band is PerformanceBand.PROFICIENT
