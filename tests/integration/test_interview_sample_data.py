"""Integration tests for the bundled SAP Interview Coach question bank.

These read the committed sample data and assert every condition the manifest
documents. The most valuable one is the first: **every reference answer must
match every concept of its own rubric**. A model answer that does not satisfy
its own keyword list is a bank bug that would show up as a candidate losing
marks for writing exactly the right thing, and it is invisible to any test that
only checks the shape of the file.
"""

from __future__ import annotations

import json

import pytest

from app.modules.interview_coach.ai_feedback import (
    InterviewCoachingService,
    InterviewFeedbackPayload,
)
from app.modules.interview_coach.builder import repair_drafted_feedback
from app.modules.interview_coach.engine import evaluate_answer
from app.modules.interview_coach.question_bank import rubric_fingerprint
from app.modules.interview_coach.scoring import score_answer
from app.schemas.common import OutputOrigin
from app.schemas.interview_coach import (
    ConceptDimension,
    FeedbackSource,
    InterviewMode,
    ScoreDimension,
)


class TestBankContract:
    def test_the_bank_holds_at_least_a_hundred_questions(self, interview_bank):
        assert len(interview_bank.questions) >= 100

    def test_every_track_is_covered(self, interview_bank, interview_manifest):
        assert len(interview_manifest["by_track"]) == 9
        for count in interview_manifest["by_track"].values():
            assert count >= 10

    def test_every_mode_has_a_usable_pool(self, interview_bank, interview_config):
        info = interview_bank.info()

        for mode, settings in interview_config.modes.items():
            available = info.by_mode.get(mode.value, 0)
            assert available >= settings.default_question_count, mode.value

    def test_every_question_carries_the_fields_the_module_is_specified_around(
        self, interview_bank
    ):
        for question in interview_bank.questions:
            assert question.question_id
            assert question.track
            assert question.topic
            assert question.difficulty
            assert question.modes
            assert question.question
            assert question.expected_concepts
            assert question.rubric.summary
            assert question.follow_up_questions
            assert question.reference_answer

    def test_every_question_can_be_scored_on_technical_and_business(self, interview_bank):
        for question in interview_bank.questions:
            dimensions = {concept.dimension for concept in question.expected_concepts}
            assert ConceptDimension.TECHNICAL in dimensions, question.question_id
            assert ConceptDimension.BUSINESS in dimensions, question.question_id

    def test_an_architecture_question_carries_architecture_concepts(self, interview_bank):
        for question in interview_bank.questions:
            if InterviewMode.ARCHITECTURE in question.modes:
                dimensions = {concept.dimension for concept in question.expected_concepts}
                assert ConceptDimension.ARCHITECTURE in dimensions, question.question_id

    def test_identifiers_are_unique(self, interview_bank):
        identifiers = [question.question_id for question in interview_bank.questions]

        assert len(identifiers) == len(set(identifiers))

    def test_every_follow_up_targets_a_concept_that_exists(self, interview_bank):
        for question in interview_bank.questions:
            known = {concept.concept_id for concept in question.expected_concepts}
            for follow_up in question.follow_up_questions:
                if follow_up.targets_concept_id:
                    assert follow_up.targets_concept_id in known, question.question_id


class TestReferenceAnswers:
    """IC-A01: the bank's own model answer has to satisfy the bank's own rubric."""

    def test_every_reference_answer_covers_every_one_of_its_concepts(
        self, interview_bank, interview_config
    ):
        failures: list[str] = []

        for question in interview_bank.questions:
            score = score_answer(
                question, question.reference_answer, interview_config,
                mode=InterviewMode.PRACTICE,
            )
            missing = [
                match.label for match in score.concept_matches if not match.matched
            ]
            if missing:
                failures.append(f"{question.question_id}: {'; '.join(missing)}")

        assert not failures, (
            "These reference answers do not match their own keyword lists, so a candidate "
            "writing the model answer would lose marks:\n" + "\n".join(failures)
        )

    def test_no_reference_answer_trips_its_own_wrong_statement_patterns(
        self, interview_bank, interview_config
    ):
        for question in interview_bank.questions:
            score = score_answer(
                question, question.reference_answer, interview_config,
                mode=InterviewMode.PRACTICE,
            )

            assert not score.incorrect_statement_matches, question.question_id

    def test_every_reference_answer_passes(self, interview_bank, interview_config):
        for question in interview_bank.questions:
            score = score_answer(
                question, question.reference_answer, interview_config,
                mode=InterviewMode.PRACTICE,
            )

            assert score.passed, f"{question.question_id} scored {score.overall_score}"


