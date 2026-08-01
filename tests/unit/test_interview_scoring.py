"""Unit tests for the SAP Interview Coach rubric scoring.

These exercise the pure scoring layer directly: no database, no HTTP, no
provider. Everything asserted here has to hold whatever the AI provider is
doing, because the provider is never consulted about a number.
"""

from __future__ import annotations

import pytest

from app.modules.interview_coach.builder import build_template_feedback, choose_follow_up
from app.modules.interview_coach.scoring import find_concept, score_answer, score_clarity
from app.modules.interview_coach.thresholds import load_interview_config
from app.schemas.common import OutputOrigin
from app.schemas.interview_coach import (
    BankQuestionSchema,
    InterviewMode,
    PerformanceBand,
    ScoreDimension,
)


def _question(**overrides) -> BankQuestionSchema:
    """A small, complete question used by most tests here."""
    payload = {
        "question_id": "IQ-TEST-001",
        "track": "sap_mm",
        "topic": "Test topic",
        "difficulty": "intermediate",
        "modes": ["practice", "technical"],
        "question": "Explain the three-way match and what the GR/IR account does.",
        "expected_concepts": [
            {
                "concept_id": "documents",
                "label": "The three documents compared",
                "dimension": "technical",
                "weight": 2.0,
                "required": True,
                "keywords": ["goods receipt", "purchase order"],
                "study_hint": "Name all three documents.",
            },
            {
                "concept_id": "grir",
                "label": "GR/IR is a clearing account",
                "dimension": "technical",
                "weight": 1.0,
                "keywords": ["clearing account"],
            },
            {
                "concept_id": "why",
                "label": "It stops payment for goods never received",
                "dimension": "business",
                "weight": 1.0,
                "keywords": ["never received"],
            },
        ],
        "incorrect_statements": [
            {
                "statement_id": "pl",
                "label": "GR/IR called a profit and loss account.",
                "patterns": ["GR/IR is a profit and loss account"],
                "correction": "GR/IR is a balance sheet clearing account.",
                "penalty_points": 25.0,
            }
        ],
        "follow_up_questions": [
            {"text": "What does an aged GR/IR balance tell you?", "targets_concept_id": "grir"},
            {"text": "When is a two-way match right?", "targets_concept_id": None},
        ],
        "reference_answer": (
            "The three-way match compares the purchase order, the goods receipt and the "
            "invoice. GR/IR is a clearing account holding the value between them, which "
            "stops the company paying for goods it never received."
        ),
        "rubric": {"summary": "", "weights": {}, "pass_score": None},
        "study_topics": ["Three-way match"],
        "tags": [],
    }
    payload.update(overrides)
    return BankQuestionSchema.model_validate(payload)


@pytest.fixture(scope="module")
def config():
    return load_interview_config()


@pytest.fixture(scope="module")
def question() -> BankQuestionSchema:
    return _question()


class TestConceptMatching:
    def test_a_keyword_is_matched_case_insensitively(self, config, question):
        concept = question.expected_concepts[0]

        finding = find_concept(concept, "We compare the GOODS RECEIPT first.", [])

        assert finding.matched is True
        assert finding.keyword == "goods receipt"

    def test_a_keyword_survives_a_line_break(self, config, question):
        """A wrapped answer is still the same answer - module 6's lesson."""
        concept = question.expected_concepts[0]

        finding = find_concept(concept, "We compare the goods\nreceipt first.", [])

        assert finding.matched is True

    def test_a_plural_still_counts(self, config):
        """A rubric that marks somebody down for the plural is marking grammar."""
        concept = _question().expected_concepts[1]

        finding = find_concept(concept, "They post to clearing accounts.", [])

        assert finding.matched is True

    def test_a_word_boundary_stops_a_false_match(self, config):
        concept = _question(
            expected_concepts=[
                {
                    "concept_id": "pr",
                    "label": "Purchase requisition",
                    "dimension": "technical",
                    "keywords": ["PR"],
                },
                {
                    "concept_id": "b",
                    "label": "Business",
                    "dimension": "business",
                    "keywords": ["buyer"],
                },
            ]
        ).expected_concepts[0]

        assert find_concept(concept, "The approval is pending.", []).matched is False

    def test_a_negated_phrase_is_not_credited(self, config, question):
        """"The goods receipt does not update stock" asserts the opposite."""
        concept = question.expected_concepts[1]

        finding = find_concept(
            concept, "It does not use a clearing account at all.", config.scoring.negation_cues
        )

        assert finding.matched is False
        assert finding.negated is True

    def test_a_distant_cue_in_the_same_clause_does_not_veto(self, config, question):
        """A cue at the far end of a clause is usually negating something else."""
        concept = question.expected_concepts[1]

        finding = find_concept(
            concept,
            "What it does not do is post straight to the supplier; it uses a clearing account.",
            config.scoring.negation_cues,
            config.scoring.negation_window_words,
        )

        assert finding.matched is True

    def test_a_negation_in_another_clause_does_not_veto(self, config, question):
        concept = question.expected_concepts[1]

        finding = find_concept(
            concept,
            "We do not post to the vendor, we post to a clearing account.",
            config.scoring.negation_cues,
            config.scoring.negation_window_words,
        )

        assert finding.matched is True


