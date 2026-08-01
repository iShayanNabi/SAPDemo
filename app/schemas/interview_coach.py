"""Request and response schemas for the SAP Interview Coach.

These are the module's API contract. A future React or Next.js front end can
build the whole page - the track picker, the mode picker, the interview screen,
the timer, the feedback panel, the session summary and the performance
dashboard - from these shapes alone.

Four conventions carry through every schema, and each of them exists because
this module scores a *person*:

* **The rubric scores, not the model.** Every number below - the overall score,
  each dimension score, every concept match - is produced by ordinary Python
  from the question's rubric. A provider is only ever asked for prose, and that
  prose arrives in its own fields carrying its own ``output_origin``.
* **A question does not travel with its answer key.** While a question is
  unanswered, :class:`InterviewQuestionSchema` carries the question text and its
  metadata and nothing else. The expected concepts, the reference answer and the
  known-wrong statements arrive in :class:`AnswerKeySchema` *after* the answer
  has been submitted. An interview question served with its marking scheme
  attached is not an interview question.
* **A score is a verdict about a rubric.** Each stored answer records the
  fingerprint of the rubric it was marked against, so a score that was computed
  against a rubric which has since been retuned reports ``scoring_is_stale``
  rather than quietly averaging into a dashboard.
* **The clock never moves the score.** Time spent is recorded, reported and
  summarised, but no dimension is raised or lowered by it. A rubric marks what
  was said; a stopwatch measures something else.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import OutputOrigin

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class InterviewTrack(str, Enum):
    """The nine learning tracks the coach supports.

    The order below is canonical: it decides the order tracks are listed in the
    catalogue, in the performance dashboard and in the UI.
    """

    SAP_MM = "sap_mm"
    SAP_ARIBA = "sap_ariba"
    SAP_S4HANA = "sap_s4hana"
    SAP_BUSINESS_NETWORK = "sap_business_network"
    SAP_INTEGRATION = "sap_integration"
    SAP_ARCHITECTURE = "sap_architecture"
    PROCUREMENT = "procurement"
    SUPPLY_CHAIN = "supply_chain"
    SAP_CONSULTING = "sap_consulting"


TRACK_ORDER: tuple[InterviewTrack, ...] = tuple(InterviewTrack)


class InterviewMode(str, Enum):
    """How an interview is run.

    The mode decides how many questions are asked, how long each answer gets,
    which difficulties are drawn and how the dimension weights are tilted - all
    of it from ``interview_rules.json``, none of it from code.
    """

    PRACTICE = "practice"
    TIMED = "timed"
    TECHNICAL = "technical"
    ARCHITECTURE = "architecture"
    BEHAVIORAL = "behavioral"
    RAPID_FIRE = "rapid_fire"


MODE_ORDER: tuple[InterviewMode, ...] = tuple(InterviewMode)


class QuestionDifficulty(str, Enum):
    """How hard a question is, ordered from least to most demanding."""

    FOUNDATIONAL = "foundational"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"

    @property
    def rank(self) -> int:
        """Numeric rank used for sorting and for difficulty mixes."""
        return {"foundational": 0, "intermediate": 1, "advanced": 2, "expert": 3}[self.value]


DIFFICULTY_ORDER: tuple[QuestionDifficulty, ...] = tuple(QuestionDifficulty)


class ScoreDimension(str, Enum):
    """The dimensions an answer is scored on.

    ``ARCHITECTURE`` is the only optional one: it is scored when the question
    declares architecture concepts and reported as ``null`` when it does not.
    Scoring an MM master-data question on architecture would be inventing a
    number, and an invented number in a score report is worse than a blank.
    """

    TECHNICAL_ACCURACY = "technical_accuracy"
    COMPLETENESS = "completeness"
    CLARITY = "clarity"
    BUSINESS_UNDERSTANDING = "business_understanding"
    ARCHITECTURE = "architecture"


DIMENSION_ORDER: tuple[ScoreDimension, ...] = tuple(ScoreDimension)


class ConceptDimension(str, Enum):
    """Which score dimension an expected concept feeds.

    Every concept feeds ``completeness``; this says which *other* dimension it
    also feeds. The three values map one-to-one onto the concept-driven score
    dimensions - clarity is measured from the shape of the answer instead.
    """

    TECHNICAL = "technical"
    BUSINESS = "business"
    ARCHITECTURE = "architecture"


class SessionStatus(str, Enum):
    """Where an interview session sits in its lifecycle."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class AnswerStatus(str, Enum):
    """Whether a served question has been answered."""

    PENDING = "pending"
    ANSWERED = "answered"
    SKIPPED = "skipped"


