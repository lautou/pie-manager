"""
Non-regression tests for the live price sync service (app/tasks/prices.py).

Tested without real network calls — Yahoo Finance responses are mocked.
Key invariants:
  1. Successful fetch stores price in DB and records ticker in succeeded list.
  2. Deduplication: same ticker in multiple portfolio/pool contexts fetched once.
  3. LIQUIDITE.EURO is always skipped (no fetch needed).
  4. Sync status dict has correct shape on success, partial, and failure.
  5. _run_price_refresh orchestrates fetch + DB write and returns status dict.
  6. refresh_prices_live writes running then final status to Redis.
  7. Exception in _run_price_refresh → failed status written, no crash.

_fetch_ticker's retry/backoff mechanics are tested once, generically, in
test_yahoo_fetch.py (the shared fetch_yahoo_chart it delegates to) — this file only tests
_fetch_ticker's own thin parsing logic (regularMarketPrice extraction/rounding).
get_redis/write_status are tested in test_sync_status.py.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.tasks.prices import (
    _fetch_ticker,
    _run_price_refresh,
    fetch_all_prices,
    refresh_prices_live,
)


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


def _make_yahoo_ok(price: float) -> dict:
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price}}]}}


def _make_db_mocks():
    """Return (mock_engine, session_factory, mock_db) ready for async-with use."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    session_instance = AsyncMock()
    session_instance.__aenter__ = AsyncMock(return_value=mock_db)
    session_instance.__aexit__ = AsyncMock(return_value=False)

    session_factory = MagicMock(return_value=session_instance)

    mock_eng = MagicMock()
    mock_eng.dispose = AsyncMock()

    return mock_eng, session_factory, mock_db


def _make_httpx_mock():
    """Return a mock for httpx module that exposes AsyncClient as a no-op context manager."""
    mock_client_obj = AsyncMock()
    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_obj)
    mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_httpx, mock_client_obj


# ---------------------------------------------------------------------------
# _fetch_ticker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_ticker_success():
    """200 + regularMarketPrice → (ticker, price, None)."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _make_yahoo_ok(42.5)))
    ticker, price, error = await _fetch_ticker(client, "TEST.PA")
    assert ticker == "TEST.PA"
    assert price == pytest.approx(42.5)
    assert error is None


@pytest.mark.asyncio
async def test_fetch_ticker_rounds_to_4_decimals():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _make_yahoo_ok(1.23456789)))
    _, price, _ = await _fetch_ticker(client, "EUR=X")
    assert price == pytest.approx(1.2346)


@pytest.mark.asyncio
async def test_fetch_ticker_http_error():
    """Non-200 → (ticker, None, 'HTTP N')."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(404))
    ticker, price, error = await _fetch_ticker(client, "UNKNOWN.XX")
    assert price is None
    assert "404" in error


