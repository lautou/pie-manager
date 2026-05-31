"""
Tests for app/main.py — covers the lifespan startup/shutdown event.

The lifespan function has one try/except block:
1. fill_missing_snapshots.delay() — snapshot backfill

It is swallowed on exception to never block startup.
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


@pytest.mark.asyncio
async def test_lifespan_startup_snap_raises():
    """Exception in fill_missing_snapshots.delay() → swallowed, startup completes."""
    import app.tasks.snapshots as snap_mod

    orig_snap = snap_mod.fill_missing_snapshots
    snap_mod.fill_missing_snapshots = _FakeTask(raise_exc=ConnectionError)
    try:
        async with lifespan(app):
            pass
    finally:
        snap_mod.fill_missing_snapshots = orig_snap


@pytest.mark.asyncio
async def test_lifespan_startup_snap_succeeds():
    """Happy path: fill_missing_snapshots.delay() called once."""
    import app.tasks.snapshots as snap_mod

    counter = {"n": 0}
    orig_snap = snap_mod.fill_missing_snapshots
    snap_mod.fill_missing_snapshots = _FakeTask(counter=counter)
    try:
        async with lifespan(app):
            pass
    finally:
        snap_mod.fill_missing_snapshots = orig_snap

    assert counter["n"] == 1