class FeedbackSource(str, Enum):
    """How a piece of feedback prose came to exist.

    Deliberately separate from :class:`OutputOrigin`: the origin says *what
    produced the words*, the source says *which layer supplied them*.
    """

    AI_GENERATED = "ai_generated"
    #: The deterministic templates wrote it, because AI was off or unusable.
    TEMPLATE = "template"


class PerformanceBand(str, Enum):
    """The band a score falls into, from the configured thresholds."""

    NEEDS_WORK = "needs_work"
    DEVELOPING = "developing"
    PROFICIENT = "proficient"
    STRONG = "strong"


# ---------------------------------------------------------------------------
# Question bank
# ---------------------------------------------------------------------------


class ExpectedConceptSchema(BaseModel):
    """One thing a good answer is expected to say.

    ``keywords`` are the surface forms that count as having said it. They are
    matched case-insensitively - vocabulary matching is exactly the place where
    ``re.IGNORECASE`` is right - on word boundaries, so "PR" never matches
    inside "approval". ``negation_patterns`` veto a hit inside the same clause,
    because "the goods receipt does not update stock" contains the phrase and
    asserts its opposite.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    concept_id: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=3, max_length=200)
    dimension: ConceptDimension = ConceptDimension.TECHNICAL
    weight: float = Field(default=1.0, gt=0, le=10)
    required: bool = False
    keywords: list[str] = Field(min_length=1, max_length=30)
    negation_patterns: list[str] = Field(default_factory=list, max_length=20)
    study_hint: str = Field(default="", max_length=400)


class IncorrectStatementSchema(BaseModel):
    """A statement that is known to be wrong for this question.

    Every SAP interview has a handful of confident, plausible, wrong answers.
    Naming them in the bank is what lets the coach say "this part is incorrect"
    instead of only "this part is missing" - and it costs technical accuracy
    points, which is the only dimension a wrong statement should touch.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    statement_id: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=3, max_length=300)
    patterns: list[str] = Field(min_length=1, max_length=20)
    correction: str = Field(min_length=3, max_length=600)
    penalty_points: float = Field(default=10.0, ge=0, le=100)


