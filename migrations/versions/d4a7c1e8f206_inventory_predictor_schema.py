"""inventory predictor schema

Revision ID: d4a7c1e8f206
Revises: c9f2a1e6b3d4
Create Date: 2026-07-31 21:40:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd4a7c1e8f206'
down_revision: str | None = 'c9f2a1e6b3d4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'inventory_datasets',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('upload_id', sa.String(length=36), nullable=False),
        sa.Column('source_filename', sa.String(length=255), nullable=False),
        sa.Column('config_version', sa.String(length=20), nullable=False),
        sa.Column('applied_mapping', sa.JSON(), nullable=False),
        sa.Column('unmapped_columns', sa.JSON(), nullable=False),
        sa.Column('data_quality_issues', sa.JSON(), nullable=False),
        sa.Column('row_count', sa.Integer(), nullable=False),
        sa.Column('series_count', sa.Integer(), nullable=False),
        sa.Column('material_count', sa.Integer(), nullable=False),
        sa.Column('plant_count', sa.Integer(), nullable=False),
        sa.Column('history_start', sa.Date(), nullable=True),
        sa.Column('history_end', sa.Date(), nullable=True),
        sa.Column('frequency', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['upload_id'], ['uploaded_files.id'],
            name=op.f('fk_inventory_datasets_upload_id_uploaded_files'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_datasets')),
    )
    with op.batch_alter_table('inventory_datasets', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_inventory_datasets_created_at'), ['created_at'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_inventory_datasets_upload_id'), ['upload_id'], unique=False
        )

    op.create_table(
        'inventory_records',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('dataset_id', sa.String(length=36), nullable=False),
        sa.Column('row_number', sa.Integer(), nullable=False),
        sa.Column('material', sa.String(length=40), nullable=False),
        sa.Column('plant', sa.String(length=10), nullable=False),
        sa.Column('storage_location', sa.String(length=20), nullable=True),
        sa.Column('period_date', sa.Date(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['dataset_id'], ['inventory_datasets.id'],
            name=op.f('fk_inventory_records_dataset_id_inventory_datasets'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_records')),
    )
    with op.batch_alter_table('inventory_records', schema=None) as batch_op:
        batch_op.create_index(
            'ix_inventory_records_dataset_series', ['dataset_id', 'material', 'plant'], unique=False
        )
        batch_op.create_index(
            'ix_inventory_records_dataset_period', ['dataset_id', 'period_date'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_inventory_records_dataset_id'), ['dataset_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_inventory_records_material'), ['material'], unique=False
        )
        batch_op.create_index(batch_op.f('ix_inventory_records_plant'), ['plant'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_inventory_records_period_date'), ['period_date'], unique=False
        )

    op.create_table(
        'inventory_forecasts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('dataset_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('source_filename', sa.String(length=255), nullable=True),
        sa.Column('config_version', sa.String(length=20), nullable=False),
        sa.Column('engine_version', sa.String(length=20), nullable=False),
        sa.Column('as_of_date', sa.Date(), nullable=True),
        sa.Column('horizon_periods', sa.Integer(), nullable=False),
        sa.Column('confidence_level', sa.Float(), nullable=False),
        sa.Column('service_level', sa.Float(), nullable=False),
        sa.Column('requested_model', sa.String(length=40), nullable=True),
        sa.Column('selection_metric', sa.String(length=20), nullable=True),
        sa.Column('series_count', sa.Integer(), nullable=False),
        sa.Column('forecast_count', sa.Integer(), nullable=False),
        sa.Column('insufficient_data_count', sa.Integer(), nullable=False),
        sa.Column('shortage_count', sa.Integer(), nullable=False),
        sa.Column('reorder_now_count', sa.Integer(), nullable=False),
        sa.Column('overstock_count', sa.Integer(), nullable=False),
        sa.Column('slow_moving_count', sa.Integer(), nullable=False),
        sa.Column('dead_stock_count', sa.Integer(), nullable=False),
        sa.Column('total_forecast_demand', sa.Float(), nullable=True),
        sa.Column('model_usage', sa.JSON(), nullable=False),
        sa.Column('accuracy_summary', sa.JSON(), nullable=False),
        sa.Column('frequency_counts', sa.JSON(), nullable=False),
        sa.Column('warning_counts', sa.JSON(), nullable=False),
        sa.Column('series_errors', sa.JSON(), nullable=False),
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
        sa.Column('duration_ms', sa.Integer(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['dataset_id'], ['inventory_datasets.id'],
            name=op.f('fk_inventory_forecasts_dataset_id_inventory_datasets'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_forecasts')),
    )
    with op.batch_alter_table('inventory_forecasts', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_inventory_forecasts_created_at'), ['created_at'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_inventory_forecasts_dataset_id'), ['dataset_id'], unique=False
        )

    op.create_table(
        'inventory_forecast_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('forecast_id', sa.String(length=36), nullable=False),
        sa.Column('series_key', sa.String(length=80), nullable=False),
        sa.Column('material', sa.String(length=40), nullable=False),
        sa.Column('material_description', sa.String(length=120), nullable=True),
        sa.Column('plant', sa.String(length=10), nullable=False),
        sa.Column('storage_location', sa.String(length=20), nullable=True),
        sa.Column('supplier_id', sa.String(length=20), nullable=True),
        sa.Column('supplier_name', sa.String(length=120), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('frequency', sa.String(length=20), nullable=False),
        sa.Column('model', sa.String(length=40), nullable=True),
        sa.Column('model_label', sa.String(length=80), nullable=True),
        sa.Column('selection_basis', sa.String(length=30), nullable=True),
        sa.Column('history_period_count', sa.Integer(), nullable=False),
        sa.Column('missing_period_count', sa.Integer(), nullable=False),
        sa.Column('history_end', sa.Date(), nullable=True),
        sa.Column('total_forecast_demand', sa.Float(), nullable=True),
        sa.Column('opening_inventory', sa.Float(), nullable=True),
        sa.Column('ending_projected_inventory', sa.Float(), nullable=True),
        sa.Column('minimum_projected_inventory', sa.Float(), nullable=True),
        sa.Column('predicted_shortage_date', sa.Date(), nullable=True),
        sa.Column('days_to_shortage', sa.Integer(), nullable=True),
        sa.Column('recommended_reorder_date', sa.Date(), nullable=True),
        sa.Column('recommended_reorder_quantity', sa.Float(), nullable=True),
        sa.Column('recommended_safety_stock', sa.Float(), nullable=True),
        sa.Column('calculated_reorder_point', sa.Float(), nullable=True),
        sa.Column('order_urgency', sa.String(length=20), nullable=True),
        sa.Column('expedite_recommended', sa.Boolean(), nullable=False),
        sa.Column('movement_class', sa.String(length=20), nullable=True),
        sa.Column('is_slow_moving', sa.Boolean(), nullable=False),
        sa.Column('is_dead_stock', sa.Boolean(), nullable=False),
        sa.Column('overstock_risk', sa.String(length=10), nullable=True),
        sa.Column('days_of_cover', sa.Float(), nullable=True),
        sa.Column('annual_turnover', sa.Float(), nullable=True),
        sa.Column('accuracy_basis', sa.String(length=20), nullable=True),
        sa.Column('mae', sa.Float(), nullable=True),
        sa.Column('rmse', sa.Float(), nullable=True),
        sa.Column('mape', sa.Float(), nullable=True),
        sa.Column('smape', sa.Float(), nullable=True),
        sa.Column('mase', sa.Float(), nullable=True),
        sa.Column('warning_count', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('output_origin', sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ['forecast_id'], ['inventory_forecasts.id'],
            name=op.f('fk_inventory_forecast_items_forecast_id_inventory_forecasts'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_forecast_items')),
    )
    with op.batch_alter_table('inventory_forecast_items', schema=None) as batch_op:
        batch_op.create_index(
            'ix_inventory_items_forecast_series', ['forecast_id', 'series_key'], unique=False
        )
        batch_op.create_index(
            'ix_inventory_items_forecast_material',
            ['forecast_id', 'material', 'plant'], unique=False,
        )
        batch_op.create_index(
            'ix_inventory_items_forecast_shortage',
            ['forecast_id', 'predicted_shortage_date'], unique=False,
        )
        for column in (
            'forecast_id', 'series_key', 'material', 'plant', 'supplier_id', 'status',
            'model', 'predicted_shortage_date', 'recommended_reorder_date', 'order_urgency',
            'movement_class', 'is_slow_moving', 'is_dead_stock', 'overstock_risk',
        ):
            batch_op.create_index(
                batch_op.f(f'ix_inventory_forecast_items_{column}'), [column], unique=False
            )


def downgrade() -> None:
    with op.batch_alter_table('inventory_forecast_items', schema=None) as batch_op:
        for column in (
            'overstock_risk', 'is_dead_stock', 'is_slow_moving', 'movement_class',
            'order_urgency', 'recommended_reorder_date', 'predicted_shortage_date', 'model',
            'status', 'supplier_id', 'plant', 'material', 'series_key', 'forecast_id',
        ):
            batch_op.drop_index(batch_op.f(f'ix_inventory_forecast_items_{column}'))
        batch_op.drop_index('ix_inventory_items_forecast_shortage')
        batch_op.drop_index('ix_inventory_items_forecast_material')
        batch_op.drop_index('ix_inventory_items_forecast_series')
    op.drop_table('inventory_forecast_items')

    with op.batch_alter_table('inventory_forecasts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_inventory_forecasts_dataset_id'))
        batch_op.drop_index(batch_op.f('ix_inventory_forecasts_created_at'))
    op.drop_table('inventory_forecasts')

    with op.batch_alter_table('inventory_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_inventory_records_period_date'))
        batch_op.drop_index(batch_op.f('ix_inventory_records_plant'))
        batch_op.drop_index(batch_op.f('ix_inventory_records_material'))
        batch_op.drop_index(batch_op.f('ix_inventory_records_dataset_id'))
        batch_op.drop_index('ix_inventory_records_dataset_period')
        batch_op.drop_index('ix_inventory_records_dataset_series')
    op.drop_table('inventory_records')

    with op.batch_alter_table('inventory_datasets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_inventory_datasets_upload_id'))
        batch_op.drop_index(batch_op.f('ix_inventory_datasets_created_at'))
    op.drop_table('inventory_datasets')
