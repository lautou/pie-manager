# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Shared Yahoo Finance fetch logic for the two distinct Yahoo mechanisms every task in this app
relies on:
  - The plain chart endpoint (query1.finance.yahoo.com/v8/finance/chart/{ticker}) — used by
    prices.py's single latest quote and macro_indicators.py's/country_performance.py's/
    sector_performance.py's full daily history. No auth needed.
  - The crumb-authenticated quoteSummary endpoint (query2.finance.yahoo.com/v10/finance/
    quoteSummary/{ticker}) — used by etf_holdings.py and equity_premium.py for fundamentals
    (topHoldings, assetProfile, summaryDetail) that the chart endpoint never exposes. Requires
    a warm-up cookie + CSRF crumb token, fetched fresh per run via get_yahoo_session_crumb
    below — a genuinely different auth/session mechanism from the chart endpoint's plain GETs,
    but now shared here since two independent tasks need it.

The chart-endpoint retry/backoff/429 scaffold below was extracted from what used to be
near-identical private copies in each task module; the crumb/quoteSummary helpers were
extracted later from etf_holdings.py (their original, sole owner) once equity_premium.py
needed the identical mechanism for a second, unrelated universe.
"""

import asyncio
from datetime import date, datetime, timezone
from typing import Callable, Optional, TypeVar

import httpx

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; portfolio-tracker/1.0)",
    "Accept": "application/json",
}
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]  # seconds between retries on 429

T = TypeVar("T")

YAHOO_QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
YAHOO_CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
YAHOO_WARMUP_URL = "https://fc.yahoo.com"
# Any real, always-listed ticker works here — this call only exists to collect the session
# cookies finance.yahoo.com sets before the crumb endpoint will issue a token.
YAHOO_WARMUP_QUOTE_URL = "https://finance.yahoo.com/quote/AAPL"
YAHOO_CRUMB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; portfolio-tracker/1.0)",
    # The crumb endpoint (query2.finance.yahoo.com/v1/test/getcrumb) returns 406 Not Acceptable
    # for "Accept: application/json" — confirmed empirically the User-Agent is not the issue,
    # only this header is. quoteSummary itself returns JSON regardless of Accept, so "*/*"
    # works for every request the crumb-authenticated helpers below make. Distinct from this
    # module's own YAHOO_HEADERS above (chart endpoint, "application/json") — they must not
    # merge into one constant.
    "Accept": "*/*",
}


# ---------------------------------------------------------------------------
# Crumb-authenticated quoteSummary endpoint (etf_holdings.py, equity_premium.py)
# ---------------------------------------------------------------------------

async def get_yahoo_session_crumb(client: httpx.AsyncClient) -> Optional[str]:
    """
    Acquires the session cookie + CSRF crumb required by the quoteSummary endpoint.
    Returns None (never raises) if any step fails — callers must abort the whole task.
    """
    try:
        await client.get(YAHOO_WARMUP_URL, headers=YAHOO_CRUMB_HEADERS, timeout=10.0)
        await client.get(YAHOO_WARMUP_QUOTE_URL, headers=YAHOO_CRUMB_HEADERS, timeout=10.0)
        resp = await client.get(YAHOO_CRUMB_URL, headers=YAHOO_CRUMB_HEADERS, timeout=10.0)
        if resp.status_code != 200:
            return None
        crumb = resp.text.strip()
        return crumb or None
    except Exception:
        return None


async def fetch_quote_summary_module(
    client: httpx.AsyncClient, crumb: str, ticker: str,
    module: str, parse: Callable[[dict], Optional[T]], empty_error: str,
) -> tuple[str, Optional[T], Optional[str]]:
    """
    Shared fetch/parse/error-handling shape for any quoteSummary module (topHoldings/
    assetProfile for etf_holdings.py, summaryDetail for equity_premium.py) — same request
    pattern, only the module name, parser, and "nothing came back" message differ.

    Returns (ticker, parsed_or_None, error_or_None).
    """
    try:
        resp = await client.get(
            YAHOO_QUOTE_SUMMARY_URL.format(ticker=ticker),
            params={"modules": module, "crumb": crumb},
            headers=YAHOO_CRUMB_HEADERS,
            timeout=10.0,
        )
        if resp.status_code != 200:
            return ticker, None, f"HTTP {resp.status_code}"
        parsed = parse(resp.json())
        if parsed is None:
            return ticker, None, empty_error
        return ticker, parsed, None
    except Exception as exc:
        return ticker, None, str(exc)[:120]


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
