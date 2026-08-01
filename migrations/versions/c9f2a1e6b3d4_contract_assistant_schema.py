"""contract assistant schema

Revision ID: c9f2a1e6b3d4
Revises: b7e41c9d5a02
Create Date: 2026-07-31 19:45:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c9f2a1e6b3d4'
down_revision: str | None = 'b7e41c9d5a02'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'contracts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('upload_id', sa.String(length=36), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('file_extension', sa.String(length=10), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('extractor', sa.String(length=30), nullable=True),
        sa.Column('source_format', sa.String(length=20), nullable=True),
        sa.Column('page_basis', sa.String(length=20), nullable=True),
        sa.Column('page_count', sa.Integer(), nullable=False),
        sa.Column('char_count', sa.Integer(), nullable=False),
        sa.Column('section_count', sa.Integer(), nullable=False),
        sa.Column('needs_ocr', sa.Boolean(), nullable=False),
        sa.Column('ocr_used', sa.Boolean(), nullable=False),
        sa.Column('ocr_provider', sa.String(length=40), nullable=True),
        sa.Column('extraction_notes', sa.JSON(), nullable=False),
        sa.Column('extraction_metadata', sa.JSON(), nullable=False),
        sa.Column('contract_title', sa.String(length=255), nullable=True),
        sa.Column('title_reference', sa.JSON(), nullable=False),
        sa.Column('parties', sa.JSON(), nullable=False),
        sa.Column('sections', sa.JSON(), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=True),
        sa.Column('expiration_date', sa.Date(), nullable=True),
        sa.Column('renewal_date', sa.Date(), nullable=True),
        sa.Column('notice_deadline', sa.Date(), nullable=True),
        sa.Column('auto_renewal', sa.Boolean(), nullable=False),
        sa.Column('notice_period_days', sa.Integer(), nullable=True),
        sa.Column('key_dates', sa.JSON(), nullable=False),
        sa.Column('clauses_found', sa.Integer(), nullable=False),
        sa.Column('clauses_expected', sa.Integer(), nullable=False),
        sa.Column('missing_clause_count', sa.Integer(), nullable=False),
        sa.Column('obligation_count', sa.Integer(), nullable=False),
        sa.Column('risk_count', sa.Integer(), nullable=False),
        sa.Column('severity_counts', sa.JSON(), nullable=False),
        sa.Column('risk_score', sa.Float(), nullable=False),
        sa.Column('risk_band', sa.String(length=20), nullable=True),
        sa.Column('missing_clauses', sa.JSON(), nullable=False),
        sa.Column('injection_detected', sa.Boolean(), nullable=False),
        sa.Column('injection_markers', sa.JSON(), nullable=False),
        sa.Column('rule_errors', sa.JSON(), nullable=False),
        sa.Column('as_of_date', sa.Date(), nullable=True),
        sa.Column('config_version', sa.String(length=20), nullable=False),
        sa.Column('engine_version', sa.String(length=20), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=False),
        sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ai_provider', sa.String(length=30), nullable=True),
        sa.Column('ai_output_origin', sa.String(length=20), nullable=True),
        sa.Column('ai_prompt_version', sa.String(length=40), nullable=True),
        sa.Column('ai_summary', sa.Text(), nullable=True),
        sa.Column('ai_key_findings', sa.JSON(), nullable=False),
        sa.Column('ai_recommended_actions', sa.JSON(), nullable=False),
        sa.Column('ai_input_tokens', sa.Integer(), nullable=True),
        sa.Column('ai_output_tokens', sa.Integer(), nullable=True),
        sa.Column('ai_estimated_cost_usd', sa.Float(), nullable=True),
        sa.Column('ai_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['upload_id'], ['uploaded_files.id'],
            name=op.f('fk_contracts_upload_id_uploaded_files'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_contracts')),
    )
    with op.batch_alter_table('contracts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_contracts_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_contracts_upload_id'), ['upload_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_contracts_sha256'), ['sha256'], unique=False)
        batch_op.create_index(batch_op.f('ix_contracts_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_contracts_needs_ocr'), ['needs_ocr'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_contracts_expiration_date'), ['expiration_date'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_contracts_notice_deadline'), ['notice_deadline'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_contracts_auto_renewal'), ['auto_renewal'], unique=False
        )
        batch_op.create_index(batch_op.f('ix_contracts_risk_score'), ['risk_score'], unique=False)
        batch_op.create_index(batch_op.f('ix_contracts_risk_band'), ['risk_band'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_contracts_injection_detected'), ['injection_detected'], unique=False
        )

    op.create_table(
        'contract_pages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('contract_id', sa.String(length=36), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('char_count', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ['contract_id'], ['contracts.id'],
            name=op.f('fk_contract_pages_contract_id_contracts'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_contract_pages')),
    )
    with op.batch_alter_table('contract_pages', schema=None) as batch_op:
        batch_op.create_index(
            'ix_contract_pages_contract_page', ['contract_id', 'page_number'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_contract_pages_contract_id'), ['contract_id'], unique=False
        )

    op.create_table(
        'contract_clauses',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('contract_id', sa.String(length=36), nullable=False),
        sa.Column('clause_type', sa.String(length=40), nullable=False),
        sa.Column('label', sa.String(length=80), nullable=False),
        sa.Column('present', sa.Boolean(), nullable=False),
        sa.Column('required', sa.Boolean(), nullable=False),
        sa.Column('importance', sa.String(length=20), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('needs_review', sa.Boolean(), nullable=False),
        sa.Column('heading_matched', sa.Boolean(), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=True),
        sa.Column('section_heading', sa.String(length=200), nullable=True),
        sa.Column('excerpt', sa.Text(), nullable=False),
        sa.Column('matched_terms', sa.JSON(), nullable=False),
        sa.Column('values', sa.JSON(), nullable=False),
        sa.Column('references', sa.JSON(), nullable=False),
        sa.Column('ai_summary', sa.Text(), nullable=True),
        sa.Column('ai_origin', sa.String(length=20), nullable=True),
        sa.Column('output_origin', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ['contract_id'], ['contracts.id'],
            name=op.f('fk_contract_clauses_contract_id_contracts'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_contract_clauses')),
    )
    with op.batch_alter_table('contract_clauses', schema=None) as batch_op:
        batch_op.create_index(
            'ix_contract_clauses_contract_type', ['contract_id', 'clause_type'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_contract_clauses_contract_id'), ['contract_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_contract_clauses_clause_type'), ['clause_type'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_contract_clauses_present'), ['present'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_contract_clauses_needs_review'), ['needs_review'], unique=False
        )

    op.create_table(
        'contract_risks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('contract_id', sa.String(length=36), nullable=False),
        sa.Column('rule_id', sa.String(length=20), nullable=False),
        sa.Column('rule_name', sa.String(length=120), nullable=False),
        sa.Column('category', sa.String(length=40), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('recommended_action', sa.Text(), nullable=False),
        sa.Column('clause_type', sa.String(length=40), nullable=True),
        sa.Column('page_number', sa.Integer(), nullable=True),
        sa.Column('section_heading', sa.String(length=200), nullable=True),
        sa.Column('excerpt', sa.Text(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('references', sa.JSON(), nullable=False),
        sa.Column('output_origin', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ['contract_id'], ['contracts.id'],
            name=op.f('fk_contract_risks_contract_id_contracts'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_contract_risks')),
    )
    with op.batch_alter_table('contract_risks', schema=None) as batch_op:
        batch_op.create_index(
            'ix_contract_risks_contract_severity', ['contract_id', 'severity'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_contract_risks_contract_id'), ['contract_id'], unique=False
        )
        batch_op.create_index(batch_op.f('ix_contract_risks_rule_id'), ['rule_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_contract_risks_category'), ['category'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_contract_risks_severity'), ['severity'], unique=False
        )

    op.create_table(
        'contract_obligations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('contract_id', sa.String(length=36), nullable=False),
        sa.Column('obligation_id', sa.String(length=20), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('party', sa.String(length=120), nullable=True),
        sa.Column('party_role', sa.String(length=30), nullable=True),
        sa.Column('duty_type', sa.String(length=30), nullable=False),
        sa.Column('is_prohibition', sa.Boolean(), nullable=False),
        sa.Column('clause_type', sa.String(length=40), nullable=True),
        sa.Column('page_number', sa.Integer(), nullable=True),
        sa.Column('section_heading', sa.String(length=200), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('reference', sa.JSON(), nullable=False),
        sa.Column('output_origin', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ['contract_id'], ['contracts.id'],
            name=op.f('fk_contract_obligations_contract_id_contracts'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_contract_obligations')),
    )
    with op.batch_alter_table('contract_obligations', schema=None) as batch_op:
        batch_op.create_index(
            'ix_contract_obligations_contract_party',
            ['contract_id', 'party_role'], unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_contract_obligations_contract_id'), ['contract_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_contract_obligations_party_role'), ['party_role'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_contract_obligations_duty_type'), ['duty_type'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('contract_obligations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contract_obligations_duty_type'))
        batch_op.drop_index(batch_op.f('ix_contract_obligations_party_role'))
        batch_op.drop_index(batch_op.f('ix_contract_obligations_contract_id'))
        batch_op.drop_index('ix_contract_obligations_contract_party')
    op.drop_table('contract_obligations')

    with op.batch_alter_table('contract_risks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contract_risks_severity'))
        batch_op.drop_index(batch_op.f('ix_contract_risks_category'))
        batch_op.drop_index(batch_op.f('ix_contract_risks_rule_id'))
        batch_op.drop_index(batch_op.f('ix_contract_risks_contract_id'))
        batch_op.drop_index('ix_contract_risks_contract_severity')
    op.drop_table('contract_risks')

    with op.batch_alter_table('contract_clauses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contract_clauses_needs_review'))
        batch_op.drop_index(batch_op.f('ix_contract_clauses_present'))
        batch_op.drop_index(batch_op.f('ix_contract_clauses_clause_type'))
        batch_op.drop_index(batch_op.f('ix_contract_clauses_contract_id'))
        batch_op.drop_index('ix_contract_clauses_contract_type')
    op.drop_table('contract_clauses')

    with op.batch_alter_table('contract_pages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contract_pages_contract_id'))
        batch_op.drop_index('ix_contract_pages_contract_page')
    op.drop_table('contract_pages')

    with op.batch_alter_table('contracts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_contracts_injection_detected'))
        batch_op.drop_index(batch_op.f('ix_contracts_risk_band'))
        batch_op.drop_index(batch_op.f('ix_contracts_risk_score'))
        batch_op.drop_index(batch_op.f('ix_contracts_auto_renewal'))
        batch_op.drop_index(batch_op.f('ix_contracts_notice_deadline'))
        batch_op.drop_index(batch_op.f('ix_contracts_expiration_date'))
        batch_op.drop_index(batch_op.f('ix_contracts_needs_ocr'))
        batch_op.drop_index(batch_op.f('ix_contracts_status'))
        batch_op.drop_index(batch_op.f('ix_contracts_sha256'))
        batch_op.drop_index(batch_op.f('ix_contracts_upload_id'))
        batch_op.drop_index(batch_op.f('ix_contracts_created_at'))
    op.drop_table('contracts')
