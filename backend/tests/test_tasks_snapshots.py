"""
Tests for app/tasks/snapshots.py.

_compute_daily_snapshots_all_users/_compute_monthly_snapshots_all_users are unchanged from
before issue #66 (still called directly, not via Celery's .delay() — PgQueuer wraps them now,
see app/tasks/pgq_app.py and test_pgq_app.py). _run_fill_missing_snapshots and
_run_recompute_snapshots are new (issue #66 step 4) async cores, replacing the old Celery
tasks' asyncio.run()-per-phase bodies with a single session/engine for the whole run — see
pgq_app.py's module docstring for why nesting asyncio.run() inside a PgQueuer handler crashes.
refresh_prices_task (dead code — no beat entry, no caller anywhere, fully superseded by
app/tasks/prices.py's refresh_prices_live) was deleted along with its tests here.
"""
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks import job_runs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_portfolio(pid: int):
    """Minimal portfolio-like object with .id attribute."""
    p = MagicMock()
    p.id = pid
    return p


def _make_full_session(mock_db):
    """Wrap mock_db in a session factory that works as async context manager.

    Uses a plain class with async __aenter__/__aexit__ to avoid leaking
    AsyncMock._execute_mock_call coroutines in Python 3.14's stricter GC.
    """
    class _FakeSession:
        async def __aenter__(self):
            return mock_db

        async def __aexit__(self, *args):
            return False

    return MagicMock(return_value=_FakeSession())


def _make_engine_mock():
    """Make a mock async engine."""
    eng = MagicMock()
    eng.dispose = AsyncMock()
    return eng


# ---------------------------------------------------------------------------
# _compute_daily_snapshots_all_users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_compute_daily_iterates_all_portfolios():
    """
    _compute_daily_snapshots_all_users must call compute_daily_snapshot
    for every portfolio returned by get_all_portfolios and commit once.
    """
    import app.tasks.snapshots as mod

    portfolios = [_make_portfolio(1), _make_portfolio(2)]

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_session_class = _make_full_session(mock_db)

    with patch.object(mod, "AsyncSessionLocal", mock_session_class), \
         patch.object(mod, "get_all_portfolios", new_callable=AsyncMock, return_value=portfolios), \
         patch.object(mod, "compute_daily_snapshot", new_callable=AsyncMock) as mock_snap:
        await mod._compute_daily_snapshots_all_users("2025-03-10")

    assert mock_snap.call_count == 2
    calls = mock_snap.call_args_list
    user_ids_called = {c.kwargs["portfolio_id"] for c in calls}
    assert user_ids_called == {1, 2}
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_async_compute_daily_defaults_to_today():
    """When target_date_str is None, snap_date defaults to date.today()."""
    import app.tasks.snapshots as mod

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_session_class = _make_full_session(mock_db)

    with patch.object(mod, "AsyncSessionLocal", mock_session_class), \
         patch.object(mod, "get_all_portfolios", new_callable=AsyncMock, return_value=[]), \
         patch.object(mod, "compute_daily_snapshot", new_callable=AsyncMock):
        await mod._compute_daily_snapshots_all_users(None)


# ---------------------------------------------------------------------------
# _compute_monthly_snapshots_all_users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_compute_monthly_iterates_all_portfolios():
    import app.tasks.snapshots as mod

    portfolios = [_make_portfolio(10), _make_portfolio(20)]

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_session_class = _make_full_session(mock_db)

    with patch.object(mod, "AsyncSessionLocal", mock_session_class), \
         patch.object(mod, "get_all_portfolios", new_callable=AsyncMock, return_value=portfolios), \
         patch.object(mod, "compute_monthly_snapshot", new_callable=AsyncMock) as mock_snap:
        await mod._compute_monthly_snapshots_all_users("2025-01-31")

    assert mock_snap.call_count == 2
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_async_compute_monthly_defaults_to_today():
    import app.tasks.snapshots as mod

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_session_class = _make_full_session(mock_db)

    with patch.object(mod, "AsyncSessionLocal", mock_session_class), \
         patch.object(mod, "get_all_portfolios", new_callable=AsyncMock, return_value=[]), \
         patch.object(mod, "compute_monthly_snapshot", new_callable=AsyncMock):
        await mod._compute_monthly_snapshots_all_users(None)


