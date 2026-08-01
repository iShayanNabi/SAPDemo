"""Typed, validated access to the SAP Interview Coach configuration.

Everything the coach decides for itself lives in ``config/interview_rules.json``
and is validated here at load time: the dimension weights, the band thresholds,
the clarity length bands, the negation cues, the non-answer phrases, how many
questions each mode asks, what the weak-area threshold is and which study
actions a track suggests.

That separation is what makes the marking arguable. A candidate who disagrees
with a score can be shown the exact numbers that produced it, and a coach who
thinks clarity is over-weighted can retune it without touching a line of Python.
The one thing no amount of configuration can move is *who* does the scoring:
the rubric scores, and the model writes prose.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.schemas.interview_coach import (
    DIMENSION_ORDER,
    MODE_ORDER,
    TRACK_ORDER,
    InterviewMode,
    InterviewTrack,
    PerformanceBand,
    QuestionDifficulty,
    ScoreDimension,
)

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "interview_rules.json"

#: Bands ordered from weakest to strongest, used for threshold resolution.
BAND_LADDER: tuple[PerformanceBand, ...] = (
    PerformanceBand.NEEDS_WORK,
    PerformanceBand.DEVELOPING,
    PerformanceBand.PROFICIENT,
    PerformanceBand.STRONG,
)


class ClarityComponentWeights(BaseModel):
    """How the three clarity components combine."""

    length: float = Field(default=0.4, gt=0)
    sentences: float = Field(default=0.3, gt=0)
    structure: float = Field(default=0.3, gt=0)

    def normalised(self) -> dict[str, float]:
        """Return the three weights scaled to sum to one."""
        total = self.length + self.sentences + self.structure
        return {
            "length": self.length / total,
            "sentences": self.sentences / total,
            "structure": self.structure / total,
        }


class ClaritySettings(BaseModel):
    """How the shape of an answer becomes a clarity score.

    Clarity is deliberately measured from structure - length, sentence length,
    signposting, filler - and never from vocabulary. A candidate who says all
    the right things in one unreadable 90-word sentence should lose clarity
    marks and keep every technical point they earned.
    """

    description: str = ""
    min_words: int = Field(default=12, ge=1)
    ideal_min_words: int = Field(default=45, ge=1)
    ideal_max_words: int = Field(default=220, ge=2)
    max_words: int = Field(default=420, ge=2)
    max_average_sentence_words: float = Field(default=28.0, gt=0)
    hard_average_sentence_words: float = Field(default=55.0, gt=0)
    structure_markers: list[str] = Field(default_factory=list)
    structure_marker_target: int = Field(default=3, ge=1)
    structure_base_score: float = Field(default=55.0, ge=0, le=100)
    filler_phrases: list[str] = Field(default_factory=list)
    filler_penalty_points: float = Field(default=6.0, ge=0, le=100)
    max_filler_penalty: float = Field(default=24.0, ge=0, le=100)
    component_weights: ClarityComponentWeights = Field(
        default_factory=ClarityComponentWeights
    )

    def model_post_init(self, _context: object) -> None:
        if self.min_words > self.ideal_min_words:
            raise ValueError("clarity.min_words is greater than clarity.ideal_min_words")
        if self.ideal_min_words > self.ideal_max_words:
            raise ValueError("clarity.ideal_min_words is greater than clarity.ideal_max_words")
        if self.ideal_max_words > self.max_words:
            raise ValueError("clarity.ideal_max_words is greater than clarity.max_words")
        if self.max_average_sentence_words > self.hard_average_sentence_words:
            raise ValueError(
                "clarity.max_average_sentence_words is greater than "
                "clarity.hard_average_sentence_words"
            )

    def merged_with(self, overrides: dict[str, Any] | None) -> "ClaritySettings":
        """Return a copy with the mode's clarity overrides applied.

        A rapid-fire answer is not a short essay: the mode may narrow the length
        band without redefining the whole clarity model.
        """
        if not overrides:
            return self
        merged = self.model_dump()
        merged.update(overrides)
        return ClaritySettings.model_validate(merged)


class ScoringSettings(BaseModel):
    """The published rubric: weights, bands, penalties and the text guards."""

    description: str = ""
    pass_score: float = Field(default=60.0, ge=0, le=100)
    dimension_weights: dict[ScoreDimension, float] = Field(default_factory=dict)
    bands: dict[str, float] = Field(default_factory=dict)
    required_concept_miss_penalty: float = Field(default=8.0, ge=0, le=100)
    max_required_concept_penalty: float = Field(default=24.0, ge=0, le=100)
    max_incorrect_statement_penalty: float = Field(default=45.0, ge=0, le=100)
    excerpt_chars: int = Field(default=140, ge=20, le=1000)
    non_answer_patterns: list[str] = Field(default_factory=list)
    negation_cues: list[str] = Field(default_factory=list)
    #: How many words before a keyword the negation check looks at. A cue at the
    #: far end of a long clause is usually negating something else - "what it
    #: does not do is reach the long tail" is a statement *about* the long tail,
    #: not a denial of it - so the veto only fires when the cue is close enough
    #: to plausibly govern the phrase.
    negation_window_words: int = Field(default=4, ge=1, le=20)
    clarity: ClaritySettings = Field(default_factory=ClaritySettings)

    def model_post_init(self, _context: object) -> None:
        missing = [item for item in DIMENSION_ORDER if item not in self.dimension_weights]
        if missing:
            raise ValueError(
                "scoring.dimension_weights is missing: "
                + ", ".join(item.value for item in missing)
            )
        for dimension, weight in self.dimension_weights.items():
            if weight <= 0:
                raise ValueError(
                    f"scoring.dimension_weights['{dimension.value}'] must be greater than zero"
                )
        for name in ("developing", "proficient", "strong"):
            if name not in self.bands:
                raise ValueError(f"scoring.bands is missing '{name}'")
        if not (
            0 < self.bands["developing"] < self.bands["proficient"] < self.bands["strong"] <= 100
        ):
            raise ValueError(
                "scoring.bands must increase: 0 < developing < proficient < strong <= 100"
            )

    def band_for(self, score: float | None) -> PerformanceBand | None:
        """Return the band a score falls into, or ``None`` for no score."""
        if score is None:
            return None
        if score >= self.bands["strong"]:
            return PerformanceBand.STRONG
        if score >= self.bands["proficient"]:
            return PerformanceBand.PROFICIENT
        if score >= self.bands["developing"]:
            return PerformanceBand.DEVELOPING
        return PerformanceBand.NEEDS_WORK


class SelectionSettings(BaseModel):
    """How a session's question list is drawn from the bank."""

    description: str = ""
    default_seed: int = Field(default=20260801, ge=0)
    max_questions_per_session: int = Field(default=25, ge=1, le=100)
    prefer_distinct_topics: bool = True
    #: When a mode's difficulty mix yields nothing for a track, fall back to any
    #: difficulty rather than dropping the track. A session with four questions
    #: instead of five is a worse outcome than one slightly easier question.
    allow_difficulty_fallback: bool = True


