# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for the sovereign bond performance refresh task
(app/tasks/bond_performance.py). Mirrors test_sector_performance_task.py.

Tested without real network calls — Yahoo Finance responses are mocked. Key invariants:
  1. _run_bond_performance_refresh fetches each country's bond series plus one shared
     FX-to-EUR series per distinct non-EUR currency (deduped).
  2. EUR countries contribute no FX ticker at all.

fetch_yahoo_history's own retry/backoff/parsing mechanics are tested once, generically, in
test_yahoo_fetch.py. This module's PgQueuer entrypoint/schedule wrappers are tested in
test_pgq_app.py.
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.bond_performance import BondPerfConfig
from app.tasks.bond_performance import _run_bond_performance_refresh


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
    BondPerfConfig(code="us", label="États-Unis", index_ticker="IEF", currency="USD", index_label="Trésor américain"),
    BondPerfConfig(code="fr", label="France", index_ticker="IFRB.AS", currency="EUR", index_label="Obligations françaises"),
]

_COUNTRIES_SHARED_CURRENCY = [
    BondPerfConfig(code="us", label="États-Unis", index_ticker="IEF", currency="USD", index_label="Trésor américain"),
    BondPerfConfig(code="in", label="Inde", index_ticker="INGB.AS", currency="USD", index_label="Obligations indiennes"),
]


# ---------------------------------------------------------------------------
# _run_bond_performance_refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_refresh_no_countries_returns_empty_success():
    mock_eng, session_factory, _ = _make_db_mocks()
    with patch("app.tasks.bond_performance.list_bond_configs",
               new_callable=AsyncMock, return_value=[]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_bond_performance_refresh()
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

    with patch("app.tasks.bond_performance.list_bond_configs",
               new_callable=AsyncMock, return_value=[_COUNTRIES_TWO_CURRENCIES[1]]), \
         patch("app.tasks.bond_performance.fetch_yahoo_history", side_effect=mock_fetch), \
         patch("app.tasks.bond_performance.replace_series_prices", new_callable=AsyncMock), \
         patch("app.tasks.bond_performance.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_bond_performance_refresh()

    assert fetched_tickers == ["IFRB.AS"]
    assert result["total_tickers"] == 1
    assert result["succeeded"] == 1


@pytest.mark.asyncio
async def test_run_refresh_all_succeed_with_dedicated_fx_ticker():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetch_results = [
        ("IEF", [(date(2025, 1, 1), 95.0), (date(2026, 1, 1), 97.0)], None),
        ("IFRB.AS", [(date(2025, 1, 1), 100.0), (date(2026, 1, 1), 103.0)], None),
        ("USDEUR=X", [(date(2025, 1, 1), 0.9), (date(2026, 1, 1), 0.95)], None),
    ]
    with patch("app.tasks.bond_performance.list_bond_configs",
               new_callable=AsyncMock, return_value=_COUNTRIES_TWO_CURRENCIES), \
         patch("app.tasks.bond_performance.fetch_yahoo_history", side_effect=fetch_results), \
         patch("app.tasks.bond_performance.replace_series_prices", new_callable=AsyncMock) as mock_replace, \
         patch("app.tasks.bond_performance.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_bond_performance_refresh()

    assert result["status"] == "success"
    assert result["total_tickers"] == 3
    assert result["succeeded"] == 3
    assert result["failed_tickers"] == []
    assert mock_replace.call_count == 3
    mock_db.commit.assert_called_once()

    series_written = {call.args[1] for call in mock_replace.call_args_list}
    assert series_written == {"bond_us_govt", "bond_fr_govt", "fx_usd"}


@pytest.mark.asyncio
async def test_run_refresh_dedupes_fx_ticker_across_shared_currency():
    """Two countries sharing USD must only produce ONE fx_usd fetch, not two."""
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetch_results = [
        ("IEF", [(date(2025, 1, 1), 95.0), (date(2026, 1, 1), 97.0)], None),
        ("INGB.AS", [(date(2025, 1, 1), 70.0), (date(2026, 1, 1), 75.0)], None),
        ("USDEUR=X", [(date(2025, 1, 1), 0.9), (date(2026, 1, 1), 0.95)], None),
    ]
    with patch("app.tasks.bond_performance.list_bond_configs",
               new_callable=AsyncMock, return_value=_COUNTRIES_SHARED_CURRENCY), \
         patch("app.tasks.bond_performance.fetch_yahoo_history", side_effect=fetch_results), \
         patch("app.tasks.bond_performance.replace_series_prices", new_callable=AsyncMock), \
         patch("app.tasks.bond_performance.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_bond_performance_refresh()

    # 2 price tickers + exactly 1 shared fx ticker, not 2
    assert result["total_tickers"] == 3
    assert result["succeeded"] == 3


@pytest.mark.asyncio
async def test_run_refresh_partial_failure():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetch_results = [
        ("IEF", [(date(2025, 1, 1), 95.0), (date(2026, 1, 1), 97.0)], None),
        ("IFRB.AS", None, "HTTP 500"),
        ("USDEUR=X", [(date(2025, 1, 1), 0.9), (date(2026, 1, 1), 0.95)], None),
    ]
    with patch("app.tasks.bond_performance.list_bond_configs",
               new_callable=AsyncMock, return_value=_COUNTRIES_TWO_CURRENCIES), \
         patch("app.tasks.bond_performance.fetch_yahoo_history", side_effect=fetch_results), \
         patch("app.tasks.bond_performance.replace_series_prices", new_callable=AsyncMock), \
         patch("app.tasks.bond_performance.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_bond_performance_refresh()

    assert result["status"] == "partial"
    assert result["succeeded"] == 2
    assert any("bond_fr_govt" in f and "IFRB.AS" in f for f in result["failed_tickers"])


@pytest.mark.asyncio
async def test_run_refresh_all_fail_is_failed_status():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    fetch_results = [
        ("IEF", None, "boom"), ("IFRB.AS", None, "boom"), ("USDEUR=X", None, "boom"),
    ]
    with patch("app.tasks.bond_performance.list_bond_configs",
               new_callable=AsyncMock, return_value=_COUNTRIES_TWO_CURRENCIES), \
         patch("app.tasks.bond_performance.fetch_yahoo_history", side_effect=fetch_results), \
         patch("app.tasks.bond_performance.replace_series_prices", new_callable=AsyncMock), \
         patch("app.tasks.bond_performance.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_bond_performance_refresh()

    assert result["status"] == "failed"
    assert result["succeeded"] == 0
    assert len(result["failed_tickers"]) == 3
