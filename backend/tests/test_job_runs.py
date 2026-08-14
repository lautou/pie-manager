"""
Non-regression tests for the job_runs progress/status helpers (app/tasks/job_runs.py).

Real Postgres via the db_session fixture for the `_start_run`/`_update_progress`/`_finish_run`
core (no reason to mock straightforward DB code). The standalone (own-session)
`start_run`/`update_progress`/`finish_run`/`get_latest` wrappers open their own fresh
engine/session per call rather than the fixture's SAVEPOINT-isolated one, so tests exercising
them clean up explicitly instead of relying on rollback.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.job_run import JobRun
from app.tasks import job_runs


@pytest.mark.asyncio
async def test_start_run_creates_running_row(db_session):
    run_id = await job_runs._start_run(db_session, "refresh_prices_live", trigger="schedule")
    run = await db_session.get(JobRun, run_id)
    assert run.task_name == "refresh_prices_live"
    assert run.trigger == "schedule"
    assert run.status == "running"
    assert run.finished_at is None
    assert run.current_step == 0
    assert run.total_steps == 0
    assert run.failed_items == []


@pytest.mark.asyncio
async def test_start_run_accepts_pgq_job_id(db_session):
    run_id = await job_runs._start_run(
        db_session, "recompute_snapshots_range", trigger="on_demand", pgq_job_id=42,
    )
    run = await db_session.get(JobRun, run_id)
    assert run.pgq_job_id == 42


@pytest.mark.asyncio
async def test_start_run_allows_duplicate_pgq_job_id(db_session):
    """Confirmed live (issue #66 step 3, kill/restart resilience pass): PgQueuer redelivers a
    job that was `picked` but never finished to the same job.id after a worker restart, so
    start_run legitimately runs twice for one pgq_job_id — a second row, not an IntegrityError."""
    first_id = await job_runs._start_run(
        db_session, "refresh_country_performance", trigger="on_demand", pgq_job_id=27,
    )
    second_id = await job_runs._start_run(
        db_session, "refresh_country_performance", trigger="on_demand", pgq_job_id=27,
    )
    assert first_id != second_id
    first = await db_session.get(JobRun, first_id)
    second = await db_session.get(JobRun, second_id)
    assert first.pgq_job_id == second.pgq_job_id == 27


@pytest.mark.asyncio
async def test_update_progress_updates_current_total_label(db_session):
    run_id = await job_runs._start_run(db_session, "recompute_snapshots_range", trigger="on_demand")
    await job_runs._update_progress(db_session, run_id, current=3, total=10, label="2026-08-10")
    run = await db_session.get(JobRun, run_id)
    assert run.current_step == 3
    assert run.total_steps == 10
    assert run.current_label == "2026-08-10"


@pytest.mark.asyncio
async def test_finish_run_success_sets_terminal_fields(db_session):
    run_id = await job_runs._start_run(db_session, "refresh_prices_live", trigger="schedule")
    await job_runs._finish_run(
        db_session, run_id, status="success",
        total_steps=5, succeeded_steps=5, failed_items=[], error=None,
    )
    run = await db_session.get(JobRun, run_id)
    assert run.status == "success"
    assert run.finished_at is not None
    assert run.total_steps == 5
    assert run.succeeded_steps == 5
    assert run.failed_items == []
    assert run.error is None


@pytest.mark.asyncio
async def test_finish_run_partial_failure_records_failed_items(db_session):
    run_id = await job_runs._start_run(db_session, "refresh_etf_holdings", trigger="schedule")
    await job_runs._finish_run(
        db_session, run_id, status="partial",
        total_steps=5, succeeded_steps=3, failed_items=["TICKER1", "TICKER2(reason)"],
    )
    run = await db_session.get(JobRun, run_id)
    assert run.status == "partial"
    assert run.succeeded_steps == 3
    assert run.failed_items == ["TICKER1", "TICKER2(reason)"]


@pytest.mark.asyncio
async def test_finish_run_defaults_failed_items_to_empty_list(db_session):
    run_id = await job_runs._start_run(db_session, "refresh_macro_indicators", trigger="schedule")
    await job_runs._finish_run(db_session, run_id, status="failed", error="boom")
    run = await db_session.get(JobRun, run_id)
    assert run.failed_items == []
    assert run.error == "boom"


@pytest.mark.asyncio
async def test_standalone_wrappers_round_trip_against_real_db():
    """Exercises the standalone (own-session) start_run/update_progress/finish_run wrappers
    end-to-end — these open their own fresh engine per call (see job_runs.py's module
    docstring on why), so db_session's SAVEPOINT isolation doesn't apply; clean up explicitly
    instead. Verification also uses its own fresh engine rather than the shared
    app.core.database.AsyncSessionLocal — confirmed live that reusing that shared,
    module-level engine here caused a genuine "Future attached to a different loop" crash when
    running the full suite (each test function gets pytest-asyncio's own event loop, and the
    shared engine's connection pool binds to whichever loop first touched it)."""
    run_id = await job_runs.start_run("refresh_prices_live", trigger="schedule")
    await job_runs.update_progress(run_id, current=1, total=2, label="day-1")
    await job_runs.finish_run(
        run_id, status="partial", total_steps=2, succeeded_steps=1,
        failed_items=["X"], error=None,
    )

    eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    try:
        async with Session() as db:
            run = await db.get(JobRun, run_id)
            assert run.status == "partial"
            assert run.current_step == 1
            assert run.total_steps == 2
            assert run.succeeded_steps == 1
            assert run.failed_items == ["X"]
            await db.delete(run)
            await db.commit()
    finally:
        await eng.dispose()


def test_run_tracked_returns_the_coroutine_result_on_success():
    async def _ok():
        return 42

    assert job_runs.run_tracked(_ok()) == 42


def test_run_tracked_swallows_exceptions_and_returns_none():
    """job_runs bookkeeping must never be able to break the primary Celery task it's
    attached to — a raising coroutine (e.g. Postgres briefly unreachable) is swallowed."""
    async def _boom():
        raise RuntimeError("boom")

    assert job_runs.run_tracked(_boom()) is None


@pytest.mark.asyncio
async def test_standalone_start_run_forwards_pgq_job_id():
    run_id = await job_runs.start_run("refresh_prices_live", trigger="on_demand", pgq_job_id=99)

    eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    try:
        async with Session() as db:
            run = await db.get(JobRun, run_id)
            assert run.pgq_job_id == 99
            await db.delete(run)
            await db.commit()
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_get_latest_returns_most_recent_row_for_task():
    """Uses the standalone (own-session, real-commit) wrappers for setup — get_latest() opens
    its own fresh connection, which can't see db_session's SAVEPOINT-isolated, never-really-
    committed writes (same class of issue documented in job_runs.py's module docstring)."""
    older = await job_runs.start_run("refresh_country_performance", trigger="schedule")
    await job_runs.finish_run(older, status="success")
    newer = await job_runs.start_run("refresh_country_performance", trigger="on_demand")
    await job_runs.finish_run(newer, status="partial")

    run = await job_runs.get_latest("refresh_country_performance")
    assert run is not None
    assert run.id == newer
    assert run.status == "partial"


@pytest.mark.asyncio
async def test_get_latest_returns_none_when_no_rows_exist():
    run = await job_runs.get_latest("a_task_name_nothing_ever_writes_to")
    assert run is None


def test_to_sync_status_dict_never_run_placeholder():
    assert job_runs.to_sync_status_dict(None) == {
        "status": "never", "started_at": None, "finished_at": None,
        "total_tickers": 0, "succeeded": 0, "failed_tickers": [],
    }


@pytest.mark.asyncio
async def test_to_sync_status_dict_maps_a_populated_run(db_session):
    run_id = await job_runs._start_run(db_session, "refresh_etf_holdings", trigger="schedule")
    await job_runs._finish_run(
        db_session, run_id, status="partial",
        total_steps=4, succeeded_steps=3, failed_items=["X(reason)"],
    )
    run = await db_session.get(JobRun, run_id)

    mapped = job_runs.to_sync_status_dict(run)
    assert mapped["status"] == "partial"
    assert mapped["total_tickers"] == 4
    assert mapped["succeeded"] == 3
    assert mapped["failed_tickers"] == ["X(reason)"]
    assert mapped["started_at"] is not None
    assert mapped["finished_at"] is not None
    # issue #72: must carry an explicit UTC offset, not a naive/ambiguous string —
    # otherwise the frontend's `new Date(...)` parses it as local time instead of UTC.
    assert mapped["started_at"].endswith("+00:00")
    assert mapped["finished_at"].endswith("+00:00")


# ---------------------------------------------------------------------------
# get_by_id / to_task_status_dict (issue #66 step 4 — recompute_snapshots_range's
# admin progress-bar polling)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_by_id_returns_the_matching_row():
    run_id = await job_runs.start_run("recompute_snapshots_range", trigger="on_demand")
    run = await job_runs.get_by_id(run_id)
    assert run is not None
    assert run.id == run_id
    assert run.task_name == "recompute_snapshots_range"


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_unknown_id():
    run = await job_runs.get_by_id(-1)
    assert run is None


def test_to_task_status_dict_unknown_run_is_pending():
    assert job_runs.to_task_status_dict(None) == {
        "state": "PENDING", "current": 0, "total": 0, "date": None, "error": None,
    }


def test_to_task_status_dict_running_with_no_progress_yet_is_pending():
    """Enqueued but not yet picked up by pgq-worker (or a slow-starting handler that hasn't
    called update_progress yet) — total_steps==0 must map to PENDING, not PROGRESS. current_
    step/total_steps default to 0 at the DB/INSERT level (see JobRun's mapped_column
    defaults) — set explicitly here since this row is never actually persisted."""
    run = JobRun(
        task_name="recompute_snapshots_range", trigger="on_demand", status="running",
        current_step=0, total_steps=0,
    )
    mapped = job_runs.to_task_status_dict(run)
    assert mapped == {"state": "PENDING", "current": 0, "total": 0, "date": None, "error": None}


def test_to_task_status_dict_running_with_progress():
    run = JobRun(
        task_name="recompute_snapshots_range", trigger="on_demand", status="running",
        current_step=3, total_steps=10, current_label="2026-05-16",
    )
    mapped = job_runs.to_task_status_dict(run)
    assert mapped == {
        "state": "PROGRESS", "current": 3, "total": 10, "date": "2026-05-16", "error": None,
    }


@pytest.mark.parametrize("status", ["success", "partial"])
def test_to_task_status_dict_success_or_partial_is_success(status):
    """'partial' is unreachable for recompute_snapshots_range today (its own finish_run call
    always writes 'success'), but to_task_status_dict is a general-purpose mapper like its
    sibling to_sync_status_dict — cover the branch directly."""
    run = JobRun(
        task_name="recompute_snapshots_range", trigger="on_demand", status=status,
        total_steps=8, current_label="2026-05-20",
    )
    mapped = job_runs.to_task_status_dict(run)
    assert mapped == {
        "state": "SUCCESS", "current": 8, "total": 8, "date": "2026-05-20", "error": None,
    }


def test_to_task_status_dict_failed():
    run = JobRun(
        task_name="recompute_snapshots_range", trigger="on_demand", status="failed",
        current_step=2, total_steps=10, current_label="2026-05-17", error="boom",
    )
    mapped = job_runs.to_task_status_dict(run)
    assert mapped == {
        "state": "FAILURE", "current": 2, "total": 10, "date": "2026-05-17", "error": "boom",
    }
