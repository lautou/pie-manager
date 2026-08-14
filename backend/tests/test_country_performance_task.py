"""
Non-regression tests for the country performance refresh task
(app/tasks/country_performance.py).

Tested without real network calls — Yahoo Finance responses are mocked, mirroring the
pattern in test_macro_indicators_task.py. Key invariants:
  1. _run_country_performance_refresh fetches each country's index series plus one shared
     FX-to-EUR series per distinct non-EUR currency (deduped).
  2. EUR countries contribute no FX ticker at all.

fetch_yahoo_history's own retry/backoff/parsing mechanics are tested once, generically, in
test_yahoo_fetch.py. This module's PgQueuer entrypoint/schedule wrappers (issue #66 step 3)
are tested in test_pgq_app.py — refresh_country_performance no longer exists as a separate
Celery task function here.
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.country_performance import CountryPerfConfig
from app.tasks.country_performance import _run_country_performance_refresh


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

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


_COUNTRIES_TWO_CURRENCIES = [
    CountryPerfConfig(code="us", label="États-Unis", index_ticker="^GSPC", currency="USD", index_label="S&P 500"),
    CountryPerfConfig(code="de", label="Allemagne", index_ticker="^GDAXI", currency="EUR", index_label="DAX 40"),
]

_COUNTRIES_SHARED_CURRENCY = [
    CountryPerfConfig(code="us", label="États-Unis", index_ticker="^GSPC", currency="USD", index_label="S&P 500"),
    CountryPerfConfig(
        code="ca", label="Canada (fictif USD)", index_ticker="^GSPTSE", currency="USD", index_label="TSX",
    ),
]


# ---------------------------------------------------------------------------
# _run_country_performance_refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_refresh_no_countries_returns_empty_success():
    mock_eng, session_factory, _ = _make_db_mocks()
    with patch("app.tasks.country_performance.list_country_configs",
               new_callable=AsyncMock, return_value=[]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_country_performance_refresh()
    assert result["status"] == "success"
    assert result["total_tickers"] == 0
    assert result["failed_tickers"] == []


@pytest.mark.asyncio
async def test_run_refresh_eur_country_needs_no_fx_ticker():
    """A EUR-only country contributes no fx_* ticker to the fetch list."""
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetched_tickers = []

    async def mock_fetch(client, ticker, period1, period2):
        fetched_tickers.append(ticker)
        return ticker, [(date(2026, 1, 1), 100.0)], None

    with patch("app.tasks.country_performance.list_country_configs",
               new_callable=AsyncMock, return_value=[_COUNTRIES_TWO_CURRENCIES[1]]), \
         patch("app.tasks.country_performance.fetch_yahoo_history", side_effect=mock_fetch), \
         patch("app.tasks.country_performance.replace_series_prices", new_callable=AsyncMock), \
         patch("app.tasks.country_performance.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_country_performance_refresh()

    assert fetched_tickers == ["^GDAXI"]
    assert result["total_tickers"] == 1
    assert result["succeeded"] == 1


@pytest.mark.asyncio
async def test_run_refresh_all_succeed_with_dedicated_fx_ticker():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetch_results = [
        ("^GSPC", [(date(2025, 1, 1), 4000.0), (date(2026, 1, 1), 4500.0)], None),
        ("^GDAXI", [(date(2025, 1, 1), 15000.0), (date(2026, 1, 1), 16000.0)], None),
        ("USDEUR=X", [(date(2025, 1, 1), 0.9), (date(2026, 1, 1), 0.95)], None),
    ]
    with patch("app.tasks.country_performance.list_country_configs",
               new_callable=AsyncMock, return_value=_COUNTRIES_TWO_CURRENCIES), \
         patch("app.tasks.country_performance.fetch_yahoo_history", side_effect=fetch_results), \
         patch("app.tasks.country_performance.replace_series_prices", new_callable=AsyncMock) as mock_replace, \
         patch("app.tasks.country_performance.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_country_performance_refresh()

    assert result["status"] == "success"
    assert result["total_tickers"] == 3
    assert result["succeeded"] == 3
    assert result["failed_tickers"] == []
    assert mock_replace.call_count == 3
    mock_db.commit.assert_called_once()

    series_written = {call.args[1] for call in mock_replace.call_args_list}
    assert series_written == {"country_us_equity", "country_de_equity", "fx_usd"}


@pytest.mark.asyncio
async def test_run_refresh_dedupes_fx_ticker_across_shared_currency():
    """Two countries sharing USD must only produce ONE fx_usd fetch, not two."""
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetch_results = [
        ("^GSPC", [(date(2025, 1, 1), 4000.0), (date(2026, 1, 1), 4500.0)], None),
        ("^GSPTSE", [(date(2025, 1, 1), 20000.0), (date(2026, 1, 1), 21000.0)], None),
        ("USDEUR=X", [(date(2025, 1, 1), 0.9), (date(2026, 1, 1), 0.95)], None),
    ]
    with patch("app.tasks.country_performance.list_country_configs",
               new_callable=AsyncMock, return_value=_COUNTRIES_SHARED_CURRENCY), \
         patch("app.tasks.country_performance.fetch_yahoo_history", side_effect=fetch_results), \
         patch("app.tasks.country_performance.replace_series_prices", new_callable=AsyncMock), \
         patch("app.tasks.country_performance.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_country_performance_refresh()

    # 2 index tickers + exactly 1 shared fx ticker, not 2
    assert result["total_tickers"] == 3
    assert result["succeeded"] == 3


@pytest.mark.asyncio
async def test_run_refresh_partial_failure():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetch_results = [
        ("^GSPC", [(date(2025, 1, 1), 4000.0), (date(2026, 1, 1), 4500.0)], None),
        ("^GDAXI", None, "HTTP 500"),
        ("USDEUR=X", [(date(2025, 1, 1), 0.9), (date(2026, 1, 1), 0.95)], None),
    ]
    with patch("app.tasks.country_performance.list_country_configs",
               new_callable=AsyncMock, return_value=_COUNTRIES_TWO_CURRENCIES), \
         patch("app.tasks.country_performance.fetch_yahoo_history", side_effect=fetch_results), \
         patch("app.tasks.country_performance.replace_series_prices", new_callable=AsyncMock), \
         patch("app.tasks.country_performance.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_country_performance_refresh()

    assert result["status"] == "partial"
    assert result["succeeded"] == 2
    assert any("country_de_equity" in f and "^GDAXI" in f for f in result["failed_tickers"])


@pytest.mark.asyncio
async def test_run_refresh_all_fail_is_failed_status():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetch_results = [
        ("^GSPC", None, "boom"), ("^GDAXI", None, "boom"), ("USDEUR=X", None, "boom"),
    ]
    with patch("app.tasks.country_performance.list_country_configs",
               new_callable=AsyncMock, return_value=_COUNTRIES_TWO_CURRENCIES), \
         patch("app.tasks.country_performance.fetch_yahoo_history", side_effect=fetch_results), \
         patch("app.tasks.country_performance.replace_series_prices", new_callable=AsyncMock), \
         patch("app.tasks.country_performance.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_country_performance_refresh()

    assert result["status"] == "failed"
    assert result["succeeded"] == 0
    assert len(result["failed_tickers"]) == 3