class TestDocumentedAnchors:
    def _rows(self, baseline: dict, question_id: str) -> dict[str, dict]:
        return {
            row["answer_kind"]: row
            for row in baseline["anchors"]
            if row["question_id"] == question_id
        }

    def test_the_baseline_matches_what_the_engine_produces_today(
        self, interview_bank, interview_config, interview_baseline
    ):
        for row in interview_baseline["anchors"]:
            question = interview_bank.get(row["question_id"])
            mode = InterviewMode(row["mode"])
            if row["answer_kind"] == "reference":
                text = question.reference_answer
            elif row["answer_kind"] == "non_answer":
                text = "I don't know"
            else:
                continue

            score = score_answer(question, text, interview_config, mode=mode)

            assert score.overall_score == row["overall_score"], row["question_id"]
            assert score.overall_band.value == row["band"]
            assert score.passed is row["passed"]

    def test_a_reference_answer_beats_a_partial_one(self, interview_baseline):
        """IC-A02: a rubric that cannot separate the two is not a rubric."""
        for question_id in {row["question_id"] for row in interview_baseline["anchors"]}:
            rows = self._rows(interview_baseline, question_id)

            assert rows["reference"]["overall_score"] > rows["partial"]["overall_score"]
            assert rows["reference"]["passed"] is True
            assert rows["partial"]["passed"] is False

    def test_a_non_answer_scores_zero_everywhere(self, interview_baseline):
        """IC-A03: silence and a wrong answer are different things."""
        for row in interview_baseline["anchors"]:
            if row["answer_kind"] != "non_answer":
                continue

            assert row["overall_score"] == 0.0
            assert row["non_answer"] is True
            assert all(value == 0.0 for value in row["dimensions"].values())

    def test_a_wrong_statement_costs_accuracy_and_leaves_completeness_alone(
        self, interview_baseline
    ):
        """IC-A04: the penalty belongs to one dimension, not spread across them."""
        checked = 0
        for question_id in {row["question_id"] for row in interview_baseline["anchors"]}:
            rows = self._rows(interview_baseline, question_id)
            if "incorrect" not in rows:
                continue
            checked += 1
            reference = rows["reference"]["dimensions"]
            incorrect = rows["incorrect"]

            assert incorrect["incorrect_statements"] >= 1
            assert (
                incorrect["dimensions"]["technical_accuracy"]
                < reference["technical_accuracy"]
            )
            assert incorrect["dimensions"]["completeness"] == reference["completeness"]
            assert incorrect["overall_score"] < rows["reference"]["overall_score"]

        assert checked >= 1

    def test_every_documented_expectation_has_a_test(self, interview_manifest):
        documented = {item["id"] for item in interview_manifest["expectations"]}

        assert documented == {"IC-A01", "IC-A02", "IC-A03", "IC-A04", "IC-A05"}


