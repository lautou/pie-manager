from __future__ import annotations
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from pydantic import BaseModel, ConfigDict

from app.core.database import get_db
from app.models import Portfolio

router = APIRouter(tags=["portfolios"])


class PortfolioCreate(BaseModel):
    name: str


class PortfolioRename(BaseModel):
    name: str


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: Optional[datetime] = None


@router.get("/", response_model=list[PortfolioOut])
async def list_portfolios(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Portfolio).order_by(Portfolio.created_at))
    return result.scalars().all()


@router.post("/", response_model=PortfolioOut, status_code=201)
async def create_portfolio(body: PortfolioCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Portfolio).where(Portfolio.name == body.name.strip()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A portfolio with that name already exists")
    portfolio = Portfolio(name=body.name.strip())
    db.add(portfolio)
    await db.commit()
    await db.refresh(portfolio)
    return portfolio


@router.get("/{portfolio_id}", response_model=PortfolioOut)
async def get_portfolio(portfolio_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio


@router.put("/{portfolio_id}", response_model=PortfolioOut)
async def rename_portfolio(portfolio_id: int, body: PortfolioRename, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    conflict = await db.execute(
        select(Portfolio).where(Portfolio.name == body.name.strip(), Portfolio.id != portfolio_id)
    )
    if conflict.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="That name is already in use")
    portfolio.name = body.name.strip()
    await db.commit()
    await db.refresh(portfolio)
    return portfolio


@router.delete("/{portfolio_id}", status_code=204)
async def delete_portfolio(portfolio_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # Cascade-delete in correct FK order (no DB-level CASCADE on portfolio_id FKs)
    await db.execute(text(
        "DELETE FROM daily_snapshots WHERE portfolio_id = :uid"
    ), {"uid": portfolio_id})  # cascade → daily_pool_snapshots
    await db.execute(text("DELETE FROM monthly_snapshots WHERE portfolio_id = :uid"), {"uid": portfolio_id})
    await db.execute(text("DELETE FROM transactions WHERE portfolio_id = :uid"), {"uid": portfolio_id})
    # pool_products reference pools → delete pool_products first
    await db.execute(text(
        "DELETE FROM pool_products WHERE pool_id IN (SELECT id FROM pools WHERE portfolio_id = :uid)"
    ), {"uid": portfolio_id})
    await db.execute(text("DELETE FROM pools WHERE portfolio_id = :uid"), {"uid": portfolio_id})
    # portfolio_accounts cascade is handled by ON DELETE CASCADE on the FK
    await db.delete(portfolio)
    await db.commit()
