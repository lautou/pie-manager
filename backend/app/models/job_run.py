# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobRun(Base):
    """One row per background-task execution attempt (schedule/on-demand/startup-triggered).

    Generalizes two things Celery currently gives for free that no queue library replacement
    provides out of the box: `recompute_snapshots_range`'s live PROGRESS state (`current_step`/
    `total_steps`/`current_label`) and the 4 sync tasks' rich terminal status dict
    (`total_steps`/`succeeded_steps`/`failed_items`/`error`) — see issue #66. `pgq_job_id` is
    intentionally not a foreign key: PgQueuer deletes its own job row on completion, so a hard
    FK would either block that deletion or be dangling by design.

    `pgq_job_id` is deliberately NOT unique. Confirmed live (issue #66 step 3, resilience pass):
    if pgq-worker dies mid-handler, PgQueuer redelivers the same still-`picked` job (same
    `job.id`) after restart, so the entrypoint handler's own `start_run` call runs a second time
    for that job_id — a unique constraint here turned a routine, expected redelivery into an
    unhandled IntegrityError. Each row is one execution attempt; several rows sharing a
    `pgq_job_id` is the normal shape of a job that needed more than one attempt, not corruption."""

    __tablename__ = "job_runs"
    __table_args__ = (
        Index("idx_job_runs_task_name_started_at", "task_name", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pgq_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_name: Mapped[str] = mapped_column(String(60), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failed_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
