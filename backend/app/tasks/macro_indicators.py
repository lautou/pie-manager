# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Macro indicators daily refresh — runs once a day via PgQueuer (see app/tasks/pgq_app.py).

Strategy:
  - Same unauthenticated query1.finance.yahoo.com/v8/finance/chart/{ticker} endpoint as
    app/tasks/prices.py (no crumb/session needed, unlike app/tasks/etf_holdings.py) — fetch
    logic lives in the shared app/tasks/yahoo_fetch.py.
  - Full daily history is fetched every run (not just "today"), using explicit period1/period2
    Unix timestamps with interval=1d. This is deliberate: requesting range=max&interval=1d
    gets silently downsampled by Yahoo to ~monthly granularity for long spans (confirmed:
    only ~168 points over 42 years of ^GSPC), while an explicit period1/period2 window
    returns true, uncapped daily data. Refetching the full history every run is cheap
    (~6500 rows/series) and self-heals any gap or Yahoo revision — no separate
    backfill-vs-daily-delta logic needed.
"""

import asyncio
from datetime import date, datetime, timezone

import httpx

from app.tasks.yahoo_fetch import fetch_yahoo_history
from app.services.macro_indicators_service import (
    DEFAULT_TICKERS,
    get_macro_settings,
    list_regions,
)
from app.services.macro_series_price_service import replace_series_prices

# Comfortably before all 4 series' real Yahoo inception (^SPXEW 2006, ^TNX 1985,
# CL=F/GC=F 2000) — no need for per-ticker introspection of firstTradeDate.
HISTORY_FLOOR = date(2000, 1, 1)


# ---------------------------------------------------------------------------
# Core async refresh
# ---------------------------------------------------------------------------

async def _run_macro_indicators_refresh() -> dict:
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    started_at = datetime.now(timezone.utc).isoformat()
    period1 = int(datetime(HISTORY_FLOOR.year, HISTORY_FLOOR.month, HISTORY_FLOOR.day, tzinfo=timezone.utc).timestamp())
    period2 = int(datetime.now(timezone.utc).timestamp())

    eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            macro_settings = await get_macro_settings(db)
            regions = await list_regions(db)
    finally:
        await eng.dispose()

    tickers_by_series = {series: macro_settings[series] for series in DEFAULT_TICKERS}
    for region in regions:
        tickers_by_series[f"{region.code}_equity"] = region.equity_ticker
        tickers_by_series[f"{region.code}_bond"] = region.bond_ticker

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[fetch_yahoo_history(client, ticker, period1, period2) for ticker in tickers_by_series.values()]
        )

    series_by_ticker = {ticker: series for series, ticker in tickers_by_series.items()}
    succeeded: list[str] = []
    failed: list[str] = []

    eng2 = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session2 = async_sessionmaker(eng2, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session2() as db:
            for ticker, points, error in results:
                series = series_by_ticker[ticker]
                if points is None:
                    failed.append(f"{series}({ticker}):{error}")
                    continue
                await replace_series_prices(db, series, points)
                succeeded.append(series)
            await db.commit()
    finally:
        await eng2.dispose()

    total = len(tickers_by_series)
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
