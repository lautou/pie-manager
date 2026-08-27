# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from pgqueuer import Queries
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional
from datetime import date as Date

from app.core.database import get_db
from app.core.pgq import get_pgq_queries
from app.models import Transaction
from app.api.deps import get_or_404
from app.services.transaction_service import (
    TransactionCreate,
    TransactionUpdate,
    create_transaction_core,
    update_transaction_core,
    delete_transaction_core,
    trigger_snapshot_recompute,
)

router = APIRouter(tags=["transactions"])


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    portfolio_id: int
    account_id: int
    date: Date
    type: str
    ticker: str
    currency: str
    exchange_rate: float
    quantity: float
    unit_price: float
    unit_price_eur: float
    total_amount: float
    total_amount_eur: float
    balance_currency: Optional[float]
    balance_eur: Optional[float]
    fractional_parent_id: Optional[int]
    linked_transaction_id: Optional[int]
    operation: Optional[str] = None

    @field_validator("balance_eur", "balance_currency", mode="before")
    @classmethod
    def _normalize_zero(cls, v: object) -> object:
        # Bulk DB updates (balance ± delta) can produce IEEE 754 −0.0 when the
        # result cancels exactly.  −0.0 == 0.0 in Python, so the assignment
        # below converts negative zero to positive zero without touching other values.
        if isinstance(v, float) and v == 0.0:
            return 0.0
        return v


@router.get("/", response_model=list[TransactionOut])
async def list_transactions(
    portfolio_id: int = Query(...),
    account_id: Optional[int] = Query(None),
    ticker: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
    date_from: Optional[Date] = Query(None),
    date_to: Optional[Date] = Query(None),
    skip: int = Query(0),
    limit: int = Query(5000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Transaction).where(Transaction.portfolio_id == portfolio_id)
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if ticker:
        stmt = stmt.where(Transaction.ticker.ilike(f"%{ticker}%"))
    if currency:
        stmt = stmt.where(Transaction.currency.ilike(f"%{currency}%"))
    if date_from:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to:
        stmt = stmt.where(Transaction.date <= date_to)
    stmt = stmt.order_by(
        Transaction.date.desc(),
        Transaction.id.desc()
    ).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=TransactionOut, status_code=201)
async def create_transaction(
    body: TransactionCreate,
    db: AsyncSession = Depends(get_db),
    queries: Queries = Depends(get_pgq_queries),
):
    tx = await create_transaction_core(body, db)
    await db.commit()
    await db.refresh(tx)
    await trigger_snapshot_recompute(tx.portfolio_id, tx.date, queries)
    return tx


@router.put("/{transaction_id}", response_model=TransactionOut)
async def update_transaction(
    transaction_id: int,
    body: TransactionUpdate,
    db: AsyncSession = Depends(get_db),
    queries: Queries = Depends(get_pgq_queries),
):
    tx = await get_or_404(db, Transaction.id, transaction_id, "Transaction not found")
    tx = await update_transaction_core(tx, body, db)
    await db.commit()
    await db.refresh(tx)
    await trigger_snapshot_recompute(tx.portfolio_id, tx.date, queries)
    return tx


@router.delete("/{transaction_id}", status_code=204)
async def delete_transaction(
    transaction_id: int,
    db: AsyncSession = Depends(get_db),
    queries: Queries = Depends(get_pgq_queries),
):
    tx = await get_or_404(db, Transaction.id, transaction_id, "Transaction not found")
    portfolio_id, tx_date = await delete_transaction_core(tx, db)
    await db.commit()
    await trigger_snapshot_recompute(portfolio_id, tx_date, queries)
