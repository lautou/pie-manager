from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import date

from app.core.database import get_db
from app.models import DailySnapshot, MonthlySnapshot, Pool
from app.services.price_service import r2

router = APIRouter(tags=["snapshots"])


def _compute_twrr(
    value_series: list[tuple[date, float]],
    flows: dict[date, float],
) -> list[dict]:
    """
    Pure TWRR computation — module-level for testability.

    value_series: [(date, end-of-day value)] sorted ascending.
    flows: {date: external_flow} — positive = capital inflow to the portfolio/pool.

    r_t = V_t / (V_{t-1} + F_t)  [days with flow]
    r_t = V_t / V_{t-1}           [days without flow]

    Index starts at 100 on the first day with a positive value.
    """
    result: list[dict] = []
    index = 100.0
    prev_v: float | None = None
    for dt, v in value_series:
        if prev_v is None or prev_v <= 0:
            if v > 0:
                result.append({"date": dt.isoformat(), "index": round(index, 2)})
                prev_v = v
            continue
        f = flows.get(dt, 0.0)
        denom = prev_v + f
        if denom > 0 and v >= 0:
            index *= v / denom
        result.append({"date": dt.isoformat(), "index": round(index, 2)})
        prev_v = v
    return result


class MonthlySnapshotCreate(BaseModel):
    portfolio_id: int
    date: date


class DailySnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    portfolio_id: int
    date: date
    total_eur: float
    offensive_eur: Optional[float]
    defensive_eur: Optional[float]


class MonthlySnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    portfolio_id: int
    date: date
    total_eur: float
    offensive_eur: Optional[float]
    defensive_eur: Optional[float]
    contributions_eur: Optional[float]
    performance_pct: Optional[float]
    performance_index: Optional[float]


class PoolValue(BaseModel):
    pool_id: int
    pool_name: str
    strategy: str
    value_eur: float


class DailyWithPoolsOut(BaseModel):
    date: date
    total_eur: float
    offensive_eur: float
    defensive_eur: float
    pools: list[PoolValue]


