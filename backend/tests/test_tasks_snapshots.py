"""
Tests for app/tasks/snapshots.py — Celery tasks for snapshot computation.

All tests call the task functions directly (not via .delay()) and mock all
async DB calls so no real database is needed. This isolates the orchestration
logic from the snapshot computation logic.

Coverage targets:
  - compute_daily_snapshots_all_users  (lines 13-14)
  - compute_monthly_snapshots_all_users (lines 17-19)
  - _compute_daily_snapshots_all_users  (lines 22-28)
  - _compute_monthly_snapshots_all_users (lines 31-37)
  - fill_missing_snapshots              (lines 40-100)
  - recompute_snapshots_range           (lines 103-167)
  - refresh_prices_task                 (lines 170-225)
"""
import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from tests.conftest import fetch_latest_job_run


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
# compute_daily_snapshots_all_users  (lines 12-14)
# ---------------------------------------------------------------------------

def test_compute_daily_snapshots_all_users_calls_asyncio_run():
    """
    The Celery task must call asyncio.run. We verify it runs without error
    by mocking the async helper to be a plain coroutine that returns immediately.
    """
    import app.tasks.snapshots as mod

    async def fake_helper(target_date_str):
        return None

    with patch.object(mod, "_compute_daily_snapshots_all_users", side_effect=fake_helper), \
         patch("app.tasks.snapshots.asyncio.run") as mock_run:
        mock_run.return_value = None
        mod.compute_daily_snapshots_all_users("2025-01-15")
        assert mock_run.called


def test_compute_daily_snapshots_all_users_no_date():
    """Passing no target_date calls the helper with None."""
    import app.tasks.snapshots as mod

    async def fake_helper(target_date_str):
        assert target_date_str is None

    with patch.object(mod, "_compute_daily_snapshots_all_users", side_effect=fake_helper), \
         patch("app.tasks.snapshots.asyncio.run") as mock_run:
        mock_run.return_value = None
        mod.compute_daily_snapshots_all_users()
        assert mock_run.called


# ---------------------------------------------------------------------------
# compute_monthly_snapshots_all_users  (lines 17-19)
# ---------------------------------------------------------------------------

def test_compute_monthly_snapshots_all_users_calls_asyncio_run():
    import app.tasks.snapshots as mod

    async def fake_helper(target_date_str):
        return None

    with patch.object(mod, "_compute_monthly_snapshots_all_users", side_effect=fake_helper), \
         patch("app.tasks.snapshots.asyncio.run") as mock_run:
        mock_run.return_value = None
        mod.compute_monthly_snapshots_all_users("2025-02-28")
        assert mock_run.called


def test_compute_monthly_snapshots_all_users_no_date():
    import app.tasks.snapshots as mod

    async def fake_helper(target_date_str):
        assert target_date_str is None

    with patch.object(mod, "_compute_monthly_snapshots_all_users", side_effect=fake_helper), \
         patch("app.tasks.snapshots.asyncio.run") as mock_run:
        mock_run.return_value = None
        mod.compute_monthly_snapshots_all_users()
        assert mock_run.called


# ---------------------------------------------------------------------------
# _compute_daily_snapshots_all_users  (lines 22-28)
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
# _compute_monthly_snapshots_all_users  (lines 31-37)
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
# fill_missing_snapshots  (lines 40-100)
# ---------------------------------------------------------------------------

def test_fill_missing_snapshots_no_portfolios():
    """
    fill_missing_snapshots with no portfolios → nothing computed, no error.
    """
    import app.tasks.snapshots as mod

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    all_result = MagicMock()
    all_result.all.return_value = []
    mock_db.execute = AsyncMock(return_value=scalar_result)

    session_factory = _make_full_session(mock_db)

    with patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.snapshots.compute_daily_snapshot", new_callable=AsyncMock):
        mod.fill_missing_snapshots()