class TestDimensionScores:
    def test_a_complete_answer_scores_every_dimension(self, config, question):
        score = score_answer(
            question, question.reference_answer, config, mode=InterviewMode.PRACTICE
        )

        assert score.overall_score > 80
        assert score.overall_band is PerformanceBand.STRONG
        assert score.passed is True
        assert score.technical_accuracy_score == 100.0
        assert score.completeness_score == 100.0
        assert score.business_understanding_score == 100.0
        assert score.output_origin is OutputOrigin.RULE_BASED

    def test_architecture_is_blank_not_zero_when_it_does_not_apply(self, config, question):
        """An invented number in a score report is worse than a blank."""
        score = score_answer(
            question, question.reference_answer, config, mode=InterviewMode.PRACTICE
        )
        architecture = next(
            item for item in score.dimensions if item.dimension is ScoreDimension.ARCHITECTURE
        )

        assert architecture.applicable is False
        assert architecture.score is None
        assert architecture.weight == 0.0

    def test_the_weights_of_the_applicable_dimensions_sum_to_one(self, config, question):
        score = score_answer(
            question, question.reference_answer, config, mode=InterviewMode.PRACTICE
        )
        total = sum(item.weight for item in score.dimensions if item.applicable)

        assert round(total, 4) == 1.0

    def test_a_partial_answer_scores_below_a_complete_one(self, config, question):
        partial = score_answer(
            question,
            "It involves the purchase order and some checks before payment happens.",
            config,
            mode=InterviewMode.PRACTICE,
        )
        full = score_answer(
            question, question.reference_answer, config, mode=InterviewMode.PRACTICE
        )

        assert partial.overall_score < full.overall_score
        assert partial.passed is False

    def test_a_missing_required_concept_costs_completeness(self, config, question):
        score = score_answer(
            question,
            "GR/IR is a clearing account and it stops paying for goods never received.",
            config,
            mode=InterviewMode.PRACTICE,
        )

        assert score.completeness_score is not None
        assert score.completeness_score < 100.0
        assert any("required concept" in note for note in score.scoring_notes)


class TestIncorrectStatements:
    def test_a_wrong_statement_costs_technical_accuracy_only(self, config, question):
        clean = score_answer(
            question, question.reference_answer, config, mode=InterviewMode.PRACTICE
        )
        wrong = score_answer(
            question,
            question.reference_answer + " GR/IR is a profit and loss account.",
            config,
            mode=InterviewMode.PRACTICE,
        )

        assert wrong.incorrect_statement_matches
        assert wrong.technical_accuracy_score < clean.technical_accuracy_score
        # Saying something incorrect does not make the answer less complete.
        assert wrong.completeness_score == clean.completeness_score
        assert wrong.business_understanding_score == clean.business_understanding_score
        assert wrong.overall_score < clean.overall_score

    def test_the_correction_is_reported_with_the_penalty(self, config, question):
        score = score_answer(
            question,
            question.reference_answer + " GR/IR is a profit and loss account.",
            config,
            mode=InterviewMode.PRACTICE,
        )
        match = score.incorrect_statement_matches[0]

        assert match.statement_id == "pl"
        assert "balance sheet" in match.correction
        assert match.penalty_points == 25.0
        assert match.excerpt


class TestNonAnswers:
    @pytest.mark.parametrize("text", ["I don't know", "no idea", "Not sure", "skip"])
    def test_a_non_answer_scores_zero_and_says_why(self, config, question, text):
        score = score_answer(question, text, config, mode=InterviewMode.PRACTICE)

        assert score.non_answer is True
        assert score.overall_score == 0.0
        assert all(
            item.score == 0.0 for item in score.dimensions if item.applicable
        )
        assert score.scoring_notes

    def test_a_real_short_answer_is_not_a_non_answer(self, config, question):
        score = score_answer(
            question,
            "I do not know the account name, but the goods receipt is compared with the "
            "purchase order and the invoice before payment.",
            config,
            mode=InterviewMode.PRACTICE,
        )

        assert score.non_answer is False
        assert score.overall_score > 0


