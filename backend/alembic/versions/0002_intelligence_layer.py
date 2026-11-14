"""Part 2: prediction_records, bottleneck_detections, optimization_results, reports

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('prediction_records',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('queue_id', sa.Integer(), nullable=False),
    sa.Column('predicted_waiting_time', sa.Float(), nullable=False),
    sa.Column('actual_waiting_time', sa.Float(), nullable=True),
    sa.Column('prediction_method', sa.String(length=40), nullable=False),
    sa.Column('prediction_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('input_features', sa.JSON(), nullable=False),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('matched_entry_id', sa.Integer(), nullable=True),
    sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.CheckConstraint('predicted_waiting_time >= 0', name=op.f('ck_prediction_records_predicted_nonneg')),
    sa.CheckConstraint('actual_waiting_time IS NULL OR actual_waiting_time >= 0', name=op.f('ck_prediction_records_actual_nonneg')),
    sa.ForeignKeyConstraint(['matched_entry_id'], ['queue_entries.id'], name=op.f('fk_prediction_records_matched_entry_id_queue_entries'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_prediction_records_queue_id_queues'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_prediction_records'))
    )
    with op.batch_alter_table('prediction_records', schema=None) as batch_op:
        batch_op.create_index('ix_prediction_records_queue_timestamp', ['queue_id', 'prediction_timestamp'], unique=False)

    op.create_table('bottleneck_detections',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('queue_id', sa.Integer(), nullable=False),
    sa.Column('counter_id', sa.Integer(), nullable=True),
    sa.Column('bottleneck_type', sa.String(length=40), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('supporting_metrics', sa.JSON(), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('operational_impact', sa.Text(), nullable=False),
    sa.Column('recommendation', sa.Text(), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('window_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.CheckConstraint("severity IN ('LOW','MEDIUM','HIGH','CRITICAL')", name=op.f('ck_bottleneck_detections_severity_valid')),
    sa.CheckConstraint("bottleneck_type IN ('counter_overload','uneven_utilization','arrival_spike','slow_service','capacity_demand_imbalance')", name=op.f('ck_bottleneck_detections_type_valid')),
    sa.ForeignKeyConstraint(['counter_id'], ['service_counters.id'], name=op.f('fk_bottleneck_detections_counter_id_service_counters'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_bottleneck_detections_queue_id_queues'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bottleneck_detections'))
    )
    with op.batch_alter_table('bottleneck_detections', schema=None) as batch_op:
        batch_op.create_index('ix_bottleneck_detections_queue_created', ['queue_id', 'created_at'], unique=False)

    op.create_table('optimization_results',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('queue_id', sa.Integer(), nullable=False),
    sa.Column('current_allocation', sa.JSON(), nullable=False),
    sa.Column('proposed_allocation', sa.JSON(), nullable=False),
    sa.Column('current_metrics', sa.JSON(), nullable=False),
    sa.Column('proposed_metrics', sa.JSON(), nullable=False),
    sa.Column('estimated_improvement', sa.JSON(), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_optimization_results_queue_id_queues'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_optimization_results'))
    )
    with op.batch_alter_table('optimization_results', schema=None) as batch_op:
        batch_op.create_index('ix_optimization_results_queue_created', ['queue_id', 'created_at'], unique=False)

    op.create_table('reports',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('report_type', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=True),
    sa.Column('queue_id', sa.Integer(), nullable=True),
    sa.Column('report_data', sa.JSON(), nullable=False),
    sa.Column('contains_synthetic_data', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("report_type IN ('queue_performance','simulation_results','prediction_evaluation','bottleneck_analysis','optimization_comparison')", name=op.f('ck_reports_type_valid')),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_reports_queue_id_queues'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reports'))
    )
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.create_index('ix_reports_type_created', ['report_type', 'created_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.drop_index('ix_reports_type_created')
    op.drop_table('reports')
    with op.batch_alter_table('optimization_results', schema=None) as batch_op:
        batch_op.drop_index('ix_optimization_results_queue_created')
    op.drop_table('optimization_results')
    with op.batch_alter_table('bottleneck_detections', schema=None) as batch_op:
        batch_op.drop_index('ix_bottleneck_detections_queue_created')
    op.drop_table('bottleneck_detections')
    with op.batch_alter_table('prediction_records', schema=None) as batch_op:
        batch_op.drop_index('ix_prediction_records_queue_timestamp')
    op.drop_table('prediction_records')
