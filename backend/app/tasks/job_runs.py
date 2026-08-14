"""
Postgres-backed foundation for background-job progress/status tracking (issue #66).

Generalizes two things Celery+Redis currently provide for free that no queue-library
replacement gives out of the box: `recompute_snapshots_range`'s live PROGRESS state, and the
4 sync tasks' rich terminal status dict. See app/models/job_run.py for the schema.

As of issue #66 step 4, `job_runs` is the sole status store for all 6 periodic/on-demand
background tasks — the 4 independent sync tasks migrated in step 3
(refresh_prices_live/refresh_etf_holdings/refresh_macro_indicators/refresh_country_performance)
plus the 4 snapshot-family tasks migrated in step 4 (compute_daily_snapshots_all_users/
compute_monthly_snapshots_all_users/fill_missing_snapshots/recompute_snapshots_range). Their
Redis dual-write (app/tasks/sync_status.py) and Celery's own AsyncResult have both been
removed. `recompute_snapshots_range` is the one task whose `job_runs` row is created by its
*caller* (app/api/routers/admin.py) before enqueueing, not by its own PgQueuer handler — see
`get_by_id`/`to_task_status_dict` below and pgq_app.py's registration for why.

Two API levels: `_start_run`/`_update_progress`/`_finish_run` take an explicit `db` session
(directly testable against the real db_session fixture); `start_run`/`update_progress`/
`finish_run`/`get_latest` are the standalone, own-session convenience wrappers callable from
either a sync Celery task body (via `asyncio.run(...)`) or directly `await`ed from an async
context (PgQueuer handlers, FastAPI routes) — both are safe since each opens its own fresh
engine per call (see below).

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

from sqlalchemy import select
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


async def start_run(task_name: str, trigger: str, pgq_job_id: int | None = None) -> int:
    Session, eng = _make_session()
    try:
        async with Session() as db:
            return await _start_run(db, task_name, trigger, pgq_job_id=pgq_job_id)
    finally:
        await eng.dispose()


async def get_latest(task_name: str) -> JobRun | None:
    Session, eng = _make_session()
    try:
        async with Session() as db:
            result = await db.execute(
                select(JobRun).where(JobRun.task_name == task_name)
                .order_by(JobRun.id.desc()).limit(1)
            )
            return result.scalars().first()
    finally:
        await eng.dispose()


async def get_by_id(run_id: int) -> JobRun | None:
    Session, eng = _make_session()
    try:
        async with Session() as db:
            return await db.get(JobRun, run_id)
    finally:
        await eng.dispose()


def to_task_status_dict(run: JobRun | None) -> dict:
    """Maps a JobRun onto the admin recompute-snapshots progress-bar JSON shape polled via
    GET /api/admin/task/{task_id} — a distinct shape/consumer from to_sync_status_dict above
    (that one serves the 4 already-migrated tasks' /sync-status endpoints). `state` mirrors
    Celery AsyncResult's own vocabulary (PENDING/PROGRESS/SUCCESS/FAILURE) since the frontend's
    TaskStatus.state TS type is a closed union over exactly those 4 strings — any other value
    renders a blank result box in SystemAdminPage.tsx, so an unrecognized run_id or a `running`
    row with no progress yet must map to PENDING, not fall through unmapped."""
    if run is None or (run.status == "running" and run.total_steps == 0):
        return {"state": "PENDING", "current": 0, "total": 0, "date": None, "error": None}
    if run.status == "running":
        return {
            "state": "PROGRESS", "current": run.current_step, "total": run.total_steps,
            "date": run.current_label, "error": None,
        }
    if run.status in ("success", "partial"):
        return {
            "state": "SUCCESS", "current": run.total_steps, "total": run.total_steps,
            "date": run.current_label, "error": None,
        }
    return {
        "state": "FAILURE", "current": run.current_step, "total": run.total_steps,
        "date": run.current_label, "error": run.error,
    }


def to_sync_status_dict(run: JobRun | None) -> dict:
    """Maps a JobRun onto the sync-status JSON shape every GET .../sync-status endpoint
    returns — a free function (not a JobRun method) since it must also represent the
    "never run" case, which a method can't cleanly do on a None receiver."""
    if run is None:
        return {
            "status": "never", "started_at": None, "finished_at": None,
            "total_tickers": 0, "succeeded": 0, "failed_tickers": [],
        }
    return {
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "total_tickers": run.total_steps,
        "succeeded": run.succeeded_steps,
        "failed_tickers": run.failed_items,
    }


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