class TestClarity:
    def test_a_well_shaped_answer_scores_well(self, config):
        text = (
            "First, the requisition records the need. Then the buyer assigns a source of "
            "supply and converts it into a purchase order. Next the warehouse posts a goods "
            "receipt against that order. Finally accounts payable posts the invoice and the "
            "payment run settles it, which closes the document flow for that requirement."
        )

        score, breakdown = score_clarity(text, config.scoring.clarity)

        assert score > 80
        assert breakdown.structure_markers >= 3
        assert breakdown.filler_penalty == 0.0

    def test_one_enormous_sentence_loses_clarity_marks(self, config):
        text = " ".join(["word"] * 120) + "."

        score, breakdown = score_clarity(text, config.scoring.clarity)

        assert breakdown.sentence_count == 1
        assert breakdown.sentence_score < 50
        assert score < 70

    def test_filler_is_penalised_up_to_the_configured_cap(self, config):
        text = (
            "Basically, you know, it is kind of the thing where, I guess, stuff like that "
            "happens with the purchase order and, you know, the rest of it as well really."
        )

        _score, breakdown = score_clarity(text, config.scoring.clarity)

        assert breakdown.filler_hits
        assert breakdown.filler_penalty <= config.scoring.clarity.max_filler_penalty

    def test_rapid_fire_uses_its_own_length_band(self, config, question):
        """A rapid-fire answer is not a short essay."""
        short = (
            "The purchase order, the goods receipt and the invoice are compared, and GR/IR "
            "is a clearing account holding the value in between."
        )

        practice = score_answer(question, short, config, mode=InterviewMode.PRACTICE)
        rapid = score_answer(question, short, config, mode=InterviewMode.RAPID_FIRE)

        assert rapid.clarity_score > practice.clarity_score

    def test_the_clarity_explanation_states_the_numbers_behind_it(self, config, question):
        score = score_answer(
            question, question.reference_answer, config, mode=InterviewMode.PRACTICE
        )
        clarity = next(
            item for item in score.dimensions if item.dimension is ScoreDimension.CLARITY
        )

        assert str(score.clarity.word_count) in clarity.explanation


class TestModeWeights:
    def test_technical_mode_weights_technical_accuracy_higher(self, config, question):
        technical = score_answer(
            question, question.reference_answer, config, mode=InterviewMode.TECHNICAL
        )
        practice = score_answer(
            question, question.reference_answer, config, mode=InterviewMode.PRACTICE
        )

        def weight_of(score, dimension):
            return next(
                item.weight for item in score.dimensions if item.dimension is dimension
            )

        assert weight_of(technical, ScoreDimension.TECHNICAL_ACCURACY) > weight_of(
            practice, ScoreDimension.TECHNICAL_ACCURACY
        )

    def test_a_configuration_edit_changes_the_score_with_no_code_change(
        self, tmp_path, config, question
    ):
        """The whole point of the JSON config: retune the marking, change nothing else."""
        import json

        from app.modules.interview_coach.thresholds import DEFAULT_CONFIG_PATH

        raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        raw["scoring"]["dimension_weights"]["clarity"] = 0.8
        edited_path = tmp_path / "interview_rules.json"
        edited_path.write_text(json.dumps(raw), encoding="utf-8")
        edited = load_interview_config(edited_path)

        answer = "The purchase order and clearing account matter for goods never received."
        before = score_answer(question, answer, config, mode=InterviewMode.PRACTICE)
        after = score_answer(question, answer, edited, mode=InterviewMode.PRACTICE)

        assert before.overall_score != after.overall_score


class TestFeedback:
    def test_the_follow_up_targets_the_missing_concept(self, config, question):
        score = score_answer(
            question,
            "The purchase order and the goods receipt are compared before payment, so you "
            "are not paying for goods never received.",
            config,
            mode=InterviewMode.PRACTICE,
        )

        assert choose_follow_up(question, score, config) == (
            "What does an aged GR/IR balance tell you?"
        )

    def test_a_complete_answer_falls_back_to_the_untargeted_follow_up(self, config, question):
        score = score_answer(
            question, question.reference_answer, config, mode=InterviewMode.PRACTICE
        )

        assert choose_follow_up(question, score, config) == "When is a two-way match right?"

    def test_a_full_marks_answer_gets_no_study_topics(self, config, question):
        """"Study this anyway" after a perfect answer trains people to ignore the list."""
        score = score_answer(
            question, question.reference_answer, config, mode=InterviewMode.PRACTICE
        )
        feedback = build_template_feedback(question, score, config)

        assert feedback.topics_to_study == []
        assert feedback.missing_concepts == []
        assert feedback.strengths

    def test_missing_concepts_carry_their_study_hint(self, config, question):
        score = score_answer(question, "Something about invoices.", config,
                             mode=InterviewMode.PRACTICE)
        feedback = build_template_feedback(question, score, config)

        assert any("Name all three documents." in item for item in feedback.missing_concepts)
        assert feedback.topics_to_study
        assert feedback.improved_sample_answer