def test_fill_missing_snapshots_already_up_to_date():
    """
    If last_date is yesterday, start > yesterday → continue (no computation).
    """
    import app.tasks.snapshots as mod

    yesterday = date.today() - timedelta(days=1)
    portfolio = _make_portfolio(99)

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = yesterday

    all_result = MagicMock()
    all_result.all.return_value = []

    mock_db.execute = AsyncMock(side_effect=[scalar_result, all_result])

    session_factory = _make_full_session(mock_db)

    with patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[portfolio]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.tasks.snapshots.compute_daily_snapshot", new_callable=AsyncMock) as mock_snap:
        mod.fill_missing_snapshots()

    mock_snap.assert_not_called()


def test_fill_missing_snapshots_computes_missing_days():
    """
    If last_date is 3 days ago and there are 2 trading days to fill,
    compute_daily_snapshot is called once per trading day.
    """
    import app.tasks.snapshots as mod

    yesterday = date.today() - timedelta(days=1)
    two_days_ago = yesterday - timedelta(days=1)
    trading_days = [two_days_ago, yesterday]
    portfolio = _make_portfolio(7)

    # Each asyncio.run() call gets a fresh engine
    mock_eng = _make_engine_mock()

    # DB for gap-detection phase
    mock_db_gaps = AsyncMock()
    four_days_ago = yesterday - timedelta(days=3)
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = four_days_ago
    all_result = MagicMock()
    all_result.all.return_value = [(d,) for d in trading_days]
    mock_db_gaps.execute = AsyncMock(side_effect=[scalar_result, all_result])
    session_gaps = _make_full_session(mock_db_gaps)

    # DB for compute phases
    mock_db_compute = AsyncMock()
    mock_db_compute.commit = AsyncMock()
    session_compute = _make_full_session(mock_db_compute)

    session_call_count = [0]

    def session_factory_side(*args, **kwargs):
        session_call_count[0] += 1
        if session_call_count[0] == 1:
            return session_gaps()
        return session_compute()

    snap_mock = AsyncMock()

    with patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[portfolio]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=MagicMock(side_effect=session_factory_side)), \
         patch("app.tasks.snapshots.compute_daily_snapshot", snap_mock):
        mod.fill_missing_snapshots()

    assert snap_mock.call_count == len(trading_days)


def test_fill_missing_snapshots_no_last_date_uses_default_start():
    """
    When no last DailySnapshot exists, start = date(2024, 1, 1).
    If no trading days are returned either, nothing is computed.
    """
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
        mod.fill_missing_snapshots()

    mock_snap.assert_not_called()


def test_fill_missing_snapshots_exception_in_compute_does_not_crash():
    """
    If compute_daily_snapshot raises for one day, the loop continues without crash.
    """
    import app.tasks.snapshots as mod

    yesterday = date.today() - timedelta(days=1)
    portfolio = _make_portfolio(55)

    mock_eng = _make_engine_mock()

    mock_db_gaps = AsyncMock()
    four_days_ago = yesterday - timedelta(days=3)
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = four_days_ago
    all_result = MagicMock()
    all_result.all.return_value = [(yesterday,)]
    mock_db_gaps.execute = AsyncMock(side_effect=[scalar_result, all_result])
    session_gaps = _make_full_session(mock_db_gaps)

    mock_db_compute = AsyncMock()
    mock_db_compute.commit = AsyncMock()
    session_compute = _make_full_session(mock_db_compute)

    session_call_count = [0]

    def session_factory_side(*args, **kwargs):
        session_call_count[0] += 1
        if session_call_count[0] == 1:
            return session_gaps()
        return session_compute()

    snap_mock = AsyncMock(side_effect=RuntimeError("DB exploded"))

    with patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[portfolio]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=MagicMock(side_effect=session_factory_side)), \
         patch("app.tasks.snapshots.compute_daily_snapshot", snap_mock):
        # Must not raise
        mod.fill_missing_snapshots()


