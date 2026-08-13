"""
Postgres-backed foundation for background-job progress/status tracking (issue #66).

Generalizes two things Celery+Redis currently provide for free that no queue-library
replacement gives out of the box: `recompute_snapshots_range`'s live PROGRESS state, and the
4 sync tasks' rich terminal status dict. See app/models/job_run.py for the schema.

In this step every write here happens *alongside* the existing Celery/Redis `write_status`
calls (app/tasks/sync_status.py) -- Celery/Redis remain the primary read path for the frontend
until a later step cuts routers over to read from job_runs instead.

Two API levels: `_start_run`/`_update_progress`/`_finish_run` take an explicit `db` session
(directly testable against the real db_session fixture); `start_run`/`update_progress`/
`finish_run` are the standalone, own-session convenience wrappers that task modules call from
inside a sync Celery task body via `asyncio.run(...)`.

The standalone wrappers each open a *fresh* engine per call rather than reusing the shared
module-level `AsyncSessionLocal` — mirroring app/tasks/snapshots.py's own `make_session()`
helper and its documented reason ("Fresh engine + session per asyncio.run() call to avoid loop
binding issues"). A sync Celery task body can call multiple of these wrappers across separate
`asyncio.run()` calls (each spins up and tears down its own event loop); a shared,
already-connected engine gets bound to whichever loop first touched it and silently
misbehaves on a later, different one. Confirmed live: reusing the shared AsyncSessionLocal
here made `start_run` intermittently fail (swallowed by `run_tracked`, surfacing only as a
stray "fully NULL primary key identity" SAWarning from the following `_update_progress` call).
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Coroutine

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.job_run import JobRun


async def _start_run(
    db: AsyncSession, task_name: str, trigger: str, pgq_job_id: int | None = None,
) -> int:
    run = JobRun(task_name=task_name, trigger=trigger, pgq_job_id=pgq_job_id, status="running")
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run.id


async def _update_progress(
    db: AsyncSession, run_id: int, current: int, total: int, label: str | None,
) -> None:
    run = await db.get(JobRun, run_id)
    run.current_step = current
    run.total_steps = total
    run.current_label = label
    await db.commit()


async def _finish_run(
    db: AsyncSession,
    run_id: int,
    status: str,
    total_steps: int = 0,
    succeeded_steps: int = 0,
    failed_items: list | None = None,
    error: str | None = None,
) -> None:
    run = await db.get(JobRun, run_id)
    run.status = status
    # naive UTC: the `finished_at` column is DateTime without a timezone — asyncpg rejects
    # binding a timezone-aware value against it ("can't subtract offset-naive and
    # offset-aware datetimes"), confirmed live against a real Postgres in test_job_runs.py.
    run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    run.total_steps = total_steps
    run.succeeded_steps = succeeded_steps
    run.failed_items = failed_items or []
    run.error = error
    await db.commit()


def _make_session() -> tuple[async_sessionmaker, AsyncEngine]:
    eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
    return async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession), eng


async def start_run(task_name: str, trigger: str) -> int:
    Session, eng = _make_session()
    try:
        async with Session() as db:
            return await _start_run(db, task_name, trigger)
    finally:
        await eng.dispose()


async def update_progress(run_id: int, current: int, total: int, label: str | None) -> None:
    Session, eng = _make_session()
    try:
        async with Session() as db:
            await _update_progress(db, run_id, current, total, label)
    finally:
        await eng.dispose()


async def finish_run(
    run_id: int,
    status: str,
    total_steps: int = 0,
    succeeded_steps: int = 0,
    failed_items: list | None = None,
    error: str | None = None,
) -> None:
    Session, eng = _make_session()
    try:
        async with Session() as db:
            await _finish_run(
                db, run_id, status,
                total_steps=total_steps, succeeded_steps=succeeded_steps,
                failed_items=failed_items, error=error,
            )
    finally:
        await eng.dispose()


def run_tracked(coro: Coroutine[Any, Any, Any]) -> Any | None:
    """Run a job_runs coroutine via asyncio.run from inside a sync Celery task body,
    swallowing any failure. This is observability/progress-tracking plumbing (issue #66 step
    1, dual-written alongside the still-authoritative Redis/update_state calls) and must never
    be able to break the primary task it's attached to."""
    try:
        return asyncio.run(coro)
    except Exception:
        return None
