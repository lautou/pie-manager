"""Add job_runs table (progress/status foundation for the Celery->PgQueuer migration)

Revision ID: tt33uu44vv55
Revises: ss22tt33uu44
Create Date: 2026-08-13

Issue #66 (Plan a PgQueuer replacement for Celery+Redis) identified two gaps no candidate queue
library solves out of the box: a live progress readout for `recompute_snapshots_range` (today via
Celery's `self.update_state()`/`AsyncResult`) and the 4 sync tasks' rich terminal status dict
(today via Redis keys written by app/tasks/sync_status.py). This table is the app-owned store for
both, generalized into one shape: `current_step`/`total_steps`/`current_label` cover the progress
case, `succeeded_steps`/`failed_items`/`error` cover the rich-status case.

This step (see the "Step 1" plan for issue #66) only adds the table and writes to it
*alongside* the existing Redis/`update_state` calls — Celery/Redis stay the primary,
unmodified data path. `pgq_job_id` is populated only once PgQueuer is actually wired to a real
router in a later step; it is not a foreign key to PgQueuer's own `pgqueuer` table because that
row is deleted by PgQueuer itself on completion (queue, not a log) — a hard FK would either
block that deletion or be dangling by design.
"""
from alembic import op
import sqlalchemy as sa

revision = 'tt33uu44vv55'
down_revision = 'ss22tt33uu44'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'job_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('pgq_job_id', sa.Integer(), nullable=True),
        sa.Column('task_name', sa.String(60), nullable=False),
        sa.Column('trigger', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('started_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('current_step', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_steps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('succeeded_steps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('current_label', sa.String(80), nullable=True),
        sa.Column('failed_items', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('error', sa.String(200), nullable=True),
    )
    op.create_index(
        'idx_job_runs_task_name_started_at', 'job_runs', ['task_name', 'started_at'],
    )
    op.create_index(
        'uq_job_runs_pgq_job_id', 'job_runs', ['pgq_job_id'],
        unique=True, postgresql_where=sa.text('pgq_job_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_job_runs_pgq_job_id', table_name='job_runs')
    op.drop_index('idx_job_runs_task_name_started_at', table_name='job_runs')
    op.drop_table('job_runs')
