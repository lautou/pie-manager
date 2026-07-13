"""
Tests for app/main.py — covers the lifespan startup/shutdown event.

The lifespan function has two independent try/except blocks:
1. fill_missing_snapshots.delay() — snapshot backfill
2. refresh_prices_live.delay() — immediate live price sync

Each is swallowed on exception to never block startup, and independently
of the other (one failing must not prevent the other from running).
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
    """Patch both lifespan tasks with safe no-op fakes for every test in this
    file, so `async with lifespan(app)` never fires a real Celery `.delay()`
    (which would try to reach a broker and hang). Individual tests override
    `app.tasks.snapshots.fill_missing_snapshots` and/or
    `app.tasks.prices.refresh_prices_live` on top of this baseline."""
    import app.tasks.snapshots as snap_mod
    import app.tasks.prices as prices_mod

    orig_snap = snap_mod.fill_missing_snapshots
    orig_refresh = prices_mod.refresh_prices_live
    snap_mod.fill_missing_snapshots = _FakeTask()
    prices_mod.refresh_prices_live = _FakeTask()
    yield
    snap_mod.fill_missing_snapshots = orig_snap
    prices_mod.refresh_prices_live = orig_refresh


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
