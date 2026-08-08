"""
Live price refresh — runs every 15 min via Celery Beat.

Strategy:
  - Parallel HTTP calls to query1.finance.yahoo.com/v8/finance/chart/{ticker}
  - regularMarketPrice → real-time quote during market hours, last close otherwise
  - Exponential backoff on 429; individual ticker failures recorded in Redis
  - Result written to Redis key "pie:sync:status" for frontend display
"""

import asyncio
from datetime import datetime, date, timezone

import httpx

from app.tasks.celery_app import celery_app
from app.tasks.sync_status import get_redis, write_status
from app.tasks.yahoo_fetch import fetch_yahoo_chart
from app.services.price_service import get_active_tickers

SYNC_STATUS_KEY = "pie:sync:status"
SYNC_STATUS_TTL = 3600  # expire after 1 h


# ---------------------------------------------------------------------------
# Core async fetch
# ---------------------------------------------------------------------------

async def _fetch_ticker(client: httpx.AsyncClient, ticker: str) -> tuple[str, float | None, str | None]:
    """Returns (ticker, price_or_None, error_or_None) — thin parsing wrapper around the
    shared fetch_yahoo_chart (retry/backoff is tested directly there, see test_yahoo_fetch.py)."""
    ticker, result, error = await fetch_yahoo_chart(client, ticker, timeout=10.0)
    if result is None:
        return ticker, None, error
    price = result.get("meta", {}).get("regularMarketPrice")
    if price is None:
        return ticker, None, "regularMarketPrice missing"
    return ticker, round(float(price), 4), None


async def _run_price_refresh() -> dict:
    """
    Fetches all active tickers in parallel, writes results to DB.
    Returns a sync-status dict.
    """
    from sqlalchemy import text
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    started_at = datetime.now(timezone.utc).isoformat()
    today = date.today()

    eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)

    try:
        async with Session() as db:
            tickers_currencies = await get_active_tickers(db)
    finally:
        await eng.dispose()

    # Deduplicate, skip cash
    seen: set[str] = set()
    to_fetch: list[tuple[str, str]] = []
    for ticker, currency in tickers_currencies:
        if ticker == "LIQUIDITE.EURO" or ticker in seen:
            continue
        seen.add(ticker)
        to_fetch.append((ticker, currency))

    if not to_fetch:
        return {
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "total_tickers": 0,
            "succeeded": 0,
            "failed_tickers": [],
        }

    # Parallel fetch — all tickers at once (like UrlFetchApp.fetchAll)
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_ticker(client, ticker) for ticker, _ in to_fetch]
        results = await asyncio.gather(*tasks)

    # Build currency lookup
    currency_map = {ticker: currency for ticker, currency in to_fetch}

    # Write successful prices to DB
    eng2 = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session2 = async_sessionmaker(eng2, class_=AsyncSession, expire_on_commit=False)
    succeeded: list[str] = []
    failed: list[str] = []

    try:
        async with Session2() as db:
            # Fetch previous prices in one query for glitch detection
            tickers_list = [t for t, _ in to_fetch]
            prev_rows = await db.execute(text("""
                SELECT DISTINCT ON (ticker) ticker, price
                FROM asset_prices
                WHERE ticker = ANY(:tickers) AND date < :today
                ORDER BY ticker, date DESC
            """), {"tickers": tickers_list, "today": today})
            prev_prices: dict[str, float] = {row.ticker: row.price for row in prev_rows}

            for ticker, price, error in results:
                if price is not None:
                    prev = prev_prices.get(ticker)
                    # Glitch guard: reject if new price deviates by more than ×10
                    # from the previous day (catches Yahoo returning ×100 scale errors).
                    if prev and prev > 0 and not (0.1 <= price / prev <= 10.0):
                        failed.append(f"{ticker}(glitch:{price:.4f}vs{prev:.4f})")
                        continue
                    await db.execute(text("""
                        INSERT INTO asset_prices (ticker, date, price, currency, source)
                        VALUES (:ticker, :date, :price, :currency, 'yfinance')
                        ON CONFLICT ON CONSTRAINT uq_asset_price_ticker_date
                        DO UPDATE SET price = EXCLUDED.price, source = EXCLUDED.source
                    """), {
                        "ticker": ticker,
                        "date": today,
                        "price": price,
                        "currency": currency_map.get(ticker, "EUR"),
                    })
                    succeeded.append(ticker)
                else:
                    failed.append(ticker)
            await db.commit()
    finally:
        await eng2.dispose()

    total = len(to_fetch)
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
# Celery tasks
# ---------------------------------------------------------------------------

@celery_app.task(name="app.tasks.prices.refresh_prices_live")
def refresh_prices_live():
    """
    Main scheduled task: fetch live prices every 15 min.
    Writes sync status to Redis for frontend display.
    """
    r = get_redis()
    write_status(r, SYNC_STATUS_KEY, {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "status": "running",
        "total_tickers": 0,
        "succeeded": 0,
        "failed_tickers": [],
    }, ttl_seconds=SYNC_STATUS_TTL)

    try:
        result = asyncio.run(_run_price_refresh())
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

    write_status(r, SYNC_STATUS_KEY, result, ttl_seconds=SYNC_STATUS_TTL)
    return result


@celery_app.task(name="app.tasks.prices.fetch_all_prices")
def fetch_all_prices():
    """Alias — old daily cron entry points here for backward-compat."""
    return refresh_prices_live()
