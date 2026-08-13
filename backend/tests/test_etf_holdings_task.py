"""
Non-regression tests for the ETF holdings refresh task (app/tasks/etf_holdings.py).

Tested without real network calls — Yahoo Finance responses are mocked, mirroring the
pattern in test_price_sync.py. Key invariants:
  1. Crumb acquisition failure aborts the whole task cleanly (no crash, "failed" status).
  2. topHoldings parsing extracts holdings/sectors/bond metrics, drops exact-zero sectors.
  3. A fund with no fundamentals data (404-style empty result) is a per-ticker failure.
  4. assetProfile.sectorKey parsing for direct stocks; missing sectorKey is a failure.
  5. _run_etf_holdings_refresh orchestrates ETF + direct-stock fetches and writes both.
  6. refresh_etf_holdings (Celery task) writes running then final status to Redis.

get_redis/write_status are tested once, generically, in test_sync_status.py.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import fetch_latest_job_run

from app.tasks.etf_holdings import (
    _get_yahoo_session_crumb,
    _parse_top_holdings,
    _parse_asset_profile_sector,
    _fetch_top_holdings,
    _fetch_asset_profile_sector,
    _run_etf_holdings_refresh,
    refresh_etf_holdings,
    SYNC_STATUS_KEY,
)


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


def _top_holdings_payload(holdings=None, sector_weightings=None, duration=None, maturity=None):
    bond = {}
    if duration is not None:
        bond["duration"] = {"raw": duration}
    else:
        bond["duration"] = {}
    if maturity is not None:
        bond["maturity"] = {"raw": maturity}
    else:
        bond["maturity"] = {}
    return {
        "quoteSummary": {
            "error": None,
            "result": [{
                "topHoldings": {
                    "holdings": holdings or [],
                    "sectorWeightings": [
                        {k: {"raw": v}} for k, v in (sector_weightings or {}).items()
                    ],
                    "bondHoldings": bond,
                },
            }],
        },
    }


def _no_data_payload():
    return {"quoteSummary": {"result": [], "error": {"code": "Not Found"}}}


def _asset_profile_payload(sector_key: str | None):
    profile = {"sectorKey": sector_key} if sector_key else {}
    return {"quoteSummary": {"error": None, "result": [{"assetProfile": profile}]}}


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


# ---------------------------------------------------------------------------
# _get_yahoo_session_crumb
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_yahoo_session_crumb_success():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        _FakeResponse(404),  # fc.yahoo.com quirk, still sets cookies in real life
        _FakeResponse(301),  # finance.yahoo.com/quote/AAPL redirect
        _FakeResponse(200, text=" abc123crumb \n"),
    ])
    crumb = await _get_yahoo_session_crumb(client)
    assert crumb == "abc123crumb"


@pytest.mark.asyncio
async def test_get_yahoo_session_crumb_non_200_returns_none():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        _FakeResponse(200), _FakeResponse(200), _FakeResponse(401, text=""),
    ])
    crumb = await _get_yahoo_session_crumb(client)
    assert crumb is None


@pytest.mark.asyncio
async def test_get_yahoo_session_crumb_empty_body_returns_none():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[_FakeResponse(200), _FakeResponse(200), _FakeResponse(200, text="   ")])
    crumb = await _get_yahoo_session_crumb(client)
    assert crumb is None


@pytest.mark.asyncio
async def test_get_yahoo_session_crumb_exception_returns_none():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=ConnectionError("network down"))
    crumb = await _get_yahoo_session_crumb(client)
    assert crumb is None


# ---------------------------------------------------------------------------
# _parse_top_holdings
# ---------------------------------------------------------------------------

def test_parse_top_holdings_extracts_all_fields():
    payload = _top_holdings_payload(
        holdings=[{"symbol": "0700.HK", "holdingName": "Tencent Holdings Ltd",
                   "holdingPercent": {"raw": 0.1239}}],
        sector_weightings={"energy": 0.9946, "communication_services": 0.0},
        duration=1.32, maturity=8.57,
    )
    parsed = _parse_top_holdings(payload)
    assert parsed["holdings"] == [{"ticker": "0700.HK", "name": "Tencent Holdings Ltd", "weight_pct": 0.1239}]
    # Exact-zero sectors are dropped
    assert parsed["sector_weightings"] == {"energy": 0.9946}
    assert parsed["bond_duration"] == pytest.approx(1.32)
    assert parsed["bond_maturity"] == pytest.approx(8.57)


def test_parse_top_holdings_no_bond_metrics_returns_none():
    payload = _top_holdings_payload(holdings=[{"symbol": "X", "holdingName": "X", "holdingPercent": {"raw": 1.0}}])
    parsed = _parse_top_holdings(payload)
    assert parsed["bond_duration"] is None
    assert parsed["bond_maturity"] is None


def test_parse_top_holdings_empty_result_returns_none():
    assert _parse_top_holdings(_no_data_payload()) is None


# ---------------------------------------------------------------------------
# _parse_asset_profile_sector
# ---------------------------------------------------------------------------

def test_parse_asset_profile_sector_returns_key():
    assert _parse_asset_profile_sector(_asset_profile_payload("energy")) == "energy"


def test_parse_asset_profile_sector_normalizes_hyphens_to_underscores():
    """
    Regression: assetProfile.sectorKey uses hyphens for multi-word sectors (confirmed on
    real stocks MC.PA -> "consumer-cyclical", AI.PA -> "basic-materials"), but
    topHoldings.sectorWeightings uses underscores for the same sectors. Without
    normalization, a direct stock's sector would never merge with an ETF's.
    """
    assert _parse_asset_profile_sector(_asset_profile_payload("consumer-cyclical")) == "consumer_cyclical"
    assert _parse_asset_profile_sector(_asset_profile_payload("basic-materials")) == "basic_materials"


def test_parse_asset_profile_sector_missing_key_returns_none():
    assert _parse_asset_profile_sector(_asset_profile_payload(None)) is None


def test_parse_asset_profile_sector_empty_result_returns_none():
    assert _parse_asset_profile_sector(_no_data_payload()) is None


# ---------------------------------------------------------------------------
# _fetch_top_holdings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_top_holdings_success():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _top_holdings_payload(
        holdings=[{"symbol": "X", "holdingName": "X", "holdingPercent": {"raw": 1.0}}]
    )))
    ticker, parsed, error = await _fetch_top_holdings(client, "crumb123", "FLXC.DE")
    assert ticker == "FLXC.DE"
    assert parsed is not None
    assert error is None


@pytest.mark.asyncio
async def test_fetch_top_holdings_http_error():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(500))
    ticker, parsed, error = await _fetch_top_holdings(client, "crumb", "BAD.DE")
    assert parsed is None
    assert "500" in error


@pytest.mark.asyncio
async def test_fetch_top_holdings_no_fundamentals():
    """Mirrors GOLD-EUR.PA's real 404-style empty result."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _no_data_payload()))
    ticker, parsed, error = await _fetch_top_holdings(client, "crumb", "GOLD-EUR.PA")
    assert parsed is None
    assert error == "no fundamentals data"


