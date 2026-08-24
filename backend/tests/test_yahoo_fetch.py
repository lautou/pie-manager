# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for the shared Yahoo Finance fetch helpers (app/tasks/yahoo_fetch.py).

Extracted from what used to be near-identical private copies of these tests in
test_price_sync.py (_fetch_ticker's retry/backoff) and test_macro_indicators_task.py
(_fetch_series_history) — the retry/backoff scaffold is now tested once here via
fetch_yahoo_chart; fetch_yahoo_history only gets its own small set of tests for the
history-specific parsing it adds on top.

The crumb-authenticated quoteSummary helpers (get_yahoo_session_crumb,
fetch_quote_summary_module) were extracted here from test_etf_holdings_task.py once
equity_premium.py needed the identical mechanism for a second, unrelated task.
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock, patch

from app.tasks.yahoo_fetch import (
    fetch_quote_summary_module,
    fetch_yahoo_chart,
    fetch_yahoo_history,
    get_yahoo_session_crumb,
)


class _FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


def _chart_payload(timestamps: list[int], closes: list[float | None]) -> dict:
    return {"chart": {"result": [{"timestamp": timestamps, "indicators": {"quote": [{"close": closes}]}}]}}


def _meta_payload(price: float) -> dict:
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price}}]}}


# ---------------------------------------------------------------------------
# fetch_yahoo_chart — generic retry/backoff scaffold
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_yahoo_chart_success_returns_raw_result():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _meta_payload(42.5)))
    ticker, result, error = await fetch_yahoo_chart(client, "TEST.PA")
    assert ticker == "TEST.PA"
    assert result == {"meta": {"regularMarketPrice": 42.5}}
    assert error is None


@pytest.mark.asyncio
async def test_fetch_yahoo_chart_no_chart_data():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, {"chart": {"result": []}}))
    _, result, error = await fetch_yahoo_chart(client, "BAD=F")
    assert result is None
    assert error == "no chart data"


@pytest.mark.asyncio
async def test_fetch_yahoo_chart_http_error():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(404))
    _, result, error = await fetch_yahoo_chart(client, "UNKNOWN.XX")
    assert result is None
    assert "404" in error


@pytest.mark.asyncio
async def test_fetch_yahoo_chart_429_exhausts_retries():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(429))
    with patch("app.tasks.yahoo_fetch.asyncio.sleep", new_callable=AsyncMock):
        _, result, error = await fetch_yahoo_chart(client, "RATE.XX")
    assert result is None
    assert "429" in error


@pytest.mark.asyncio
async def test_fetch_yahoo_chart_429_then_success():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[_FakeResponse(429), _FakeResponse(200, _meta_payload(99.0))])
    with patch("app.tasks.yahoo_fetch.asyncio.sleep", new_callable=AsyncMock):
        _, result, error = await fetch_yahoo_chart(client, "RETRY.PA")
    assert result == {"meta": {"regularMarketPrice": 99.0}}
    assert error is None


@pytest.mark.asyncio
async def test_fetch_yahoo_chart_exception_on_every_retry():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=ConnectionError("network down"))
    with patch("app.tasks.yahoo_fetch.asyncio.sleep", new_callable=AsyncMock):
        ticker, result, error = await fetch_yahoo_chart(client, "CRASH.PA")
    assert result is None
    assert error and len(error) > 0


@pytest.mark.asyncio
async def test_fetch_yahoo_chart_exception_then_success():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[ConnectionError("timeout"), _FakeResponse(200, _meta_payload(77.0))])
    with patch("app.tasks.yahoo_fetch.asyncio.sleep", new_callable=AsyncMock):
        _, result, error = await fetch_yahoo_chart(client, "RECOV.PA")
    assert result == {"meta": {"regularMarketPrice": 77.0}}
    assert error is None


@pytest.mark.asyncio
async def test_fetch_yahoo_chart_max_retries_zero_falls_through():
    """With MAX_RETRIES=0 the for-loop body never executes, hitting the safety
    'return ticker, None, "max retries exceeded"' after the loop."""
    client = AsyncMock()
    with patch("app.tasks.yahoo_fetch.MAX_RETRIES", 0):
        _, result, error = await fetch_yahoo_chart(client, "ZERO.XX")
    assert result is None
    assert error == "max retries exceeded"


