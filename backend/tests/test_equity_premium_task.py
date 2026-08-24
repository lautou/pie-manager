# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for the equity risk premium refresh task
(app/tasks/equity_premium.py). Crumb-aware shape mirrors test_etf_holdings_task.py, not
test_sector_performance_task.py/test_country_performance_task.py's plain chart-endpoint
shape — both a country's equity and bond leg go through the crumb-authenticated quoteSummary
endpoint (summaryDetail module), never fetch_yahoo_history.

Tested without real network calls — Yahoo Finance responses are mocked. Key invariants:
  1. Crumb acquisition failure aborts the whole task cleanly (no crash, "failed" status).
  2. _parse_trailing_pe_yield extracts 1/trailingPE; missing/zero/None trailingPE -> None.
  3. _parse_bond_yield extracts summaryDetail.yield; missing -> None (the known-gap shape).
  4. Per-leg independence: one country's equity leg can succeed while its bond leg fails,
     without failing the other leg or the whole country.
  5. _run_equity_premium_refresh orchestrates both legs for every configured country.

get_yahoo_session_crumb/fetch_quote_summary_module's own retry/parsing mechanics are tested
once, generically, in test_yahoo_fetch.py. This module's PgQueuer entrypoint/schedule wrappers
are tested in test_pgq_app.py.
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.equity_premium import EquityPremiumConfig
from app.tasks.equity_premium import (
    _fetch_bond_yield,
    _fetch_equity_yield,
    _parse_bond_yield,
    _parse_trailing_pe_yield,
    _run_equity_premium_refresh,
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


def _summary_detail_payload(trailing_pe=None, yield_value=None):
    summary_detail = {}
    if trailing_pe is not None:
        summary_detail["trailingPE"] = {"raw": trailing_pe}
    if yield_value is not None:
        summary_detail["yield"] = {"raw": yield_value}
    return {"quoteSummary": {"error": None, "result": [{"summaryDetail": summary_detail}]}}


def _no_data_payload():
    return {"quoteSummary": {"result": [], "error": {"code": "Not Found"}}}


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


_ONE_COUNTRY = [
    EquityPremiumConfig(code="us", label="États-Unis", equity_ticker="SPY", bond_ticker="IEF",
                         equity_label="S&P 500", bond_label="Trésor US"),
]

_TWO_COUNTRIES = [
    EquityPremiumConfig(code="us", label="États-Unis", equity_ticker="SPY", bond_ticker="IEF",
                         equity_label="S&P 500", bond_label="Trésor US"),
    EquityPremiumConfig(code="fr", label="France", equity_ticker="EWQ", bond_ticker="IFRB.L",
                         equity_label="CAC (EWQ)", bond_label="OAT (IFRB.L)"),
]


# ---------------------------------------------------------------------------
# _parse_trailing_pe_yield
# ---------------------------------------------------------------------------

def test_parse_trailing_pe_yield_extracts_inverse():
    payload = _summary_detail_payload(trailing_pe=25.0)
    assert _parse_trailing_pe_yield(payload) == pytest.approx(0.04)


def test_parse_trailing_pe_yield_missing_returns_none():
    assert _parse_trailing_pe_yield(_summary_detail_payload()) is None


def test_parse_trailing_pe_yield_zero_returns_none():
    assert _parse_trailing_pe_yield(_summary_detail_payload(trailing_pe=0)) is None


def test_parse_trailing_pe_yield_empty_result_returns_none():
    assert _parse_trailing_pe_yield(_no_data_payload()) is None


# ---------------------------------------------------------------------------
# _parse_bond_yield
# ---------------------------------------------------------------------------

def test_parse_bond_yield_extracts_raw_value():
    payload = _summary_detail_payload(yield_value=0.045)
    assert _parse_bond_yield(payload) == pytest.approx(0.045)


def test_parse_bond_yield_missing_returns_none():
    """The exact shape of a known-gap country: a real fund with an empty yield field."""
    assert _parse_bond_yield(_summary_detail_payload()) is None


def test_parse_bond_yield_empty_result_returns_none():
    assert _parse_bond_yield(_no_data_payload()) is None


# ---------------------------------------------------------------------------
# _fetch_equity_yield / _fetch_bond_yield — thin wrappers over
# fetch_quote_summary_module(module="summaryDetail", ...)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_equity_yield_success():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _summary_detail_payload(trailing_pe=25.0)))
    ticker, value, error = await _fetch_equity_yield(client, "crumb123", "SPY")
    assert ticker == "SPY"
    assert value == pytest.approx(0.04)
    assert error is None


@pytest.mark.asyncio
async def test_fetch_equity_yield_missing_trailing_pe():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _summary_detail_payload()))
    ticker, value, error = await _fetch_equity_yield(client, "crumb", "BAD")
    assert value is None
    assert error == "trailingPE missing"


@pytest.mark.asyncio
async def test_fetch_bond_yield_success():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _summary_detail_payload(yield_value=0.015)))
    ticker, value, error = await _fetch_bond_yield(client, "crumb123", "IEF")
    assert ticker == "IEF"
    assert value == pytest.approx(0.015)
    assert error is None


