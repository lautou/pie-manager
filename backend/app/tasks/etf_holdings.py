"""
ETF look-through holdings refresh — runs weekly via Celery Beat.

Strategy:
  - Unlike the price-sync task's chart endpoint, ETF composition requires an unofficial
    session: a warm-up cookie (fc.yahoo.com), then a CSRF "crumb" token
    (query2.finance.yahoo.com/v1/test/getcrumb), passed as a query param on every
    quoteSummary call. If crumb acquisition fails, the whole task aborts cleanly —
    previously fetched data stays in place, only holdings_updated_at fails to advance.
  - ETF/SICAV-FCP products: module=topHoldings gives top-10 holdings, sector weightings,
    and (for bond funds) duration/maturity — the latter never surfaced in Yahoo's own UI.
  - Direct-stock products (instrument_type='Action') in a pool that also holds an ETF:
    module=assetProfile gives sectorKey, written as a synthetic 100%-self holding/sector
    row so pool-level look-through aggregation never special-cases "ETF vs direct stock".
  - Result written to Redis key "pie:etf_holdings:status" for consistency with prices.py.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Callable, Optional, TypeVar

import httpx

from app.tasks.celery_app import celery_app
from app.services.etf_holdings_service import (
    get_etf_tickers,
    get_direct_stock_tickers_in_etf_pools,
    save_etf_fetch_result,
)

T = TypeVar("T")

SYNC_STATUS_KEY = "pie:etf_holdings:status"
YAHOO_QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
YAHOO_CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
YAHOO_WARMUP_URL = "https://fc.yahoo.com"
# Any real, always-listed ticker works here — this call only exists to collect the session
# cookies finance.yahoo.com sets before the crumb endpoint will issue a token.
YAHOO_WARMUP_QUOTE_URL = "https://finance.yahoo.com/quote/AAPL"
YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; portfolio-tracker/1.0)",
    "Accept": "application/json",
}


# ---------------------------------------------------------------------------
# Redis helpers (mirrors app/tasks/prices.py)
# ---------------------------------------------------------------------------

def _get_redis():
    import redis as redis_lib
    from app.core.config import settings
    return redis_lib.Redis.from_url(settings.celery_broker_url, decode_responses=True)


def _write_status(r, status: dict):
    r.set(SYNC_STATUS_KEY, json.dumps(status), ex=3600 * 24 * 7)  # expire after 1 week


# ---------------------------------------------------------------------------
# Yahoo session (cookie + crumb)
# ---------------------------------------------------------------------------

async def _get_yahoo_session_crumb(client: httpx.AsyncClient) -> Optional[str]:
    """
    Acquires the session cookie + CSRF crumb required by the quoteSummary endpoint.
    Returns None (never raises) if any step fails — callers must abort the whole task.
    """
    try:
        await client.get(YAHOO_WARMUP_URL, headers=YAHOO_HEADERS, timeout=10.0)
        await client.get(YAHOO_WARMUP_QUOTE_URL, headers=YAHOO_HEADERS, timeout=10.0)
        resp = await client.get(YAHOO_CRUMB_URL, headers=YAHOO_HEADERS, timeout=10.0)
        if resp.status_code != 200:
            return None
        crumb = resp.text.strip()
        return crumb or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_top_holdings(payload: dict) -> Optional[dict]:
    """Returns {holdings, sector_weightings, bond_duration, bond_maturity} or None."""
    results = (payload.get("quoteSummary") or {}).get("result") or []
    if not results:
        return None
    top_holdings = results[0].get("topHoldings") or {}

    holdings = [
        {"ticker": h["symbol"], "name": h["holdingName"], "weight_pct": h["holdingPercent"]["raw"]}
        for h in top_holdings.get("holdings", [])
    ]
    sector_weightings = {
        sector: value["raw"]
        for entry in top_holdings.get("sectorWeightings", [])
        for sector, value in entry.items()
        if value.get("raw")  # drop exact-zero sectors — most funds report 7-9 of these
    }
    bond_holdings = top_holdings.get("bondHoldings") or {}
    return {
        "holdings": holdings,
        "sector_weightings": sector_weightings,
        "bond_duration": bond_holdings.get("duration", {}).get("raw"),
        "bond_maturity": bond_holdings.get("maturity", {}).get("raw"),
    }


def _parse_asset_profile_sector(payload: dict) -> Optional[str]:
    """
    Returns the sectorKey normalized to match topHoldings.sectorWeightings' format, or None.

    assetProfile.sectorKey uses hyphens for multi-word sectors (e.g. "consumer-cyclical",
    confirmed on real stocks: MC.PA, AI.PA) while topHoldings.sectorWeightings uses
    underscores (e.g. "consumer_cyclical") for the exact same sector — without this
    normalization, a direct stock's sector would never merge with an ETF's sector
    weightings for any multi-word sector, only single-word ones like "energy".
    """
    results = (payload.get("quoteSummary") or {}).get("result") or []
    if not results:
        return None
    sector_key = (results[0].get("assetProfile") or {}).get("sectorKey")
    return sector_key.replace("-", "_") if sector_key else sector_key


# ---------------------------------------------------------------------------
# Per-ticker fetch
# ---------------------------------------------------------------------------

async def _fetch_module(
    client: httpx.AsyncClient, crumb: str, ticker: str,
    module: str, parse: Callable[[dict], Optional[T]], empty_error: str,
) -> tuple[str, Optional[T], Optional[str]]:
    """
    Shared fetch/parse/error-handling shape for both quoteSummary modules used by this task
    (topHoldings for funds, assetProfile for a direct stock's sector) — same request pattern,
    only the module name, parser, and "nothing came back" message differ.

    Returns (ticker, parsed_or_None, error_or_None).
    """
    try:
        resp = await client.get(
            YAHOO_QUOTE_SUMMARY_URL.format(ticker=ticker),
            params={"modules": module, "crumb": crumb},
            headers=YAHOO_HEADERS,
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


async def _fetch_top_holdings(
    client: httpx.AsyncClient, crumb: str, ticker: str
) -> tuple[str, Optional[dict], Optional[str]]:
    return await _fetch_module(client, crumb, ticker, "topHoldings", _parse_top_holdings, "no fundamentals data")


async def _fetch_asset_profile_sector(
    client: httpx.AsyncClient, crumb: str, ticker: str
) -> tuple[str, Optional[str], Optional[str]]:
    return await _fetch_module(client, crumb, ticker, "assetProfile", _parse_asset_profile_sector, "sectorKey missing")


# ---------------------------------------------------------------------------
# Core async refresh
# ---------------------------------------------------------------------------

async def _run_etf_holdings_refresh() -> dict:
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    started_at = datetime.now(timezone.utc).isoformat()
    fetched_at = datetime.now(timezone.utc)

    eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            etf_tickers = await get_etf_tickers(db)
            direct_stocks = await get_direct_stock_tickers_in_etf_pools(db)
    finally:
        await eng.dispose()

    total = len(etf_tickers) + len(direct_stocks)
    if total == 0:
        return {
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "total_tickers": 0,
            "succeeded": 0,
            "failed_tickers": [],
        }

    async with httpx.AsyncClient(follow_redirects=True) as client:
        crumb = await _get_yahoo_session_crumb(client)
        if crumb is None:
            return {
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "status": "failed",
                "total_tickers": total,
                "succeeded": 0,
                "failed_tickers": [],
                "error": "could not acquire Yahoo session crumb",
            }

        etf_results = await asyncio.gather(
            *[_fetch_top_holdings(client, crumb, t) for t in etf_tickers]
        )
        stock_results = await asyncio.gather(
            *[_fetch_asset_profile_sector(client, crumb, t) for t, _ in direct_stocks]
        )

    stock_names = dict(direct_stocks)
    succeeded: list[str] = []
    failed: list[str] = []

    eng2 = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session2 = async_sessionmaker(eng2, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session2() as db:
            for ticker, parsed, error in etf_results:
                if parsed is None:
                    failed.append(f"{ticker}({error})")
                    continue
                await save_etf_fetch_result(
                    db, ticker,
                    holdings=parsed["holdings"],
                    sector_weightings=parsed["sector_weightings"],
                    fetched_at=fetched_at,
                    bond_duration=parsed["bond_duration"],
                    bond_maturity=parsed["bond_maturity"],
                )
                succeeded.append(ticker)

            for ticker, sector_key, error in stock_results:
                if sector_key is None:
                    failed.append(f"{ticker}({error})")
                    continue
                await save_etf_fetch_result(
                    db, ticker,
                    holdings=[{"ticker": ticker, "name": stock_names[ticker], "weight_pct": 1.0}],
                    sector_weightings={sector_key: 1.0},
                    fetched_at=fetched_at,
                )
                succeeded.append(ticker)

            await db.commit()
    finally:
        await eng2.dispose()

    n_ok = len(succeeded)
    status = "success" if not failed else ("partial" if n_ok > 0 else "failed")

    return {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "total_tickers": total,
        "succeeded": n_ok,
        "failed_tickers": failed,
    }


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(name="app.tasks.etf_holdings.refresh_etf_holdings")
def refresh_etf_holdings():
    """
    Main scheduled task: refresh ETF top-10 holdings/sector weightings weekly.
    Writes sync status to Redis, mirroring app.tasks.prices.refresh_prices_live.
    """
    r = _get_redis()
    _write_status(r, {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "status": "running",
        "total_tickers": 0,
        "succeeded": 0,
        "failed_tickers": [],
    })

    try:
        result = asyncio.run(_run_etf_holdings_refresh())
    except Exception as exc:
        result = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
            "total_tickers": 0,
            "succeeded": 0,
            "failed_tickers": [],
            "error": str(exc)[:200],
        }

    _write_status(r, result)
    return result
