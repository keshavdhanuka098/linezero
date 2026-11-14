"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-11-14 02:35:16.987942
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('queues',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('last_token', sa.Integer(), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('scenario', sa.String(length=60), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('active','paused','closed')", name=op.f('ck_queues_status_valid')),
    sa.CheckConstraint('last_token >= 0', name=op.f('ck_queues_last_token_nonneg')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_queues'))
    )
    with op.batch_alter_table('queues', schema=None) as batch_op:
        batch_op.create_index('ix_queues_is_synthetic', ['is_synthetic'], unique=False)
        batch_op.create_index(batch_op.f('ix_queues_name'), ['name'], unique=False)
        batch_op.create_index(batch_op.f('ix_queues_status'), ['status'], unique=False)

    op.create_table('simulation_runs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('configuration', sa.JSON(), nullable=False),
    sa.Column('results', sa.JSON(), nullable=True),
    sa.Column('seed', sa.Integer(), nullable=True),
    sa.Column('runtime_ms', sa.Float(), nullable=True),
    sa.Column('comparison_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('queued','running','completed','failed')", name=op.f('ck_simulation_runs_status_valid')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_simulation_runs'))
    )
    with op.batch_alter_table('simulation_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_simulation_runs_comparison_id'), ['comparison_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_simulation_runs_created_at'), ['created_at'], unique=False)

    op.create_table('service_counters',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('queue_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('service_rate', sa.Float(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('current_load', sa.Integer(), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.CheckConstraint("status IN ('active','paused','closed')", name=op.f('ck_service_counters_status_valid')),
    sa.CheckConstraint('current_load >= 0', name=op.f('ck_service_counters_current_load_nonneg')),
    sa.CheckConstraint('service_rate > 0', name=op.f('ck_service_counters_service_rate_positive')),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_service_counters_queue_id_queues'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_service_counters')),
    sa.UniqueConstraint('queue_id', 'name', name=op.f('uq_service_counters_queue_name'))
    )
    with op.batch_alter_table('service_counters', schema=None) as batch_op:
        batch_op.create_index('ix_service_counters_queue_status', ['queue_id', 'status'], unique=False)

    op.create_table('queue_entries',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('queue_id', sa.Integer(), nullable=False),
    sa.Column('counter_id', sa.Integer(), nullable=True),
    sa.Column('token_number', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('arrival_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('service_start_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('service_end_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.CheckConstraint("status IN ('waiting','serving','completed','removed','abandoned')", name=op.f('ck_queue_entries_status_valid')),
    sa.CheckConstraint('service_end_time IS NULL OR service_start_time IS NULL OR service_end_time >= service_start_time', name=op.f('ck_queue_entries_service_times_ordered')),
    sa.CheckConstraint('token_number > 0', name=op.f('ck_queue_entries_token_positive')),
    sa.ForeignKeyConstraint(['counter_id'], ['service_counters.id'], name=op.f('fk_queue_entries_counter_id_service_counters'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_queue_entries_queue_id_queues'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_queue_entries')),
    sa.UniqueConstraint('queue_id', 'token_number', name=op.f('uq_queue_entries_queue_token'))
    )
    with op.batch_alter_table('queue_entries', schema=None) as batch_op:
        batch_op.create_index('ix_queue_entries_arrival_time', ['arrival_time'], unique=False)
        batch_op.create_index('ix_queue_entries_queue_status_token', ['queue_id', 'status', 'token_number'], unique=False)

    op.create_table('queue_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('queue_id', sa.Integer(), nullable=False),
    sa.Column('counter_id', sa.Integer(), nullable=True),
    sa.Column('event_type', sa.String(length=40), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('metadata', sa.JSON(), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.ForeignKeyConstraint(['counter_id'], ['service_counters.id'], name=op.f('fk_queue_events_counter_id_service_counters'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_queue_events_queue_id_queues'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_queue_events'))
    )
    with op.batch_alter_table('queue_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_queue_events_event_type'), ['event_type'], unique=False)
        batch_op.create_index('ix_queue_events_queue_timestamp', ['queue_id', 'timestamp'], unique=False)

    op.create_table('service_records',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('queue_id', sa.Integer(), nullable=False),
    sa.Column('counter_id', sa.Integer(), nullable=True),
    sa.Column('entry_id', sa.Integer(), nullable=True),
    sa.Column('waiting_time', sa.Float(), nullable=False),
    sa.Column('service_time', sa.Float(), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.CheckConstraint('service_time >= 0', name=op.f('ck_service_records_service_time_nonneg')),
    sa.CheckConstraint('waiting_time >= 0', name=op.f('ck_service_records_waiting_time_nonneg')),
    sa.ForeignKeyConstraint(['counter_id'], ['service_counters.id'], name=op.f('fk_service_records_counter_id_service_counters'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['entry_id'], ['queue_entries.id'], name=op.f('fk_service_records_entry_id_queue_entries'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_service_records_queue_id_queues'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_service_records')),
    sa.UniqueConstraint('entry_id', name=op.f('uq_service_records_entry'))
    )
    with op.batch_alter_table('service_records', schema=None) as batch_op:
        batch_op.create_index('ix_service_records_counter', ['counter_id'], unique=False)
        batch_op.create_index('ix_service_records_queue_completed', ['queue_id', 'completed_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('service_records', schema=None) as batch_op:
        batch_op.drop_index('ix_service_records_queue_completed')
        batch_op.drop_index('ix_service_records_counter')

    op.drop_table('service_records')
    with op.batch_alter_table('queue_events', schema=None) as batch_op:
        batch_op.drop_index('ix_queue_events_queue_timestamp')
        batch_op.drop_index(batch_op.f('ix_queue_events_event_type'))

    op.drop_table('queue_events')
    with op.batch_alter_table('queue_entries', schema=None) as batch_op:
        batch_op.drop_index('ix_queue_entries_queue_status_token')
        batch_op.drop_index('ix_queue_entries_arrival_time')

    op.drop_table('queue_entries')
    with op.batch_alter_table('service_counters', schema=None) as batch_op:
        batch_op.drop_index('ix_service_counters_queue_status')

    op.drop_table('service_counters')
    with op.batch_alter_table('simulation_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_simulation_runs_created_at'))
        batch_op.drop_index(batch_op.f('ix_simulation_runs_comparison_id'))

    op.drop_table('simulation_runs')
    with op.batch_alter_table('queues', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_queues_status'))
        batch_op.drop_index(batch_op.f('ix_queues_name'))
        batch_op.drop_index('ix_queues_is_synthetic')

    op.drop_table('queues')
