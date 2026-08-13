"""
Country stock-market performance daily refresh — runs once a day via Celery Beat.

Strategy:
  - Same shared Yahoo chart fetch as macro_indicators.py (app/tasks/yahoo_fetch.py).
  - Only needs a trailing ~1-year window (not full history since 2000, unlike
    macro_indicators.py's 7-year moving average) since the ranking only ever compares "now"
    vs "~1 year ago" — see country_performance_service.py's ASOF_TOLERANCE_DAYS.
  - Fetches each country's index series plus one shared FX-to-EUR series per distinct
    non-EUR currency (deduped — two countries sharing a currency fetch it once), using the
    same f"{CCY}EUR=X" convention already established for portfolio forex positions
    (see CLAUDE.md's "Transaction conventions" — Cash instrument_type).
  - Result written to Redis key "pie:country_perf:status" for consistency with the other tasks.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app.tasks import job_runs
from app.tasks.celery_app import celery_app
from app.tasks.sync_status import get_redis, write_status
from app.tasks.yahoo_fetch import fetch_yahoo_history
from app.services.country_performance_service import list_country_configs
from app.services.macro_series_price_service import replace_series_prices

SYNC_STATUS_KEY = "pie:country_perf:status"
SYNC_STATUS_TTL = 3600 * 24 * 7  # expire after 1 week

HISTORY_WINDOW_DAYS = 450  # trailing 1 year + buffer for weekends/holidays/retry lag


# ---------------------------------------------------------------------------
# Core async refresh
# ---------------------------------------------------------------------------

async def _run_country_performance_refresh() -> dict:
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
            configs = await list_country_configs(db)
    finally:
        await eng.dispose()

    tickers_by_series = {f"country_{c.code}_equity": c.index_ticker for c in configs}
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


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(name="app.tasks.country_performance.refresh_country_performance")
def refresh_country_performance():
    """
    Main scheduled task: refresh every configured country's index series plus each
    distinct non-EUR currency's FX-to-EUR series once a day.
    Writes sync status to Redis, mirroring app.tasks.prices.refresh_prices_live.
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
    # job_runs dual-write (issue #66 step 1) — see app/tasks/job_runs.py. "schedule" is a
    # best-effort default here since Celery doesn't tell a task how it was triggered; a later
    # step threads the real trigger through once routers actually read from job_runs.
    run_id = job_runs.run_tracked(job_runs.start_run("refresh_country_performance", trigger="schedule"))

    try:
        result = asyncio.run(_run_country_performance_refresh())
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
    job_runs.run_tracked(job_runs.finish_run(
        run_id,
        status=result["status"],
        total_steps=result.get("total_tickers", 0),
        succeeded_steps=result.get("succeeded", 0),
        failed_items=result.get("failed_tickers", []),
        error=result.get("error"),
    ))
    return result