class ModeSettings(BaseModel):
    """One interview mode: how long, how many, how hard and weighted how."""

    label: str = Field(min_length=2, max_length=80)
    description: str = ""
    default_question_count: int = Field(default=5, ge=1, le=100)
    time_limit_seconds: int | None = Field(default=None, ge=5, le=7200)
    timer_enabled: bool = False
    difficulty_mix: list[QuestionDifficulty] = Field(min_length=1)
    dimension_weight_overrides: dict[ScoreDimension, float] = Field(default_factory=dict)
    clarity_overrides: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, _context: object) -> None:
        for dimension, weight in self.dimension_weight_overrides.items():
            if weight <= 0:
                raise ValueError(
                    f"dimension_weight_overrides['{dimension.value}'] must be greater than zero"
                )
        if self.timer_enabled and self.time_limit_seconds is None:
            raise ValueError("a mode with timer_enabled needs a time_limit_seconds")
        seen: set[QuestionDifficulty] = set()
        self.difficulty_mix = [
            item for item in self.difficulty_mix if not (item in seen or seen.add(item))
        ]


class TrackSettings(BaseModel):
    """How one learning track is described to a candidate."""

    label: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=600)


class PerformanceSettings(BaseModel):
    """How the dashboard decides what is weak, strong and worth studying."""

    description: str = ""
    min_answers_for_topic: int = Field(default=2, ge=1)
    weak_area_threshold: float = Field(default=60.0, ge=0, le=100)
    strong_area_threshold: float = Field(default=78.0, ge=0, le=100)
    max_weak_areas: int = Field(default=5, ge=1, le=50)
    max_strong_areas: int = Field(default=5, ge=1, le=50)
    max_topics_reported: int = Field(default=40, ge=1, le=500)
    max_score_over_time_points: int = Field(default=25, ge=1, le=500)
    recent_session_limit: int = Field(default=5, ge=1, le=50)
    default_session_window: int = Field(default=50, ge=1, le=500)
    max_most_missed_concepts: int = Field(default=5, ge=1, le=50)

    def model_post_init(self, _context: object) -> None:
        if self.weak_area_threshold >= self.strong_area_threshold:
            raise ValueError(
                "performance.weak_area_threshold must be below "
                "performance.strong_area_threshold"
            )


