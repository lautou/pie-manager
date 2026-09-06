# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for app/main.py — covers the lifespan startup/shutdown event.

The lifespan function has several independent try/except blocks, all PgQueuer-based (issue #66
step 4: fill_missing_snapshots moved off Celery's .delay() to the same enqueue pattern as
refresh_prices_live/refresh_etf_holdings/refresh_macro_indicators/
refresh_country_performance/refresh_sector_performance/refresh_equity_premium), each
`await get_pgq_queries().enqueue(name, payload=b"startup")`. Each is swallowed on exception to
never block startup, independently of the others (one failing must not prevent the others from
running).

`init_pgq_pool`/`close_pgq_pool`/`get_pgq_queries` are mocked by the autouse fixture below —
without this, lifespan would try to open a real asyncpg pool against the (absent, in tests)
Postgres.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.main import app, lifespan


class _FakeQueries:
    """Stand-in for pgqueuer.Queries — enqueue() can be made to count calls or raise per
    entrypoint name."""

    def __init__(self):
        self._counters: dict[str, dict] = {}
        self._raises: dict[str, type] = {}

    def configure(self, entrypoint: str, raise_exc=None, counter=None):
        if counter is not None:
            self._counters[entrypoint] = counter
        if raise_exc is not None:
            self._raises[entrypoint] = raise_exc

    async def enqueue(self, entrypoint, payload=None, priority=0):
        if entrypoint in self._counters:
            self._counters[entrypoint]["n"] += 1
        if entrypoint in self._raises:
            raise self._raises[entrypoint]("job queue unavailable")
        return [1]


@pytest.fixture
def fake_queries():
    return _FakeQueries()


@pytest.fixture(autouse=True)
def _patch_startup_tasks(fake_queries):
    """Patch PgQueuer's pool init/close + get_pgq_queries with a fake Queries, for every test
    in this file — so `async with lifespan(app)` never opens a real asyncpg connection.
    Individual tests configure specific entrypoints on top of this baseline."""
    with patch("app.core.pgq.init_pgq_pool", new_callable=AsyncMock), \
         patch("app.core.pgq.close_pgq_pool", new_callable=AsyncMock), \
         patch("app.core.pgq.get_pgq_queries", return_value=fake_queries):
        yield


