# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from pgqueuer import Queries
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import date

from app.core.database import get_db
from app.core.pgq import get_pgq_queries
from app.models import AssetPrice

router = APIRouter(tags=["prices"])


class PriceCreate(BaseModel):
    ticker: str
    date: date
    price: float
    currency: str
    source: str = "manual"


class PriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    date: date
    price: float
    currency: str
    source: str


@router.get("/", response_model=list[PriceOut])
async def list_prices(
    ticker: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AssetPrice)
    if ticker:
        stmt = stmt.where(AssetPrice.ticker == ticker)
    if date_from:
        stmt = stmt.where(AssetPrice.date >= date_from)
    if date_to:
        stmt = stmt.where(AssetPrice.date <= date_to)
    stmt = stmt.order_by(AssetPrice.date.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=PriceOut, status_code=201)
async def upsert_price(body: PriceCreate, db: AsyncSession = Depends(get_db)):
    stmt = (
        pg_insert(AssetPrice)
        .values(**body.model_dump())
        .on_conflict_do_update(
            constraint="uq_asset_price_ticker_date",
            set_={"price": body.price, "source": body.source},
        )
        .returning(AssetPrice)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()


@router.post("/fetch")
async def trigger_price_fetch(queries: Queries = Depends(get_pgq_queries)):
    """Same underlying entrypoint as admin.py's /refresh-prices — fetch_all_prices was a pure
    Python-level alias for refresh_prices_live, which no longer exists as a separate name."""
    job_ids = await queries.enqueue("refresh_prices_live", payload=b"on_demand")
    return {"job_id": job_ids[0], "status": "queued"}
