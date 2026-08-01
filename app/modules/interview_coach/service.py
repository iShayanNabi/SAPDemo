"""Orchestration and persistence for the SAP Interview Coach.

This is the only layer that knows about the database. It wires the pure pieces
together in one direction:

    request -> seeded question selection -> serve one question at a time
    -> rubric score -> optional coaching prose -> persist -> summarise
    -> aggregate across sessions into the performance dashboard

Four rules run through everything below:

* **A question is served without its answer key.** While a question is pending,
  the API returns the question text and its metadata. The expected concepts, the
  reference answer and the known-wrong statements are attached to the *answer*,
  after it has been submitted. Anything else is an open-book test that calls
  itself an interview.
* **A completed session is frozen.** Answers can be revised while an interview
  is in progress - that is what practice is - but not after it has been
  completed, so a summary can never describe answers that changed underneath it.
* **The question is copied onto the answer as it is served.** The bundled bank
  is demo content and gets regenerated. A session recorded against an older bank
  still reads correctly, and its topic still aggregates.
* **A score is a verdict about a rubric.** The rubric fingerprint travels with
  the score. When the bank is retuned, old answers report ``scoring_is_stale``
  rather than silently averaging alongside answers marked under different rules.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.rounding import decimal_mean
from app.models.interview_coach import InterviewAnswer, InterviewSession
from app.modules.interview_coach.engine import ENGINE_VERSION, evaluate_answer, timing_for
from app.modules.interview_coach.performance import (
    AnswerRecord,
    SessionRecord,
    build_dashboard,
    summarise_answers,
)
from app.modules.interview_coach.question_bank import (
    MANIFEST_FILE,
    QuestionBank,
    get_question_bank,
)
from app.modules.interview_coach.selection import plan_questions
from app.modules.interview_coach.thresholds import (
    InterviewCoachConfig,
    get_interview_config,
)
from app.schemas.common import OutputOrigin
from app.schemas.interview_coach import (
    DIFFICULTY_ORDER,
    DIMENSION_ORDER,
    MODE_ORDER,
    TRACK_ORDER,
    AnswerFeedbackSchema,
    AnswerScoreSchema,
    AnswerStatus,
    CompleteInterviewRequest,
    InterviewAnswerSchema,
    InterviewCatalogueSchema,
    InterviewMode,
    InterviewQuestionSchema,
    InterviewSessionSchema,
    InterviewTrack,
    ModeInfoSchema,
    PerformanceDashboardSchema,
    QuestionBankInfoSchema,
    QuestionDifficulty,
    QuestionListResponse,
    SessionListItemSchema,
    SessionStatus,
    SessionSummarySchema,
    StartInterviewRequest,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    TrackInfoSchema,
)

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex[:32]


def _as_utc(value: datetime | None) -> datetime | None:
    """Return an aware UTC datetime.

    SQLite gives naive datetimes back even for ``DateTime(timezone=True)``
    columns, so subtracting one from :func:`_now` would raise. Everything this
    module writes is UTC, so an unlabelled value is labelled rather than
    converted.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


