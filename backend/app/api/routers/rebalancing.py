# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.models import Pool, PoolProduct, Product
from app.services.price_service import r2
from app.services.rebalancing_service import (
    PoolRebalanceInput,
    compute_injection_total_needed,
    compute_rebalancing,
    find_untargeted_pools_with_value,
)
from app.services.dashboard_service import (
    _get_latest_prices,
    _get_spot_rates,
    _get_latest_holdings,
    _get_liquidity_eur,
)
from app.services.valuation_service import compute_pool_values

router = APIRouter(tags=["dashboard"])


class RebalancingRequest(BaseModel):
    portfolio_id: int
    external_injection: float = 0.0
    commission_pct: float = 0.0   # percentage, e.g. 0.1 means 0.1%
    commission_min: float = 0.0   # minimum € per trade, e.g. 1.0


class PoolBlockingOut(BaseModel):
    id: int
    name: str
    current_value: float


class PoolRebalanceOut(BaseModel):
    id: int
    name: str
    strategy: str
    target_pct: float
    current_value: float
    current_pct: float
    target_value_after: float
    injection_amount: float
    rebalance_amount: float
    hybrid_amount: float
    injection_fee: float = 0.0
    rebalance_fee: float = 0.0
    hybrid_fee: float = 0.0
    injection_net: float = 0.0
    rebalance_net: float = 0.0
    hybrid_net: float = 0.0


class RebalancingOut(BaseModel):
    total_current: float
    total_apport: float
    total_after: float
    liquidity_available: float
    external_injection: float
    injection_total_needed: float | None
    injection_blocking_pools: list[PoolBlockingOut]
    pools: list[PoolRebalanceOut]


@router.post("/rebalancing", response_model=RebalancingOut)
async def compute_rebalancing_endpoint(
    body: RebalancingRequest,
    db: AsyncSession = Depends(get_db),
):
    pools_result = await db.execute(
        select(Pool).where(Pool.portfolio_id == body.portfolio_id, Pool.is_active == True)  # noqa: E712
    )
    pools = list(pools_result.scalars().all())
    if not pools:
        raise HTTPException(status_code=404, detail="No active pools found for portfolio")

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

    positions = await _get_latest_holdings(db, body.portfolio_id)
    prices = await _get_latest_prices(db, list(all_tickers))
    spot_rates = await _get_spot_rates(db)
    liquidity_eur = await _get_liquidity_eur(db, body.portfolio_id)

    # Fetch instrument types so Or physique assets (OR.PHYSIQUE) are valued
    # using price = total value, not qty × price (which would give 0 since no qty tracked)
    itype_result = await db.execute(
        select(Product.ticker, Product.instrument_type).where(Product.ticker.in_(all_tickers))
    )
    rebal_instrument_types = {row.ticker: row.instrument_type for row in itype_result.all()}

    pool_values = compute_pool_values(
        pools, tickers_by_pool, positions, prices, spot_rates, rebal_instrument_types
    )

    pool_inputs = [
        PoolRebalanceInput(
            id=pool.id,
            name=pool.name,
            strategy=pool.strategy,
            target_pct=pool.target_pct,
            current_value=pool_values[pool.id],
        )
        for pool in pools
    ]

    results = compute_rebalancing(
        pool_inputs, liquidity_eur, body.external_injection,
        commission_pct=body.commission_pct,
        commission_min=body.commission_min,
    )

    total_current = sum(p.current_value for p in pool_inputs)
    total_apport = liquidity_eur + body.external_injection
    injection_total_needed = compute_injection_total_needed(pool_inputs)
    blocking_pools = find_untargeted_pools_with_value(pool_inputs)

    return RebalancingOut(
        total_current=r2(total_current),
        total_apport=r2(total_apport),
        total_after=r2(total_current + total_apport),
        liquidity_available=r2(liquidity_eur),
        external_injection=r2(body.external_injection),
        injection_total_needed=injection_total_needed,
        injection_blocking_pools=[
            PoolBlockingOut(id=p.id, name=p.name, current_value=r2(p.current_value))
            for p in blocking_pools
        ],
        pools=[PoolRebalanceOut(**r.__dict__) for r in results],
    )