class FollowUpSchema(BaseModel):
    """One suggested follow-up question.

    ``targets_concept_id`` is what makes the follow-up chosen for an answer
    rather than picked off the top of a list: the coach asks about the highest
    weighted concept the candidate missed.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=5, max_length=500)
    targets_concept_id: str | None = Field(default=None, max_length=60)


class RubricSchema(BaseModel):
    """The explicit rubric a question is marked against."""

    model_config = ConfigDict(str_strip_whitespace=True)

    summary: str = Field(default="", max_length=600)
    #: Per-question dimension weights. Empty means "use the mode/global
    #: weights", which is the normal case.
    weights: dict[ScoreDimension, float] = Field(default_factory=dict)
    pass_score: float | None = Field(default=None, ge=0, le=100)

    @field_validator("weights")
    @classmethod
    def _positive_weights(cls, value: dict[ScoreDimension, float]) -> dict[ScoreDimension, float]:
        for dimension, weight in value.items():
            if weight <= 0:
                raise ValueError(f"rubric weight for '{dimension.value}' must be greater than zero")
        return value


class InterviewQuestionSchema(BaseModel):
    """One interview question **without** its answer key.

    This is what the candidate sees. The expected concepts, the reference answer
    and the known-wrong statements are deliberately absent: they arrive in
    :class:`AnswerKeySchema` once the answer has been submitted.
    """

    question_id: str
    track: InterviewTrack
    topic: str
    difficulty: QuestionDifficulty
    modes: list[InterviewMode] = Field(default_factory=list)
    question: str
    rubric_summary: str = ""
    #: How many concepts a complete answer covers. The candidate is told the
    #: number, never the list - it tells them how much to say without telling
    #: them what to say.
    expected_concept_count: int = 0
    time_limit_seconds: int | None = None
    tags: list[str] = Field(default_factory=list)


class AnswerKeySchema(BaseModel):
    """Everything the coach marked an answer against, revealed after answering."""

    question_id: str
    expected_concepts: list[ExpectedConceptSchema] = Field(default_factory=list)
    incorrect_statements: list[IncorrectStatementSchema] = Field(default_factory=list)
    follow_up_questions: list[FollowUpSchema] = Field(default_factory=list)
    reference_answer: str = ""
    rubric: RubricSchema = Field(default_factory=RubricSchema)
    study_topics: list[str] = Field(default_factory=list)


class BankQuestionSchema(BaseModel):
    """One complete question as it is stored in the bundled question bank."""

    model_config = ConfigDict(str_strip_whitespace=True)

    question_id: str = Field(min_length=3, max_length=40)
    track: InterviewTrack
    topic: str = Field(min_length=2, max_length=120)
    difficulty: QuestionDifficulty
    modes: list[InterviewMode] = Field(min_length=1)
    question: str = Field(min_length=15, max_length=1200)
    expected_concepts: list[ExpectedConceptSchema] = Field(min_length=1, max_length=15)
    incorrect_statements: list[IncorrectStatementSchema] = Field(
        default_factory=list, max_length=10
    )
    follow_up_questions: list[FollowUpSchema] = Field(default_factory=list, max_length=8)
    reference_answer: str = Field(min_length=40, max_length=4000)
    rubric: RubricSchema = Field(default_factory=RubricSchema)
    study_topics: list[str] = Field(default_factory=list, max_length=10)
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("modes")
    @classmethod
    def _dedupe_modes(cls, value: list[InterviewMode]) -> list[InterviewMode]:
        seen: set[InterviewMode] = set()
        return [item for item in value if not (item in seen or seen.add(item))]


class QuestionBankSchema(BaseModel):
    """The bundled question bank, validated as a whole."""

    bank_version: str = Field(min_length=1, max_length=40)
    description: str = ""
    manifest: str | None = None
    questions: list[BankQuestionSchema] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class StartInterviewRequest(BaseModel):
    """Start an interview session."""

    model_config = ConfigDict(str_strip_whitespace=True)

    #: The tracks to draw questions from, **in the order the caller listed
    #: them**. When fewer questions are asked for than tracks are requested,
    #: the tracks listed last are the ones that go without a question.
    tracks: list[InterviewTrack] = Field(min_length=1, max_length=len(TRACK_ORDER))
    mode: InterviewMode = InterviewMode.PRACTICE
    difficulties: list[QuestionDifficulty] = Field(
        default_factory=list, max_length=len(DIFFICULTY_ORDER)
    )
    question_count: int | None = Field(default=None, ge=1, le=50)
    candidate_name: str | None = Field(default=None, max_length=120)
    session_name: str | None = Field(default=None, max_length=200)
    topics: list[str] = Field(default_factory=list, max_length=20)
    #: Seeds the deterministic selection. The same seed, tracks, mode and
    #: difficulties always produce the same question list, which is what makes
    #: a demo repeatable and a test meaningful.
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)

    @field_validator("tracks", "difficulties")
    @classmethod
    def _dedupe(cls, value: list[Any]) -> list[Any]:
        seen: set[Any] = set()
        return [item for item in value if not (item in seen or seen.add(item))]

    @field_validator("topics", mode="before")
    @classmethod
    def _clean_topics(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.splitlines()
        if isinstance(value, list):
            return [str(item).strip()[:120] for item in value if str(item).strip()]
        return value


class SubmitAnswerRequest(BaseModel):
    """Submit an answer to one question in a session."""

    model_config = ConfigDict(str_strip_whitespace=True)

    #: Omit to answer the session's next pending question.
    question_id: str | None = Field(default=None, max_length=40)
    answer_text: str = Field(min_length=1, max_length=20_000)
    #: Measured by the client. When absent the server derives it from when the
    #: previous answer was recorded, or from the session start.
    seconds_spent: int | None = Field(default=None, ge=0, le=24 * 3600)
    #: When false no provider is called at all. The scores are identical either
    #: way; only the feedback prose changes.
    use_ai: bool = True


class CompleteInterviewRequest(BaseModel):
    """Complete an interview session."""

    model_config = ConfigDict(str_strip_whitespace=True)

    #: Mark the session abandoned rather than completed. Both freeze it; only
    #: the label differs, and the dashboard counts them separately.
    abandoned: bool = False
    notes: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class ConceptMatchSchema(BaseModel):
    """Whether one expected concept was found in the answer, and where."""

    concept_id: str
    label: str
    dimension: ConceptDimension
    weight: float = 1.0
    required: bool = False
    matched: bool = False
    #: The keyword that matched, so a candidate can see why a concept counted.
    matched_keyword: str | None = None
    #: A short window of the answer around the match.
    excerpt: str | None = None
    #: Set when a keyword was present but vetoed by a negation in its clause.
    negated: bool = False
    study_hint: str = ""


class IncorrectStatementMatchSchema(BaseModel):
    """One known-wrong statement the answer made."""

    statement_id: str
    label: str
    correction: str
    penalty_points: float = 0.0
    excerpt: str | None = None


class DimensionScoreSchema(BaseModel):
    """One dimension of the score, with the arithmetic that produced it."""

    dimension: ScoreDimension
    #: ``None`` means "not applicable to this question" - never zero.
    score: float | None = None
    weight: float = 0.0
    applicable: bool = True
    band: PerformanceBand | None = None
    explanation: str = ""
    #: How many concepts fed this dimension, and how many were found.
    concepts_expected: int = 0
    concepts_matched: int = 0


class ClarityBreakdownSchema(BaseModel):
    """How the clarity score was reached, in numbers a reader can re-check."""

    word_count: int = 0
    sentence_count: int = 0
    average_sentence_words: float = 0.0
    structure_markers: int = 0
    filler_hits: list[str] = Field(default_factory=list)
    length_score: float = 0.0
    sentence_score: float = 0.0
    structure_score: float = 0.0
    filler_penalty: float = 0.0


class AnswerFeedbackSchema(BaseModel):
    """The prose half of the feedback, always labelled with its origin."""

    strengths: list[str] = Field(default_factory=list)
    missing_concepts: list[str] = Field(default_factory=list)
    incorrect_statements: list[str] = Field(default_factory=list)
    improved_sample_answer: str = ""
    follow_up_question: str | None = None
    topics_to_study: list[str] = Field(default_factory=list)
    coaching_note: str = ""
    source: FeedbackSource = FeedbackSource.TEMPLATE
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_prompt_version: str | None = None
    ai_error: str | None = None
    #: What the deterministic repair had to fix in the drafted prose.
    validation_notes: list[str] = Field(default_factory=list)


class AnswerScoreSchema(BaseModel):
    """The complete, deterministic score of one answer."""

    overall_score: float = 0.0
    overall_band: PerformanceBand = PerformanceBand.NEEDS_WORK
    passed: bool = False
    pass_score: float = 0.0
    dimensions: list[DimensionScoreSchema] = Field(default_factory=list)
    concept_matches: list[ConceptMatchSchema] = Field(default_factory=list)
    incorrect_statement_matches: list[IncorrectStatementMatchSchema] = Field(
        default_factory=list
    )
    clarity: ClarityBreakdownSchema = Field(default_factory=ClarityBreakdownSchema)
    #: Set when the answer was one of the configured non-answers ("I don't
    #: know"). Everything scores zero and the reason is stated rather than
    #: dressed up as a low mark.
    non_answer: bool = False
    scoring_notes: list[str] = Field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED

    # -- convenience accessors used by clients and by the export layer ----
    def dimension_score(self, dimension: ScoreDimension) -> float | None:
        """Return one dimension's score, or ``None`` when not applicable."""
        for item in self.dimensions:
            if item.dimension is dimension:
                return item.score
        return None

    @property
    def technical_accuracy_score(self) -> float | None:
        return self.dimension_score(ScoreDimension.TECHNICAL_ACCURACY)

    @property
    def completeness_score(self) -> float | None:
        return self.dimension_score(ScoreDimension.COMPLETENESS)

    @property
    def clarity_score(self) -> float | None:
        return self.dimension_score(ScoreDimension.CLARITY)

    @property
    def business_understanding_score(self) -> float | None:
        return self.dimension_score(ScoreDimension.BUSINESS_UNDERSTANDING)

    @property
    def architecture_score(self) -> float | None:
        return self.dimension_score(ScoreDimension.ARCHITECTURE)


