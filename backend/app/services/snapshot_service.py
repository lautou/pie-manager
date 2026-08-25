# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import date
from typing import Sequence

from sqlalchemy import select, select as sa_select, and_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.pool import Pool
from app.models.product import Product
from app.models.snapshot import DailySnapshot, DailyPoolSnapshot, MonthlySnapshot, MonthlyPoolSnapshot
from app.models.transaction import Transaction
from app.services.valuation_service import compute_pool_values, load_prices_at_date
from app.services.dashboard_service import get_holdings, _get_spot_rates


def dedupe_snapshots_by_date(snapshots: Sequence[DailySnapshot]) -> list[DailySnapshot]:
    """Collapses same-day duplicate DailySnapshot rows (a portfolio can accumulate more than
    one snapshot per date — e.g. a recompute after a backfilled transaction) down to one per
    date, keeping the highest id (assumed to be the most recently computed), sorted ascending
    by date."""
    seen: dict[date, DailySnapshot] = {}
    for snap in snapshots:
        if snap.date not in seen or snap.id > seen[snap.date].id:
            seen[snap.date] = snap
    return sorted(seen.values(), key=lambda s: s.date)


async def compute_daily_snapshot(db: AsyncSession, portfolio_id: int, snap_date: date) -> DailySnapshot:
    """
    Computes portfolio value on snap_date by replaying transactions to get
    current positions, then pricing each position with the closest known price.
    """
    pools = await _get_user_pools_with_products(db, portfolio_id)

    # Build holdings: {ticker: quantity} from all transactions up to snap_date
    positions = await get_holdings(db, portfolio_id, as_of=snap_date)

    # Fetch product instrument types for all pool tickers
    all_tickers = {pp.ticker for pool in pools for pp in pool.products}
    itype_result = await db.execute(
        sa_select(Product.ticker, Product.instrument_type).where(Product.ticker.in_(all_tickers))
    )
    instrument_types = {row.ticker: row.instrument_type for row in itype_result.all()}

    # Fetch latest FX rates (tickers like GBPEUR=X, USDEUR=X) at or before snap_date
    spot_rates = await _get_spot_rates(db, as_of=snap_date)

    # Build tickers_by_pool mapping (required by compute_pool_values)
    tickers_by_pool: dict[int, list[str]] = {
        pool.id: [pp.ticker for pp in pool.products]
        for pool in pools
    }

    # Pre-load prices for all non-liquidity tickers at snap_date in one batch
    priced_tickers = all_tickers - {"LIQUIDITE.EURO"}
    prices = await load_prices_at_date(db, priced_tickers, snap_date)

    # Compute pool values using the shared valuation logic
    pool_values = compute_pool_values(
        pools, tickers_by_pool, positions, prices, spot_rates, instrument_types
    )

    total = sum(pool_values.values())
    # Use dict lookup to avoid zip ordering issues
    offensive = sum(pool_values[p.id] for p in pools if p.strategy == "Offensive")
    defensive = sum(pool_values[p.id] for p in pools if p.strategy == "Defensive")

    # Upsert daily snapshot
    stmt = insert(DailySnapshot).values(
        portfolio_id=portfolio_id, date=snap_date, total_eur=total,
        offensive_eur=offensive, defensive_eur=defensive
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_daily_snapshot",
        set_={"total_eur": total, "offensive_eur": offensive, "defensive_eur": defensive},
    )
    await db.execute(stmt)

    # Re-fetch to get id
    snap = await db.execute(
        select(DailySnapshot).where(
            DailySnapshot.portfolio_id == portfolio_id, DailySnapshot.date == snap_date
        )
    )
    snapshot = snap.scalar_one()

    # Replace pool snapshots (delete + re-insert to avoid stale duplicates)
    from sqlalchemy import delete as sa_delete
    await db.execute(
        sa_delete(DailyPoolSnapshot).where(DailyPoolSnapshot.daily_snapshot_id == snapshot.id)
    )
    for pool_id, value in pool_values.items():
        db.add(DailyPoolSnapshot(daily_snapshot_id=snapshot.id, pool_id=pool_id, value_eur=value))

    # Flush immediately so the next iteration within the same session sees
    # the updated pool snapshots (avoids stale 0-values on bank holidays).
    await db.flush()

    return snapshot