@pytest.mark.asyncio
async def test_fetch_top_holdings_exception():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=ConnectionError("timeout"))
    ticker, parsed, error = await _fetch_top_holdings(client, "crumb", "CRASH.DE")
    assert parsed is None
    assert error is not None


# ---------------------------------------------------------------------------
# _fetch_asset_profile_sector
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_asset_profile_sector_success():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _asset_profile_payload("energy")))
    ticker, sector, error = await _fetch_asset_profile_sector(client, "crumb", "TTE.PA")
    assert sector == "energy"
    assert error is None


@pytest.mark.asyncio
async def test_fetch_asset_profile_sector_http_error():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(403))
    ticker, sector, error = await _fetch_asset_profile_sector(client, "crumb", "TTE.PA")
    assert sector is None
    assert "403" in error


@pytest.mark.asyncio
async def test_fetch_asset_profile_sector_missing_key():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _asset_profile_payload(None)))
    ticker, sector, error = await _fetch_asset_profile_sector(client, "crumb", "TTE.PA")
    assert sector is None
    assert error == "sectorKey missing"


@pytest.mark.asyncio
async def test_fetch_asset_profile_sector_exception():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=ConnectionError("down"))
    ticker, sector, error = await _fetch_asset_profile_sector(client, "crumb", "TTE.PA")
    assert sector is None
    assert error is not None


# ---------------------------------------------------------------------------
# _run_etf_holdings_refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_refresh_no_tickers_returns_empty_success():
    mock_eng, session_factory, _ = _make_db_mocks()
    with patch("app.tasks.etf_holdings.get_etf_tickers", new_callable=AsyncMock, return_value=[]), \
         patch("app.tasks.etf_holdings.get_direct_stock_tickers_in_etf_pools",
               new_callable=AsyncMock, return_value=[]), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_etf_holdings_refresh()
    assert result["status"] == "success"
    assert result["total_tickers"] == 0