class TestAiValidation:
    """IC-A05, plus the structured validation of what a provider returns."""

    def test_the_mock_provider_returns_a_payload_that_validates(
        self, interview_bank, interview_config
    ):
        question = interview_bank.get("IQ-MM-003")
        score = score_answer(
            question, question.reference_answer, interview_config,
            mode=InterviewMode.PRACTICE,
        )
        service = InterviewCoachingService()

        result = service.draft_feedback(
            {
                "question_id": question.question_id,
                "topic": question.topic,
                "question": question.question,
                "reference_answer": question.reference_answer,
                "study_topics": list(question.study_topics),
            },
            {
                "band": score.overall_band.value,
                "passed": score.passed,
                "covered_concepts": [
                    match.label for match in score.concept_matches if match.matched
                ],
                "missing_concepts": [],
                "incorrect_statements": [],
            },
            question.reference_answer,
        )

        assert result.available is True
        assert result.origin is OutputOrigin.MOCK_AI
        assert result.prompt_version
        assert InterviewFeedbackPayload.model_validate(result.draft)

    @pytest.mark.parametrize(
        "draft",
        [
            {},
            {"coaching_note": "", "improved_sample_answer": "", "topics_to_study": []},
            {"coaching_note": "ok", "improved_sample_answer": "too short"},
            {"coaching_note": "x" * 5000, "improved_sample_answer": "y" * 20000},
            {"topics_to_study": "One topic, another topic"},
        ],
    )
    def test_a_bad_draft_is_repaired_rather_than_thrown_away(
        self, interview_bank, interview_config, draft
    ):
        question = interview_bank.get("IQ-MM-003")
        score = score_answer(
            question, "Something about invoices.", interview_config,
            mode=InterviewMode.PRACTICE,
        )
        payload = InterviewFeedbackPayload.model_validate(draft).model_dump()

        feedback = repair_drafted_feedback(
            payload, question, score, interview_config, origin=OutputOrigin.MOCK_AI
        )

        assert feedback.coaching_note
        assert len(feedback.coaching_note) <= interview_config.feedback.max_coaching_note_chars
        assert (
            len(feedback.improved_sample_answer)
            <= interview_config.feedback.max_improved_answer_chars
        )
        assert len(feedback.improved_sample_answer) >= (
            interview_config.feedback.min_improved_answer_chars
        )
        assert feedback.source is FeedbackSource.AI_GENERATED

    def test_a_provider_can_never_change_a_stated_fact_about_the_marking(
        self, interview_bank, interview_config
    ):
        """The strengths and the missing concepts are findings, not prose."""
        question = interview_bank.get("IQ-MM-003")
        score = score_answer(
            question, "Something about invoices.", interview_config,
            mode=InterviewMode.PRACTICE,
        )
        hostile = {
            "coaching_note": "Excellent, you covered everything.",
            "improved_sample_answer": "x" * 200,
            "topics_to_study": ["nothing at all"],
        }

        feedback = repair_drafted_feedback(
            hostile, question, score, interview_config, origin=OutputOrigin.MOCK_AI
        )

        assert feedback.missing_concepts, "the rubric found gaps, so they must be reported"
        assert len(feedback.missing_concepts) == sum(
            1 for match in score.concept_matches if not match.matched
        )
        assert feedback.follow_up_question in {
            item.text for item in question.follow_up_questions
        }

    def test_ai_failure_falls_back_to_the_template_and_keeps_the_score(
        self, interview_bank, interview_config
    ):
        class BrokenService(InterviewCoachingService):
            def __init__(self) -> None:  # noqa: D107 - test double
                pass

            def draft_feedback(self, *_args, **_kwargs):
                from app.modules.interview_coach.ai_feedback import InterviewFeedbackResult

                return InterviewFeedbackResult(error="provider exploded", provider="mock")

        question = interview_bank.get("IQ-MM-003")
        with_ai = evaluate_answer(
            question, question.reference_answer, interview_config,
            mode=InterviewMode.PRACTICE, use_ai=True,
            coaching_service=BrokenService(),
        )
        without_ai = evaluate_answer(
            question, question.reference_answer, interview_config,
            mode=InterviewMode.PRACTICE, use_ai=False,
        )

        assert with_ai.ai_used is False
        assert with_ai.ai_error == "provider exploded"
        assert with_ai.feedback.source is FeedbackSource.TEMPLATE
        assert with_ai.feedback.improved_sample_answer
        assert with_ai.score == without_ai.score

    def test_the_score_never_moves_with_the_provider(
        self, interview_bank, interview_config
    ):
        """IC-A05, asserted through the engine rather than the API."""
        for question_id in ("IQ-MM-003", "IQ-AC-002", "IQ-CO-002"):
            question = interview_bank.get(question_id)
            mode = InterviewMode.PRACTICE

            on = evaluate_answer(
                question, question.reference_answer, interview_config, mode=mode, use_ai=True
            )
            off = evaluate_answer(
                question, question.reference_answer, interview_config, mode=mode, use_ai=False
            )

            assert on.score == off.score, question_id
            assert on.feedback.source is FeedbackSource.AI_GENERATED
            assert off.feedback.source is FeedbackSource.TEMPLATE