class StudyPlanSettings(BaseModel):
    """The deterministic study actions suggested for a weak topic."""

    description: str = ""
    max_items: int = Field(default=5, ge=1, le=50)
    default_actions: list[str] = Field(min_length=1)
    track_actions: dict[InterviewTrack, list[str]] = Field(default_factory=dict)
    step_down_difficulty: bool = True

    def actions_for(self, track: InterviewTrack | None, topic: str) -> list[str]:
        """Return the study actions for one weak topic, most specific first."""
        actions = list(self.track_actions.get(track, [])) if track else []
        actions.extend(self.default_actions)
        return [action.replace("{topic}", topic) for action in actions]


class FeedbackTemplates(BaseModel):
    """The wording the deterministic feedback falls back to."""

    strength_concept: str = "Covered {label}."
    strength_clarity: str = "The answer is well structured and easy to follow."
    strength_length: str = "The answer is the right length for the question."
    strength_none: str = "Nothing in this answer matched the marking scheme yet."
    missing_concept: str = "{label}{hint}"
    improved_answer_intro: str = "A complete answer to this question covers the following."
    improved_answer_missing_intro: str = "Your answer did not mention:"
    coaching_note_pass: str = "This answer would pass."
    coaching_note_borderline: str = "This answer is close."
    coaching_note_fail: str = "Work through the study topics below."
    coaching_note_non_answer: str = "No answer was given, so nothing could be scored."
    follow_up_default: str = "Can you say more about the part you are least sure of?"


class FeedbackSettings(BaseModel):
    """Size limits and wording for the feedback half of a result."""

    description: str = ""
    max_strengths: int = Field(default=5, ge=1, le=50)
    max_missing_concepts: int = Field(default=6, ge=1, le=50)
    max_incorrect_statements: int = Field(default=5, ge=1, le=50)
    max_topics_to_study: int = Field(default=5, ge=1, le=50)
    max_improved_answer_chars: int = Field(default=3000, ge=100)
    max_coaching_note_chars: int = Field(default=900, ge=50)
    min_improved_answer_chars: int = Field(default=40, ge=10)
    templates: FeedbackTemplates = Field(default_factory=FeedbackTemplates)

    def model_post_init(self, _context: object) -> None:
        if self.min_improved_answer_chars >= self.max_improved_answer_chars:
            raise ValueError(
                "feedback.min_improved_answer_chars must be below "
                "feedback.max_improved_answer_chars"
            )


class ReportingSettings(BaseModel):
    """The standing disclaimers printed wherever a score is shown."""

    disclaimer: str = ""
    ai_note: str = ""
    scoring_note: str = ""