@router.get("/daily-with-pools", response_model=list[DailyWithPoolsOut])
async def list_daily_with_pools(
    portfolio_id: int = Query(...),
    date_from: Optional[date] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Returns daily snapshots with per-pool breakdown, ordered ascending for charts."""
    from sqlalchemy.orm import selectinload

    # Fetch pools for this portfolio (name + strategy)
    pools_result = await db.execute(
        select(Pool).where(Pool.portfolio_id == portfolio_id, Pool.is_active == True)  # noqa: E712
    )
    pools = {p.id: p for p in pools_result.scalars().all()}

    # Fetch daily snapshots + pool breakdown
    stmt = (
        select(DailySnapshot)
        .where(DailySnapshot.portfolio_id == portfolio_id, DailySnapshot.total_eur > 0)
        .options(selectinload(DailySnapshot.pool_snapshots))
        .order_by(DailySnapshot.date.asc())
    )
    if date_from:
        stmt = stmt.where(DailySnapshot.date >= date_from)

    result = await db.execute(stmt)
    all_snaps = result.scalars().all()

    # Deduplicate: keep only one snapshot per date (latest by id)
    seen: dict[date, DailySnapshot] = {}
    for snap in all_snaps:
        if snap.date not in seen or snap.id > seen[snap.date].id:
            seen[snap.date] = snap
    snapshots = sorted(seen.values(), key=lambda s: s.date)

    out = []
    for snap in snapshots:
        # Deduplicate pool snapshots: keep latest value per pool
        pool_latest: dict[int, float] = {}
        for ps in snap.pool_snapshots:
            if ps.pool_id not in pool_latest:
                pool_latest[ps.pool_id] = ps.value_eur
        pool_values = []
        seen_pools: set[int] = set()
        for ps in snap.pool_snapshots:
            if ps.pool_id in seen_pools:
                continue
            seen_pools.add(ps.pool_id)
            pool = pools.get(ps.pool_id)
            if pool:
                pool_values.append(PoolValue(
                    pool_id=ps.pool_id,
                    pool_name=pool.name,
                    strategy=pool.strategy,
                    value_eur=r2(ps.value_eur),
                ))
        out.append(DailyWithPoolsOut(
            date=snap.date,
            total_eur=r2(snap.total_eur),
            offensive_eur=r2(snap.offensive_eur or 0),
            defensive_eur=r2(snap.defensive_eur or 0),
            pools=pool_values,
        ))
    return out


@router.get("/daily", response_model=list[DailySnapshotOut])
async def list_daily_snapshots(
    portfolio_id: int = Query(...),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(DailySnapshot).where(DailySnapshot.portfolio_id == portfolio_id)
    if date_from:
        stmt = stmt.where(DailySnapshot.date >= date_from)
    if date_to:
        stmt = stmt.where(DailySnapshot.date <= date_to)
    stmt = stmt.order_by(DailySnapshot.date.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/monthly", response_model=list[MonthlySnapshotOut])
async def list_monthly_snapshots(
    portfolio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MonthlySnapshot)
        .where(MonthlySnapshot.portfolio_id == portfolio_id)
        .order_by(MonthlySnapshot.date.desc())
    )
    return result.scalars().all()


@router.get("/twrr")
async def get_twrr(
    portfolio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Time-Weighted Rate of Return (TWRR) for total portfolio, offensive/defensive
    strategies, and each pool. Returns daily index series (base 100).

    TWRR formula per sub-period:
        r_t = V_t / (V_{t-1} + F_t)   [days with external flow F_t]
        r_t = V_t / V_{t-1}            [days with no flow]

    External flow to a pool on day t:
        F_t = -sum(total_amount_eur for that pool's tickers on day t)
        (buys have negative total_amount_eur → F_t > 0, i.e. inflow)

    External flow to total portfolio:
        Approximated as net LIQUIDITE.EURO transactions per day.
        This captures cash deposits and withdrawals while buy/sell pairs
        cancel out (each buy: LIQUIDITE -X / position +X, net = 0).
    """
    from app.services.twrr_service import fetch_pool_twrr_data, fetch_position_twrr_data

    # ── 1. Daily snapshots ─────────────────────────────────────────────────
    snaps_raw = await db.execute(
        select(DailySnapshot)
        .where(DailySnapshot.portfolio_id == portfolio_id, DailySnapshot.total_eur > 0)
        .order_by(DailySnapshot.date.asc())
    )
    # Deduplicate per date (keep latest id)
    seen_dates: dict[date, DailySnapshot] = {}
    for s in snaps_raw.scalars().all():
        if s.date not in seen_dates or s.id > seen_dates[s.date].id:
            seen_dates[s.date] = s
    daily_list = sorted(seen_dates.values(), key=lambda s: s.date)
    if not daily_list:
        return {"total": [], "offensive": [], "defensive": [], "pools": {}}

    snapshot_date_set = set(s.date for s in daily_list)

    def remap_flows(flows: dict[date, float]) -> dict[date, float]:
        remapped: dict[date, float] = {}
        for dt, f in flows.items():
            if dt in snapshot_date_set:
                remapped[dt] = remapped.get(dt, 0.0) + f
            else:
                next_snap = next(
                    (sd for sd in sorted(snapshot_date_set) if sd >= dt), None
                )
                if next_snap:
                    remapped[next_snap] = remapped.get(next_snap, 0.0) + f
        return remapped

    # ── 2–4. Fetch pool/strategy data via service ──────────────────────────
    pool_data = await fetch_pool_twrr_data(
        db, portfolio_id, daily_list, snapshot_date_set, remap_flows
    )
    pools = pool_data["pools"]
    pool_daily = pool_data["pool_daily"]
    pool_flows = pool_data["pool_flows"]
    strat_flows_off = pool_data["strat_flows_off"]
    strat_flows_def = pool_data["strat_flows_def"]
    total_flows = pool_data["total_flows"]

    # ── 5. TWRR computation ────────────────────────────────────────────────
    # Total
    total_series = [(s.date, s.total_eur) for s in daily_list]
    twrr_total = _compute_twrr(total_series, total_flows)

    # Offensive / Defensive
    off_series = [(s.date, s.offensive_eur or 0.0) for s in daily_list if (s.offensive_eur or 0) > 0]
    def_series = [(s.date, s.defensive_eur or 0.0) for s in daily_list if (s.defensive_eur or 0) > 0]
    twrr_off = _compute_twrr(off_series, strat_flows_off)
    twrr_def = _compute_twrr(def_series, strat_flows_def)

    # Pools
    twrr_pools: dict[str, list[dict]] = {}
    all_dates = [s.date for s in daily_list]
    for pool_id, pool in pools.items():
        series = [(dt, pool_daily.get(dt, {}).get(pool_id, 0.0)) for dt in all_dates]
        series = [(dt, v) for dt, v in series if v > 0 or any(
            pool_daily.get(d2, {}).get(pool_id, 0) > 0 for d2 in all_dates if d2 >= dt
        )]
        if series:
            twrr_pools[pool.name] = _compute_twrr(series, pool_flows.get(pool_id, {}))

    # ── 6. Per-position TWRR ───────────────────────────────────────────────
    twrr_positions = await fetch_position_twrr_data(
        db, portfolio_id, all_dates, remap_flows
    )

    return {
        "total": twrr_total,
        "offensive": twrr_off,
        "defensive": twrr_def,
        "pools": twrr_pools,
        "positions": twrr_positions,
    }


@router.post("/monthly", response_model=MonthlySnapshotOut, status_code=201)
async def create_monthly_snapshot(
    body: MonthlySnapshotCreate,
    db: AsyncSession = Depends(get_db),
):
    from app.services.snapshot_service import compute_monthly_snapshot

    try:
        snapshot = await compute_monthly_snapshot(db, body.portfolio_id, body.date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return snapshot