class TestRubricFingerprints:
    def test_the_recorded_fingerprints_still_match_the_bank(
        self, interview_bank, interview_baseline
    ):
        for question_id, fingerprint in interview_baseline["rubric_fingerprints"].items():
            assert interview_bank.fingerprint(question_id) == fingerprint, question_id

    def test_retuning_a_rubric_changes_its_fingerprint(self, interview_bank):
        """A score is a verdict about a rubric, so the rubric has to be identifiable."""
        question = interview_bank.get("IQ-MM-003")
        before = rubric_fingerprint(question)

        retuned = question.model_copy(deep=True)
        retuned.expected_concepts[0].keywords.append("a new phrase")

        assert rubric_fingerprint(retuned) != before

    def test_rewording_a_question_does_not_invalidate_a_score(self, interview_bank):
        """Fixing a typo must not mark every past score as stale."""
        question = interview_bank.get("IQ-MM-003")
        before = rubric_fingerprint(question)

        reworded = question.model_copy(deep=True)
        reworded.question = question.question + " Please be specific."
        reworded.follow_up_questions = []

        assert rubric_fingerprint(reworded) == before


class TestStaleScores:
    def test_a_score_marked_under_an_old_rubric_is_flagged_not_hidden(
        self, api_client, db_session, interview_bank
    ):
        """Kept, flagged and still counted - module 9's lesson in a new place."""
        from app.models.interview_coach import InterviewAnswer

        started = api_client.post(
            "/api/v1/interviews/start",
            json={"tracks": ["sap_mm"], "mode": "practice", "question_count": 1, "seed": 777},
        ).json()["data"]
        api_client.post(
            f"/api/v1/interviews/{started['session_id']}/answer",
            json={"answer_text": "The purchase order and the goods receipt are compared."},
        )

        row = (
            db_session.query(InterviewAnswer)
            .filter(InterviewAnswer.session_id == started["session_id"])
            .one()
        )
        recorded_score = row.overall_score
        row.rubric_fingerprint = "0000deadbeef0000"
        db_session.commit()

        session = api_client.get(f"/api/v1/interviews/{started['session_id']}").json()["data"]
        answer = session["answers"][0]

        assert answer["scoring_is_stale"] is True
        assert answer["score"]["overall_score"] == recorded_score
        assert session["summary"]["stale_score_count"] == 1
        assert session["summary"]["average_score"] == recorded_score


class TestManifest:
    def test_the_manifest_and_the_bank_agree(self, interview_bank, interview_manifest):
        assert interview_manifest["bank_version"] == interview_bank.bank_version
        assert interview_manifest["question_count"] == len(interview_bank.questions)
        assert sum(interview_manifest["by_track"].values()) == len(interview_bank.questions)

    def test_the_manifest_says_the_data_is_fictional(self, interview_manifest):
        assert "fictional" in interview_manifest["manifest"].lower()
        assert "certification" in interview_manifest["manifest"].lower()

    def test_the_markdown_manifest_exists_and_documents_the_anchors(self):
        from app.core.config import PROJECT_ROOT

        path = PROJECT_ROOT / "data" / "sample" / "INTERVIEW_SCENARIO_MANIFEST.md"
        if not path.is_file():
            pytest.skip("Run 'python scripts/generate_interview_sample_data.py' first.")
        text = path.read_text(encoding="utf-8")

        assert "IC-A01" in text
        assert "fictional" in text.lower()

    def test_the_baseline_records_the_config_it_was_produced_under(
        self, interview_baseline, interview_config
    ):
        assert interview_baseline["config_version"] == interview_config.config_version
        assert json.dumps(interview_baseline["anchors"])


class TestDimensionApplicability:
    def test_architecture_is_scored_only_where_the_question_carries_it(
        self, interview_bank, interview_config
    ):
        scored = 0
        blank = 0

        for question in interview_bank.questions[:40]:
            score = score_answer(
                question, question.reference_answer, interview_config,
                mode=InterviewMode.PRACTICE,
            )
            architecture = next(
                item
                for item in score.dimensions
                if item.dimension is ScoreDimension.ARCHITECTURE
            )
            has_concepts = any(
                concept.dimension is ConceptDimension.ARCHITECTURE
                for concept in question.expected_concepts
            )

            assert architecture.applicable is has_concepts
            if has_concepts:
                scored += 1
            else:
                assert architecture.score is None
                blank += 1

        assert scored > 0 and blank > 0