class InterviewAnswerSchema(BaseModel):
    """One question in a session, with the answer and everything it produced."""

    answer_id: str
    session_id: str
    position: int
    question: InterviewQuestionSchema
    status: AnswerStatus = AnswerStatus.PENDING

    answer_text: str = ""
    seconds_spent: int = 0
    time_limit_seconds: int | None = None
    within_time_limit: bool = True
    over_by_seconds: int = 0
    attempt_count: int = 0

    score: AnswerScoreSchema | None = None
    feedback: AnswerFeedbackSchema | None = None
    #: Revealed only once the question has been answered.
    answer_key: AnswerKeySchema | None = None

    #: True when the rubric this score was computed against has changed since.
    #: The score is kept - somebody really earned it - and flagged, because it
    #: is a verdict about a rubric that no longer exists.
    scoring_is_stale: bool = False
    rubric_fingerprint: str = ""
    question_bank_version: str = ""

    injection_detected: bool = False
    injection_markers: list[str] = Field(default_factory=list)

    asked_at: datetime | None = None
    answered_at: datetime | None = None


class SessionSummarySchema(BaseModel):
    """Everything a summary screen shows without walking the answer list."""

    question_count: int = 0
    answered_count: int = 0
    pending_count: int = 0
    average_score: float | None = None
    best_score: float | None = None
    lowest_score: float | None = None
    passed_count: int = 0
    average_by_dimension: dict[str, float] = Field(default_factory=dict)
    average_by_topic: dict[str, float] = Field(default_factory=dict)
    average_by_difficulty: dict[str, float] = Field(default_factory=dict)
    band: PerformanceBand | None = None
    total_seconds_spent: int = 0
    average_seconds_per_answer: float | None = None
    over_time_count: int = 0
    #: Scores whose rubric has since been retuned. Counted separately so a
    #: reader can see how much of the average rests on an old marking scheme.
    stale_score_count: int = 0
    strong_topics: list[str] = Field(default_factory=list)
    weak_topics: list[str] = Field(default_factory=list)
    most_missed_concepts: list[str] = Field(default_factory=list)
    recommended_study_topics: list[str] = Field(default_factory=list)


