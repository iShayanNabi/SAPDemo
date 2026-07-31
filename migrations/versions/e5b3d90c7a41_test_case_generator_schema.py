"""test case generator schema

Revision ID: e5b3d90c7a41
Revises: d4a7c1e8f206
Create Date: 2026-07-31 21:10:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5b3d90c7a41'
down_revision: Union[str, None] = 'd4a7c1e8f206'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'test_suites',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('sap_product', sa.String(length=120), nullable=False),
        sa.Column('sap_module', sa.String(length=120), nullable=False),
        sa.Column('business_process', sa.String(length=200), nullable=False),
        sa.Column('process_description', sa.Text(), nullable=False),
        sa.Column('preconditions', sa.JSON(), nullable=False),
        sa.Column('business_rules', sa.JSON(), nullable=False),
        sa.Column('systems_involved', sa.JSON(), nullable=False),
        sa.Column('integrations', sa.JSON(), nullable=False),
        sa.Column('user_roles', sa.JSON(), nullable=False),
        sa.Column('test_data_requirements', sa.JSON(), nullable=False),
        sa.Column('requested_test_types', sa.JSON(), nullable=False),
        sa.Column('requested_count', sa.Integer(), nullable=False),
        sa.Column('allocation', sa.JSON(), nullable=False),
        sa.Column('uncovered_test_types', sa.JSON(), nullable=False),
        sa.Column('default_owner', sa.String(length=120), nullable=False),
        sa.Column('notes', sa.JSON(), nullable=False),
        sa.Column('generation_issues', sa.JSON(), nullable=False),
        sa.Column('injection_detected', sa.Boolean(), nullable=False),
        sa.Column('injection_markers', sa.JSON(), nullable=False),
        sa.Column('config_version', sa.String(length=20), nullable=False),
        sa.Column('engine_version', sa.String(length=20), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=False),
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
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_test_suites')),
    )
    with op.batch_alter_table('test_suites', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_test_suites_created_at'), ['created_at'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_test_suites_sap_module'), ['sap_module'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_test_suites_business_process'), ['business_process'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_test_suites_injection_detected'), ['injection_detected'], unique=False
        )

    op.create_table(
        'test_cases',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('suite_id', sa.String(length=36), nullable=False),
        sa.Column('test_case_id', sa.String(length=40), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('test_type', sa.String(length=30), nullable=False),
        sa.Column('focus', sa.String(length=200), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('objective', sa.Text(), nullable=False),
        sa.Column('priority', sa.String(length=20), nullable=False),
        sa.Column('preconditions', sa.JSON(), nullable=False),
        sa.Column('test_data', sa.JSON(), nullable=False),
        sa.Column('steps', sa.JSON(), nullable=False),
        sa.Column('expected_result', sa.Text(), nullable=False),
        sa.Column('owner', sa.String(length=120), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('actual_result', sa.Text(), nullable=False),
        sa.Column('execution_result', sa.String(length=20), nullable=False),
        sa.Column('evidence_reference', sa.String(length=500), nullable=False),
        sa.Column('comments', sa.Text(), nullable=False),
        sa.Column('execution_is_stale', sa.Boolean(), nullable=False),
        sa.Column('approved_by', sa.String(length=120), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('executed_by', sa.String(length=120), nullable=True),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('output_origin', sa.String(length=20), nullable=False),
        sa.Column('ai_provider', sa.String(length=30), nullable=True),
        sa.Column('ai_prompt_version', sa.String(length=40), nullable=True),
        sa.Column('validation_notes', sa.JSON(), nullable=False),
        sa.Column('regenerated_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['suite_id'], ['test_suites.id'],
            name=op.f('fk_test_cases_suite_id_test_suites'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_test_cases')),
    )
    with op.batch_alter_table('test_cases', schema=None) as batch_op:
        batch_op.create_index('ix_test_cases_suite_sequence', ['suite_id', 'sequence'], unique=False)
        batch_op.create_index(
            'uq_test_cases_suite_identifier', ['suite_id', 'test_case_id'], unique=True
        )
        batch_op.create_index(batch_op.f('ix_test_cases_suite_id'), ['suite_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_test_cases_test_case_id'), ['test_case_id'], unique=False
        )
        batch_op.create_index(batch_op.f('ix_test_cases_test_type'), ['test_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_test_cases_priority'), ['priority'], unique=False)
        batch_op.create_index(batch_op.f('ix_test_cases_status'), ['status'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_test_cases_execution_result'), ['execution_result'], unique=False
        )
        batch_op.create_index(batch_op.f('ix_test_cases_source'), ['source'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_test_cases_execution_is_stale'), ['execution_is_stale'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_test_cases_created_at'), ['created_at'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('test_cases', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_test_cases_created_at'))
        batch_op.drop_index(batch_op.f('ix_test_cases_execution_is_stale'))
        batch_op.drop_index(batch_op.f('ix_test_cases_source'))
        batch_op.drop_index(batch_op.f('ix_test_cases_execution_result'))
        batch_op.drop_index(batch_op.f('ix_test_cases_status'))
        batch_op.drop_index(batch_op.f('ix_test_cases_priority'))
        batch_op.drop_index(batch_op.f('ix_test_cases_test_type'))
        batch_op.drop_index(batch_op.f('ix_test_cases_test_case_id'))
        batch_op.drop_index(batch_op.f('ix_test_cases_suite_id'))
        batch_op.drop_index('uq_test_cases_suite_identifier')
        batch_op.drop_index('ix_test_cases_suite_sequence')
    op.drop_table('test_cases')

    with op.batch_alter_table('test_suites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_test_suites_injection_detected'))
        batch_op.drop_index(batch_op.f('ix_test_suites_business_process'))
        batch_op.drop_index(batch_op.f('ix_test_suites_sap_module'))
        batch_op.drop_index(batch_op.f('ix_test_suites_created_at'))
    op.drop_table('test_suites')