@pytest.mark.asyncio
async def test_fetch_bond_yield_missing():
    """Mirrors a known-gap country's real fund + empty yield field."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _summary_detail_payload()))
    ticker, value, error = await _fetch_bond_yield(client, "crumb", "GAP.PA")
    assert value is None
    assert error == "yield missing"


# ---------------------------------------------------------------------------
# _run_equity_premium_refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_refresh_no_countries_returns_empty_success():
    mock_eng, session_factory, _ = _make_db_mocks()
    with patch("app.tasks.equity_premium.list_premium_configs",
               new_callable=AsyncMock, return_value=[]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_equity_premium_refresh()
    assert result["status"] == "success"
    assert result["total_tickers"] == 0
    assert result["failed_tickers"] == []


@pytest.mark.asyncio
async def test_run_refresh_crumb_failure_aborts_cleanly():
    mock_eng, session_factory, _ = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()
    with patch("app.tasks.equity_premium.list_premium_configs",
               new_callable=AsyncMock, return_value=_ONE_COUNTRY), \
         patch("app.tasks.equity_premium.get_yahoo_session_crumb",
               new_callable=AsyncMock, return_value=None), \
         patch("app.tasks.equity_premium.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_equity_premium_refresh()
    assert result["status"] == "failed"
    assert "crumb" in result["error"]
    assert result["succeeded"] == 0
    assert result["total_tickers"] == 2  # 1 country x 2 legs


@pytest.mark.asyncio
async def test_run_refresh_both_legs_succeed():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()
    today = date.today()

    with patch("app.tasks.equity_premium.list_premium_configs",
               new_callable=AsyncMock, return_value=_ONE_COUNTRY), \
         patch("app.tasks.equity_premium.get_yahoo_session_crumb",
               new_callable=AsyncMock, return_value="crumb123"), \
         patch("app.tasks.equity_premium._fetch_equity_yield",
               new_callable=AsyncMock, return_value=("SPY", 0.04, None)), \
         patch("app.tasks.equity_premium._fetch_bond_yield",
               new_callable=AsyncMock, return_value=("IEF", 0.015, None)), \
         patch("app.tasks.equity_premium.replace_series_prices", new_callable=AsyncMock) as mock_replace, \
         patch("app.tasks.equity_premium.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_equity_premium_refresh()

    assert result["status"] == "success"
    assert result["total_tickers"] == 2
    assert result["succeeded"] == 2
    assert result["failed_tickers"] == []
    mock_db.commit.assert_called_once()

    series_written = {call.args[1]: call.args[2] for call in mock_replace.call_args_list}
    assert series_written["premium_us_equity_yield"] == [(today, 0.04)]
    assert series_written["premium_us_bond_yield"] == [(today, 0.015)]


@pytest.mark.asyncio
async def test_run_refresh_per_leg_independence_equity_ok_bond_fails():
    """A country's equity leg succeeding while its bond leg fails must still write the equity
    series — this is what lets a known-gap country self-heal without any code change once
    Yahoo starts exposing its yield."""
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    with patch("app.tasks.equity_premium.list_premium_configs",
               new_callable=AsyncMock, return_value=_ONE_COUNTRY), \
         patch("app.tasks.equity_premium.get_yahoo_session_crumb",
               new_callable=AsyncMock, return_value="crumb123"), \
         patch("app.tasks.equity_premium._fetch_equity_yield",
               new_callable=AsyncMock, return_value=("SPY", 0.04, None)), \
         patch("app.tasks.equity_premium._fetch_bond_yield",
               new_callable=AsyncMock, return_value=("IEF", None, "yield missing")), \
         patch("app.tasks.equity_premium.replace_series_prices", new_callable=AsyncMock) as mock_replace, \
         patch("app.tasks.equity_premium.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_equity_premium_refresh()

    assert result["status"] == "partial"
    assert result["succeeded"] == 1
    assert any("premium_us_bond_yield" in f and "yield missing" in f for f in result["failed_tickers"])
    written_series = {call.args[1] for call in mock_replace.call_args_list}
    assert written_series == {"premium_us_equity_yield"}


@pytest.mark.asyncio
async def test_run_refresh_multi_country_bookkeeping():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    async def fake_equity(client, crumb, ticker):
        return ticker, (0.04 if ticker == "SPY" else 0.05), None

    async def fake_bond(client, crumb, ticker):
        return ticker, (0.015 if ticker == "IEF" else 0.02), None

    with patch("app.tasks.equity_premium.list_premium_configs",
               new_callable=AsyncMock, return_value=_TWO_COUNTRIES), \
         patch("app.tasks.equity_premium.get_yahoo_session_crumb",
               new_callable=AsyncMock, return_value="crumb123"), \
         patch("app.tasks.equity_premium._fetch_equity_yield", side_effect=fake_equity), \
         patch("app.tasks.equity_premium._fetch_bond_yield", side_effect=fake_bond), \
         patch("app.tasks.equity_premium.replace_series_prices", new_callable=AsyncMock) as mock_replace, \
         patch("app.tasks.equity_premium.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_equity_premium_refresh()

    assert result["status"] == "success"
    assert result["total_tickers"] == 4  # 2 countries x 2 legs
    assert result["succeeded"] == 4
    assert mock_replace.call_count == 4
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_run_refresh_all_fail_is_failed_status():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    with patch("app.tasks.equity_premium.list_premium_configs",
               new_callable=AsyncMock, return_value=_ONE_COUNTRY), \
         patch("app.tasks.equity_premium.get_yahoo_session_crumb",
               new_callable=AsyncMock, return_value="crumb123"), \
         patch("app.tasks.equity_premium._fetch_equity_yield",
               new_callable=AsyncMock, return_value=("SPY", None, "trailingPE missing")), \
         patch("app.tasks.equity_premium._fetch_bond_yield",
               new_callable=AsyncMock, return_value=("IEF", None, "yield missing")), \
         patch("app.tasks.equity_premium.replace_series_prices", new_callable=AsyncMock), \
         patch("app.tasks.equity_premium.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_equity_premium_refresh()

    assert result["status"] == "failed"
    assert result["succeeded"] == 0
    assert len(result["failed_tickers"]) == 2
