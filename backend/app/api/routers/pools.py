# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

from app.core.database import get_db
from app.models import Pool, PoolProduct
from app.services.etf_holdings_service import compute_pool_lookthrough

router = APIRouter(tags=["pools"])


class PoolCreate(BaseModel):
    portfolio_id: int
    name: str
    strategy: str
    target_pct: float
    is_active: bool = True
    color: Optional[str] = None


class PoolUpdate(BaseModel):
    name: Optional[str] = None
    strategy: Optional[str] = None
    target_pct: Optional[float] = None
    is_active: Optional[bool] = None
    color: Optional[str] = None


class PoolProductAdd(BaseModel):
    ticker: str


class PoolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    portfolio_id: int
    name: str
    strategy: str
    target_pct: float
    is_active: bool
    color: Optional[str] = None


class PoolProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pool_id: int
    ticker: str


class AllocationEntryOut(BaseModel):
    key: str      # underlying ticker (by_company) or raw Yahoo sector key (by_sector)
    label: str    # company name (by_company) or raw sector key, frontend i18n-translates it
    value_eur: float
    pct: float


class PoolAllocationOut(BaseModel):
    pool_id: int
    pool_name: str
    total_eur: float
    by_sector: list[AllocationEntryOut]
    by_company: list[AllocationEntryOut]
    unclassified_eur: float
    unclassified_pct: float
    holdings_updated_at: Optional[datetime] = None


@router.get("/", response_model=list[PoolOut])
async def list_pools(
    portfolio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Pool).where(Pool.portfolio_id == portfolio_id))
    return result.scalars().all()


@router.post("/", response_model=PoolOut, status_code=201)
async def create_pool(body: PoolCreate, db: AsyncSession = Depends(get_db)):
    pool = Pool(**body.model_dump())
    db.add(pool)
    await db.commit()
    await db.refresh(pool)
    return pool


@router.put("/{pool_id}", response_model=PoolOut)
async def update_pool(
    pool_id: int,
    body: PoolUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Pool).where(Pool.id == pool_id))
    pool = result.scalar_one_or_none()
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(pool, field, value)
    await db.commit()
    await db.refresh(pool)
    return pool


@router.delete("/{pool_id}", status_code=204)
async def delete_pool(pool_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Pool).where(Pool.id == pool_id))
    pool = result.scalar_one_or_none()
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")
    await db.delete(pool)
    await db.commit()


@router.get("/{pool_id}/products", response_model=list[PoolProductOut])
async def list_pool_products(pool_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PoolProduct).where(PoolProduct.pool_id == pool_id)
    )
    return result.scalars().all()


@router.get("/{pool_id}/allocation", response_model=PoolAllocationOut)
async def get_pool_allocation(
    pool_id: int,
    portfolio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Look-through sector/company allocation for this pool: every ETF's top-10 holdings
    decomposed and merged with any directly held stock exposure to the same underlying
    ticker/sector — see app.services.etf_holdings_service.compute_pool_lookthrough.
    """
    allocation = await compute_pool_lookthrough(db, portfolio_id, pool_id)
    if allocation is None:
        raise HTTPException(status_code=404, detail="Pool not found")
    return allocation


@router.post("/{pool_id}/products", response_model=PoolProductOut, status_code=201)
async def add_product_to_pool(
    pool_id: int,
    body: PoolProductAdd,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Pool).where(Pool.id == pool_id))
    pool = result.scalar_one_or_none()
    if not pool:
        raise HTTPException(status_code=404, detail="Pool not found")

    # Rule: a ticker can belong to at most one pool (per portfolio)
    any_pool = await db.execute(
        select(PoolProduct)
        .join(Pool, Pool.id == PoolProduct.pool_id)
        .where(PoolProduct.ticker == body.ticker, Pool.portfolio_id == pool.portfolio_id)
    )
    if any_pool.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Ticker '{body.ticker}' is already assigned to another pool in this portfolio",
        )

    pp = PoolProduct(pool_id=pool_id, ticker=body.ticker)
    db.add(pp)
    await db.commit()
    await db.refresh(pp)
    return pp


@router.delete("/{pool_id}/products/{ticker}", status_code=204)
async def remove_product_from_pool(
    pool_id: int,
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PoolProduct).where(
            PoolProduct.pool_id == pool_id, PoolProduct.ticker == ticker
        )
    )
    pp = result.scalar_one_or_none()
    if not pp:
        raise HTTPException(status_code=404, detail="Ticker not found in pool")
    await db.delete(pp)
    await db.commit()
