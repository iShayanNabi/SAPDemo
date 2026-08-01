"""blueprint generator schema

Revision ID: f6c4e2a9b710
Revises: e5b3d90c7a41
Create Date: 2026-07-31 23:24:02.101700
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f6c4e2a9b710'
down_revision: str | None = 'e5b3d90c7a41'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('blueprints',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('owner', sa.String(length=120), nullable=False),
    sa.Column('company', sa.String(length=160), nullable=False),
    sa.Column('industry', sa.String(length=120), nullable=False),
    sa.Column('sap_product', sa.String(length=160), nullable=False),
    sa.Column('modules', sa.JSON(), nullable=False),
    sa.Column('business_objectives', sa.JSON(), nullable=False),
    sa.Column('current_process', sa.Text(), nullable=False),
    sa.Column('desired_process', sa.Text(), nullable=False),
    sa.Column('countries', sa.JSON(), nullable=False),
    sa.Column('locations', sa.JSON(), nullable=False),
    sa.Column('company_codes', sa.JSON(), nullable=False),
    sa.Column('plants', sa.JSON(), nullable=False),
    sa.Column('purchasing_organizations', sa.JSON(), nullable=False),
    sa.Column('systems_involved', sa.JSON(), nullable=False),
    sa.Column('integrations', sa.JSON(), nullable=False),
    sa.Column('data_sources', sa.JSON(), nullable=False),
    sa.Column('user_groups', sa.JSON(), nullable=False),
    sa.Column('timeline', sa.Text(), nullable=False),
    sa.Column('constraints', sa.JSON(), nullable=False),
    sa.Column('assumptions', sa.JSON(), nullable=False),
    sa.Column('requested_sections', sa.JSON(), nullable=False),
    sa.Column('excluded_sections', sa.JSON(), nullable=False),
    sa.Column('current_version', sa.Integer(), nullable=False),
    sa.Column('custom_sections_issued', sa.Integer(), nullable=False),
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
    sa.PrimaryKeyConstraint('id', name=op.f('pk_blueprints'))
    )
    with op.batch_alter_table('blueprints', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_blueprints_company'), ['company'], unique=False)
        batch_op.create_index(batch_op.f('ix_blueprints_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_blueprints_injection_detected'), ['injection_detected'], unique=False)
        batch_op.create_index(batch_op.f('ix_blueprints_sap_product'), ['sap_product'], unique=False)

    op.create_table('blueprint_sections',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('blueprint_id', sa.String(length=36), nullable=False),
    sa.Column('section_id', sa.String(length=40), nullable=False),
    sa.Column('section_key', sa.String(length=60), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('is_custom', sa.Boolean(), nullable=False),
    sa.Column('content_kind', sa.String(length=20), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('narrative', sa.Text(), nullable=False),
    sa.Column('items', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('output_origin', sa.String(length=20), nullable=False),
    sa.Column('comments', sa.Text(), nullable=False),
    sa.Column('approved_by', sa.String(length=120), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('missing_inputs', sa.JSON(), nullable=False),
    sa.Column('validation_notes', sa.JSON(), nullable=False),
    sa.Column('content_revision', sa.Integer(), nullable=False),
    sa.Column('depends_on', sa.JSON(), nullable=False),
    sa.Column('dependency_revisions', sa.JSON(), nullable=False),
    sa.Column('regenerated_count', sa.Integer(), nullable=False),
    sa.Column('edited_by_user', sa.Boolean(), nullable=False),
    sa.Column('ai_provider', sa.String(length=30), nullable=True),
    sa.Column('ai_prompt_version', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['blueprint_id'], ['blueprints.id'], name=op.f('fk_blueprint_sections_blueprint_id_blueprints'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_blueprint_sections'))
    )
    with op.batch_alter_table('blueprint_sections', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_blueprint_sections_blueprint_id'), ['blueprint_id'], unique=False)
        batch_op.create_index('ix_blueprint_sections_bp_position', ['blueprint_id', 'position'], unique=False)
        batch_op.create_index(batch_op.f('ix_blueprint_sections_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_blueprint_sections_is_custom'), ['is_custom'], unique=False)
        batch_op.create_index(batch_op.f('ix_blueprint_sections_section_id'), ['section_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_blueprint_sections_section_key'), ['section_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_blueprint_sections_source'), ['source'], unique=False)
        batch_op.create_index(batch_op.f('ix_blueprint_sections_status'), ['status'], unique=False)
        batch_op.create_index('uq_blueprint_sections_bp_identifier', ['blueprint_id', 'section_id'], unique=True)
        batch_op.create_index('uq_blueprint_sections_bp_key', ['blueprint_id', 'section_key'], unique=True)

    op.create_table('blueprint_versions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('blueprint_id', sa.String(length=36), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('created_by', sa.String(length=120), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('sections', sa.JSON(), nullable=False),
    sa.Column('section_count', sa.Integer(), nullable=False),
    sa.Column('item_count', sa.Integer(), nullable=False),
    sa.Column('approved_count', sa.Integer(), nullable=False),
    sa.Column('needs_input_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['blueprint_id'], ['blueprints.id'], name=op.f('fk_blueprint_versions_blueprint_id_blueprints'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_blueprint_versions'))
    )
    with op.batch_alter_table('blueprint_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_blueprint_versions_blueprint_id'), ['blueprint_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_blueprint_versions_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_blueprint_versions_version_number'), ['version_number'], unique=False)
        batch_op.create_index('uq_blueprint_versions_bp_number', ['blueprint_id', 'version_number'], unique=True)



def downgrade() -> None:
    with op.batch_alter_table('blueprint_versions', schema=None) as batch_op:
        batch_op.drop_index('uq_blueprint_versions_bp_number')
        batch_op.drop_index(batch_op.f('ix_blueprint_versions_version_number'))
        batch_op.drop_index(batch_op.f('ix_blueprint_versions_created_at'))
        batch_op.drop_index(batch_op.f('ix_blueprint_versions_blueprint_id'))

    op.drop_table('blueprint_versions')
    with op.batch_alter_table('blueprint_sections', schema=None) as batch_op:
        batch_op.drop_index('uq_blueprint_sections_bp_key')
        batch_op.drop_index('uq_blueprint_sections_bp_identifier')
        batch_op.drop_index(batch_op.f('ix_blueprint_sections_status'))
        batch_op.drop_index(batch_op.f('ix_blueprint_sections_source'))
        batch_op.drop_index(batch_op.f('ix_blueprint_sections_section_key'))
        batch_op.drop_index(batch_op.f('ix_blueprint_sections_section_id'))
        batch_op.drop_index(batch_op.f('ix_blueprint_sections_is_custom'))
        batch_op.drop_index(batch_op.f('ix_blueprint_sections_created_at'))
        batch_op.drop_index('ix_blueprint_sections_bp_position')
        batch_op.drop_index(batch_op.f('ix_blueprint_sections_blueprint_id'))

    op.drop_table('blueprint_sections')
    with op.batch_alter_table('blueprints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_blueprints_sap_product'))
        batch_op.drop_index(batch_op.f('ix_blueprints_injection_detected'))
        batch_op.drop_index(batch_op.f('ix_blueprints_created_at'))
        batch_op.drop_index(batch_op.f('ix_blueprints_company'))

    op.drop_table('blueprints')