def start_session(db: Session, request: StartInterviewRequest) -> InterviewSessionSchema:
    """Start an interview session and serve its first question."""
    config = get_interview_config()
    bank = get_question_bank()
    mode_settings = config.mode(request.mode)

    plan = plan_questions(
        bank,
        config,
        tracks=request.tracks,
        mode=request.mode,
        difficulties=request.difficulties or None,
        question_count=request.question_count,
        topics=request.topics or None,
        seed=request.seed,
    )
    if not plan.questions:
        raise ValidationError(
            "No question in the bundled bank matches this request. Try another mode, add a "
            "track, or clear the difficulty and topic filters.",
            details={
                "tracks": [track.value for track in request.tracks],
                "mode": request.mode.value,
                "difficulties": [item.value for item in request.difficulties],
                "topics": list(request.topics),
            },
        )

    started = _now()
    session = InterviewSession(
        id=_new_id(),
        name=(
            request.session_name
            or f"{mode_settings.label} - {', '.join(track.value for track in request.tracks[:3])}"
        )[:200],
        candidate_name=request.candidate_name or "",
        tracks=[track.value for track in request.tracks],
        mode=request.mode.value,
        difficulties=[item.value for item in plan.effective_difficulties],
        topics=list(request.topics),
        requested_question_count=request.question_count
        or mode_settings.default_question_count,
        seed=plan.seed,
        status=SessionStatus.IN_PROGRESS.value,
        time_limit_seconds=mode_settings.time_limit_seconds,
        uncovered_tracks=[track.value for track in plan.uncovered_tracks],
        notes=list(plan.notes),
        question_bank_version=bank.bank_version,
        config_version=config.config_version,
        engine_version=ENGINE_VERSION,
        started_at=started,
    )
    db.add(session)
    db.flush()

    for position, question in enumerate(plan.questions, start=1):
        db.add(
            InterviewAnswer(
                id=_new_id(),
                session_id=session.id,
                position=position,
                question_id=question.question_id,
                track=question.track.value,
                topic=question.topic,
                difficulty=question.difficulty.value,
                question_text=question.question,
                status=AnswerStatus.PENDING.value,
                time_limit_seconds=mode_settings.time_limit_seconds,
                question_bank_version=bank.bank_version,
                # Only the first question is on screen, so only the first one
                # has been asked. The rest are stamped as they are served.
                asked_at=started if position == 1 else None,
            )
        )

    db.commit()
    db.refresh(session)
    logger.info(
        "Started interview session %s: %d question(s), mode '%s', seed %d",
        session.id,
        len(plan.questions),
        session.mode,
        session.seed,
    )
    return _session_schema(db, session, config, bank)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_session(db: Session, session_id: str) -> InterviewSessionSchema:
    """Return one session with its questions, answers and summary."""
    return _session_schema(
        db, _require_session(db, session_id), get_interview_config(), get_question_bank()
    )


