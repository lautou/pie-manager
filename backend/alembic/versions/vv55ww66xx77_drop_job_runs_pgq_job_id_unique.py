# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drop job_runs.pgq_job_id's unique constraint (issue #66 step 3, resilience finding)

Revision ID: vv55ww66xx77
Revises: uu44vv55ww66
Create Date: 2026-08-13

Live kill/restart resilience testing (Pass 3 of issue #66 step 3's verification plan) found
that PgQueuer redelivers a job that was `picked` but never finished (pgq-worker killed
mid-handler) to the *same* `job.id` once the worker restarts. The entrypoint handler calls
`job_runs.start_run(..., pgq_job_id=job.id)` again for that redelivery, which raised
`IntegrityError` against the unique partial index added in `tt33uu44vv55` — a routine,
expected PgQueuer redelivery was crashing the job instead of being tracked as a second
attempt. See the updated docstring on `JobRun` (`app/models/job_run.py`) for the full
rationale kept alongside the model.
"""
from alembic import op
import sqlalchemy as sa

revision = 'vv55ww66xx77'
down_revision = 'uu44vv55ww66'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index('uq_job_runs_pgq_job_id', table_name='job_runs')


def downgrade() -> None:
    op.create_index(
        'uq_job_runs_pgq_job_id', 'job_runs', ['pgq_job_id'],
        unique=True, postgresql_where=sa.text('pgq_job_id IS NOT NULL'),
    )