# ---------------------------------------------------------------------------
# recompute_snapshots_range  (lines 103-167)
#
# bind=True task: access the underlying function via .__wrapped__ or run
# by calling the function attribute on the class directly. Since celery
# decorates at import time, we call mod.recompute_snapshots_range.run(...)
# using the task's __wrapped__ attribute, or we call the raw function by
# accessing __func__ from the Celery task object.
# ---------------------------------------------------------------------------

def test_recompute_snapshots_range_no_trading_days():
    """
    recompute_snapshots_range with no trading days in date range → no compute called.
    task.run is a bound method (self=task instance already bound by Celery).
    Call it with just (start_date, end_date).
    """
    import app.tasks.snapshots as mod

    mock_eng = _make_engine_mock()
    mock_db_trading = AsyncMock()
    trading_result = MagicMock()
    trading_result.all.return_value = []
    mock_db_trading.execute = AsyncMock(return_value=trading_result)
    session_trading = _make_full_session(mock_db_trading)

    mock_db_portfolios = AsyncMock()
    session_portfolios = _make_full_session(mock_db_portfolios)

    call_count = [0]

    def session_factory_side(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return session_trading()
        return session_portfolios()

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=MagicMock(side_effect=session_factory_side)), \
         patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[]), \
         patch("app.tasks.snapshots.compute_daily_snapshot", new_callable=AsyncMock) as mock_snap:
        # task.run is a bound method — call with just (start_date, end_date)
        mod.recompute_snapshots_range.run("2025-01-01", "2025-01-07")

    mock_snap.assert_not_called()


def test_recompute_snapshots_range_reraises_and_records_job_runs_failure(engine):
    """If the task fails before/during the trading-days or portfolios fetch, the exception
    still propagates unchanged (existing behavior) — the job_runs dual-write (issue #66 step
    1) just also records a 'failed' row alongside it, it must never swallow the real error."""
    import app.tasks.snapshots as mod

    mock_eng = _make_engine_mock()
    mock_db_trading = AsyncMock()
    trading_result = MagicMock()
    trading_result.all.return_value = []
    mock_db_trading.execute = AsyncMock(return_value=trading_result)
    session_trading = _make_full_session(mock_db_trading)

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker",
               return_value=MagicMock(side_effect=lambda *a, **kw: session_trading())), \
         patch("app.tasks.snapshots.get_all_portfolios",
               new_callable=AsyncMock, side_effect=RuntimeError("portfolios unavailable")):
        with pytest.raises(RuntimeError, match="portfolios unavailable"):
            mod.recompute_snapshots_range.run("2025-01-01", "2025-01-07")

    run = asyncio.run(fetch_latest_job_run("recompute_snapshots_range"))
    assert run.status == "failed"
    assert run.error == "portfolios unavailable"


def test_recompute_snapshots_range_calls_update_state_and_compute(engine):
    """
    recompute_snapshots_range with 2 trading days and 1 portfolio calls
    update_state twice and compute_daily_snapshot twice.
    We patch self.update_state to avoid Celery trying to talk to the broker.

    Also exercises the job_runs dual-write (issue #66 step 1): `engine` (unused directly)
    guarantees the schema exists when this file runs in isolation, and — since these tests
    don't mock asyncio.run at all — the job_runs progress/finish calls execute for real
    against the real test DB alongside the mocked update_state calls.
    """
    import app.tasks.snapshots as mod

    portfolio = _make_portfolio(5)
    trading_days = [date(2025, 1, 2), date(2025, 1, 3)]

    mock_eng = _make_engine_mock()

    mock_db_trading = AsyncMock()
    trading_result = MagicMock()
    trading_result.all.return_value = [(d,) for d in trading_days]
    mock_db_trading.execute = AsyncMock(return_value=trading_result)
    session_trading = _make_full_session(mock_db_trading)

    mock_db_portfolios = AsyncMock()
    session_portfolios = _make_full_session(mock_db_portfolios)

    mock_db_compute = AsyncMock()
    mock_db_compute.commit = AsyncMock()
    session_compute = _make_full_session(mock_db_compute)

    call_count = [0]

    def session_factory_side(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return session_trading()
        elif call_count[0] == 2:
            return session_portfolios()
        return session_compute()

    snap_mock = AsyncMock()

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=MagicMock(side_effect=session_factory_side)), \
         patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[portfolio]), \
         patch("app.tasks.snapshots.compute_daily_snapshot", snap_mock), \
         patch.object(mod.recompute_snapshots_range, "update_state"):
        mod.recompute_snapshots_range.run("2025-01-01", "2025-01-07")

    assert snap_mock.call_count == 2
    run = asyncio.run(fetch_latest_job_run("recompute_snapshots_range"))
    assert run.status == "success"
    assert run.trigger == "on_demand"
    assert run.current_step == 2
    assert run.total_steps == 2
    assert run.succeeded_steps == 2
    assert run.finished_at is not None


