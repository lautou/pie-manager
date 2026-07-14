"""
Macro indicators daily refresh — runs once a day via Celery Beat.

Strategy:
  - Same unauthenticated query1.finance.yahoo.com/v8/finance/chart/{ticker} endpoint as
    app/tasks/prices.py (no crumb/session needed, unlike app/tasks/etf_holdings.py).
  - Full daily history is fetched every run (not just "today"), using explicit period1/period2
    Unix timestamps with interval=1d. This is deliberate: requesting range=max&interval=1d
    gets silently downsampled by Yahoo to ~monthly granularity for long spans (confirmed:
    only ~168 points over 42 years of ^GSPC), while an explicit period1/period2 window
    returns true, uncapped daily data. Refetching the full history every run is cheap
    (~6500 rows/series) and self-heals any gap or Yahoo revision — no separate
    backfill-vs-daily-delta logic needed.
  - Result written to Redis key "pie:macro:status" for consistency with prices.py/etf_holdings.py.
"""

import asyncio
import json
from datetime import date, datetime, timezone

import httpx

from app.tasks.celery_app import celery_app
from app.services.macro_indicators_service import (
    DEFAULT_TICKERS,
    get_macro_settings,
    list_regions,
    replace_series_prices,
)

SYNC_STATUS_KEY = "pie:macro:status"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; portfolio-tracker/1.0)",
    "Accept": "application/json",
}
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]  # seconds between retries on 429

# Comfortably before all 4 series' real Yahoo inception (^SPXEW 2006, ^TNX 1985,
# CL=F/GC=F 2000) — no need for per-ticker introspection of firstTradeDate.
HISTORY_FLOOR = date(2000, 1, 1)


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
# Per-series fetch
# ---------------------------------------------------------------------------

async def _fetch_series_history(
    client: httpx.AsyncClient, ticker: str, period1: int, period2: int
) -> tuple[str, list[tuple[date, float]] | None, str | None]:
    """
    Returns (ticker, points_or_None, error_or_None). points is a full [(date, value), ...]
    history for the requested window. Retries up to MAX_RETRIES times on 429.
    """
    url = YAHOO_CHART_URL.format(ticker=ticker)
    params = {"period1": period1, "period2": period2, "interval": "1d"}
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(url, params=params, headers=YAHOO_HEADERS, timeout=15.0)
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
            timestamps = results[0].get("timestamp") or []
            closes = results[0].get("indicators", {}).get("quote", [{}])[0].get("close") or []
            points = [
                (datetime.fromtimestamp(ts, tz=timezone.utc).date(), close)
                for ts, close in zip(timestamps, closes)
                if close is not None
            ]
            if not points:
                return ticker, None, "no usable data points"
            return ticker, points, None
        except Exception as exc:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BACKOFF[attempt])
                continue
            return ticker, None, str(exc)[:120]
    return ticker, None, "max retries exceeded"


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
            *[_fetch_series_history(client, ticker, period1, period2) for ticker in tickers_by_series.values()]
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


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(name="app.tasks.macro_indicators.refresh_macro_indicators")
def refresh_macro_indicators():
    """
    Main scheduled task: refresh every region's equity/bond series plus oil/gold once a day.
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
        result = asyncio.run(_run_macro_indicators_refresh())
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