# ---------------------------------------------------------------------------
# _run_fill_missing_snapshots — single session for the whole run (issue #66 step 4)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_fill_missing_snapshots_no_portfolios():
    import app.tasks.snapshots as mod

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    session_factory = _make_full_session(mock_db)

    with patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await mod._run_fill_missing_snapshots()

    assert result == {"status": "success", "total_tickers": 0, "succeeded": 0, "failed_tickers": []}


@pytest.mark.asyncio
async def test_run_fill_missing_snapshots_already_up_to_date():
    """If last_date is yesterday, start > yesterday → continue (no computation)."""
    import app.tasks.snapshots as mod

    yesterday = date.today() - timedelta(days=1)
    portfolio = _make_portfolio(99)

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = yesterday
    mock_db.execute = AsyncMock(return_value=scalar_result)

    session_factory = _make_full_session(mock_db)

    with patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[portfolio]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.snapshots.compute_daily_snapshot", new_callable=AsyncMock) as mock_snap:
        result = await mod._run_fill_missing_snapshots()

    mock_snap.assert_not_called()
    assert result["succeeded"] == 0


@pytest.mark.asyncio
async def test_run_fill_missing_snapshots_computes_missing_days():
    """If last_date is 3 days ago and there are 2 trading days to fill,
    compute_daily_snapshot is called once per trading day."""
    import app.tasks.snapshots as mod

    yesterday = date.today() - timedelta(days=1)
    two_days_ago = yesterday - timedelta(days=1)
    trading_days = [two_days_ago, yesterday]
    portfolio = _make_portfolio(7)
    four_days_ago = yesterday - timedelta(days=3)

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = four_days_ago
    all_result = MagicMock()
    all_result.all.return_value = [(d,) for d in trading_days]
    mock_db.execute = AsyncMock(side_effect=[scalar_result, all_result])

    session_factory = _make_full_session(mock_db)
    snap_mock = AsyncMock()

    with patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[portfolio]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.snapshots.compute_daily_snapshot", snap_mock):
        result = await mod._run_fill_missing_snapshots()

    assert snap_mock.call_count == len(trading_days)
    assert result["succeeded"] == len(trading_days)


@pytest.mark.asyncio
async def test_run_fill_missing_snapshots_no_last_date_uses_default_start():
    """When no last DailySnapshot exists, start = date(2024, 1, 1).
    If no trading days are returned either, nothing is computed."""
    import app.tasks.snapshots as mod

    portfolio = _make_portfolio(42)
    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    all_result = MagicMock()
    all_result.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[scalar_result, all_result])
    session_factory = _make_full_session(mock_db)

    with patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[portfolio]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.snapshots.compute_daily_snapshot", new_callable=AsyncMock) as mock_snap:
        await mod._run_fill_missing_snapshots()

    mock_snap.assert_not_called()


@pytest.mark.asyncio
async def test_run_fill_missing_snapshots_exception_in_compute_does_not_crash():
    """If compute_daily_snapshot raises for one day, the loop continues without crash —
    the exception is caught and that day's session is rolled back, not the whole run."""
    import app.tasks.snapshots as mod

    yesterday = date.today() - timedelta(days=1)
    portfolio = _make_portfolio(55)
    four_days_ago = yesterday - timedelta(days=3)

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    mock_db.rollback = AsyncMock()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = four_days_ago
    all_result = MagicMock()
    all_result.all.return_value = [(yesterday,)]
    mock_db.execute = AsyncMock(side_effect=[scalar_result, all_result])
    session_factory = _make_full_session(mock_db)

    snap_mock = AsyncMock(side_effect=RuntimeError("DB exploded"))

    with patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[portfolio]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.snapshots.compute_daily_snapshot", snap_mock):
        # Must not raise
        result = await mod._run_fill_missing_snapshots()

    mock_db.rollback.assert_called_once()
    assert result["succeeded"] == 0


