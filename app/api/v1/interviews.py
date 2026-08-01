"""HTTP routes for the SAP Interview Coach.

Routes stay thin: validate input, call the service layer, wrap the result in the
shared envelope. All business logic lives in ``app/modules/interview_coach``.

The five routes the module is specified around:

* ``POST /interviews/start``                  - start a session and serve question 1
* ``GET  /interviews/{session_id}``           - the session, its answers and its summary
* ``POST /interviews/{session_id}/answer``    - mark one answer and serve the next question
* ``POST /interviews/{session_id}/complete``  - close the session and return the summary
* ``GET  /interviews/performance``            - the performance dashboard

plus the endpoints a usable interview screen needs: the catalogue that lets a
client render the setup form and the score cards, a browsable view of the
question bank, the session list, and the active AI provider.

Route order matters here: the static paths (``/start``, ``/performance``,
``/catalog``, ``/questions``, ``/ai-status``, ``/bank/info``) are declared before
``/{session_id}``, otherwise FastAPI would match "performance" as a session id.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.openapi import COMMON_ERROR_RESPONSES
from app.core.logging import get_logger
from app.models.session import get_db
from app.modules.interview_coach import service
from app.schemas.common import ApiResponse
from app.schemas.interview_coach import (
    CompleteInterviewRequest,
    InterviewCatalogueSchema,
    InterviewMode,
    InterviewSessionSchema,
    InterviewTrack,
    PerformanceDashboardSchema,
    QuestionBankInfoSchema,
    QuestionDifficulty,
    QuestionListResponse,
    SessionListResponse,
    StartInterviewRequest,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)
from app.services.ai.factory import describe_active_provider

logger = get_logger(__name__)

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(
    prefix="/interviews",
    tags=["SAP Interview Coach"],
    # The error shapes every route in this module can return, documented
    # once so a generated client writes its error handling against the
    # contract rather than against whatever it happened to hit first.
    responses=COMMON_ERROR_RESPONSES,
)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


@router.post(
    "/start",
    response_model=ApiResponse[InterviewSessionSchema],
    status_code=201,
    summary="Start an interview session",
)
def start(
    db: DbSession, request: StartInterviewRequest
) -> ApiResponse[InterviewSessionSchema]:
    """Start an interview and serve the first question.

    The question list is drawn from the bundled bank by a seeded, deterministic
    selection: the same tracks, mode, difficulties and seed always produce the
    same interview. The questions come back **without** their marking schemes;
    each answer key is attached to the answer once it has been submitted.
    """
    return ApiResponse.ok(service.start_session(db, request))


# ---------------------------------------------------------------------------
# Static paths (declared before /{session_id})
# ---------------------------------------------------------------------------


@router.get(
    "/performance",
    response_model=ApiResponse[PerformanceDashboardSchema],
    summary="Performance dashboard across sessions",
)
def performance(
    db: DbSession,
    track: Annotated[list[InterviewTrack] | None, Query()] = None,
    mode: InterviewMode | None = None,
    session_limit: Annotated[int | None, Query(ge=1, le=500)] = None,
) -> ApiResponse[PerformanceDashboardSchema]:
    """Return average score, breakdowns, trends, weak areas and the study plan.

    Every figure is calculated from the recorded answers by deterministic
    Python, including the study plan: the topics it names are the ones with the
    lowest recorded averages and the concepts it names are the ones those
    answers actually missed.
    """
    return ApiResponse.ok(
        service.performance(db, tracks=track, mode=mode, session_limit=session_limit)
    )


@router.get(
    "/catalog",
    response_model=ApiResponse[InterviewCatalogueSchema],
    summary="Tracks, modes, bands and the marking rules",
)
def catalog() -> ApiResponse[InterviewCatalogueSchema]:
    """Return the tracks, modes, difficulties, bands and the published rubric."""
    return ApiResponse.ok(service.get_catalogue())


@router.get(
    "/questions",
    response_model=ApiResponse[QuestionListResponse],
    summary="Browse the question bank",
)
def questions(
    track: Annotated[list[InterviewTrack] | None, Query()] = None,
    mode: InterviewMode | None = None,
    difficulty: Annotated[list[QuestionDifficulty] | None, Query()] = None,
    topic: Annotated[list[str] | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[QuestionListResponse]:
    """List questions from the bundled bank.

    Answer keys are never included, whatever the filters say: this endpoint
    exists so a candidate can see what a track covers, not so they can revise
    the marking scheme.
    """
    return ApiResponse.ok(
        service.list_questions(
            tracks=track,
            mode=mode,
            difficulties=difficulty,
            topics=topic,
            limit=limit,
            offset=offset,
        )
    )


@router.get(
    "/bank/info",
    response_model=ApiResponse[QuestionBankInfoSchema],
    summary="Describe the bundled question bank",
)
def bank_info() -> ApiResponse[QuestionBankInfoSchema]:
    """Describe the bundled, entirely fictional question bank."""
    return ApiResponse.ok(service.bank_info())


@router.get(
    "/ai-status", response_model=ApiResponse[dict[str, Any]], summary="Active AI provider"
)
def ai_status() -> ApiResponse[dict[str, Any]]:
    """Report which AI provider is active. API keys are never included."""
    return ApiResponse.ok(describe_active_provider())


@router.get(
    "/sessions",
    response_model=ApiResponse[SessionListResponse],
    summary="List interview sessions",
)
def list_sessions(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[SessionListResponse]:
    """Return interview sessions, newest first."""
    total, sessions = service.list_sessions(db, limit=limit, offset=offset)
    return ApiResponse.ok(
        SessionListResponse(total=total, limit=limit, offset=offset, sessions=sessions)
    )


# ---------------------------------------------------------------------------
# One session
# ---------------------------------------------------------------------------


@router.get(
    "/{session_id}",
    response_model=ApiResponse[InterviewSessionSchema],
    summary="Get one interview session",
)
def get_session(db: DbSession, session_id: str) -> ApiResponse[InterviewSessionSchema]:
    """Return the session with every question asked, answer given and score."""
    return ApiResponse.ok(service.get_session(db, session_id))


@router.post(
    "/{session_id}/answer",
    response_model=ApiResponse[SubmitAnswerResponse],
    summary="Submit an answer and get the feedback",
)
def submit_answer(
    db: DbSession, session_id: str, request: SubmitAnswerRequest
) -> ApiResponse[SubmitAnswerResponse]:
    """Mark one answer against its rubric and serve the next question.

    Every number in the response - the overall score, each dimension, the band,
    the pass verdict - is produced by deterministic Python from the question's
    rubric. ``use_ai`` decides only who writes the coaching prose; the scores are
    identical with a provider, with the mock and with ``use_ai=false``.
    """
    return ApiResponse.ok(service.submit_answer(db, session_id, request))


@router.post(
    "/{session_id}/complete",
    response_model=ApiResponse[InterviewSessionSchema],
    summary="Complete an interview session",
)
def complete(
    db: DbSession, session_id: str, request: CompleteInterviewRequest | None = None
) -> ApiResponse[InterviewSessionSchema]:
    """Close the session and return it with its final summary.

    Completing with questions unanswered is allowed and reported: the summary
    carries ``pending_count`` and every average is over what was answered.
    """
    return ApiResponse.ok(
        service.complete_session(db, session_id, request or CompleteInterviewRequest())
    )
