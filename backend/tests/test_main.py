"""
Tests for app/main.py — covers the lifespan startup/shutdown event.

The lifespan function has five independent try/except blocks (one per startup-fired
Celery task: snapshots, prices, etf_holdings, macro_indicators, country_performance).
Each is swallowed on exception to never block startup, and independently of the others
(one failing must not prevent the others from running).

All five are mocked by the autouse fixture below — without this, each unmocked block's
real `.delay()` call would try to reach the (absent, in tests) Celery broker/result
backend and take ~19s to time out per call, making this file's 6 tests take minutes.
"""
import pytest

from app.main import app, lifespan


class _FakeTask:
    def __init__(self, raise_exc=None, counter=None):
        self._raise = raise_exc
        self._counter = counter

    def delay(self, *args, **kwargs):
        if self._counter is not None:
            self._counter["n"] += 1
        if self._raise:
            raise self._raise("broker unavailable")


@pytest.fixture(autouse=True)
def _patch_startup_tasks():
    """Patch all five lifespan tasks with safe no-op fakes for every test in this file,
    so `async with lifespan(app)` never fires a real Celery `.delay()`. Individual tests
    override one or more of these on top of this baseline."""
    import app.tasks.snapshots as snap_mod
    import app.tasks.prices as prices_mod
    import app.tasks.etf_holdings as etf_mod
    import app.tasks.macro_indicators as macro_mod
    import app.tasks.country_performance as country_mod

    originals = {
        "snap": snap_mod.fill_missing_snapshots,
        "prices": prices_mod.refresh_prices_live,
        "etf": etf_mod.refresh_etf_holdings,
        "macro": macro_mod.refresh_macro_indicators,
        "country": country_mod.refresh_country_performance,
    }
    snap_mod.fill_missing_snapshots = _FakeTask()
    prices_mod.refresh_prices_live = _FakeTask()
    etf_mod.refresh_etf_holdings = _FakeTask()
    macro_mod.refresh_macro_indicators = _FakeTask()
    country_mod.refresh_country_performance = _FakeTask()
    yield
    snap_mod.fill_missing_snapshots = originals["snap"]
    prices_mod.refresh_prices_live = originals["prices"]
    etf_mod.refresh_etf_holdings = originals["etf"]
    macro_mod.refresh_macro_indicators = originals["macro"]
    country_mod.refresh_country_performance = originals["country"]


@pytest.mark.asyncio
async def test_lifespan_startup_snap_raises():
    """Exception in fill_missing_snapshots.delay() → swallowed, startup completes."""
    import app.tasks.snapshots as snap_mod

    snap_mod.fill_missing_snapshots = _FakeTask(raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_snap_succeeds():
    """Happy path: fill_missing_snapshots.delay() called once."""
    import app.tasks.snapshots as snap_mod

    counter = {"n": 0}
    snap_mod.fill_missing_snapshots = _FakeTask(counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_price_refresh_raises():
    """Exception in refresh_prices_live.delay() → swallowed, startup completes."""
    import app.tasks.prices as prices_mod

    prices_mod.refresh_prices_live = _FakeTask(raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_price_refresh_succeeds():
    """Happy path: refresh_prices_live.delay() called once."""
    import app.tasks.prices as prices_mod

    counter = {"n": 0}
    prices_mod.refresh_prices_live = _FakeTask(counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_etf_holdings_raises():
    """Exception in refresh_etf_holdings.delay() → swallowed, startup completes."""
    import app.tasks.etf_holdings as etf_mod

    etf_mod.refresh_etf_holdings = _FakeTask(raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_etf_holdings_succeeds():
    """Happy path: refresh_etf_holdings.delay() called once."""
    import app.tasks.etf_holdings as etf_mod

    counter = {"n": 0}
    etf_mod.refresh_etf_holdings = _FakeTask(counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_macro_indicators_raises():
    """Exception in refresh_macro_indicators.delay() → swallowed, startup completes."""
    import app.tasks.macro_indicators as macro_mod

    macro_mod.refresh_macro_indicators = _FakeTask(raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_macro_indicators_succeeds():
    """Happy path: refresh_macro_indicators.delay() called once."""
    import app.tasks.macro_indicators as macro_mod

    counter = {"n": 0}
    macro_mod.refresh_macro_indicators = _FakeTask(counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_country_performance_raises():
    """Exception in refresh_country_performance.delay() → swallowed, startup completes."""
    import app.tasks.country_performance as country_mod

    country_mod.refresh_country_performance = _FakeTask(raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_country_performance_succeeds():
    """Happy path: refresh_country_performance.delay() called once."""
    import app.tasks.country_performance as country_mod

    counter = {"n": 0}
    country_mod.refresh_country_performance = _FakeTask(counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_price_refresh_runs_even_if_snapshot_fails():
    """A failure in fill_missing_snapshots must not prevent refresh_prices_live
    from also being triggered — the two try/except blocks are independent."""
    import app.tasks.snapshots as snap_mod
    import app.tasks.prices as prices_mod

    counter = {"n": 0}
    snap_mod.fill_missing_snapshots = _FakeTask(raise_exc=ConnectionError)
    prices_mod.refresh_prices_live = _FakeTask(counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_snapshot_runs_even_if_price_refresh_fails():
    """A failure in refresh_prices_live must not prevent fill_missing_snapshots
    from also being triggered — the two try/except blocks are independent."""
    import app.tasks.snapshots as snap_mod
    import app.tasks.prices as prices_mod

    counter = {"n": 0}
    snap_mod.fill_missing_snapshots = _FakeTask(counter=counter)
    prices_mod.refresh_prices_live = _FakeTask(raise_exc=ConnectionError)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_country_performance_runs_even_if_macro_indicators_fails():
    """A failure in refresh_macro_indicators must not prevent
    refresh_country_performance from also being triggered."""
    import app.tasks.macro_indicators as macro_mod
    import app.tasks.country_performance as country_mod

    counter = {"n": 0}
    macro_mod.refresh_macro_indicators = _FakeTask(raise_exc=ConnectionError)
    country_mod.refresh_country_performance = _FakeTask(counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1