class InterviewSessionSchema(BaseModel):
    """One interview session with its questions, answers and summary."""

    session_id: str
    name: str
    candidate_name: str = ""
    tracks: list[InterviewTrack] = Field(default_factory=list)
    mode: InterviewMode = InterviewMode.PRACTICE
    difficulties: list[QuestionDifficulty] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    requested_question_count: int = 0
    seed: int | None = None
    status: SessionStatus = SessionStatus.IN_PROGRESS

    time_limit_seconds: int | None = None
    summary: SessionSummarySchema = Field(default_factory=SessionSummarySchema)
    answers: list[InterviewAnswerSchema] = Field(default_factory=list)
    #: The next question to put on screen, or ``None`` when none is pending.
    next_question: InterviewQuestionSchema | None = None

    #: Tracks that were requested but that no question could be drawn for.
    uncovered_tracks: list[InterviewTrack] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    question_bank_version: str = ""
    config_version: str = "0.0.0"
    engine_version: str = "0.0.0"
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED

    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SubmitAnswerResponse(BaseModel):
    """What comes back from submitting one answer."""

    session_id: str
    answer: InterviewAnswerSchema
    next_question: InterviewQuestionSchema | None = None
    remaining_questions: int = 0
    summary: SessionSummarySchema = Field(default_factory=SessionSummarySchema)