def test_recompute_snapshots_range_exception_per_portfolio_continues():
    """
    If compute_daily_snapshot raises for a portfolio, the task continues
    silently (exception is caught in _compute_one).
    """
    import app.tasks.snapshots as mod

    portfolio = _make_portfolio(8)
    trading_days = [date(2025, 2, 3)]

    mock_eng = _make_engine_mock()

    mock_db_trading = AsyncMock()
    trading_result = MagicMock()
    trading_result.all.return_value = [(d,) for d in trading_days]
    mock_db_trading.execute = AsyncMock(return_value=trading_result)
    session_trading = _make_full_session(mock_db_trading)

    mock_db_portfolios = AsyncMock()
    session_portfolios = _make_full_session(mock_db_portfolios)

    mock_db_compute = AsyncMock()
    mock_db_compute.commit = AsyncMock()
    session_compute = _make_full_session(mock_db_compute)

    call_count = [0]

    def session_factory_side(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return session_trading()
        elif call_count[0] == 2:
            return session_portfolios()
        return session_compute()

    snap_mock = AsyncMock(side_effect=RuntimeError("compute failed"))

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=MagicMock(side_effect=session_factory_side)), \
         patch("app.tasks.snapshots.get_all_portfolios", new_callable=AsyncMock, return_value=[portfolio]), \
         patch("app.tasks.snapshots.compute_daily_snapshot", snap_mock), \
         patch.object(mod.recompute_snapshots_range, "update_state"):
        # Must not raise
        mod.recompute_snapshots_range.run("2025-02-01", "2025-02-28")

    # Exception was caught — snap was called once (for the one day)
    assert snap_mock.call_count == 1


# ---------------------------------------------------------------------------
# refresh_prices_task  (lines 170-225)
#
# get_active_tickers is imported locally inside the function body as:
#   from app.services.price_service import get_active_tickers
# so we patch 'app.services.price_service.get_active_tickers' directly.
# ---------------------------------------------------------------------------

def test_refresh_prices_task_returns_zero_when_no_tickers():
    """
    refresh_prices_task with no active tickers returns 0.
    """
    import app.tasks.snapshots as mod

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    session_factory = _make_full_session(mock_db)

    mock_yf = MagicMock()
    mock_yf.download.return_value = MagicMock()

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.services.price_service.get_active_tickers", new_callable=AsyncMock, return_value=[]), \
         patch.dict("sys.modules", {"yfinance": mock_yf}):
        result = mod.refresh_prices_task()

    assert result == 0


def test_refresh_prices_task_skips_empty_dataframe():
    """
    refresh_prices_task skips a ticker when yfinance returns empty DataFrame.
    """
    import app.tasks.snapshots as mod
    import pandas as pd

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    session_factory = _make_full_session(mock_db)

    empty_df = pd.DataFrame()
    mock_yf = MagicMock()
    mock_yf.download.return_value = empty_df

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.services.price_service.get_active_tickers",
               new_callable=AsyncMock, return_value=[("EMPTY.PA", "EUR")]), \
         patch.dict("sys.modules", {"yfinance": mock_yf}):
        result = mod.refresh_prices_task()

    assert result == 0


