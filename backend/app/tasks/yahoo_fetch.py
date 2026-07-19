"""
Shared Yahoo Finance chart-endpoint fetch-with-retry logic, used by every task that reads
query1.finance.yahoo.com/v8/finance/chart/{ticker} (prices.py's single latest quote,
macro_indicators.py's/country_performance.py's full daily history).

Extracted from what used to be near-identical private copies in each task module — the
retry/backoff/429 scaffold was byte-for-byte duplicated; only the request params, timeout,
and response parsing differed.

etf_holdings.py is NOT built on this module — it hits a different, crumb-authenticated
Yahoo endpoint (quoteSummary) with its own session/parsing logic.
"""

import asyncio
from datetime import date, datetime, timezone

import httpx

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; portfolio-tracker/1.0)",
    "Accept": "application/json",
}
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]  # seconds between retries on 429


async def fetch_yahoo_chart(
    client: httpx.AsyncClient, ticker: str, *, params: dict | None = None, timeout: float = 15.0,
) -> tuple[str, dict | None, str | None]:
    """
    Generic retry/backoff wrapper around Yahoo's chart endpoint. Returns
    (ticker, result[0]_or_None, error_or_None) — callers parse the raw `result[0]` dict
    (meta / timestamp / indicators.quote[0].close) into whatever shape they need.
    """
    url = YAHOO_CHART_URL.format(ticker=ticker)
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url, params=params, headers=YAHOO_HEADERS, timeout=timeout)
            if resp.status_code == 429:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BACKOFF[attempt])
                    continue
                return ticker, None, "429 rate-limited after retries"
            if resp.status_code != 200:
                return ticker, None, f"HTTP {resp.status_code}"
            data = resp.json()
            results = (data.get("chart") or {}).get("result") or []
            if not results:
                return ticker, None, "no chart data"
            return ticker, results[0], None
        except Exception as exc:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BACKOFF[attempt])
                continue
            return ticker, None, str(exc)[:120]
    return ticker, None, "max retries exceeded"


async def fetch_yahoo_history(
    client: httpx.AsyncClient, ticker: str, period1: int, period2: int,
) -> tuple[str, list[tuple[date, float]] | None, str | None]:
    """
    Full daily [(date, close), ...] history for the requested window — shared by
    macro_indicators.py and country_performance.py (both need more than one point;
    prices.py only needs the single latest quote, see its own thin _fetch_ticker wrapper).
    """
    ticker, result, error = await fetch_yahoo_chart(
        client, ticker, params={"period1": period1, "period2": period2, "interval": "1d"}, timeout=15.0,
    )
    if result is None:
        return ticker, None, error
    timestamps = result.get("timestamp") or []
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close") or []
    points = [
        (datetime.fromtimestamp(ts, tz=timezone.utc).date(), close)
        for ts, close in zip(timestamps, closes)
        if close is not None
    ]
    if not points:
        return ticker, None, "no usable data points"
    return ticker, points, None