# ---------------------------------------------------------------------------
# _run_recompute_snapshots — single session for the whole run; run_id is created by the
# caller (admin.py) before enqueue, this core only ever reports progress onto it.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_recompute_snapshots_no_trading_days():
    import app.tasks.snapshots as mod

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    trading_result = MagicMock()
    trading_result.all.return_value = []
    mock_db.execute = AsyncMock(return_value=trading_result)
    session_factory = _make_full_session(mock_db)

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[]), \
         patch("app.tasks.snapshots.compute_daily_snapshot", new_callable=AsyncMock) as mock_snap:
        result = await mod._run_recompute_snapshots("2025-01-01", "2025-01-07", run_id=1)

    mock_snap.assert_not_called()
    assert result == {"total": 0}


@pytest.mark.asyncio
async def test_run_recompute_snapshots_propagates_exception_unchanged():
    """A failure fetching portfolios/trading days propagates as-is — the caller (pgq_app.py's
    entrypoint handler) is responsible for catching it and recording job_runs failure, not
    this core."""
    import app.tasks.snapshots as mod

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    trading_result = MagicMock()
    trading_result.all.return_value = []
    mock_db.execute = AsyncMock(return_value=trading_result)
    session_factory = _make_full_session(mock_db)

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.snapshots.get_all_portfolios",
               new_callable=AsyncMock, side_effect=RuntimeError("portfolios unavailable")):
        with pytest.raises(RuntimeError, match="portfolios unavailable"):
            await mod._run_recompute_snapshots("2025-01-01", "2025-01-07", run_id=1)


@pytest.mark.asyncio
async def test_run_recompute_snapshots_updates_progress_and_computes(engine):
    """2 trading days, 1 portfolio: compute_daily_snapshot called twice, job_runs.
    update_progress called once per day against a real row (engine fixture guarantees the
    schema exists — this is a real DB write, matching this module's established convention
    for job_runs-touching tests, see job_runs.py's own module docstring)."""
    import app.tasks.snapshots as mod

    portfolio = _make_portfolio(5)
    trading_days = [date(2025, 1, 2), date(2025, 1, 3)]

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    trading_result = MagicMock()
    trading_result.all.return_value = [(d,) for d in trading_days]
    mock_db.execute = AsyncMock(return_value=trading_result)
    session_factory = _make_full_session(mock_db)

    snap_mock = AsyncMock()
    run_id = await job_runs.start_run("recompute_snapshots_range", trigger="on_demand")

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[portfolio]), \
         patch("app.tasks.snapshots.compute_daily_snapshot", snap_mock):
        result = await mod._run_recompute_snapshots("2025-01-01", "2025-01-07", run_id)

    assert snap_mock.call_count == 2
    assert result == {"total": 2}

    run = await job_runs.get_by_id(run_id)
    assert run.current_step == 2
    assert run.total_steps == 2
    assert run.current_label == "2025-01-03"


@pytest.mark.asyncio
async def test_run_recompute_snapshots_exception_per_portfolio_continues():
    """If compute_daily_snapshot raises for a portfolio, the run continues silently (matches
    the old Celery task's per-portfolio exception swallowing)."""
    import app.tasks.snapshots as mod

    portfolio = _make_portfolio(8)
    trading_days = [date(2025, 2, 3)]

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    trading_result = MagicMock()
    trading_result.all.return_value = [(d,) for d in trading_days]
    mock_db.execute = AsyncMock(return_value=trading_result)
    session_factory = _make_full_session(mock_db)

    snap_mock = AsyncMock(side_effect=RuntimeError("compute failed"))

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[portfolio]), \
         patch("app.tasks.snapshots.compute_daily_snapshot", snap_mock), \
         patch("app.tasks.job_runs.update_progress", new_callable=AsyncMock):
        # Must not raise
        result = await mod._run_recompute_snapshots("2025-02-01", "2025-02-28", run_id=1)

    assert snap_mock.call_count == 1
    assert result == {"total": 1}