def test_refresh_prices_task_handles_yfinance_exception():
    """
    refresh_prices_task catches per-ticker exceptions and continues.
    """
    import app.tasks.snapshots as mod

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    session_factory = _make_full_session(mock_db)

    mock_yf = MagicMock()
    mock_yf.download.side_effect = RuntimeError("network error")

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.services.price_service.get_active_tickers",
               new_callable=AsyncMock, return_value=[("BAD.PA", "EUR")]), \
         patch.dict("sys.modules", {"yfinance": mock_yf}):
        result = mod.refresh_prices_task()

    assert result == 0


def test_refresh_prices_task_skips_nan_price():
    """
    refresh_prices_task skips a ticker when the price is NaN (line 207).
    We mock close_col.dropna() to return a non-empty series whose last value
    converts to float('nan') — bypassing the series.empty check at line 204.
    """
    import app.tasks.snapshots as mod
    import pandas as pd
    import math

    ticker = "NAN.PA"
    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    session_factory = _make_full_session(mock_db)

    # A series that is non-empty but whose last value is NaN (object dtype)
    idx = pd.DatetimeIndex([pd.Timestamp("2025-05-15")])
    non_empty_nan_series = pd.Series([float("nan")], index=idx, dtype=object)
    # dropna on object dtype with actual None works, but float('nan') survives
    # Better: use a Series where dropna returns non-empty but iloc[-1] is NaN
    # achieved by making dropna() return a series containing float('nan')
    mock_series = MagicMock()
    mock_series.empty = False  # passes the series.empty check
    mock_series.iloc = MagicMock()
    mock_series.iloc.__getitem__ = MagicMock(return_value=float("nan"))

    mock_close = MagicMock()
    mock_close.dropna = MagicMock(return_value=mock_series)

    mock_df = MagicMock()
    mock_df.empty = False
    mock_df.__getitem__ = MagicMock(return_value=mock_close)

    mock_yf = MagicMock()
    mock_yf.download.return_value = mock_df

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.services.price_service.get_active_tickers",
               new_callable=AsyncMock, return_value=[(ticker, "EUR")]), \
         patch.dict("sys.modules", {"yfinance": mock_yf}):
        result = mod.refresh_prices_task()

    assert result == 0


def test_refresh_prices_task_skips_all_nan_series():
    """
    refresh_prices_task skips when dropna() produces an empty series (line 204).
    """
    import app.tasks.snapshots as mod
    import pandas as pd

    ticker = "ALLNAN.PA"
    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    session_factory = _make_full_session(mock_db)

    idx = pd.DatetimeIndex([pd.Timestamp("2025-05-15")])
    series = pd.Series([float("nan")], index=idx, name="Close")
    # hasattr(series, "iloc") is True, so it will call series.dropna() → empty
    df = pd.DataFrame({"Close": series})

    mock_yf = MagicMock()
    mock_yf.download.return_value = df

    # Patch math.isnan to raise so the empty-series branch is hit first
    # Actually we need series.empty → True, so make dropna return empty series
    empty_series = pd.Series([], dtype=float)
    mock_close = MagicMock()
    mock_close.__getitem__ = MagicMock(return_value=empty_series)
    mock_close.dropna = MagicMock(return_value=empty_series)
    # hasattr(close_col, "iloc") True → uses close_col.dropna() directly
    mock_close.iloc = empty_series  # so hasattr is True

    mock_df = MagicMock()
    mock_df.empty = False
    mock_df.__getitem__ = MagicMock(return_value=mock_close)
    mock_yf.download.return_value = mock_df

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.services.price_service.get_active_tickers",
               new_callable=AsyncMock, return_value=[(ticker, "EUR")]), \
         patch.dict("sys.modules", {"yfinance": mock_yf}):
        result = mod.refresh_prices_task()

    assert result == 0


