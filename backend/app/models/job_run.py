from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobRun(Base):
    """One row per background-task execution (schedule/on-demand/startup-triggered).

    Generalizes two things Celery currently gives for free that no queue library replacement
    provides out of the box: `recompute_snapshots_range`'s live PROGRESS state (`current_step`/
    `total_steps`/`current_label`) and the 4 sync tasks' rich terminal status dict
    (`total_steps`/`succeeded_steps`/`failed_items`/`error`) — see issue #66. `pgq_job_id` is
    intentionally not a foreign key: PgQueuer deletes its own job row on completion, so a hard
    FK would either block that deletion or be dangling by design."""

    __tablename__ = "job_runs"
    __table_args__ = (
        Index("idx_job_runs_task_name_started_at", "task_name", "started_at"),
        Index(
            "uq_job_runs_pgq_job_id", "pgq_job_id", unique=True,
            postgresql_where=text("pgq_job_id IS NOT NULL"),
        ),
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
