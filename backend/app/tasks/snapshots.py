# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import date, timedelta

from sqlalchemy import select, func

from app.core.database import AsyncSessionLocal
from app.tasks import job_runs
from app.services.snapshot_service import compute_daily_snapshot, compute_monthly_snapshot
from app.services.portfolio_service import get_all_portfolios


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


async def _run_fill_missing_snapshots() -> dict:
    """Fill all missing daily snapshots from the last known snapshot to yesterday. Triggered
    from PgQueuer at backend startup and at midnight (frontend detection, see useAutoRefresh).
    Skips weekends. A single engine/session for the whole run — this now executes inside the
    PgQueuer worker's own persistent event loop (issue #66 step 4), unlike the old Celery task
    body, which needed a fresh asyncio.run() (and fresh engine) per DB interaction to avoid
    event-loop-binding issues across sync-task-body boundaries. Each (portfolio, date) gap is
    still committed and error-isolated individually, matching the old task's behavior: one
    bad date must not roll back or block any other."""
    from app.models.snapshot import DailySnapshot
    from app.models.price import AssetPrice
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    yesterday = date.today() - timedelta(days=1)
    eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    computed = 0

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

            for portfolio, trading_days in gaps:
                for snap_date in trading_days:
                    try:
                        await compute_daily_snapshot(db, portfolio_id=portfolio.id, snap_date=snap_date)
                        await db.commit()
                        computed += 1
                    except Exception:
                        await db.rollback()
        return {"status": "success", "total_tickers": computed, "succeeded": computed, "failed_tickers": []}
    finally:
        await eng.dispose()


async def _run_recompute_snapshots(start_date: str, end_date: str, run_id: int) -> dict:
    """Recompute daily snapshots for all users between start_date and end_date (inclusive).

    `run_id` is created by the caller (app/api/routers/admin.py's POST /recompute-snapshots,
    before enqueueing) so the client has a pollable task_id immediately, even before PgQueuer
    picks the job up — this core only ever reports progress onto that already-existing row via
    job_runs.update_progress, and never calls start_run/finish_run itself. The PgQueuer
    entrypoint handler (app/tasks/pgq_app.py) owns the terminal finish_run call on success or
    failure, mirroring how _run_tracked splits the same concerns for the other 5 tasks."""
    from app.models.price import AssetPrice
    from sqlalchemy import extract
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    eng = create_async_engine(settings.database_url, echo=False, pool_size=2)
    Session = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)

    try:
        async with Session() as db:
            result = await db.execute(
                select(AssetPrice.date).where(
                    AssetPrice.date >= date.fromisoformat(start_date),
                    AssetPrice.date <= date.fromisoformat(end_date),
                    extract('dow', AssetPrice.date).notin_([0, 6]),  # 0=Sunday, 6=Saturday
                ).distinct().order_by(AssetPrice.date)
            )
            trading_days = [r[0] for r in result.all()]
            total = len(trading_days)

            portfolios_list = await get_all_portfolios(db)

            for i, snap_date in enumerate(trading_days):
                await job_runs.update_progress(run_id, i + 1, total, snap_date.isoformat())
                for portfolio in portfolios_list:
                    try:
                        await compute_daily_snapshot(db, portfolio_id=portfolio.id, snap_date=snap_date)
                    except Exception:
                        pass
                await db.commit()
        return {"total": total}
    finally:
        await eng.dispose()
