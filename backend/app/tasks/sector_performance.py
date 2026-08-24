# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Sector/commodity performance daily refresh — runs once a day via PgQueuer (see
app/tasks/pgq_app.py). Structurally identical to app/tasks/country_performance.py: same
shared Yahoo chart fetch (app/tasks/yahoo_fetch.py), same ~1-year HISTORY_WINDOW_DAYS
rationale, same per-distinct-non-EUR-currency FX dedup.

Deliberately fetches its own sector_{code}_equity series for every configured row,
including "or"/"petrole" (GC=F/CL=F) — even though app/tasks/macro_indicators.py already
fetches those same tickers into the unrelated "gold"/"oil" macro_series_prices series for
the growth/inflation charts. Not special-cased/reused on purpose: keeping this CRUD entity
fully generic and symmetric with country_performance was judged more valuable than avoiding
one small redundant Yahoo fetch.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app.tasks.yahoo_fetch import fetch_yahoo_history
from app.services.sector_performance_service import list_sector_configs
from app.services.macro_series_price_service import replace_series_prices

HISTORY_WINDOW_DAYS = 450  # trailing 1 year + buffer for weekends/holidays/retry lag


# ---------------------------------------------------------------------------
# Core async refresh
# ---------------------------------------------------------------------------

async def _run_sector_performance_refresh() -> dict:
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    started_at = datetime.now(timezone.utc).isoformat()
    now = datetime.now(timezone.utc)
    period1 = int((now - timedelta(days=HISTORY_WINDOW_DAYS)).timestamp())
    period2 = int(now.timestamp())

    eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            configs = await list_sector_configs(db)
    finally:
        await eng.dispose()

    tickers_by_series = {f"sector_{c.code}_equity": c.index_ticker for c in configs}
    fx_currencies = {c.currency for c in configs if c.currency != "EUR"}
    for currency in fx_currencies:
        tickers_by_series[f"fx_{currency.lower()}"] = f"{currency}EUR=X"

    if not tickers_by_series:
        return {
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "total_tickers": 0,
            "succeeded": 0,
            "failed_tickers": [],
        }

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