@pytest.mark.asyncio
async def test_lifespan_startup_snap_raises(fake_queries):
    """Exception enqueuing fill_missing_snapshots → swallowed, startup completes."""
    fake_queries.configure("fill_missing_snapshots", raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_snap_succeeds(fake_queries):
    """Happy path: fill_missing_snapshots enqueued once with a startup payload."""
    counter = {"n": 0}
    fake_queries.configure("fill_missing_snapshots", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_price_refresh_raises(fake_queries):
    """Exception enqueuing refresh_prices_live → swallowed, startup completes."""
    fake_queries.configure("refresh_prices_live", raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_price_refresh_succeeds(fake_queries):
    """Happy path: refresh_prices_live enqueued once with a startup payload."""
    counter = {"n": 0}
    fake_queries.configure("refresh_prices_live", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_etf_holdings_raises(fake_queries):
    """Exception enqueuing refresh_etf_holdings → swallowed, startup completes."""
    fake_queries.configure("refresh_etf_holdings", raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_etf_holdings_succeeds(fake_queries):
    """Happy path: refresh_etf_holdings enqueued once."""
    counter = {"n": 0}
    fake_queries.configure("refresh_etf_holdings", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_macro_indicators_raises(fake_queries):
    """Exception enqueuing refresh_macro_indicators → swallowed, startup completes."""
    fake_queries.configure("refresh_macro_indicators", raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_macro_indicators_succeeds(fake_queries):
    """Happy path: refresh_macro_indicators enqueued once."""
    counter = {"n": 0}
    fake_queries.configure("refresh_macro_indicators", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_country_performance_raises(fake_queries):
    """Exception enqueuing refresh_country_performance → swallowed, startup completes."""
    fake_queries.configure("refresh_country_performance", raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_country_performance_succeeds(fake_queries):
    """Happy path: refresh_country_performance enqueued once."""
    counter = {"n": 0}
    fake_queries.configure("refresh_country_performance", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_price_refresh_runs_even_if_snapshot_fails(fake_queries):
    """A failure enqueuing fill_missing_snapshots must not prevent refresh_prices_live
    from also being triggered — the two try/except blocks are independent."""
    counter = {"n": 0}
    fake_queries.configure("fill_missing_snapshots", raise_exc=ConnectionError)
    fake_queries.configure("refresh_prices_live", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_snapshot_runs_even_if_price_refresh_fails(fake_queries):
    """A failure enqueuing refresh_prices_live must not prevent fill_missing_snapshots
    from also being triggered — the two try/except blocks are independent."""
    counter = {"n": 0}
    fake_queries.configure("fill_missing_snapshots", counter=counter)
    fake_queries.configure("refresh_prices_live", raise_exc=ConnectionError)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_country_performance_runs_even_if_macro_indicators_fails(fake_queries):
    """A failure enqueuing refresh_macro_indicators must not prevent
    refresh_country_performance from also being triggered."""
    counter = {"n": 0}
    fake_queries.configure("refresh_macro_indicators", raise_exc=ConnectionError)
    fake_queries.configure("refresh_country_performance", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_sector_performance_raises(fake_queries):
    """Exception enqueuing refresh_sector_performance → swallowed, startup completes."""
    fake_queries.configure("refresh_sector_performance", raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_sector_performance_succeeds(fake_queries):
    """Happy path: refresh_sector_performance enqueued once."""
    counter = {"n": 0}
    fake_queries.configure("refresh_sector_performance", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_sector_performance_runs_even_if_country_performance_fails(fake_queries):
    """A failure enqueuing refresh_country_performance must not prevent
    refresh_sector_performance from also being triggered."""
    counter = {"n": 0}
    fake_queries.configure("refresh_country_performance", raise_exc=ConnectionError)
    fake_queries.configure("refresh_sector_performance", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_equity_premium_raises(fake_queries):
    """Exception enqueuing refresh_equity_premium → swallowed, startup completes."""
    fake_queries.configure("refresh_equity_premium", raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_equity_premium_succeeds(fake_queries):
    """Happy path: refresh_equity_premium enqueued once."""
    counter = {"n": 0}
    fake_queries.configure("refresh_equity_premium", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_equity_premium_runs_even_if_sector_performance_fails(fake_queries):
    """A failure enqueuing refresh_sector_performance must not prevent
    refresh_equity_premium from also being triggered."""
    counter = {"n": 0}
    fake_queries.configure("refresh_sector_performance", raise_exc=ConnectionError)
    fake_queries.configure("refresh_equity_premium", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_bond_performance_raises(fake_queries):
    """Exception enqueuing refresh_bond_performance → swallowed, startup completes."""
    fake_queries.configure("refresh_bond_performance", raise_exc=ConnectionError)
    async with lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_startup_bond_performance_succeeds(fake_queries):
    """Happy path: refresh_bond_performance enqueued once."""
    counter = {"n": 0}
    fake_queries.configure("refresh_bond_performance", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_bond_performance_runs_even_if_equity_premium_fails(fake_queries):
    """A failure enqueuing refresh_equity_premium must not prevent
    refresh_bond_performance from also being triggered."""
    counter = {"n": 0}
    fake_queries.configure("refresh_equity_premium", raise_exc=ConnectionError)
    fake_queries.configure("refresh_bond_performance", counter=counter)
    async with lifespan(app):
        pass

    assert counter["n"] == 1


@pytest.mark.asyncio
async def test_lifespan_calls_init_and_close_pgq_pool():
    """init_pgq_pool() runs once at startup, close_pgq_pool() once at shutdown."""
    with patch("app.core.pgq.init_pgq_pool", new_callable=AsyncMock) as mock_init, \
         patch("app.core.pgq.close_pgq_pool", new_callable=AsyncMock) as mock_close, \
         patch("app.core.pgq.get_pgq_queries", return_value=_FakeQueries()):
        async with lifespan(app):
            mock_init.assert_awaited_once()
            mock_close.assert_not_awaited()
        mock_close.assert_awaited_once()