def list_sessions(
    db: Session, *, limit: int = 20, offset: int = 0
) -> tuple[int, list[SessionListItemSchema]]:
    """Return sessions, newest first."""
    total = int(db.execute(select(func.count(InterviewSession.id))).scalar_one())
    rows = (
        db.execute(
            select(InterviewSession)
            .order_by(InterviewSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return total, [_list_item(db, session) for session in rows]


# ---------------------------------------------------------------------------
# Answer
# ---------------------------------------------------------------------------


def submit_answer(
    db: Session, session_id: str, request: SubmitAnswerRequest
) -> SubmitAnswerResponse:
    """Mark one answer, record it and serve the next question.

    Answering a question that has already been answered is allowed while the
    session is in progress: practising the same question twice is the point of
    practice mode. The attempt counter goes up and the new score replaces the
    old one, because a session reporting two scores for one question would have
    to choose one of them to average, and neither choice is defensible.
    """
    config = get_interview_config()
    bank = get_question_bank()
    session = _require_session(db, session_id)

    if session.status != SessionStatus.IN_PROGRESS.value:
        raise ValidationError(
            "This interview session has been closed, so no further answers can be recorded. "
            "Start a new session to practise these questions again.",
            details={"session_id": session_id, "status": session.status},
        )

    row = _resolve_answer_row(db, session, request.question_id)
    question = bank.find(row.question_id)
    if question is None:
        raise NotFoundError(
            "This question is no longer in the bundled question bank, so the answer cannot "
            "be marked against its rubric.",
            details={"question_id": row.question_id},
        )

    mode = InterviewMode(session.mode)
    seconds = _seconds_spent(row, session, request.seconds_spent)
    within, over_by = timing_for(seconds, row.time_limit_seconds)

    evaluation = evaluate_answer(
        question,
        request.answer_text,
        config,
        mode=mode,
        use_ai=request.use_ai,
    )

    now = _now()
    row.status = AnswerStatus.ANSWERED.value
    row.answer_text = request.answer_text
    row.seconds_spent = seconds
    row.within_time_limit = within
    row.over_by_seconds = over_by
    row.attempt_count = int(row.attempt_count or 0) + 1
    row.answered_at = now

    _write_score(row, evaluation.score, evaluation.feedback)
    row.rubric_fingerprint = bank.fingerprint(question.question_id)
    row.question_bank_version = bank.bank_version
    row.injection_detected = evaluation.injection_detected
    row.injection_markers = list(evaluation.injection_markers)
    row.ai_requested = evaluation.ai_requested
    row.ai_used = evaluation.ai_used
    row.ai_provider = evaluation.feedback.ai_provider
    row.ai_model = evaluation.feedback.ai_model
    row.ai_output_origin = (
        evaluation.feedback.output_origin.value if evaluation.ai_used else None
    )
    row.ai_prompt_version = evaluation.feedback.ai_prompt_version
    row.ai_input_tokens = evaluation.ai_input_tokens
    row.ai_output_tokens = evaluation.ai_output_tokens
    row.ai_estimated_cost_usd = evaluation.ai_estimated_cost_usd
    row.ai_error = evaluation.ai_error

    # Flush before asking which question is next. ``SessionLocal`` is built with
    # ``autoflush=False`` for the whole project, so without this the query still
    # sees the row above as pending and hands the candidate the question they
    # have just answered. Found by driving the API, not by a test: every count
    # in the response was right, and only the question itself was wrong.
    db.flush()

    # The next pending question is now on screen, so its clock starts here.
    next_row = _next_pending(db, session.id)
    if next_row is not None and next_row.asked_at is None:
        next_row.asked_at = now

    db.commit()
    db.refresh(row)

    rows = _rows_for(db, session.id)
    answered = [item for item in rows if item.status == AnswerStatus.ANSWERED.value]
    summary = summarise_answers(
        [_record(item, session, bank) for item in answered], len(rows), config
    )
    next_question = (
        _public_question(next_row, bank, session) if next_row is not None else None
    )

    logger.info(
        "Recorded answer to %s in session %s (attempt %d)",
        row.question_id,
        session.id,
        row.attempt_count,
    )
    return SubmitAnswerResponse(
        session_id=session.id,
        answer=_answer_schema(row, bank, config),
        next_question=next_question,
        remaining_questions=sum(
            1 for item in rows if item.status == AnswerStatus.PENDING.value
        ),
        summary=summary,
    )


def complete_session(
    db: Session, session_id: str, request: CompleteInterviewRequest
) -> InterviewSessionSchema:
    """Close a session and return it with its final summary.

    Completing a session with unanswered questions is allowed and reported: the
    summary carries ``pending_count``, and averages are over what was actually
    answered. Counting an unanswered question as zero would punish somebody for
    stopping early rather than describing what they did.
    """
    config = get_interview_config()
    bank = get_question_bank()
    session = _require_session(db, session_id)

    if session.status != SessionStatus.IN_PROGRESS.value:
        raise ValidationError(
            "This interview session has already been closed.",
            details={"session_id": session_id, "status": session.status},
        )

    session.status = (
        SessionStatus.ABANDONED.value if request.abandoned else SessionStatus.COMPLETED.value
    )
    session.completed_at = _now()
    if request.notes:
        session.notes = [*(session.notes or []), request.notes]

    pending = sum(
        1
        for row in _rows_for(db, session.id)
        if row.status == AnswerStatus.PENDING.value
    )
    if pending:
        session.notes = [
            *(session.notes or []),
            f"The session was closed with {pending} question(s) unanswered. Every average "
            "below is over the questions that were answered.",
        ]

    db.commit()
    db.refresh(session)
    logger.info("Closed interview session %s as '%s'", session.id, session.status)
    return _session_schema(db, session, config, bank)


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


def performance(
    db: Session,
    *,
    tracks: list[InterviewTrack] | None = None,
    mode: InterviewMode | None = None,
    session_limit: int | None = None,
) -> PerformanceDashboardSchema:
    """Aggregate every recorded answer into the performance dashboard."""
    config = get_interview_config()
    bank = get_question_bank()
    limit = session_limit or config.performance.default_session_window

    query = select(InterviewSession).order_by(InterviewSession.created_at.desc()).limit(limit)
    if mode is not None:
        query = query.where(InterviewSession.mode == mode.value)
    sessions = list(db.execute(query).scalars().all())

    wanted_tracks = {track.value for track in tracks} if tracks else None
    session_records: list[SessionRecord] = []
    answer_records: list[AnswerRecord] = []

    for session in sessions:
        rows = [
            row
            for row in _rows_for(db, session.id)
            if row.status == AnswerStatus.ANSWERED.value
            and (wanted_tracks is None or row.track in wanted_tracks)
        ]
        if wanted_tracks is not None and not rows:
            # A session that contributes no answer under these filters is not
            # part of this dashboard at all - counting it would make "sessions"
            # and "answers" describe different populations.
            continue
        session_records.append(
            SessionRecord(
                session_id=session.id,
                name=session.name,
                candidate_name=session.candidate_name or "",
                tracks=[InterviewTrack(name) for name in (session.tracks or [])],
                mode=InterviewMode(session.mode),
                status=SessionStatus(session.status),
                question_count=len(_rows_for(db, session.id)),
                started_at=session.started_at,
                completed_at=session.completed_at,
            )
        )
        answer_records.extend(_record(row, session, bank) for row in rows)

    return build_dashboard(
        session_records,
        answer_records,
        config,
        filters={
            "tracks": [track.value for track in tracks] if tracks else [],
            "mode": mode.value if mode else None,
            "session_limit": limit,
        },
    )


# ---------------------------------------------------------------------------
# Catalogue and question browsing
# ---------------------------------------------------------------------------


def get_catalogue() -> InterviewCatalogueSchema:
    """Describe the tracks, the modes, the limits and the marking rules."""
    config = get_interview_config()
    bank = get_question_bank()
    info = bank.info()

    return InterviewCatalogueSchema(
        config_version=config.config_version,
        engine_version=ENGINE_VERSION,
        question_bank_version=bank.bank_version,
        question_count=len(bank.questions),
        tracks=[
            TrackInfoSchema(
                track=track,
                label=config.track(track).label,
                description=config.track(track).description,
                topics=bank.topics(track),
                question_count=info.by_track.get(track.value, 0),
            )
            for track in TRACK_ORDER
        ],
        modes=[
            ModeInfoSchema(
                mode=mode,
                label=config.mode(mode).label,
                description=config.mode(mode).description,
                default_question_count=config.mode(mode).default_question_count,
                time_limit_seconds=config.mode(mode).time_limit_seconds,
                timer_enabled=config.mode(mode).timer_enabled,
                difficulty_mix=list(config.mode(mode).difficulty_mix),
                dimension_weights={
                    dimension.value: weight
                    for dimension, weight in config.weights_for(
                        mode, list(DIMENSION_ORDER)
                    ).items()
                },
                question_count=info.by_mode.get(mode.value, 0),
            )
            for mode in MODE_ORDER
        ],
        difficulties=list(DIFFICULTY_ORDER),
        dimensions=list(DIMENSION_ORDER),
        bands=dict(config.scoring.bands),
        max_questions_per_session=config.selection.max_questions_per_session,
        pass_score=config.scoring.pass_score,
        methodology=config.methodology(),
        disclaimer=config.reporting.disclaimer,
    )


def bank_info() -> QuestionBankInfoSchema:
    """Describe the bundled fictional question bank."""
    info = get_question_bank().info()
    manifest_path = settings.sample_dir / MANIFEST_FILE
    if info.manifest is None and manifest_path.is_file():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        info.manifest = payload.get("manifest")
    return info


def list_questions(
    *,
    tracks: list[InterviewTrack] | None = None,
    mode: InterviewMode | None = None,
    difficulties: list[QuestionDifficulty] | None = None,
    topics: list[str] | None = None,
    limit: int = 25,
    offset: int = 0,
) -> QuestionListResponse:
    """Browse the question bank.

    The answer keys are never included, whatever the filters say. This endpoint
    exists so a candidate can see what a track covers, not so they can revise
    the marking scheme.
    """
    bank = get_question_bank()
    matches = bank.matching(
        tracks=tracks, mode=mode, difficulties=difficulties, topics=topics
    )
    page = matches[offset : offset + limit]
    return QuestionListResponse(
        total=len(matches),
        limit=limit,
        offset=offset,
        questions=[bank.public_question(question) for question in page],
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _require_session(db: Session, session_id: str) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise NotFoundError(
            "Interview session not found.", details={"session_id": session_id}
        )
    return session


def _rows_for(db: Session, session_id: str) -> list[InterviewAnswer]:
    return list(
        db.execute(
            select(InterviewAnswer)
            .where(InterviewAnswer.session_id == session_id)
            .order_by(InterviewAnswer.position)
        )
        .scalars()
        .all()
    )


def _next_pending(db: Session, session_id: str) -> InterviewAnswer | None:
    return (
        db.execute(
            select(InterviewAnswer)
            .where(
                InterviewAnswer.session_id == session_id,
                InterviewAnswer.status == AnswerStatus.PENDING.value,
            )
            .order_by(InterviewAnswer.position)
            .limit(1)
        )
        .scalars()
        .first()
    )


def _resolve_answer_row(
    db: Session, session: InterviewSession, question_id: str | None
) -> InterviewAnswer:
    """Find the row an answer belongs to, by question id or by turn."""
    if question_id:
        row = (
            db.execute(
                select(InterviewAnswer).where(
                    InterviewAnswer.session_id == session.id,
                    InterviewAnswer.question_id == question_id,
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            raise NotFoundError(
                "That question was not asked in this session.",
                details={"session_id": session.id, "question_id": question_id},
            )
        return row

    row = _next_pending(db, session.id)
    if row is None:
        raise ValidationError(
            "Every question in this session has been answered. Complete the session, or "
            "name the question you want to answer again.",
            details={"session_id": session.id},
        )
    return row


def _seconds_spent(
    row: InterviewAnswer, session: InterviewSession, supplied: int | None
) -> int:
    """Return the time to record against one answer.

    The client's measurement wins when it supplies one - it is the only thing
    that knows when the candidate actually started typing. When it does not, the
    time is derived from when the question was put on screen, and failing that
    from when the session started.
    """
    if supplied is not None:
        return supplied
    reference = _as_utc(row.asked_at) or _as_utc(session.started_at)
    if reference is None:
        return 0
    return max(0, int((_now() - reference).total_seconds()))


def _write_score(
    row: InterviewAnswer, score: AnswerScoreSchema, feedback: AnswerFeedbackSchema
) -> None:
    """Write the score and its indexed projections.

    The only place ``overall_score`` and ``passed`` are written. Everything that
    reads a score reads ``score_payload``.
    """
    row.score_payload = score.model_dump(mode="json")
    row.feedback_payload = feedback.model_dump(mode="json")
    row.overall_score = score.overall_score
    row.passed = score.passed
    row.missed_concepts = [
        match.label for match in score.concept_matches if not match.matched
    ]


def _is_stale(row: InterviewAnswer, bank: QuestionBank) -> bool:
    """Return ``True`` when the rubric has changed since this score was given."""
    if not row.rubric_fingerprint:
        return False
    return bank.fingerprint(row.question_id) != row.rubric_fingerprint


def _public_question(
    row: InterviewAnswer, bank: QuestionBank, session: InterviewSession
) -> InterviewQuestionSchema:
    """Return the candidate-facing question for one row.

    The live bank wins when it still holds the question, so a reworded question
    reads correctly. When the bank no longer has it, the copy taken when the
    question was served is used - a session must stay readable after the demo
    data is regenerated.
    """
    question = bank.find(row.question_id)
    if question is not None:
        return bank.public_question(question, time_limit_seconds=row.time_limit_seconds)
    return InterviewQuestionSchema(
        question_id=row.question_id,
        track=InterviewTrack(row.track),
        topic=row.topic,
        difficulty=QuestionDifficulty(row.difficulty),
        modes=[InterviewMode(session.mode)],
        question=row.question_text,
        rubric_summary="",
        expected_concept_count=0,
        time_limit_seconds=row.time_limit_seconds,
    )


def _answer_schema(
    row: InterviewAnswer, bank: QuestionBank, config: InterviewCoachConfig
) -> InterviewAnswerSchema:
    """Validate one stored row back into the API shape."""
    session = row.session
    answered = row.status == AnswerStatus.ANSWERED.value
    question = bank.find(row.question_id)

    return InterviewAnswerSchema(
        answer_id=row.id,
        session_id=row.session_id,
        position=row.position,
        question=_public_question(row, bank, session),
        status=AnswerStatus(row.status),
        answer_text=row.answer_text or "",
        seconds_spent=row.seconds_spent or 0,
        time_limit_seconds=row.time_limit_seconds,
        within_time_limit=bool(row.within_time_limit),
        over_by_seconds=row.over_by_seconds or 0,
        attempt_count=row.attempt_count or 0,
        score=(
            AnswerScoreSchema.model_validate(row.score_payload)
            if row.score_payload
            else None
        ),
        feedback=(
            AnswerFeedbackSchema.model_validate(row.feedback_payload)
            if row.feedback_payload
            else None
        ),
        # The marking scheme is attached only once the answer exists. Serving it
        # with a pending question would make the interview open-book.
        answer_key=bank.answer_key(question) if (answered and question) else None,
        scoring_is_stale=_is_stale(row, bank),
        rubric_fingerprint=row.rubric_fingerprint or "",
        question_bank_version=row.question_bank_version or "",
        injection_detected=bool(row.injection_detected),
        injection_markers=list(row.injection_markers or []),
        asked_at=row.asked_at,
        answered_at=row.answered_at,
    )


def _record(
    row: InterviewAnswer, session: InterviewSession, bank: QuestionBank
) -> AnswerRecord:
    """Flatten one answered row into the shape the aggregates work on."""
    payload = row.score_payload or {}
    dimensions = {
        item.get("dimension"): item.get("score")
        for item in payload.get("dimensions", [])
        if item.get("score") is not None
    }
    return AnswerRecord(
        session_id=row.session_id,
        question_id=row.question_id,
        track=InterviewTrack(row.track),
        topic=row.topic,
        difficulty=QuestionDifficulty(row.difficulty),
        mode=InterviewMode(session.mode),
        overall_score=float(payload.get("overall_score", 0.0)),
        dimension_scores={
            str(name): float(value) for name, value in dimensions.items() if name
        },
        missed_concepts=list(row.missed_concepts or []),
        seconds_spent=row.seconds_spent or 0,
        within_time_limit=bool(row.within_time_limit),
        scoring_is_stale=_is_stale(row, bank),
        passed=bool(payload.get("passed", False)),
        answered_at=row.answered_at,
    )


def _summary(
    db: Session, session: InterviewSession, config: InterviewCoachConfig, bank: QuestionBank
) -> SessionSummarySchema:
    rows = _rows_for(db, session.id)
    answered = [row for row in rows if row.status == AnswerStatus.ANSWERED.value]
    return summarise_answers(
        [_record(row, session, bank) for row in answered], len(rows), config
    )


def _list_item(db: Session, session: InterviewSession) -> SessionListItemSchema:
    rows = _rows_for(db, session.id)
    scores = [
        float((row.score_payload or {}).get("overall_score", 0.0))
        for row in rows
        if row.status == AnswerStatus.ANSWERED.value and row.score_payload
    ]
    return SessionListItemSchema(
        session_id=session.id,
        name=session.name,
        candidate_name=session.candidate_name or "",
        tracks=[InterviewTrack(name) for name in (session.tracks or [])],
        mode=InterviewMode(session.mode),
        status=SessionStatus(session.status),
        question_count=len(rows),
        answered_count=len(scores),
        average_score=decimal_mean(scores),
        started_at=session.started_at,
        completed_at=session.completed_at,
    )


def _session_schema(
    db: Session,
    session: InterviewSession,
    config: InterviewCoachConfig,
    bank: QuestionBank,
) -> InterviewSessionSchema:
    rows = _rows_for(db, session.id)
    answers = [_answer_schema(row, bank, config) for row in rows]
    pending = next(
        (row for row in rows if row.status == AnswerStatus.PENDING.value), None
    )
    origin = (
        OutputOrigin.MOCK_AI
        if any(row.ai_output_origin == OutputOrigin.MOCK_AI.value for row in rows)
        else OutputOrigin.RULE_BASED
    )

    return InterviewSessionSchema(
        session_id=session.id,
        name=session.name,
        candidate_name=session.candidate_name or "",
        tracks=[InterviewTrack(name) for name in (session.tracks or [])],
        mode=InterviewMode(session.mode),
        difficulties=[
            QuestionDifficulty(name) for name in (session.difficulties or [])
        ],
        topics=list(session.topics or []),
        requested_question_count=session.requested_question_count,
        seed=session.seed,
        status=SessionStatus(session.status),
        time_limit_seconds=session.time_limit_seconds,
        summary=_summary(db, session, config, bank),
        answers=answers,
        next_question=(
            _public_question(pending, bank, session) if pending is not None else None
        ),
        uncovered_tracks=[
            InterviewTrack(name) for name in (session.uncovered_tracks or [])
        ],
        notes=list(session.notes or []),
        question_bank_version=session.question_bank_version or "",
        config_version=session.config_version,
        engine_version=session.engine_version,
        # The scores are always rule-based; this labels the *session*, and it
        # says mock only when a mock provider actually wrote some prose.
        output_origin=origin,
        started_at=session.started_at,
        completed_at=session.completed_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


__all__ = [
    "bank_info",
    "complete_session",
    "get_catalogue",
    "get_session",
    "list_questions",
    "list_sessions",
    "performance",
    "start_session",
    "submit_answer",
]
