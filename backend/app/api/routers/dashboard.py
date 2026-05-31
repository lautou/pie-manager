from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import date

from app.core.database import get_db
from app.models import Pool, PoolProduct, DailySnapshot, Product
from app.services.price_service import r2
from app.services.dashboard_service import (
    _get_latest_prices,
    _get_spot_rates,
    _get_latest_holdings,
    _get_liquidity_eur,
)
from app.services.valuation_service import compute_pool_values

router = APIRouter(tags=["dashboard"])


class PoolDashboard(BaseModel):
    id: int
    name: str
    strategy: str
    target_pct: float
    current_value_eur: float
    current_pct: float
    gap_pct: float
    color: Optional[str] = None


class DashboardOut(BaseModel):
    total_eur: float
    offensive_eur: float
    defensive_eur: float
    pools: list[PoolDashboard]
    liquidity_eur: float
    last_updated: Optional[date]


@router.get("/", response_model=DashboardOut)
async def get_dashboard(
    portfolio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    latest_snapshot_result = await db.execute(
        select(DailySnapshot)
        .where(DailySnapshot.portfolio_id == portfolio_id)
        .order_by(DailySnapshot.date.desc())
        .limit(1)
    )
    latest_snapshot = latest_snapshot_result.scalar_one_or_none()

    pools_result = await db.execute(
        select(Pool).where(Pool.portfolio_id == portfolio_id, Pool.is_active == True)
    )
    pools = pools_result.scalars().all()

    if not pools:
        return DashboardOut(
            total_eur=0.0, offensive_eur=0.0, defensive_eur=0.0,
            pools=[], liquidity_eur=0.0, last_updated=None,
        )

    pool_ids = [p.id for p in pools]
    pp_result = await db.execute(
        select(PoolProduct).where(PoolProduct.pool_id.in_(pool_ids))
    )
    pool_products = pp_result.scalars().all()

    tickers_by_pool: dict[int, list[str]] = {p.id: [] for p in pools}
    all_tickers: set[str] = set()
    for pp in pool_products:
        tickers_by_pool[pp.pool_id].append(pp.ticker)
        all_tickers.add(pp.ticker)

    positions = await _get_latest_holdings(db, portfolio_id)
    prices = await _get_latest_prices(db, list(all_tickers))
    spot_rates = await _get_spot_rates(db)
    liquidity_eur = await _get_liquidity_eur(db, portfolio_id)

    last_updated = latest_snapshot.date if latest_snapshot else None

    # Fetch product categories to handle Manuel assets (price = total value directly)
    products_result = await db.execute(
        select(Product.ticker, Product.category).where(Product.ticker.in_(all_tickers))
    )
    product_categories = {row.ticker: row.category for row in products_result.all()}

    # Always compute pool values fresh from positions + latest prices
    pool_values = compute_pool_values(
        pools, tickers_by_pool, positions, prices, spot_rates, product_categories
    )

    total_eur = sum(pool_values.values()) + liquidity_eur
    offensive_eur = sum(pool_values[p.id] for p in pools if p.strategy == "Offensive")
    defensive_eur = sum(pool_values[p.id] for p in pools if p.strategy == "Defensive")

    pool_dashboards: list[PoolDashboard] = []
    for pool in pools:
        pool_val = pool_values[pool.id]

        current_pct = (pool_val / total_eur * 100) if total_eur > 0 else 0.0
        gap_pct = current_pct - (pool.target_pct * 100)

        pool_dashboards.append(
            PoolDashboard(
                id=pool.id,
                name=pool.name,
                strategy=pool.strategy,
                target_pct=pool.target_pct,
                current_value_eur=r2(pool_val),
                current_pct=round(current_pct, 2),
                gap_pct=round(gap_pct, 2),
                color=pool.color,
            )
        )

    return DashboardOut(
        total_eur=r2(total_eur),
        offensive_eur=r2(offensive_eur),
        defensive_eur=r2(defensive_eur),
        pools=pool_dashboards,
        liquidity_eur=r2(liquidity_eur),
        last_updated=last_updated,
    )
