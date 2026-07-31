"""supplier risk copilot schema

Revision ID: b7e41c9d5a02
Revises: aa9af98480ef
Create Date: 2026-07-31 07:20:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e41c9d5a02'
down_revision: Union[str, None] = 'aa9af98480ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'supplier_risk_datasets',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('upload_id', sa.String(length=36), nullable=False),
        sa.Column('event_upload_id', sa.String(length=36), nullable=True),
        sa.Column('source_filename', sa.String(length=255), nullable=False),
        sa.Column('event_filename', sa.String(length=255), nullable=True),
        sa.Column('config_version', sa.String(length=20), nullable=False),
        sa.Column('base_currency', sa.String(length=3), nullable=False),
        sa.Column('applied_mapping', sa.JSON(), nullable=False),
        sa.Column('applied_event_mapping', sa.JSON(), nullable=False),
        sa.Column('unmapped_columns', sa.JSON(), nullable=False),
        sa.Column('data_quality_issues', sa.JSON(), nullable=False),
        sa.Column('supplier_count', sa.Integer(), nullable=False),
        sa.Column('event_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['upload_id'], ['uploaded_files.id'],
            name=op.f('fk_supplier_risk_datasets_upload_id_uploaded_files'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_supplier_risk_datasets')),
    )
    with op.batch_alter_table('supplier_risk_datasets', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_datasets_created_at'), ['created_at'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_datasets_upload_id'), ['upload_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_datasets_event_upload_id'),
            ['event_upload_id'], unique=False,
        )

    op.create_table(
        'supplier_risk_records',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('dataset_id', sa.String(length=36), nullable=False),
        sa.Column('row_number', sa.Integer(), nullable=False),
        sa.Column('supplier_id', sa.String(length=20), nullable=False),
        sa.Column('supplier_name', sa.String(length=120), nullable=True),
        sa.Column('country', sa.String(length=40), nullable=True),
        sa.Column('spend_category', sa.String(length=80), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('events', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['dataset_id'], ['supplier_risk_datasets.id'],
            name=op.f('fk_supplier_risk_records_dataset_id_supplier_risk_datasets'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_supplier_risk_records')),
    )
    with op.batch_alter_table('supplier_risk_records', schema=None) as batch_op:
        batch_op.create_index(
            'ix_risk_records_dataset_supplier', ['dataset_id', 'supplier_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_records_dataset_id'), ['dataset_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_records_supplier_id'), ['supplier_id'], unique=False
        )

    op.create_table(
        'supplier_risk_assessments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('dataset_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('source_filename', sa.String(length=255), nullable=True),
        sa.Column('config_version', sa.String(length=20), nullable=False),
        sa.Column('engine_version', sa.String(length=20), nullable=False),
        sa.Column('weights', sa.JSON(), nullable=False),
        sa.Column('as_of_date', sa.Date(), nullable=True),
        sa.Column('base_currency', sa.String(length=3), nullable=False),
        sa.Column('supplier_count', sa.Integer(), nullable=False),
        sa.Column('scored_count', sa.Integer(), nullable=False),
        sa.Column('event_count', sa.Integer(), nullable=False),
        sa.Column('band_counts', sa.JSON(), nullable=False),
        sa.Column('category_averages', sa.JSON(), nullable=False),
        sa.Column('average_overall_score', sa.Float(), nullable=True),
        sa.Column('highest_risk_supplier_id', sa.String(length=20), nullable=True),
        sa.Column('highest_risk_score', sa.Float(), nullable=True),
        sa.Column('contracts_expiring_count', sa.Integer(), nullable=False),
        sa.Column('limited_data_count', sa.Integer(), nullable=False),
        sa.Column('rule_errors', sa.JSON(), nullable=False),
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
            ['dataset_id'], ['supplier_risk_datasets.id'],
            name=op.f('fk_supplier_risk_assessments_dataset_id_supplier_risk_datasets'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_supplier_risk_assessments')),
    )
    with op.batch_alter_table('supplier_risk_assessments', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_assessments_created_at'), ['created_at'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_assessments_dataset_id'), ['dataset_id'], unique=False
        )

    op.create_table(
        'supplier_risk_profiles',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('assessment_id', sa.String(length=36), nullable=False),
        sa.Column('supplier_id', sa.String(length=20), nullable=False),
        sa.Column('supplier_name', sa.String(length=120), nullable=True),
        sa.Column('country', sa.String(length=40), nullable=True),
        sa.Column('spend_category', sa.String(length=80), nullable=True),
        sa.Column('overall_score', sa.Float(), nullable=True),
        sa.Column('overall_band', sa.String(length=20), nullable=True),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('delivery_score', sa.Float(), nullable=True),
        sa.Column('quality_score', sa.Float(), nullable=True),
        sa.Column('financial_score', sa.Float(), nullable=True),
        sa.Column('spend_concentration_score', sa.Float(), nullable=True),
        sa.Column('contract_score', sa.Float(), nullable=True),
        sa.Column('invoice_score', sa.Float(), nullable=True),
        sa.Column('compliance_score', sa.Float(), nullable=True),
        sa.Column('esg_score', sa.Float(), nullable=True),
        sa.Column('geographic_score', sa.Float(), nullable=True),
        sa.Column('operational_score', sa.Float(), nullable=True),
        sa.Column('trend_direction', sa.String(length=20), nullable=True),
        sa.Column('trend_delta', sa.Float(), nullable=True),
        sa.Column('data_completeness_pct', sa.Float(), nullable=False),
        sa.Column('limited_data', sa.Boolean(), nullable=False),
        sa.Column('total_spend_base', sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column('purchase_order_count', sa.Integer(), nullable=True),
        sa.Column('active_contract_count', sa.Integer(), nullable=True),
        sa.Column('contract_status', sa.String(length=40), nullable=True),
        sa.Column('contract_expiration', sa.Date(), nullable=True),
        sa.Column('contract_expiring_soon', sa.Boolean(), nullable=False),
        sa.Column('on_time_delivery_rate', sa.Float(), nullable=True),
        sa.Column('late_delivery_count', sa.Integer(), nullable=True),
        sa.Column('invoice_exception_count', sa.Integer(), nullable=True),
        sa.Column('breakdown', sa.JSON(), nullable=False),
        sa.Column('output_origin', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ['assessment_id'], ['supplier_risk_assessments.id'],
            name=op.f('fk_supplier_risk_profiles_assessment_id_supplier_risk_assessments'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_supplier_risk_profiles')),
    )
    with op.batch_alter_table('supplier_risk_profiles', schema=None) as batch_op:
        batch_op.create_index(
            'ix_risk_profiles_assessment_supplier', ['assessment_id', 'supplier_id'], unique=False
        )
        batch_op.create_index(
            'ix_risk_profiles_assessment_rank', ['assessment_id', 'rank'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_profiles_assessment_id'), ['assessment_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_profiles_supplier_id'), ['supplier_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_profiles_overall_score'), ['overall_score'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_profiles_overall_band'), ['overall_band'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_profiles_rank'), ['rank'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_profiles_limited_data'), ['limited_data'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_supplier_risk_profiles_contract_expiring_soon'),
            ['contract_expiring_soon'], unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('supplier_risk_profiles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_supplier_risk_profiles_contract_expiring_soon'))
        batch_op.drop_index(batch_op.f('ix_supplier_risk_profiles_limited_data'))
        batch_op.drop_index(batch_op.f('ix_supplier_risk_profiles_rank'))
        batch_op.drop_index(batch_op.f('ix_supplier_risk_profiles_overall_band'))
        batch_op.drop_index(batch_op.f('ix_supplier_risk_profiles_overall_score'))
        batch_op.drop_index(batch_op.f('ix_supplier_risk_profiles_supplier_id'))
        batch_op.drop_index(batch_op.f('ix_supplier_risk_profiles_assessment_id'))
        batch_op.drop_index('ix_risk_profiles_assessment_rank')
        batch_op.drop_index('ix_risk_profiles_assessment_supplier')
    op.drop_table('supplier_risk_profiles')

    with op.batch_alter_table('supplier_risk_assessments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_supplier_risk_assessments_dataset_id'))
        batch_op.drop_index(batch_op.f('ix_supplier_risk_assessments_created_at'))
    op.drop_table('supplier_risk_assessments')

    with op.batch_alter_table('supplier_risk_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_supplier_risk_records_supplier_id'))
        batch_op.drop_index(batch_op.f('ix_supplier_risk_records_dataset_id'))
        batch_op.drop_index('ix_risk_records_dataset_supplier')
    op.drop_table('supplier_risk_records')

    with op.batch_alter_table('supplier_risk_datasets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_supplier_risk_datasets_event_upload_id'))
        batch_op.drop_index(batch_op.f('ix_supplier_risk_datasets_upload_id'))
        batch_op.drop_index(batch_op.f('ix_supplier_risk_datasets_created_at'))
    op.drop_table('supplier_risk_datasets')