class InterviewCoachConfig(BaseModel):
    """The complete, validated SAP Interview Coach configuration."""

    config_version: str
    description: str = ""
    scoring: ScoringSettings
    tracks: dict[InterviewTrack, TrackSettings]
    selection: SelectionSettings = Field(default_factory=SelectionSettings)
    modes: dict[InterviewMode, ModeSettings]
    performance: PerformanceSettings = Field(default_factory=PerformanceSettings)
    study_plan: StudyPlanSettings
    feedback: FeedbackSettings = Field(default_factory=FeedbackSettings)
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)

    def model_post_init(self, _context: object) -> None:
        missing = [item for item in MODE_ORDER if item not in self.modes]
        if missing:
            raise ValueError(
                "configuration is missing interview modes: "
                + ", ".join(item.value for item in missing)
            )
        missing_tracks = [item for item in TRACK_ORDER if item not in self.tracks]
        if missing_tracks:
            raise ValueError(
                "configuration is missing learning tracks: "
                + ", ".join(item.value for item in missing_tracks)
            )
        for mode, settings in self.modes.items():
            if settings.default_question_count > self.selection.max_questions_per_session:
                raise ValueError(
                    f"modes.{mode.value}.default_question_count exceeds "
                    "selection.max_questions_per_session"
                )
            # Validate the override block the same way the base settings are
            # validated, so a typo in one mode fails at load rather than at the
            # first rapid-fire answer.
            self.scoring.clarity.merged_with(settings.clarity_overrides)

    # -- helpers ---------------------------------------------------------
    def track(self, track: InterviewTrack | str) -> TrackSettings:
        """Return one track's label and description."""
        key = InterviewTrack(track) if not isinstance(track, InterviewTrack) else track
        if key not in self.tracks:
            raise ConfigurationError(f"Unknown learning track: {key.value}")
        return self.tracks[key]

    def mode(self, mode: InterviewMode | str) -> ModeSettings:
        """Return one mode's settings."""
        key = InterviewMode(mode) if not isinstance(mode, InterviewMode) else mode
        if key not in self.modes:
            raise ConfigurationError(f"Unknown interview mode: {key.value}")
        return self.modes[key]

    def clarity_for(self, mode: InterviewMode) -> ClaritySettings:
        """Return the clarity settings that apply in one mode."""
        return self.scoring.clarity.merged_with(self.mode(mode).clarity_overrides)

    def weights_for(
        self,
        mode: InterviewMode,
        applicable: list[ScoreDimension],
        *,
        question_weights: dict[ScoreDimension, float] | None = None,
    ) -> dict[ScoreDimension, float]:
        """Resolve the dimension weights for one question, normalised to 1.

        Resolution order is question rubric, then mode override, then the global
        default. Only the dimensions that actually apply take part, so a
        question with no architecture concepts shares that weight out among the
        others instead of scoring a blank as zero.
        """
        mode_overrides = self.mode(mode).dimension_weight_overrides
        resolved: dict[ScoreDimension, float] = {}
        for dimension in applicable:
            if question_weights and dimension in question_weights:
                resolved[dimension] = float(question_weights[dimension])
            elif dimension in mode_overrides:
                resolved[dimension] = float(mode_overrides[dimension])
            else:
                resolved[dimension] = float(self.scoring.dimension_weights[dimension])

        total = sum(resolved.values())
        if total <= 0:  # pragma: no cover - guarded by the validators above
            raise ConfigurationError("The resolved dimension weights sum to zero.")
        return {dimension: weight / total for dimension, weight in resolved.items()}

    def methodology(self) -> dict[str, Any]:
        """Describe, in plain language, how an answer is marked."""
        return {
            "deterministic": [
                "Which questions a session asks (seeded selection from the bundled bank).",
                "Whether each expected concept was covered, and which keyword matched it.",
                "Every dimension score, the overall score and the band.",
                "Every known-wrong statement detected, and the points it costs.",
                "The clarity measurement (length, sentence length, signposting, filler).",
                "The session summary, the performance dashboard and the study plan.",
            ],
            "ai_generated": [
                "The coaching note and the improved sample answer, when a provider is "
                "active and its response passes validation. Neither changes a score.",
            ],
            "dimension_weights": {
                dimension.value: weight
                for dimension, weight in self.scoring.dimension_weights.items()
            },
            "mode_weight_overrides": {
                mode.value: {
                    dimension.value: weight
                    for dimension, weight in settings.dimension_weight_overrides.items()
                }
                for mode, settings in self.modes.items()
                if settings.dimension_weight_overrides
            },
            "bands": dict(self.scoring.bands),
            "pass_score": self.scoring.pass_score,
            "clarity": {
                "ideal_words": [
                    self.scoring.clarity.ideal_min_words,
                    self.scoring.clarity.ideal_max_words,
                ],
                "max_average_sentence_words": self.scoring.clarity.max_average_sentence_words,
                "component_weights": self.scoring.clarity.component_weights.normalised(),
            },
            "penalties": {
                "required_concept_miss": self.scoring.required_concept_miss_penalty,
                "max_required_concept_penalty": self.scoring.max_required_concept_penalty,
                "max_incorrect_statement_penalty": self.scoring.max_incorrect_statement_penalty,
            },
            "performance": {
                "min_answers_for_topic": self.performance.min_answers_for_topic,
                "weak_area_threshold": self.performance.weak_area_threshold,
                "strong_area_threshold": self.performance.strong_area_threshold,
            },
            "scoring_note": self.reporting.scoring_note,
        }


def load_interview_config(path: Path | str | None = None) -> InterviewCoachConfig:
    """Load and validate the SAP Interview Coach configuration from ``path``."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigurationError(
            f"Interview Coach configuration file is missing: {config_path.name}"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Interview Coach configuration is not valid JSON: {exc.msg} (line {exc.lineno})"
        ) from exc
    try:
        config = InterviewCoachConfig.model_validate(raw)
    except PydanticValidationError as exc:
        raise ConfigurationError(
            f"Interview Coach configuration failed validation: {exc.error_count()} problem(s).",
            details={"errors": exc.errors(include_url=False)[:10]},
        ) from exc

    logger.info(
        "Loaded interview coach configuration v%s (%d modes)",
        config.config_version,
        len(config.modes),
    )
    return config


@lru_cache(maxsize=1)
def get_interview_config() -> InterviewCoachConfig:
    """Return the cached default configuration."""
    return load_interview_config()