async def compute_monthly_snapshot(db: AsyncSession, portfolio_id: int, snap_date: date) -> MonthlySnapshot:
    """
    Computes monthly performance snapshot.
    Contributions = LIQUIDITE.EURO "Actif" transactions since last snapshot.
    """
    # Get previous monthly snapshot
    prev_result = await db.execute(
        select(MonthlySnapshot)
        .where(MonthlySnapshot.portfolio_id == portfolio_id, MonthlySnapshot.date < snap_date)
        .order_by(MonthlySnapshot.date.desc())
        .limit(1)
    )
    prev = prev_result.scalar_one_or_none()

    prev_date = prev.date if prev else date(2000, 1, 1)
    prev_total = prev.total_eur if prev else 0.0
    prev_index = prev.performance_index if prev else 100.0

    # Get daily snapshot for snap_date (must exist)
    daily = await db.execute(
        select(DailySnapshot).where(
            DailySnapshot.portfolio_id == portfolio_id, DailySnapshot.date == snap_date
        )
    )
    daily_snap = daily.scalar_one_or_none()
    if not daily_snap:
        raise ValueError(f"No daily snapshot for user {portfolio_id} on {snap_date}")

    total = daily_snap.total_eur

    # Contributions = sum of LIQUIDITE.EURO "Actif" transactions in period
    contrib_result = await db.execute(
        select(Transaction)
        .where(
            and_(
                Transaction.portfolio_id == portfolio_id,
                Transaction.ticker == "LIQUIDITE.EURO",
                Transaction.type == "Actif",
                Transaction.date > prev_date,
                Transaction.date <= snap_date,
            )
        )
    )
    contributions = sum(t.total_amount_eur for t in contrib_result.scalars().all())

    # Performance% = ((total - contributions) / prev_total - 1) * 100
    if prev_total != 0:
        perf_pct = ((total - contributions) / prev_total - 1) * 100
    else:
        perf_pct = 0.0

    perf_index = prev_index * (1 + perf_pct / 100)

    stmt = insert(MonthlySnapshot).values(
        portfolio_id=portfolio_id,
        date=snap_date,
        total_eur=total,
        offensive_eur=daily_snap.offensive_eur,
        defensive_eur=daily_snap.defensive_eur,
        contributions_eur=contributions,
        performance_pct=perf_pct,
        performance_index=perf_index,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_monthly_snapshot",
        set_={
            "total_eur": total,
            "offensive_eur": daily_snap.offensive_eur,
            "defensive_eur": daily_snap.defensive_eur,
            "contributions_eur": contributions,
            "performance_pct": perf_pct,
            "performance_index": perf_index,
        },
    )
    await db.execute(stmt)

    result = await db.execute(
        select(MonthlySnapshot).where(
            MonthlySnapshot.portfolio_id == portfolio_id, MonthlySnapshot.date == snap_date
        )
    )
    monthly = result.scalar_one()

    # Populate MonthlyPoolSnapshot from the corresponding DailyPoolSnapshot entries
    pool_snap_result = await db.execute(
        select(DailyPoolSnapshot)
        .where(DailyPoolSnapshot.daily_snapshot_id == daily_snap.id)
    )
    pool_snaps = pool_snap_result.scalars().all()

    from sqlalchemy import delete as sa_delete
    await db.execute(
        sa_delete(MonthlyPoolSnapshot).where(MonthlyPoolSnapshot.monthly_snapshot_id == monthly.id)
    )
    for ps in pool_snaps:
        db.add(MonthlyPoolSnapshot(
            monthly_snapshot_id=monthly.id,
            pool_id=ps.pool_id,
            value_eur=ps.value_eur,
        ))
    await db.flush()

    return monthly



async def _get_user_pools_with_products(db: AsyncSession, portfolio_id: int) -> list[Pool]:
    result = await db.execute(
        select(Pool)
        .where(Pool.portfolio_id == portfolio_id, Pool.is_active == True)  # noqa: E712
        .options(selectinload(Pool.products))
    )
    return list(result.scalars().all())
