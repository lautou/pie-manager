import asyncio
from datetime import date, timedelta

from sqlalchemy import select, func

from app.core.database import AsyncSessionLocal
from app.tasks import job_runs
from app.tasks.celery_app import celery_app
from app.services.snapshot_service import compute_daily_snapshot, compute_monthly_snapshot
from app.services.portfolio_service import get_all_portfolios


@celery_app.task(name="app.tasks.snapshots.compute_daily_snapshots_all_users")
def compute_daily_snapshots_all_users(target_date: str | None = None):
    asyncio.run(_compute_daily_snapshots_all_users(target_date))


@celery_app.task(name="app.tasks.snapshots.compute_monthly_snapshots_all_users")
def compute_monthly_snapshots_all_users(target_date: str | None = None):
    asyncio.run(_compute_monthly_snapshots_all_users(target_date))


async def _compute_daily_snapshots_all_users(target_date_str: str | None):
    snap_date = date.fromisoformat(target_date_str) if target_date_str else date.today()
    async with AsyncSessionLocal() as db:
        portfolios = await get_all_portfolios(db)
        for portfolio in portfolios:
            await compute_daily_snapshot(db, portfolio_id=portfolio.id, snap_date=snap_date)
        await db.commit()


async def _compute_monthly_snapshots_all_users(target_date_str: str | None):
    snap_date = date.fromisoformat(target_date_str) if target_date_str else date.today()
    async with AsyncSessionLocal() as db:
        portfolios = await get_all_portfolios(db)
        for portfolio in portfolios:
            await compute_monthly_snapshot(db, portfolio_id=portfolio.id, snap_date=snap_date)
        await db.commit()


@celery_app.task(name="app.tasks.snapshots.fill_missing_snapshots")
def fill_missing_snapshots():
    """Fill all missing daily snapshots from the last known snapshot to yesterday.
    Called automatically on startup and at midnight. Skips weekends."""
    from app.models.snapshot import DailySnapshot
    from app.models.price import AssetPrice
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    yesterday = date.today() - timedelta(days=1)

    def make_session():
        eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
        return async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession), eng

    async def _get_portfolios_and_gaps():
        Session, eng = make_session()
        try:
            async with Session() as db:
                portfolios = await get_all_portfolios(db)
                gaps = []
                for portfolio in portfolios:
                    last_result = await db.execute(
                        select(func.max(DailySnapshot.date))
                        .where(DailySnapshot.portfolio_id == portfolio.id)
                    )
                    last_date = last_result.scalar_one_or_none()
                    start = (last_date + timedelta(days=1)) if last_date else date(2024, 1, 1)
                    if start > yesterday:
                        continue
                    prices_result = await db.execute(
                        select(AssetPrice.date)
                        .where(
                            AssetPrice.date >= start,
                            AssetPrice.date <= yesterday,
                            func.extract('dow', AssetPrice.date).notin_([0, 6]),
                        )
                        .distinct().order_by(AssetPrice.date)
                    )
                    trading_days = [r[0] for r in prices_result.all()]
                    gaps.append((portfolio, trading_days))
                return gaps
        finally:
            await eng.dispose()

    gaps = asyncio.run(_get_portfolios_and_gaps())

    for portfolio, trading_days in gaps:
        for snap_date in trading_days:
            async def _compute(d=snap_date, p=portfolio):
                Session, eng = make_session()
                try:
                    async with Session() as db:
                        await compute_daily_snapshot(db, portfolio_id=p.id, snap_date=d)
                        await db.commit()
                finally:
                    await eng.dispose()
            try:
                asyncio.run(_compute())
            except Exception:
                pass


