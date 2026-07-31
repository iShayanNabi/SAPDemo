"""invoice validator schema

Revision ID: aa9af98480ef
Revises: a16bad79dd24
Create Date: 2026-07-31 06:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'aa9af98480ef'
down_revision: Union[str, None] = 'a16bad79dd24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'invoice_validations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('invoice_upload_id', sa.String(length=36), nullable=False),
        sa.Column('po_upload_id', sa.String(length=36), nullable=True),
        sa.Column('gr_upload_id', sa.String(length=36), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('invoice_filename', sa.String(length=255), nullable=True),
        sa.Column('po_filename', sa.String(length=255), nullable=True),
        sa.Column('gr_filename', sa.String(length=255), nullable=True),
        sa.Column('config_version', sa.String(length=20), nullable=False),
        sa.Column('engine_version', sa.String(length=20), nullable=False),
        sa.Column('as_of_date', sa.Date(), nullable=True),
        sa.Column('tolerances', sa.JSON(), nullable=False),
        sa.Column('applied_invoice_mapping', sa.JSON(), nullable=False),
        sa.Column('applied_po_mapping', sa.JSON(), nullable=False),
        sa.Column('applied_gr_mapping', sa.JSON(), nullable=False),
        sa.Column('data_quality_issues', sa.JSON(), nullable=False),
        sa.Column('kpis', sa.JSON(), nullable=False),
        sa.Column('supplier_summary', sa.JSON(), nullable=False),
        sa.Column('three_way_matches', sa.JSON(), nullable=False),
        sa.Column('rule_executions', sa.JSON(), nullable=False),
        sa.Column('rule_errors', sa.JSON(), nullable=False),
        sa.Column('invoice_count', sa.Integer(), nullable=False),
        sa.Column('purchase_order_line_count', sa.Integer(), nullable=False),
        sa.Column('goods_receipt_count', sa.Integer(), nullable=False),
        sa.Column('supplier_count', sa.Integer(), nullable=False),
        sa.Column('total_invoice_amount', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('base_currency', sa.String(length=3), nullable=False),
        sa.Column('exceptions_count', sa.Integer(), nullable=False),
        sa.Column('critical_count', sa.Integer(), nullable=False),
        sa.Column('high_count', sa.Integer(), nullable=False),
        sa.Column('medium_count', sa.Integer(), nullable=False),
        sa.Column('low_count', sa.Integer(), nullable=False),
        sa.Column('flagged_value', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('estimated_exposure', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('exception_score', sa.Float(), nullable=False),
        sa.Column('ai_provider', sa.String(length=30), nullable=True),
        sa.Column('ai_output_origin', sa.String(length=20), nullable=True),
        sa.Column('ai_prompt_version', sa.String(length=30), nullable=True),
        sa.Column('ai_summary', sa.Text(), nullable=True),
        sa.Column('ai_key_findings', sa.JSON(), nullable=False),
        sa.Column('ai_recommended_actions', sa.JSON(), nullable=False),
        sa.Column('ai_input_tokens', sa.Integer(), nullable=True),
        sa.Column('ai_output_tokens', sa.Integer(), nullable=True),
        sa.Column('ai_estimated_cost_usd', sa.Float(), nullable=True),
        sa.Column('ai_error', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['invoice_upload_id'], ['uploaded_files.id'],
            name=op.f('fk_invoice_validations_invoice_upload_id_uploaded_files'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_invoice_validations')),
    )
    with op.batch_alter_table('invoice_validations', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_invoice_validations_created_at'), ['created_at'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_invoice_validations_invoice_upload_id'), ['invoice_upload_id'], unique=False
        )

    op.create_table(
        'invoice_exceptions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('validation_id', sa.String(length=36), nullable=False),
        sa.Column('rule_id', sa.String(length=20), nullable=False),
        sa.Column('rule_name', sa.String(length=120), nullable=False),
        sa.Column('exception_type', sa.String(length=40), nullable=False),
        sa.Column('category', sa.String(length=40), nullable=False),
        sa.Column('severity', sa.String(length=10), nullable=False),
        sa.Column('invoice_number', sa.String(length=40), nullable=True),
        sa.Column('supplier_id', sa.String(length=20), nullable=True),
        sa.Column('supplier_name', sa.String(length=120), nullable=True),
        sa.Column('po_number', sa.String(length=20), nullable=True),
        sa.Column('po_item', sa.String(length=10), nullable=True),
        sa.Column('gr_number', sa.String(length=40), nullable=True),
        sa.Column('expected_value', sa.Text(), nullable=True),
        sa.Column('actual_value', sa.Text(), nullable=True),
        sa.Column('difference', sa.Text(), nullable=True),
        sa.Column('difference_amount', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('recommended_action', sa.Text(), nullable=False),
        sa.Column('confidence_score', sa.Float(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('output_origin', sa.String(length=20), nullable=False),
        sa.Column('ai_explanation', sa.Text(), nullable=True),
        sa.Column('ai_recommended_action', sa.Text(), nullable=True),
        sa.Column('ai_output_origin', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['validation_id'], ['invoice_validations.id'],
            name=op.f('fk_invoice_exceptions_validation_id_invoice_validations'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_invoice_exceptions')),
    )
    with op.batch_alter_table('invoice_exceptions', schema=None) as batch_op:
        batch_op.create_index('ix_invoice_exceptions_validation_rule', ['validation_id', 'rule_id'], unique=False)
        batch_op.create_index('ix_invoice_exceptions_validation_severity', ['validation_id', 'severity'], unique=False)
        batch_op.create_index(batch_op.f('ix_invoice_exceptions_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_invoice_exceptions_exception_type'), ['exception_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_invoice_exceptions_invoice_number'), ['invoice_number'], unique=False)
        batch_op.create_index(batch_op.f('ix_invoice_exceptions_po_number'), ['po_number'], unique=False)
        batch_op.create_index(batch_op.f('ix_invoice_exceptions_rule_id'), ['rule_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_invoice_exceptions_severity'), ['severity'], unique=False)
        batch_op.create_index(batch_op.f('ix_invoice_exceptions_supplier_id'), ['supplier_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_invoice_exceptions_validation_id'), ['validation_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('invoice_exceptions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_invoice_exceptions_validation_id'))
        batch_op.drop_index(batch_op.f('ix_invoice_exceptions_supplier_id'))
        batch_op.drop_index(batch_op.f('ix_invoice_exceptions_severity'))
        batch_op.drop_index(batch_op.f('ix_invoice_exceptions_rule_id'))
        batch_op.drop_index(batch_op.f('ix_invoice_exceptions_po_number'))
        batch_op.drop_index(batch_op.f('ix_invoice_exceptions_invoice_number'))
        batch_op.drop_index(batch_op.f('ix_invoice_exceptions_exception_type'))
        batch_op.drop_index(batch_op.f('ix_invoice_exceptions_category'))
        batch_op.drop_index('ix_invoice_exceptions_validation_severity')
        batch_op.drop_index('ix_invoice_exceptions_validation_rule')
    op.drop_table('invoice_exceptions')

    with op.batch_alter_table('invoice_validations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_invoice_validations_invoice_upload_id'))
        batch_op.drop_index(batch_op.f('ix_invoice_validations_created_at'))
    op.drop_table('invoice_validations')
