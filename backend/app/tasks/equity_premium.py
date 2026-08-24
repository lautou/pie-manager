# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Equity risk premium daily refresh — runs once a day via PgQueuer (see app/tasks/pgq_app.py).

Structurally closer to etf_holdings.py (crumb-authenticated quoteSummary) than to
country_performance.py/sector_performance.py (plain chart endpoint + fetch_yahoo_history):
a country equity ETF's trailingPE and a country bond ETF's yield are only exposed via
quoteSummary's summaryDetail module, never the chart endpoint. Uses the shared crumb session
mechanism from app/tasks/yahoo_fetch.py (get_yahoo_session_crumb/fetch_quote_summary_module),
same as etf_holdings.py.

Stores 1/trailingPE (earnings yield, a decimal ratio) and the raw decimal bond yield —
never the raw P/E — so equity_premium_service.py's compute step is a plain subtraction with
no division at read time. No FX anywhere: both legs are same-country, same-currency,
dimensionless yields.

quoteSummary's trailingPE/yield fields carry no per-value date the way chart-endpoint history
does (they're "current" snapshot fields, not dated history points) — every successful fetch
writes a single point at date.today(), relying on compute_equity_premiums' asof() tolerance
window to absorb a missed day, exactly like every other series in this app.

Per-leg graceful failure, not per-country: if a country's equity leg succeeds but its bond leg
fails (a transient Yahoo hiccup, or one of the known-gap countries if ever added), the equity
series is still written — compute_equity_premiums excludes that country at read time based on
what's actually in the DB, so a leg that starts working again (or a gap that Yahoo eventually
fills) self-heals with zero code change.
"""

import asyncio
from datetime import date, datetime, timezone
from typing import Optional

import httpx

from app.services.equity_premium_service import list_premium_configs
from app.services.macro_series_price_service import replace_series_prices
from app.tasks.yahoo_fetch import fetch_quote_summary_module, get_yahoo_session_crumb


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_trailing_pe_yield(payload: dict) -> Optional[float]:
    """Returns 1/trailingPE, or None if trailingPE is missing/zero/non-numeric."""
    results = (payload.get("quoteSummary") or {}).get("result") or []
    if not results:
        return None
    pe = (results[0].get("summaryDetail") or {}).get("trailingPE", {}).get("raw")
    if not pe:
        return None
    return 1.0 / pe


def _parse_bond_yield(payload: dict) -> Optional[float]:
    """Returns summaryDetail.yield as a decimal, or None if missing — this is exactly where a
    known-gap country's real fund + empty yield field would surface."""
    results = (payload.get("quoteSummary") or {}).get("result") or []
    if not results:
        return None
    return (results[0].get("summaryDetail") or {}).get("yield", {}).get("raw")


# ---------------------------------------------------------------------------
# Per-ticker fetch
# ---------------------------------------------------------------------------

async def _fetch_equity_yield(
    client: httpx.AsyncClient, crumb: str, ticker: str
) -> tuple[str, Optional[float], Optional[str]]:
    return await fetch_quote_summary_module(
        client, crumb, ticker, "summaryDetail", _parse_trailing_pe_yield, "trailingPE missing",
    )


async def _fetch_bond_yield(
    client: httpx.AsyncClient, crumb: str, ticker: str
) -> tuple[str, Optional[float], Optional[str]]:
    return await fetch_quote_summary_module(
        client, crumb, ticker, "summaryDetail", _parse_bond_yield, "yield missing",
    )


# ---------------------------------------------------------------------------
# Core async refresh
# ---------------------------------------------------------------------------

async def _run_equity_premium_refresh() -> dict:
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    started_at = datetime.now(timezone.utc).isoformat()
    today = date.today()

    eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            configs = await list_premium_configs(db)
    finally:
        await eng.dispose()

    total = len(configs) * 2
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

        equity_results = await asyncio.gather(
            *[_fetch_equity_yield(client, crumb, c.equity_ticker) for c in configs]
        )
        bond_results = await asyncio.gather(
            *[_fetch_bond_yield(client, crumb, c.bond_ticker) for c in configs]
        )

    succeeded: list[str] = []
    failed: list[str] = []

    eng2 = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session2 = async_sessionmaker(eng2, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session2() as db:
            for cfg, (ticker, value, error) in zip(configs, equity_results):
                series = f"premium_{cfg.code}_equity_yield"
                if value is None:
                    failed.append(f"{series}({ticker}):{error}")
                    continue
                await replace_series_prices(db, series, [(today, value)])
                succeeded.append(series)

            for cfg, (ticker, value, error) in zip(configs, bond_results):
                series = f"premium_{cfg.code}_bond_yield"
                if value is None:
                    failed.append(f"{series}({ticker}):{error}")
                    continue
                await replace_series_prices(db, series, [(today, value)])
                succeeded.append(series)

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