@pytest.mark.asyncio
async def test_fetch_yahoo_chart_passes_params_and_timeout_through():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _meta_payload(1.0)))
    await fetch_yahoo_chart(client, "AAPL", params={"period1": 0, "period2": 1, "interval": "1d"}, timeout=15.0)
    _, kwargs = client.get.call_args
    assert kwargs["params"] == {"period1": 0, "period2": 1, "interval": "1d"}
    assert kwargs["timeout"] == 15.0


# ---------------------------------------------------------------------------
# fetch_yahoo_history — history-specific parsing on top of fetch_yahoo_chart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_yahoo_history_success_drops_none_closes():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _chart_payload(
        [1577836800, 1577923200, 1578009600], [100.0, None, 102.0]
    )))
    ticker, points, error = await fetch_yahoo_history(client, "^SPXEW", 0, 10**10)
    assert ticker == "^SPXEW"
    assert error is None
    assert points == [(date(2020, 1, 1), 100.0), (date(2020, 1, 3), 102.0)]


@pytest.mark.asyncio
async def test_fetch_yahoo_history_no_usable_points():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, _chart_payload([1577836800], [None])))
    _, points, error = await fetch_yahoo_history(client, "GC=F", 0, 1)
    assert points is None
    assert error == "no usable data points"


@pytest.mark.asyncio
async def test_fetch_yahoo_history_propagates_chart_fetch_error():
    """A chart-fetch failure (e.g. exhausted retries) passes its error straight through
    without attempting to parse a history that was never returned."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(500))
    _, points, error = await fetch_yahoo_history(client, "CL=F", 0, 1)
    assert points is None
    assert "500" in error


# ---------------------------------------------------------------------------
# get_yahoo_session_crumb — crumb-authenticated quoteSummary session (etf_holdings.py,
# equity_premium.py)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_yahoo_session_crumb_success():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        _FakeResponse(404),  # fc.yahoo.com quirk, still sets cookies in real life
        _FakeResponse(301),  # finance.yahoo.com/quote/AAPL redirect
        _FakeResponse(200, text=" abc123crumb \n"),
    ])
    crumb = await get_yahoo_session_crumb(client)
    assert crumb == "abc123crumb"


@pytest.mark.asyncio
async def test_get_yahoo_session_crumb_non_200_returns_none():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        _FakeResponse(200), _FakeResponse(200), _FakeResponse(401, text=""),
    ])
    crumb = await get_yahoo_session_crumb(client)
    assert crumb is None


@pytest.mark.asyncio
async def test_get_yahoo_session_crumb_empty_body_returns_none():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[_FakeResponse(200), _FakeResponse(200), _FakeResponse(200, text="   ")])
    crumb = await get_yahoo_session_crumb(client)
    assert crumb is None


@pytest.mark.asyncio
async def test_get_yahoo_session_crumb_exception_returns_none():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=ConnectionError("network down"))
    crumb = await get_yahoo_session_crumb(client)
    assert crumb is None


# ---------------------------------------------------------------------------
# fetch_quote_summary_module — generic quoteSummary fetch/parse (etf_holdings.py,
# equity_premium.py each build their own module-specific wrapper on top of this)
# ---------------------------------------------------------------------------

def _parse_ok(payload: dict):
    return payload.get("value")


@pytest.mark.asyncio
async def test_fetch_quote_summary_module_success():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, {"value": 42}))
    ticker, parsed, error = await fetch_quote_summary_module(
        client, "crumb123", "TEST", "someModule", _parse_ok, "empty",
    )
    assert ticker == "TEST"
    assert parsed == 42
    assert error is None


@pytest.mark.asyncio
async def test_fetch_quote_summary_module_http_error():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(500))
    _, parsed, error = await fetch_quote_summary_module(
        client, "crumb", "BAD", "someModule", _parse_ok, "empty",
    )
    assert parsed is None
    assert "500" in error


@pytest.mark.asyncio
async def test_fetch_quote_summary_module_empty_parse_result():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_FakeResponse(200, {}))
    _, parsed, error = await fetch_quote_summary_module(
        client, "crumb", "EMPTY", "someModule", _parse_ok, "no data",
    )
    assert parsed is None
    assert error == "no data"


@pytest.mark.asyncio
async def test_fetch_quote_summary_module_exception():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=ConnectionError("timeout"))
    _, parsed, error = await fetch_quote_summary_module(
        client, "crumb", "CRASH", "someModule", _parse_ok, "empty",
    )
    assert parsed is None
    assert error is not None