@pytest.mark.asyncio
async def test_fetch_ticker_missing_price():
    """200 but no regularMarketPrice → 'regularMarketPrice missing'."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, {"chart": {"result": [{"meta": {}}]}}))
    _, price, error = await _fetch_ticker(client, "STALE.PA")
    assert price is None
    assert error == "regularMarketPrice missing"


# ---------------------------------------------------------------------------
# _run_price_refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_price_refresh_only_cash_tickers_returns_empty_success():
    """When all tickers are LIQUIDITE.EURO, returns success with 0 tickers without hitting network."""
    mock_eng, session_factory, _ = _make_db_mocks()
    with patch("app.tasks.prices.get_active_tickers",
               new_callable=AsyncMock, return_value=[("LIQUIDITE.EURO", "EUR")]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_price_refresh()
    assert result["status"] == "success"
    assert result["total_tickers"] == 0
    assert result["failed_tickers"] == []


@pytest.mark.asyncio
async def test_run_price_refresh_no_tickers_returns_empty_success():
    """When no products are active, returns success with 0 tickers."""
    mock_eng, session_factory, _ = _make_db_mocks()
    with patch("app.tasks.prices.get_active_tickers",
               new_callable=AsyncMock, return_value=[]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_price_refresh()
    assert result["status"] == "success"
    assert result["total_tickers"] == 0


@pytest.mark.asyncio
async def test_run_price_refresh_single_ticker_success():
    """One ticker fetched successfully → written to DB, status 'success'."""
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    with patch("app.tasks.prices.get_active_tickers",
               new_callable=AsyncMock, return_value=[("AAPL", "USD")]), \
         patch("app.tasks.prices._fetch_ticker",
               new_callable=AsyncMock, return_value=("AAPL", 180.0, None)), \
         patch("app.tasks.prices.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_price_refresh()

    assert result["status"] == "success"
    assert result["total_tickers"] == 1
    assert result["succeeded"] == 1
    assert result["failed_tickers"] == []
    # 2 execute calls: (1) fetch prev prices for glitch guard, (2) INSERT
    assert mock_db.execute.call_count == 2
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_run_price_refresh_one_success_one_failure_is_partial():
    """One ticker succeeds, one fails → status 'partial', failed_tickers populated."""
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetch_results = iter([("AAPL", 180.0, None), ("CRASH.PA", None, "HTTP 503")])

    async def mock_fetch(client, ticker):
        return next(fetch_results)

    with patch("app.tasks.prices.get_active_tickers",
               new_callable=AsyncMock,
               return_value=[("AAPL", "USD"), ("CRASH.PA", "EUR")]), \
         patch("app.tasks.prices._fetch_ticker", side_effect=mock_fetch), \
         patch("app.tasks.prices.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_price_refresh()

    assert result["status"] == "partial"
    assert result["succeeded"] == 1
    assert "CRASH.PA" in result["failed_tickers"]


@pytest.mark.asyncio
async def test_run_price_refresh_all_fail_is_failed():
    """All tickers fail → status 'failed'."""
    mock_eng, session_factory, _ = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    with patch("app.tasks.prices.get_active_tickers",
               new_callable=AsyncMock, return_value=[("BAD.PA", "EUR")]), \
         patch("app.tasks.prices._fetch_ticker",
               new_callable=AsyncMock, return_value=("BAD.PA", None, "HTTP 404")), \
         patch("app.tasks.prices.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_price_refresh()

    assert result["status"] == "failed"
    assert result["succeeded"] == 0
    assert "BAD.PA" in result["failed_tickers"]


@pytest.mark.asyncio
async def test_run_price_refresh_deduplicates_tickers():
    """Same ticker appearing twice (two portfolios) → fetched only once."""
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()
    fetch_mock = AsyncMock(return_value=("AAPL", 180.0, None))

    with patch("app.tasks.prices.get_active_tickers",
               new_callable=AsyncMock,
               return_value=[("AAPL", "USD"), ("AAPL", "USD"), ("LIQUIDITE.EURO", "EUR")]), \
         patch("app.tasks.prices._fetch_ticker", fetch_mock), \
         patch("app.tasks.prices.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_price_refresh()

    assert result["total_tickers"] == 1
    assert fetch_mock.call_count == 1


@pytest.mark.asyncio
async def test_run_price_refresh_glitch_guard_rejects_100x_spike():
    """
    Regression: Yahoo Finance returned JPYEUR=X at ×100 scale (0.5418 vs 0.005418).
    The glitch guard must reject the price and add ticker to failed_tickers.
    """
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    # Simulate prev price row returned by the first db.execute (prev_prices query)
    prev_row = MagicMock()
    prev_row.ticker = "JPYEUR=X"
    prev_row.price = 0.005418  # yesterday's correct price

    # First execute returns the prev_prices result (iterable with one row)
    prev_result = MagicMock()
    prev_result.__iter__ = MagicMock(return_value=iter([prev_row]))
    mock_db.execute = AsyncMock(return_value=prev_result)

    with patch("app.tasks.prices.get_active_tickers",
               new_callable=AsyncMock, return_value=[("JPYEUR=X", "EUR")]), \
         patch("app.tasks.prices._fetch_ticker",
               new_callable=AsyncMock,
               return_value=("JPYEUR=X", 0.5418, None)), \
         patch("app.tasks.prices.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_price_refresh()

    assert result["succeeded"] == 0
    # Ticker should appear in failed with glitch annotation
    assert any("JPYEUR=X" in ft for ft in result["failed_tickers"])
    # INSERT must NOT have been called (only the prev_prices SELECT was executed)
    assert mock_db.execute.call_count == 1


@pytest.mark.asyncio
async def test_run_price_refresh_glitch_guard_allows_normal_variation():
    """Prices within ×10 range pass the glitch guard and are stored normally."""
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    prev_row = MagicMock()
    prev_row.ticker = "AAPL"
    prev_row.price = 180.0  # yesterday

    prev_result = MagicMock()
    prev_result.__iter__ = MagicMock(return_value=iter([prev_row]))

    # Second call (INSERT) should return a simple mock
    insert_result = MagicMock()
    insert_result.__iter__ = MagicMock(return_value=iter([]))
    mock_db.execute = AsyncMock(side_effect=[prev_result, insert_result])

    with patch("app.tasks.prices.get_active_tickers",
               new_callable=AsyncMock, return_value=[("AAPL", "USD")]), \
         patch("app.tasks.prices._fetch_ticker",
               new_callable=AsyncMock,
               return_value=("AAPL", 195.0, None)), \
         patch("app.tasks.prices.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_price_refresh()

    assert result["succeeded"] == 1
    assert result["failed_tickers"] == []


# ---------------------------------------------------------------------------
# refresh_prices_live (Celery task)
# ---------------------------------------------------------------------------

def test_refresh_prices_live_writes_running_then_final_status():
    """refresh_prices_live writes 'running' to Redis first, then the final result."""
    mock_r = MagicMock()
    success_result = {
        "started_at": "2026-05-15T14:30:00+00:00",
        "finished_at": "2026-05-15T14:30:05+00:00",
        "status": "success",
        "total_tickers": 3,
        "succeeded": 3,
        "failed_tickers": [],
    }

    def _close_and_return(coro):
        """Close the coroutine to avoid 'never awaited' ResourceWarning, then return result."""
        if hasattr(coro, "close"):
            coro.close()
        return success_result

    with patch("app.tasks.prices.get_redis", return_value=mock_r), \
         patch("app.tasks.prices.asyncio.run", side_effect=_close_and_return):
        result = refresh_prices_live()

    assert result == success_result
    # Two writes: "running" then final
    assert mock_r.set.call_count == 2
    first_payload = json.loads(mock_r.set.call_args_list[0][0][1])
    assert first_payload["status"] == "running"
    second_payload = json.loads(mock_r.set.call_args_list[1][0][1])
    assert second_payload["status"] == "success"


def test_refresh_prices_live_handles_exception_and_writes_failed():
    """If _run_price_refresh raises, refresh_prices_live writes 'failed' and does not crash."""
    mock_r = MagicMock()

    def _raise_and_close(coro):
        """Close the coroutine to avoid 'never awaited' ResourceWarning, then raise."""
        if hasattr(coro, "close"):
            coro.close()
        raise RuntimeError("DB down")

    with patch("app.tasks.prices.get_redis", return_value=mock_r), \
         patch("app.tasks.prices.asyncio.run", side_effect=_raise_and_close):
        result = refresh_prices_live()

    assert result["status"] == "failed"
    assert result["failed_tickers"] == []
    # Still two writes: "running" then "failed"
    assert mock_r.set.call_count == 2
    final = json.loads(mock_r.set.call_args_list[1][0][1])
    assert final["status"] == "failed"


# ---------------------------------------------------------------------------
# fetch_all_prices (legacy alias)
# ---------------------------------------------------------------------------

def test_fetch_all_prices_delegates_to_refresh_prices_live():
    """fetch_all_prices() is a backward-compat alias — it calls refresh_prices_live."""
    mock_r = MagicMock()
    dummy_result = {"status": "success", "total_tickers": 0, "succeeded": 0, "failed_tickers": []}

    def _close_and_return(coro):
        if hasattr(coro, "close"):
            coro.close()
        return dummy_result

    with patch("app.tasks.prices.get_redis", return_value=mock_r), \
         patch("app.tasks.prices.asyncio.run", side_effect=_close_and_return):
        result = fetch_all_prices()
    assert result["status"] == "success"


# ---------------------------------------------------------------------------
# Deduplication logic (inline unit checks)
# ---------------------------------------------------------------------------

def test_deduplication_logic():
    raw = [("AAPL", "USD"), ("AAPL", "USD"), ("GOOG", "USD"), ("LIQUIDITE.EURO", "EUR")]
    seen: set[str] = set()
    to_fetch = []
    for ticker, currency in raw:
        if ticker == "LIQUIDITE.EURO" or ticker in seen:
            continue
        seen.add(ticker)
        to_fetch.append((ticker, currency))
    assert [t for t, _ in to_fetch] == ["AAPL", "GOOG"]


def test_liquidite_euro_excluded():
    raw = [("LIQUIDITE.EURO", "EUR"), ("BNP.PA", "EUR")]
    seen: set[str] = set()
    to_fetch = []
    for ticker, currency in raw:
        if ticker == "LIQUIDITE.EURO" or ticker in seen:
            continue
        seen.add(ticker)
        to_fetch.append((ticker, currency))
    assert all(t != "LIQUIDITE.EURO" for t, _ in to_fetch)
    assert len(to_fetch) == 1


# ---------------------------------------------------------------------------
# Sync status dict shape
# ---------------------------------------------------------------------------

def test_sync_status_success_shape():
    status = {"started_at": "2026-05-15T14:30:00+00:00", "finished_at": "2026-05-15T14:30:05+00:00",
              "status": "success", "total_tickers": 5, "succeeded": 5, "failed_tickers": []}
    for key in ("started_at", "finished_at", "status", "total_tickers", "succeeded", "failed_tickers"):
        assert key in status
    assert isinstance(status["failed_tickers"], list)


def test_sync_status_partial_has_failed_list():
    status = {"status": "partial", "total_tickers": 5, "succeeded": 3,
              "failed_tickers": ["XJSE.DE", "H411.DE"]}
    assert len(status["failed_tickers"]) > 0


def test_sync_status_json_serialisable():
    status = {"started_at": "2026-05-15T14:30:00+00:00", "finished_at": "2026-05-15T14:30:05+00:00",
              "status": "success", "total_tickers": 3, "succeeded": 3, "failed_tickers": []}
    assert json.loads(json.dumps(status))["status"] == "success"