@celery_app.task(bind=True, name="app.tasks.snapshots.recompute_snapshots_range")
def recompute_snapshots_range(self, start_date: str, end_date: str):
    """Recompute daily snapshots for all users between start_date and end_date (inclusive)."""
    from app.models.price import AssetPrice
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.core.config import settings

    def make_session():
        """Fresh engine + session per asyncio.run() call to avoid loop binding issues."""
        eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
        return async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession), eng

    # job_runs dual-write (issue #66 step 1) — see app/tasks/job_runs.py. "on_demand" is
    # accurate today (this task has no schedule/startup trigger, only the admin endpoint).
    run_id = job_runs.run_tracked(job_runs.start_run("recompute_snapshots_range", trigger="on_demand"))

    try:
        # 1. Get trading days (exclude weekends: DOW 5=Saturday, 6=Sunday)
        async def _get_trading_days():
            from sqlalchemy import extract
            Session, eng = make_session()
            try:
                async with Session() as db:
                    result = await db.execute(
                        select(AssetPrice.date).where(
                            AssetPrice.date >= date.fromisoformat(start_date),
                            AssetPrice.date <= date.fromisoformat(end_date),
                            extract('dow', AssetPrice.date).notin_([0, 6]),  # 0=Sunday, 6=Saturday
                        ).distinct().order_by(AssetPrice.date)
                    )
                    return [r[0] for r in result.all()]
            finally:
                await eng.dispose()

        trading_days = asyncio.run(_get_trading_days())
        total = len(trading_days)

        # 2. Get portfolios list
        async def _get_portfolios():
            Session, eng = make_session()
            try:
                async with Session() as db:
                    return await get_all_portfolios(db)
            finally:
                await eng.dispose()

        portfolios_list = asyncio.run(_get_portfolios())

        # 3. Process each date — update_state called synchronously between asyncio.run() calls
        for i, snap_date in enumerate(trading_days):
            self.update_state(
                state="PROGRESS",
                meta={"current": i + 1, "total": total, "date": snap_date.isoformat()},
            )
            job_runs.run_tracked(job_runs.update_progress(run_id, i + 1, total, snap_date.isoformat()))

            async def _compute_one(d=snap_date):
                Session, eng = make_session()
                try:
                    async with Session() as db:
                        for portfolio in portfolios_list:
                            try:
                                await compute_daily_snapshot(db, portfolio_id=portfolio.id, snap_date=d)
                            except Exception:
                                pass
                        await db.commit()
                finally:
                    await eng.dispose()

            asyncio.run(_compute_one())
    except Exception as exc:
        job_runs.run_tracked(job_runs.finish_run(run_id, status="failed", error=str(exc)[:200]))
        raise

    job_runs.run_tracked(job_runs.finish_run(
        run_id, status="success", total_steps=total, succeeded_steps=total,
    ))


@celery_app.task(name="app.tasks.snapshots.refresh_prices_task")
def refresh_prices_task():
    """Refresh latest prices from yfinance for all active tickers.
    Uses the same logic as seed_prices.py which is known to work."""
    import math
    import yfinance as yf
    from datetime import date, timedelta
    from sqlalchemy import text
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    async def _run():
        from app.services.price_service import get_active_tickers
        eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
        Session = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
        updated = 0
        end = date.today()
        start = end - timedelta(days=3)

        try:
            async with Session() as db:
                tickers_currencies = await get_active_tickers(db)

            for ticker, currency in tickers_currencies:
                try:
                    data = yf.download([ticker], start=start, end=end, progress=False, auto_adjust=False)
                    if data.empty:
                        continue
                    close_col = data["Close"]
                    if hasattr(close_col, "iloc"):
                        series = close_col.dropna()
                    else:
                        series = close_col[ticker].dropna() if ticker in close_col else close_col.dropna()
                    if series.empty:
                        continue
                    price = round(float(series.iloc[-1]), 4)
                    if math.isnan(price):
                        continue
                    price_date = series.index[-1].date() if hasattr(series.index[-1], "date") else end

                    async with Session() as db:
                        await db.execute(text("""
                            INSERT INTO asset_prices (ticker, date, price, currency, source)
                            VALUES (:ticker, :date, :price, :currency, 'yfinance')
                            ON CONFLICT ON CONSTRAINT uq_asset_price_ticker_date
                            DO UPDATE SET price = EXCLUDED.price, source = EXCLUDED.source
                        """), {"ticker": ticker, "date": price_date, "price": price, "currency": currency})
                        await db.commit()
                    updated += 1
                except Exception:
                    continue
        finally:
            await eng.dispose()
        return updated

    return asyncio.run(_run())
