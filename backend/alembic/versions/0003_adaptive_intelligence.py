"""LineZero 2.0: calibration_records, calibration_evaluations, risk_events, intervention_history

Adds only new tables (no existing table is altered), so the migration is safe to apply to a database that already
holds queues, entries and predictions. `downgrade` drops exactly these four tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('calibration_records',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('queue_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('parameters', sa.JSON(), nullable=False),
    sa.Column('estimates', sa.JSON(), nullable=True),
    sa.Column('settings', sa.JSON(), nullable=True),
    sa.Column('training_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('training_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('validation_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('validation_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('n_train_arrivals', sa.Integer(), nullable=True),
    sa.Column('n_train_services', sa.Integer(), nullable=True),
    sa.Column('n_validation', sa.Integer(), nullable=True),
    sa.Column('candidate_metrics', sa.JSON(), nullable=True),
    sa.Column('incumbent_metrics', sa.JSON(), nullable=True),
    sa.Column('comparison', sa.JSON(), nullable=True),
    sa.Column('drift', sa.JSON(), nullable=True),
    sa.Column('decision', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('confidence_detail', sa.JSON(), nullable=True),
    sa.Column('incumbent_version', sa.Integer(), nullable=True),
    sa.Column('rollback_to_version', sa.Integer(), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("source IN ('calibration','rollback')", name=op.f('ck_calibration_records_source_valid')),
    sa.CheckConstraint("status IN ('active','superseded','rejected')", name=op.f('ck_calibration_records_status_valid')),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_calibration_records_queue_id_queues'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_calibration_records'))
    )
    with op.batch_alter_table('calibration_records', schema=None) as batch_op:
        batch_op.create_index('ix_calibration_records_queue_version', ['queue_id', 'version'], unique=False)
        batch_op.create_index('uq_calibration_records_one_active', ['queue_id'], unique=True, sqlite_where=sa.text("status = 'active'"), postgresql_where=sa.text("status = 'active'"))

    op.create_table('risk_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('queue_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('resource_type', sa.String(length=20), nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=True),
    sa.Column('resource_name', sa.String(length=120), nullable=False),
    sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('time_to_impact_min', sa.Float(), nullable=True),
    sa.Column('supporting_metrics', sa.JSON(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('uncertainty', sa.JSON(), nullable=True),
    sa.Column('recommended_intervention', sa.JSON(), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('calibration_version', sa.Integer(), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.CheckConstraint("category IN ('queue_congestion','counter_overload','waiting_time_trend','capacity_shortage','counter_failure_precursor','abnormal_arrivals','utilization_imbalance')", name=op.f('ck_risk_events_category_valid')),
    sa.CheckConstraint("severity IN ('LOW','MEDIUM','HIGH','CRITICAL')", name=op.f('ck_risk_events_severity_valid')),
    sa.CheckConstraint("status IN ('open','resolved')", name=op.f('ck_risk_events_status_valid')),
    sa.CheckConstraint('score >= 0 AND score <= 1', name=op.f('ck_risk_events_score_range')),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_risk_events_queue_id_queues'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_events'))
    )
    with op.batch_alter_table('risk_events', schema=None) as batch_op:
        batch_op.create_index('ix_risk_events_queue_detected', ['queue_id', 'detected_at'], unique=False)
        batch_op.create_index('ix_risk_events_queue_status', ['queue_id', 'status'], unique=False)

    op.create_table('calibration_evaluations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('queue_id', sa.Integer(), nullable=False),
    sa.Column('calibration_id', sa.Integer(), nullable=True),
    sa.Column('model_label', sa.String(length=30), nullable=False),
    sa.Column('version', sa.Integer(), nullable=True),
    sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('window_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('n', sa.Integer(), nullable=False),
    sa.Column('mae_s', sa.Float(), nullable=True),
    sa.Column('rmse_s', sa.Float(), nullable=True),
    sa.Column('mape_pct', sa.Float(), nullable=True),
    sa.Column('mean_error_s', sa.Float(), nullable=True),
    sa.Column('out_of_sample', sa.Boolean(), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.CheckConstraint('n >= 0', name=op.f('ck_calibration_evaluations_n_nonneg')),
    sa.ForeignKeyConstraint(['calibration_id'], ['calibration_records.id'], name=op.f('fk_calibration_evaluations_calibration_id_calibration_records'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_calibration_evaluations_queue_id_queues'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_calibration_evaluations'))
    )
    with op.batch_alter_table('calibration_evaluations', schema=None) as batch_op:
        batch_op.create_index('ix_calibration_evaluations_queue_time', ['queue_id', 'evaluated_at'], unique=False)

    op.create_table('intervention_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('queue_id', sa.Integer(), nullable=False),
    sa.Column('evaluation_id', sa.String(length=36), nullable=False),
    sa.Column('risk_event_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('intervention_type', sa.String(length=40), nullable=False),
    sa.Column('candidate_key', sa.String(length=60), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('parameters', sa.JSON(), nullable=False),
    sa.Column('assumptions', sa.JSON(), nullable=True),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('is_recommended', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('baseline', sa.JSON(), nullable=False),
    sa.Column('expected', sa.JSON(), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('simulation_meta', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('decided_by', sa.String(length=120), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('applied_by', sa.String(length=120), nullable=True),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('apply_note', sa.Text(), nullable=True),
    sa.Column('executed_by_linezero', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('outcome', sa.JSON(), nullable=True),
    sa.Column('outcome_verification', sa.String(length=40), nullable=True),
    sa.Column('outcome_recorded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('calibration_eligible', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('calibration_version', sa.Integer(), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.CheckConstraint("outcome_verification IS NULL OR outcome_verification IN ('verified_real_observation','synthetic_observation','operator_reported')", name=op.f('ck_intervention_history_verification_valid')),
    sa.CheckConstraint("status IN ('proposed','approved','rejected','applied','evaluated')", name=op.f('ck_intervention_history_status_valid')),
    sa.CheckConstraint('executed_by_linezero = false', name=op.f('ck_intervention_history_never_auto_executed')),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_intervention_history_queue_id_queues'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['risk_event_id'], ['risk_events.id'], name=op.f('fk_intervention_history_risk_event_id_risk_events'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_intervention_history'))
    )
    with op.batch_alter_table('intervention_history', schema=None) as batch_op:
        batch_op.create_index('ix_intervention_history_evaluation', ['evaluation_id'], unique=False)
        batch_op.create_index('ix_intervention_history_queue_created', ['queue_id', 'created_at'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('intervention_history', schema=None) as batch_op:
        batch_op.drop_index('ix_intervention_history_queue_created')
        batch_op.drop_index('ix_intervention_history_evaluation')

    op.drop_table('intervention_history')
    with op.batch_alter_table('calibration_evaluations', schema=None) as batch_op:
        batch_op.drop_index('ix_calibration_evaluations_queue_time')

    op.drop_table('calibration_evaluations')
    with op.batch_alter_table('risk_events', schema=None) as batch_op:
        batch_op.drop_index('ix_risk_events_queue_status')
        batch_op.drop_index('ix_risk_events_queue_detected')

    op.drop_table('risk_events')
    with op.batch_alter_table('calibration_records', schema=None) as batch_op:
        batch_op.drop_index('uq_calibration_records_one_active', sqlite_where=sa.text("status = 'active'"), postgresql_where=sa.text("status = 'active'"))
        batch_op.drop_index('ix_calibration_records_queue_version')

    op.drop_table('calibration_records')
