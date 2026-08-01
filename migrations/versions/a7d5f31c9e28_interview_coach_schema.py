"""interview coach schema

Revision ID: a7d5f31c9e28
Revises: f6c4e2a9b710
Create Date: 2026-08-01 00:59:11.402118
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7d5f31c9e28'
down_revision: Union[str, None] = 'f6c4e2a9b710'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('interview_sessions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('candidate_name', sa.String(length=120), nullable=False),
    sa.Column('tracks', sa.JSON(), nullable=False),
    sa.Column('mode', sa.String(length=30), nullable=False),
    sa.Column('difficulties', sa.JSON(), nullable=False),
    sa.Column('topics', sa.JSON(), nullable=False),
    sa.Column('requested_question_count', sa.Integer(), nullable=False),
    sa.Column('seed', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('time_limit_seconds', sa.Integer(), nullable=True),
    sa.Column('uncovered_tracks', sa.JSON(), nullable=False),
    sa.Column('notes', sa.JSON(), nullable=False),
    sa.Column('question_bank_version', sa.String(length=40), nullable=False),
    sa.Column('config_version', sa.String(length=20), nullable=False),
    sa.Column('engine_version', sa.String(length=20), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_sessions'))
    )
    with op.batch_alter_table('interview_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_interview_sessions_completed_at'), ['completed_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_sessions_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_sessions_mode'), ['mode'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_sessions_started_at'), ['started_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_sessions_status'), ['status'], unique=False)

    op.create_table('interview_answers',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.String(length=40), nullable=False),
    sa.Column('track', sa.String(length=40), nullable=False),
    sa.Column('topic', sa.String(length=120), nullable=False),
    sa.Column('difficulty', sa.String(length=20), nullable=False),
    sa.Column('question_text', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('answer_text', sa.Text(), nullable=False),
    sa.Column('seconds_spent', sa.Integer(), nullable=False),
    sa.Column('time_limit_seconds', sa.Integer(), nullable=True),
    sa.Column('within_time_limit', sa.Boolean(), nullable=False),
    sa.Column('over_by_seconds', sa.Integer(), nullable=False),
    sa.Column('attempt_count', sa.Integer(), nullable=False),
    sa.Column('score_payload', sa.JSON(), nullable=True),
    sa.Column('feedback_payload', sa.JSON(), nullable=True),
    sa.Column('overall_score', sa.Float(), nullable=True),
    sa.Column('passed', sa.Boolean(), nullable=False),
    sa.Column('missed_concepts', sa.JSON(), nullable=False),
    sa.Column('rubric_fingerprint', sa.String(length=40), nullable=False),
    sa.Column('question_bank_version', sa.String(length=40), nullable=False),
    sa.Column('injection_detected', sa.Boolean(), nullable=False),
    sa.Column('injection_markers', sa.JSON(), nullable=False),
    sa.Column('ai_requested', sa.Boolean(), nullable=False),
    sa.Column('ai_used', sa.Boolean(), nullable=False),
    sa.Column('ai_provider', sa.String(length=30), nullable=True),
    sa.Column('ai_model', sa.String(length=60), nullable=True),
    sa.Column('ai_output_origin', sa.String(length=20), nullable=True),
    sa.Column('ai_prompt_version', sa.String(length=40), nullable=True),
    sa.Column('ai_input_tokens', sa.Integer(), nullable=True),
    sa.Column('ai_output_tokens', sa.Integer(), nullable=True),
    sa.Column('ai_estimated_cost_usd', sa.Float(), nullable=True),
    sa.Column('ai_error', sa.Text(), nullable=True),
    sa.Column('asked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], name=op.f('fk_interview_answers_session_id_interview_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_answers'))
    )
    with op.batch_alter_table('interview_answers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_interview_answers_answered_at'), ['answered_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_answers_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_answers_difficulty'), ['difficulty'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_answers_injection_detected'), ['injection_detected'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_answers_overall_score'), ['overall_score'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_answers_passed'), ['passed'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_answers_question_id'), ['question_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_answers_session_id'), ['session_id'], unique=False)
        batch_op.create_index('ix_interview_answers_session_position', ['session_id', 'position'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_answers_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_answers_topic'), ['topic'], unique=False)
        batch_op.create_index(batch_op.f('ix_interview_answers_track'), ['track'], unique=False)
        batch_op.create_index('uq_interview_answers_session_question', ['session_id', 'question_id'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('interview_answers', schema=None) as batch_op:
        batch_op.drop_index('uq_interview_answers_session_question')
        batch_op.drop_index(batch_op.f('ix_interview_answers_track'))
        batch_op.drop_index(batch_op.f('ix_interview_answers_topic'))
        batch_op.drop_index(batch_op.f('ix_interview_answers_status'))
        batch_op.drop_index('ix_interview_answers_session_position')
        batch_op.drop_index(batch_op.f('ix_interview_answers_session_id'))
        batch_op.drop_index(batch_op.f('ix_interview_answers_question_id'))
        batch_op.drop_index(batch_op.f('ix_interview_answers_passed'))
        batch_op.drop_index(batch_op.f('ix_interview_answers_overall_score'))
        batch_op.drop_index(batch_op.f('ix_interview_answers_injection_detected'))
        batch_op.drop_index(batch_op.f('ix_interview_answers_difficulty'))
        batch_op.drop_index(batch_op.f('ix_interview_answers_created_at'))
        batch_op.drop_index(batch_op.f('ix_interview_answers_answered_at'))

    op.drop_table('interview_answers')
    with op.batch_alter_table('interview_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_interview_sessions_status'))
        batch_op.drop_index(batch_op.f('ix_interview_sessions_started_at'))
        batch_op.drop_index(batch_op.f('ix_interview_sessions_mode'))
        batch_op.drop_index(batch_op.f('ix_interview_sessions_created_at'))
        batch_op.drop_index(batch_op.f('ix_interview_sessions_completed_at'))

    op.drop_table('interview_sessions')
