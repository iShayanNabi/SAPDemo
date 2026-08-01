"""ORM models for the SAP Interview Coach.

Two tables. Like module 8 this module has no upload, so it does not touch the
shared ``uploaded_files`` table: its input is typed into a form.

``interview_sessions``
    One row per interview: the request exactly as it was made, the seed that
    makes the question list reproducible, the versions everything was produced
    under, and when it started and finished.
``interview_answers``
    One row per question served, whether or not it was answered. The answer, the
    time it took, the complete score and the complete feedback live here.

Three storage decisions are worth reading before changing anything:

* **The question is copied onto the answer.** The track, topic, difficulty and
  question text are denormalised out of the bundled question bank. The bank is
  demo content that gets regenerated; a session recorded last month must still
  be readable, and a dashboard must still be able to say which topic an answer
  belonged to, after a question is reworded or removed entirely.
* **The score is stored once.** ``score_payload`` is the truth. ``overall_score``
  and ``passed`` exist only as indexed projections for ordering and filtering,
  are written in exactly one place, and are never read back as the answer - the
  API always rebuilds the score from the payload. Two columns that describe the
  same thing are how modules 8 and 9 each shipped a bug.
* **The rubric fingerprint is stored next to the score.** A score is a verdict
  about a rubric. When the bank is retuned, the fingerprint recorded here no
  longer matches the one the bank computes, and the answer reports
  ``scoring_is_stale`` instead of quietly averaging into a dashboard beside
  scores earned under different rules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UtcDateTime


class InterviewSession(Base, TimestampMixin):
    """One interview practice session."""

    __tablename__ = "interview_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    candidate_name: Mapped[str] = mapped_column(String(120), default="")

    # -- the request, exactly as it was made -------------------------------
    tracks: Mapped[list[str]] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    difficulties: Mapped[list[str]] = mapped_column(JSON, default=list)
    topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    requested_question_count: Mapped[int] = mapped_column(Integer, default=0)
    #: The seed the question list was drawn with. Recorded so the same interview
    #: can be reproduced exactly - by a demo, by a test, or by somebody who wants
    #: a second attempt at the questions they have just seen.
    seed: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(20), default="in_progress", index=True)
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    uncovered_tracks: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)

    question_bank_version: Mapped[str] = mapped_column(String(40), default="")
    config_version: Mapped[str] = mapped_column(String(20), default="0.0.0")
    engine_version: Mapped[str] = mapped_column(String(20), default="0.0.0")

    started_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime(), nullable=True, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime(), nullable=True, index=True
    )

    answers: Mapped[list[InterviewAnswer]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InterviewAnswer.position",
    )


class InterviewAnswer(Base, TimestampMixin):
    """One question served inside a session, with its answer and its score."""

    __tablename__ = "interview_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)

    # -- the question, copied out of the bank ------------------------------
    question_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    track: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    question_text: Mapped[str] = mapped_column(Text, default="")

    # -- the answer ---------------------------------------------------------
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    answer_text: Mapped[str] = mapped_column(Text, default="")
    seconds_spent: Mapped[int] = mapped_column(Integer, default=0)
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    within_time_limit: Mapped[bool] = mapped_column(Boolean, default=True)
    over_by_seconds: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)

    # -- the result ---------------------------------------------------------
    #: The complete :class:`AnswerScoreSchema`. This is the truth.
    score_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: The complete :class:`AnswerFeedbackSchema`.
    feedback_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: Indexed projections of ``score_payload``, written in one place only and
    #: never read back as the answer.
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    #: The concept labels this answer missed, kept flat so the dashboard can
    #: count them without unpacking every score payload it has ever stored.
    missed_concepts: Mapped[list[str]] = mapped_column(JSON, default=list)

    #: The fingerprint of the rubric this score was computed against.
    rubric_fingerprint: Mapped[str] = mapped_column(String(40), default="")
    question_bank_version: Mapped[str] = mapped_column(String(40), default="")

    injection_detected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    injection_markers: Mapped[list[str]] = mapped_column(JSON, default=list)

    # -- provenance of the feedback call (never the API key) ---------------
    ai_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_used: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ai_output_origin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    asked_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime(), nullable=True, index=True
    )

    session: Mapped[InterviewSession] = relationship(back_populates="answers")

    __table_args__ = (
        Index("ix_interview_answers_session_position", "session_id", "position"),
        Index(
            "uq_interview_answers_session_question",
            "session_id",
            "question_id",
            unique=True,
        ),
    )
