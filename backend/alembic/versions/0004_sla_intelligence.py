"""SLA & Customer Experience Intelligence: sla_policies + queue_entries.service_class

Adds one new table and ONE nullable column (`queue_entries.service_class`); existing rows keep NULL, which means the
queue's 'standard' class. Nothing else is altered. `downgrade` removes exactly these two things.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('sla_policies',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('queue_id', sa.Integer(), nullable=False),
    sa.Column('service_class', sa.String(length=40), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=True),
    sa.Column('max_wait_min', sa.Float(), nullable=False),
    sa.Column('at_risk_probability', sa.Float(), nullable=False),
    sa.Column('critical_probability', sa.Float(), nullable=False),
    sa.Column('updated_by', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('max_wait_min > 0 AND max_wait_min <= 1440', name=op.f('ck_sla_policies_max_wait_range')),
    sa.CheckConstraint('at_risk_probability > 0 AND at_risk_probability < critical_probability AND critical_probability < 1', name=op.f('ck_sla_policies_thresholds_ordered')),
    sa.ForeignKeyConstraint(['queue_id'], ['queues.id'], name=op.f('fk_sla_policies_queue_id_queues'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sla_policies')),
    sa.UniqueConstraint('queue_id', 'service_class', name=op.f('uq_sla_policies_queue_class'))
    )
    with op.batch_alter_table('sla_policies', schema=None) as batch_op:
        batch_op.create_index('ix_sla_policies_queue', ['queue_id'], unique=False)
    with op.batch_alter_table('queue_entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('service_class', sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('queue_entries', schema=None) as batch_op:
        batch_op.drop_column('service_class')
    with op.batch_alter_table('sla_policies', schema=None) as batch_op:
        batch_op.drop_index('ix_sla_policies_queue')
    op.drop_table('sla_policies')