def test_refresh_prices_task_multiindex_column_path():
    """
    refresh_prices_task handles the MultiIndex column case (line 202):
    When close_col has no .iloc attribute, it indexes by ticker name.
    We use a real pandas DataFrame with a MultiIndex column structure.
    """
    import app.tasks.snapshots as mod
    import pandas as pd

    ticker = "MULTI.PA"
    price_val = 55.0
    price_date = pd.Timestamp("2025-05-15")

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    session_tickers = AsyncMock()
    session_tickers.__aenter__.return_value = mock_db
    session_tickers.__aexit__.return_value = False

    session_upsert = AsyncMock()
    session_upsert.__aenter__.return_value = mock_db
    session_upsert.__aexit__.return_value = False

    call_count = [0]

    def session_factory_side():
        call_count[0] += 1
        return session_tickers if call_count[0] == 1 else session_upsert

    session_factory = MagicMock(side_effect=session_factory_side)

    # Build a real pandas MultiIndex DataFrame as yfinance returns for multiple tickers
    idx = pd.DatetimeIndex([price_date])
    data = {("Close", ticker): [price_val], ("Open", ticker): [54.0]}
    df = pd.DataFrame(data, index=idx)
    # df["Close"] returns a DataFrame (not a Series), so hasattr(close_col, "iloc") is True
    # We need to test the `else` branch: hasattr is False.
    # Simulate by returning a DataFrame column that doesn't have .iloc.
    # Actually in pandas, DataFrame["Close"] always has .iloc.
    # The else branch fires when yfinance returns a DataFrame for multi-ticker
    # where close_col is a DataFrame itself and ticker is a column key.
    # Simplest approach: mock the df["Close"] to return an object without .iloc.

    class NoIlocMapping:
        """Behaves like a mapping (for `ticker in close_col`) but has no .iloc."""
        def __contains__(self, key):
            return key == ticker

        def __getitem__(self, key):
            return pd.Series([price_val], index=idx)

        def dropna(self):
            return pd.Series([price_val], index=idx)

    mock_df = MagicMock()
    mock_df.empty = False
    mock_df.__getitem__ = MagicMock(return_value=NoIlocMapping())

    mock_yf = MagicMock()
    mock_yf.download.return_value = mock_df

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.services.price_service.get_active_tickers",
               new_callable=AsyncMock, return_value=[(ticker, "EUR")]), \
         patch.dict("sys.modules", {"yfinance": mock_yf}):
        result = mod.refresh_prices_task()

    assert result == 1


def test_refresh_prices_task_writes_price_to_db():
    """
    When yfinance returns a valid price, it is upserted to DB and count increments.
    """
    import app.tasks.snapshots as mod
    import pandas as pd
    import numpy as np

    ticker = "AAPL"
    price_val = 180.0
    price_date = date(2025, 5, 15)

    mock_eng = _make_engine_mock()
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    # We need two sessions: one for get_active_tickers, one per ticker upsert
    session_tickers = AsyncMock()
    session_tickers.__aenter__.return_value = mock_db
    session_tickers.__aexit__.return_value = False

    session_upsert = AsyncMock()
    session_upsert.__aenter__.return_value = mock_db
    session_upsert.__aexit__.return_value = False

    call_count = [0]

    def session_factory_side():
        call_count[0] += 1
        return session_tickers if call_count[0] == 1 else session_upsert

    session_factory = MagicMock(side_effect=session_factory_side)

    # Build a minimal DataFrame that mimics yfinance output
    # yfinance can return columns as MultiIndex or simple Index
    idx = pd.DatetimeIndex([pd.Timestamp(price_date)])
    series = pd.Series([price_val], index=idx, name="Close")
    df = pd.DataFrame({"Close": series})

    mock_yf = MagicMock()
    mock_yf.download.return_value = df

    with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory), \
         patch("app.services.price_service.get_active_tickers",
               new_callable=AsyncMock, return_value=[(ticker, "USD")]), \
         patch.dict("sys.modules", {"yfinance": mock_yf}):
        result = mod.refresh_prices_task()

    # result should be 1 (one ticker updated)
    assert result == 1