@pytest.mark.asyncio
async def test_run_refresh_crumb_failure_aborts_cleanly():
    mock_eng, session_factory, _ = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()
    with patch("app.tasks.etf_holdings.get_etf_tickers", new_callable=AsyncMock, return_value=["FLXC.DE"]), \
         patch("app.tasks.etf_holdings.get_direct_stock_tickers_in_etf_pools",
               new_callable=AsyncMock, return_value=[]), \
         patch("app.tasks.etf_holdings._get_yahoo_session_crumb",
               new_callable=AsyncMock, return_value=None), \
         patch("app.tasks.etf_holdings.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_etf_holdings_refresh()
    assert result["status"] == "failed"
    assert "crumb" in result["error"]
    assert result["succeeded"] == 0


@pytest.mark.asyncio
async def test_run_refresh_etf_and_direct_stock_success():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    with patch("app.tasks.etf_holdings.get_etf_tickers",
               new_callable=AsyncMock, return_value=["FLXC.DE"]), \
         patch("app.tasks.etf_holdings.get_direct_stock_tickers_in_etf_pools",
               new_callable=AsyncMock, return_value=[("TTE.PA", "TotalEnergies SE")]), \
         patch("app.tasks.etf_holdings._get_yahoo_session_crumb",
               new_callable=AsyncMock, return_value="crumb123"), \
         patch("app.tasks.etf_holdings._fetch_top_holdings",
               new_callable=AsyncMock,
               return_value=("FLXC.DE", {"holdings": [], "sector_weightings": {"energy": 1.0},
                                          "bond_duration": None, "bond_maturity": None}, None)), \
         patch("app.tasks.etf_holdings._fetch_asset_profile_sector",
               new_callable=AsyncMock, return_value=("TTE.PA", "energy", None)), \
         patch("app.tasks.etf_holdings.save_etf_fetch_result", new_callable=AsyncMock) as mock_save, \
         patch("app.tasks.etf_holdings.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_etf_holdings_refresh()

    assert result["status"] == "success"
    assert result["total_tickers"] == 2
    assert result["succeeded"] == 2
    assert mock_save.call_count == 2
    mock_db.commit.assert_called_once()
    # The direct stock's synthetic self-row uses the fetched product name.
    stock_call = next(c for c in mock_save.call_args_list if c.args[1] == "TTE.PA")
    assert stock_call.kwargs["holdings"] == [{"ticker": "TTE.PA", "name": "TotalEnergies SE", "weight_pct": 1.0}]
    assert stock_call.kwargs["sector_weightings"] == {"energy": 1.0}


@pytest.mark.asyncio
async def test_run_refresh_partial_failure():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    with patch("app.tasks.etf_holdings.get_etf_tickers",
               new_callable=AsyncMock, return_value=["OK.DE", "BAD.DE"]), \
         patch("app.tasks.etf_holdings.get_direct_stock_tickers_in_etf_pools",
               new_callable=AsyncMock, return_value=[]), \
         patch("app.tasks.etf_holdings._get_yahoo_session_crumb",
               new_callable=AsyncMock, return_value="crumb123"), \
         patch("app.tasks.etf_holdings._fetch_top_holdings", side_effect=[
             ("OK.DE", {"holdings": [], "sector_weightings": {}, "bond_duration": None, "bond_maturity": None}, None),
             ("BAD.DE", None, "no fundamentals data"),
         ]), \
         patch("app.tasks.etf_holdings.save_etf_fetch_result", new_callable=AsyncMock), \
         patch("app.tasks.etf_holdings.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_etf_holdings_refresh()

    assert result["status"] == "partial"
    assert result["succeeded"] == 1
    assert any("BAD.DE" in f for f in result["failed_tickers"])


@pytest.mark.asyncio
async def test_run_refresh_all_fail_is_failed_status():
    mock_eng, session_factory, mock_db = _make_db_mocks()
    mock_httpx, _ = _make_httpx_mock()

    with patch("app.tasks.etf_holdings.get_etf_tickers",
               new_callable=AsyncMock, return_value=[]), \
         patch("app.tasks.etf_holdings.get_direct_stock_tickers_in_etf_pools",
               new_callable=AsyncMock, return_value=[("BADSTOCK.PA", "Bad Stock")]), \
         patch("app.tasks.etf_holdings._get_yahoo_session_crumb",
               new_callable=AsyncMock, return_value="crumb123"), \
         patch("app.tasks.etf_holdings._fetch_asset_profile_sector",
               new_callable=AsyncMock, return_value=("BADSTOCK.PA", None, "sectorKey missing")), \
         patch("app.tasks.etf_holdings.save_etf_fetch_result", new_callable=AsyncMock), \
         patch("app.tasks.etf_holdings.httpx", mock_httpx), \
         patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_eng), \
         patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=session_factory):
        result = await _run_etf_holdings_refresh()

    assert result["status"] == "failed"
    assert result["succeeded"] == 0
    assert any("BADSTOCK.PA" in f for f in result["failed_tickers"])


# ---------------------------------------------------------------------------
# refresh_etf_holdings (Celery task)
# ---------------------------------------------------------------------------

def test_refresh_etf_holdings_writes_running_then_final_status():
    mock_r = MagicMock()
    success_result = {
        "started_at": "2026-07-14T06:00:00+00:00",
        "finished_at": "2026-07-14T06:00:05+00:00",
        "status": "success",
        "total_tickers": 3,
        "succeeded": 3,
        "failed_tickers": [],
    }

    def _close_and_return(coro):
        if hasattr(coro, "close"):
            coro.close()
        return success_result

    with patch("app.tasks.etf_holdings.get_redis", return_value=mock_r), \
         patch("app.tasks.etf_holdings.asyncio.run", side_effect=_close_and_return):
        result = refresh_etf_holdings()

    assert result == success_result
    assert mock_r.set.call_count == 2
    first_payload = json.loads(mock_r.set.call_args_list[0][0][1])
    assert first_payload["status"] == "running"
    second_payload = json.loads(mock_r.set.call_args_list[1][0][1])
    assert second_payload["status"] == "success"


def test_refresh_etf_holdings_handles_exception_and_writes_failed():
    mock_r = MagicMock()

    def _raise_and_close(coro):
        if hasattr(coro, "close"):
            coro.close()
        raise RuntimeError("DB down")

    with patch("app.tasks.etf_holdings.get_redis", return_value=mock_r), \
         patch("app.tasks.etf_holdings.asyncio.run", side_effect=_raise_and_close):
        result = refresh_etf_holdings()

    assert result["status"] == "failed"
    assert mock_r.set.call_count == 2
    final = json.loads(mock_r.set.call_args_list[1][0][1])
    assert final["status"] == "failed"


def test_sync_status_key_value():
    assert SYNC_STATUS_KEY == "pie:etf_holdings:status"


# ---------------------------------------------------------------------------
# job_runs dual-write (issue #66 step 1) — real DB row, real asyncio.run this time
# ---------------------------------------------------------------------------

def test_refresh_etf_holdings_writes_job_runs_row_on_success(engine):
    """Depends on the `engine` fixture (unused directly) purely to guarantee the schema
    exists when this file runs in isolation."""
    mock_r = MagicMock()
    success_result = {
        "started_at": "2026-05-15T14:30:00+00:00",
        "finished_at": "2026-05-15T14:30:05+00:00",
        "status": "partial",
        "total_tickers": 4,
        "succeeded": 3,
        "failed_tickers": ["ETF1(no crumb)"],
    }
    with patch("app.tasks.etf_holdings.get_redis", return_value=mock_r), \
         patch("app.tasks.etf_holdings._run_etf_holdings_refresh",
               new_callable=AsyncMock, return_value=success_result):
        result = refresh_etf_holdings()

    assert result == success_result
    run = asyncio.run(fetch_latest_job_run("refresh_etf_holdings"))
    assert run.status == "partial"
    assert run.total_steps == 4
    assert run.succeeded_steps == 3
    assert run.failed_items == ["ETF1(no crumb)"]


def test_refresh_etf_holdings_writes_job_runs_failed_row_on_exception(engine):
    mock_r = MagicMock()
    with patch("app.tasks.etf_holdings.get_redis", return_value=mock_r), \
         patch("app.tasks.etf_holdings._run_etf_holdings_refresh",
               new_callable=AsyncMock, side_effect=RuntimeError("DB down")):
        refresh_etf_holdings()

    run = asyncio.run(fetch_latest_job_run("refresh_etf_holdings"))
    assert run.status == "failed"
    assert run.error == "DB down"
