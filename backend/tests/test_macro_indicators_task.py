"""
Non-regression tests for the macro indicators refresh task (app/tasks/macro_indicators.py).

Tested without real network calls — Yahoo Finance responses are mocked, mirroring the
pattern in test_price_sync.py / test_etf_holdings_task.py. Key invariants:
  1. _fetch_series_history uses explicit period1/period2 (not range=max) and drops None closes.
  2. 429 responses are retried up to MAX_RETRIES before failing.
  3. _run_macro_indicators_refresh fetches all 4 configured tickers and upserts each series.
  4. refresh_macro_indicators (Celery task) writes running then final status to Redis.
"""

import json
import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.macro_indicator import MacroRegion
from app.tasks.macro_indicators import (
    _fetch_series_history,
    _get_redis,
    _run_macro_indicators_refresh,
    refresh_macro_indicators,
    SYNC_STATUS_KEY,
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


def _chart_payload(timestamps: list[int], closes: list[float | None]) -> dict:
    return {"chart": {"result": [{"timestamp": timestamps, "indicators": {"quote": [{"close": closes}]}}]}}


def _make_db_mocks():
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
    mock_client_obj = AsyncMock()
    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_obj)
    mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_httpx, mock_client_obj


_SETTINGS = {"oil": "CL=F", "gold": "GC=F", "ma_years": 7.0}

_REGIONS = [
    MacroRegion(code="us", label="États-Unis", equity_ticker="^SPXEW", bond_ticker="GOVT"),
    MacroRegion(code="fr", label="France", equity_ticker="^FCHI", bond_ticker="MTE.PA"),
    MacroRegion(code="world", label="Monde", equity_ticker="MWEQ.L", bond_ticker="BNDW"),
]


# ---------------------------------------------------------------------------
# _get_redis
# ---------------------------------------------------------------------------

def test_get_redis_creates_client_from_broker_url():
    mock_client = MagicMock()
    with patch("redis.Redis.from_url", return_value=mock_client) as mock_from_url, \
         patch("app.core.config.settings") as mock_settings:
        mock_settings.celery_broker_url = "redis://localhost:6379/0"
        result = _get_redis()
    mock_from_url.assert_called_once_with("redis://localhost:6379/0", decode_responses=True)
    assert result is mock_client


# ---------------------------------------------------------------------------
# _fetch_series_history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_series_history_success_drops_none_closes():
    # 2020-01-01T00:00:00Z and 2020-01-02T00:00:00Z, with a None close in between skipped
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _chart_payload(
        [1577836800, 1577923200, 1578009600], [100.0, None, 102.0]
    )))
    ticker, points, error = await _fetch_series_history(client, "^SPXEW", 0, 10**10)
    assert ticker == "^SPXEW"
    assert error is None
    assert points == [(date(2020, 1, 1), 100.0), (date(2020, 1, 3), 102.0)]


@pytest.mark.asyncio
async def test_fetch_series_history_429_exhausts_retries():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(429))
    with patch("app.tasks.macro_indicators.asyncio.sleep", new_callable=AsyncMock):
        _, points, error = await _fetch_series_history(client, "CL=F", 0, 1)
    assert points is None
    assert "429" in error


@pytest.mark.asyncio
async def test_fetch_series_history_http_error():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(500))
    _, points, error = await _fetch_series_history(client, "CL=F", 0, 1)
    assert points is None
    assert "500" in error


@pytest.mark.asyncio
async def test_fetch_series_history_no_chart_data():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, {"chart": {"result": []}}))
    _, points, error = await _fetch_series_history(client, "BAD=F", 0, 1)
    assert points is None
    assert error == "no chart data"


@pytest.mark.asyncio
async def test_fetch_series_history_no_usable_points():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _chart_payload([1577836800], [None])))
    _, points, error = await _fetch_series_history(client, "GC=F", 0, 1)
    assert points is None
    assert error == "no usable data points"


@pytest.mark.asyncio
async def test_fetch_series_history_exception():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=ConnectionError("timeout"))
    _, points, error = await _fetch_series_history(client, "^TNX", 0, 1)
    assert points is None
    assert error is not None


@pytest.mark.asyncio
async def test_fetch_series_history_max_retries_zero_falls_through():
    """With MAX_RETRIES=0 the for-loop body never executes, hitting the safety
    'return ticker, None, "max retries exceeded"' after the loop (mirrors
    test_price_sync.py's equivalent test for _fetch_ticker)."""
    client = AsyncMock()
    with patch("app.tasks.macro_indicators.MAX_RETRIES", 0):
        _, points, error = await _fetch_series_history(client, "ZERO=F", 0, 1)
    assert points is None
    assert error == "max retries exceeded"