class SessionListItemSchema(BaseModel):
    """One row of the session list."""

    session_id: str
    name: str
    candidate_name: str = ""
    tracks: list[InterviewTrack] = Field(default_factory=list)
    mode: InterviewMode = InterviewMode.PRACTICE
    status: SessionStatus = SessionStatus.IN_PROGRESS
    question_count: int = 0
    answered_count: int = 0
    average_score: float | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class SessionListResponse(BaseModel):
    """Paginated session list."""

    total: int
    limit: int
    offset: int
    sessions: list[SessionListItemSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Performance dashboard
# ---------------------------------------------------------------------------


class TopicPerformanceSchema(BaseModel):
    """How one topic is going across every answer in scope."""

    topic: str
    track: InterviewTrack | None = None
    answer_count: int = 0
    average_score: float = 0.0
    best_score: float = 0.0
    lowest_score: float = 0.0
    band: PerformanceBand = PerformanceBand.NEEDS_WORK
    #: False when fewer answers exist than the configured minimum. The topic is
    #: still listed with its average, but it is never called a weakness on the
    #: strength of one answer.
    has_enough_answers: bool = False
    most_missed_concepts: list[str] = Field(default_factory=list)


class DifficultyPerformanceSchema(BaseModel):
    """How one difficulty level is going."""

    difficulty: QuestionDifficulty
    answer_count: int = 0
    average_score: float = 0.0
    band: PerformanceBand = PerformanceBand.NEEDS_WORK


class TrackPerformanceSchema(BaseModel):
    """How one track is going."""

    track: InterviewTrack
    answer_count: int = 0
    average_score: float = 0.0
    band: PerformanceBand = PerformanceBand.NEEDS_WORK


class DimensionPerformanceSchema(BaseModel):
    """How one score dimension is going across every answer in scope."""

    dimension: ScoreDimension
    answer_count: int = 0
    average_score: float = 0.0
    band: PerformanceBand = PerformanceBand.NEEDS_WORK


class ScoreOverTimePointSchema(BaseModel):
    """One point on the score-over-time series: one session."""

    session_id: str
    session_name: str = ""
    mode: InterviewMode = InterviewMode.PRACTICE
    tracks: list[InterviewTrack] = Field(default_factory=list)
    answered_count: int = 0
    average_score: float = 0.0
    recorded_at: datetime | None = None


class StudyPlanItemSchema(BaseModel):
    """One recommended piece of study, and why it was recommended."""

    priority: int = 1
    topic: str
    track: InterviewTrack | None = None
    average_score: float = 0.0
    answer_count: int = 0
    reason: str = ""
    actions: list[str] = Field(default_factory=list)
    #: The concepts most often missed on this topic, from the recorded answers.
    focus_concepts: list[str] = Field(default_factory=list)
    suggested_difficulty: QuestionDifficulty | None = None


class PerformanceDashboardSchema(BaseModel):
    """The complete performance dashboard payload."""

    session_count: int = 0
    completed_session_count: int = 0
    answer_count: int = 0
    average_score: float | None = None
    band: PerformanceBand | None = None
    total_seconds_spent: int = 0
    #: Scores computed against a rubric that has since been retuned. They are
    #: included in every average above and counted here, so nothing silently
    #: disappears and nothing silently misleads.
    stale_score_count: int = 0

    by_dimension: list[DimensionPerformanceSchema] = Field(default_factory=list)
    by_topic: list[TopicPerformanceSchema] = Field(default_factory=list)
    by_difficulty: list[DifficultyPerformanceSchema] = Field(default_factory=list)
    by_track: list[TrackPerformanceSchema] = Field(default_factory=list)
    score_over_time: list[ScoreOverTimePointSchema] = Field(default_factory=list)
    weak_areas: list[TopicPerformanceSchema] = Field(default_factory=list)
    strong_areas: list[TopicPerformanceSchema] = Field(default_factory=list)
    study_plan: list[StudyPlanItemSchema] = Field(default_factory=list)
    recent_sessions: list[SessionListItemSchema] = Field(default_factory=list)

    filters: dict[str, Any] = Field(default_factory=dict)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


class TrackInfoSchema(BaseModel):
    """One supported track, as the UI should describe it."""

    track: InterviewTrack
    label: str
    description: str = ""
    topics: list[str] = Field(default_factory=list)
    question_count: int = 0


class ModeInfoSchema(BaseModel):
    """One supported interview mode, with its deterministic settings."""

    mode: InterviewMode
    label: str
    description: str = ""
    default_question_count: int = 5
    time_limit_seconds: int | None = None
    timer_enabled: bool = False
    difficulty_mix: list[QuestionDifficulty] = Field(default_factory=list)
    dimension_weights: dict[str, float] = Field(default_factory=dict)
    question_count: int = 0


class InterviewCatalogueSchema(BaseModel):
    """Everything a client needs to render the setup form and the score cards."""

    config_version: str
    engine_version: str
    question_bank_version: str = ""
    question_count: int = 0
    tracks: list[TrackInfoSchema] = Field(default_factory=list)
    modes: list[ModeInfoSchema] = Field(default_factory=list)
    difficulties: list[QuestionDifficulty] = Field(default_factory=list)
    dimensions: list[ScoreDimension] = Field(default_factory=list)
    bands: dict[str, float] = Field(default_factory=dict)
    max_questions_per_session: int = 25
    pass_score: float = 60.0
    methodology: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str = ""


class QuestionBankInfoSchema(BaseModel):
    """Describes the bundled fictional question bank."""

    available: bool = False
    bank_version: str = ""
    question_count: int = 0
    by_track: dict[str, int] = Field(default_factory=dict)
    by_difficulty: dict[str, int] = Field(default_factory=dict)
    by_mode: dict[str, int] = Field(default_factory=dict)
    topics: list[str] = Field(default_factory=list)
    manifest: str | None = None


class QuestionListResponse(BaseModel):
    """A page of questions from the bank, always without their answer keys."""

    total: int
    limit: int
    offset: int
    questions: list[InterviewQuestionSchema] = Field(default_factory=list)
