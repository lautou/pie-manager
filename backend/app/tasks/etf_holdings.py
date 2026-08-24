# SPDX-License-Identifier: AGPL-3.0-or-later
"""
ETF look-through holdings refresh — runs weekly via PgQueuer (see app/tasks/pgq_app.py).

Strategy:
  - Unlike the price-sync task's chart endpoint, ETF composition requires the unofficial
    crumb-authenticated quoteSummary session — see app/tasks/yahoo_fetch.py's
    get_yahoo_session_crumb/fetch_quote_summary_module (shared with equity_premium.py, the
    other quoteSummary-based task). If crumb acquisition fails, the whole task aborts
    cleanly — previously fetched data stays in place, only holdings_updated_at fails to
    advance.
  - ETF/SICAV-FCP products: module=topHoldings gives top-10 holdings, sector weightings,
    and (for bond funds) duration/maturity — the latter never surfaced in Yahoo's own UI.
  - Direct-stock products (instrument_type='Action') in a pool that also holds an ETF:
    module=assetProfile gives sectorKey, written as a synthetic 100%-self holding/sector
    row so pool-level look-through aggregation never special-cases "ETF vs direct stock".
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.services.etf_holdings_service import (
    get_etf_tickers,
    get_direct_stock_tickers_in_etf_pools,
    save_etf_fetch_result,
)
from app.tasks.yahoo_fetch import fetch_quote_summary_module, get_yahoo_session_crumb


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

async def _fetch_top_holdings(
    client: httpx.AsyncClient, crumb: str, ticker: str
) -> tuple[str, Optional[dict], Optional[str]]:
    return await fetch_quote_summary_module(
        client, crumb, ticker, "topHoldings", _parse_top_holdings, "no fundamentals data",
    )


async def _fetch_asset_profile_sector(
    client: httpx.AsyncClient, crumb: str, ticker: str
) -> tuple[str, Optional[str], Optional[str]]:
    return await fetch_quote_summary_module(
        client, crumb, ticker, "assetProfile", _parse_asset_profile_sector, "sectorKey missing",
    )


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
        crumb = await get_yahoo_session_crumb(client)
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