# ---------------------------------------------------------------------------
# _run_macro_indicators_refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_refresh_all_succeed():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetch_results = [
        ("CL=F", [(date(2020, 1, 1), 50.0)], None),
        ("GC=F", [(date(2020, 1, 1), 1800.0)], None),
        ("^SPXEW", [(date(2020, 1, 1), 100.0)], None),
        ("GOVT", [(date(2020, 1, 1), 22.0)], None),
        ("^FCHI", [(date(2020, 1, 1), 6000.0)], None),
        ("MTE.PA", [(date(2020, 1, 1), 200.0)], None),
        ("MWEQ.L", [(date(2020, 1, 1), 4800.0)], None),
        ("BNDW", [(date(2020, 1, 1), 68.0)], None),
    ]
    with patch("app.tasks.macro_indicators.list_regions", new_callable=AsyncMock, return_value=_REGIONS), \
         patch("app.tasks.macro_indicators.get_macro_settings", new_callable=AsyncMock, return_value=_SETTINGS), \
         patch("app.tasks.macro_indicators._fetch_series_history", side_effect=fetch_results), \
         patch("app.tasks.macro_indicators.replace_series_prices", new_callable=AsyncMock) as mock_replace, \
         patch("app.tasks.macro_indicators.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_macro_indicators_refresh()

    assert result["status"] == "success"
    assert result["total_tickers"] == 8
    assert result["succeeded"] == 8
    assert result["failed_tickers"] == []
    assert mock_replace.call_count == 8
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_run_refresh_partial_failure():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetch_results = [
        ("CL=F", [(date(2020, 1, 1), 50.0)], None),
        ("GC=F", [(date(2020, 1, 1), 1800.0)], None),
        ("^SPXEW", [(date(2020, 1, 1), 100.0)], None),
        ("GOVT", None, "HTTP 500"),
        ("^FCHI", [(date(2020, 1, 1), 6000.0)], None),
        ("MTE.PA", [(date(2020, 1, 1), 200.0)], None),
        ("MWEQ.L", [(date(2020, 1, 1), 4800.0)], None),
        ("BNDW", [(date(2020, 1, 1), 68.0)], None),
    ]
    with patch("app.tasks.macro_indicators.list_regions", new_callable=AsyncMock, return_value=_REGIONS), \
         patch("app.tasks.macro_indicators.get_macro_settings", new_callable=AsyncMock, return_value=_SETTINGS), \
         patch("app.tasks.macro_indicators._fetch_series_history", side_effect=fetch_results), \
         patch("app.tasks.macro_indicators.replace_series_prices", new_callable=AsyncMock), \
         patch("app.tasks.macro_indicators.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_macro_indicators_refresh()

    assert result["status"] == "partial"
    assert result["succeeded"] == 7
    assert any("us_bond" in f and "GOVT" in f for f in result["failed_tickers"])


@pytest.mark.asyncio
async def test_run_refresh_all_fail_is_failed_status():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetch_results = [
        ("CL=F", None, "boom"), ("GC=F", None, "boom"),
        ("^SPXEW", None, "boom"), ("GOVT", None, "boom"),
        ("^FCHI", None, "boom"), ("MTE.PA", None, "boom"),
        ("MWEQ.L", None, "boom"), ("BNDW", None, "boom"),
    ]
    with patch("app.tasks.macro_indicators.list_regions", new_callable=AsyncMock, return_value=_REGIONS), \
         patch("app.tasks.macro_indicators.get_macro_settings", new_callable=AsyncMock, return_value=_SETTINGS), \
         patch("app.tasks.macro_indicators._fetch_series_history", side_effect=fetch_results), \
         patch("app.tasks.macro_indicators.replace_series_prices", new_callable=AsyncMock), \
         patch("app.tasks.macro_indicators.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_macro_indicators_refresh()

    assert result["status"] == "failed"
    assert result["succeeded"] == 0
    assert len(result["failed_tickers"]) == 8


# ---------------------------------------------------------------------------
# refresh_macro_indicators (Celery task)
# ---------------------------------------------------------------------------

def test_refresh_macro_indicators_writes_running_then_final_status():
    mock_r = MagicMock()
    success_result = {
        "started_at": "2026-07-14T07:00:00+00:00",
        "finished_at": "2026-07-14T07:00:05+00:00",
        "status": "success",
        "total_tickers": 4,
        "succeeded": 4,
        "failed_tickers": [],
    }

    def _close_and_return(coro):
        if hasattr(coro, "close"):
            coro.close()
        return success_result

    with patch("app.tasks.macro_indicators._get_redis", return_value=mock_r), \
         patch("app.tasks.macro_indicators.asyncio.run", side_effect=_close_and_return):
        result = refresh_macro_indicators()

    assert result == success_result
    assert mock_r.set.call_count == 2
    first_payload = json.loads(mock_r.set.call_args_list[0][0][1])
    assert first_payload["status"] == "running"
    second_payload = json.loads(mock_r.set.call_args_list[1][0][1])
    assert second_payload["status"] == "success"


def test_refresh_macro_indicators_handles_exception_and_writes_failed():
    mock_r = MagicMock()

    def _raise_and_close(coro):
        if hasattr(coro, "close"):
            coro.close()
        raise RuntimeError("DB down")

    with patch("app.tasks.macro_indicators._get_redis", return_value=mock_r), \
         patch("app.tasks.macro_indicators.asyncio.run", side_effect=_raise_and_close):
        result = refresh_macro_indicators()

    assert result["status"] == "failed"
    assert mock_r.set.call_count == 2
    final = json.loads(mock_r.set.call_args_list[1][0][1])
    assert final["status"] == "failed"


def test_sync_status_key_value():
    assert SYNC_STATUS_KEY == "pie:macro:status"
