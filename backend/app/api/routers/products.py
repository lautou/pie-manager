from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, ConfigDict
from typing import Optional

from app.core.database import get_db
from app.models import Product
from app.models.transaction import Transaction

router = APIRouter(tags=["products"])


class ProductCreate(BaseModel):
    ticker: str
    name: str
    category: Optional[str] = None
    instrument_type: Optional[str] = None
    fee_type: Optional[str] = None
    currency: Optional[str] = None
    isin: Optional[str] = None
    notes: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    instrument_type: Optional[str] = None
    fee_type: Optional[str] = None
    currency: Optional[str] = None
    isin: Optional[str] = None
    notes: Optional[str] = None
    is_ttf_eligible: Optional[bool] = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    name: str
    category: Optional[str]
    instrument_type: Optional[str] = None
    fee_type: Optional[str] = None
    currency: Optional[str]
    isin: Optional[str]
    notes: Optional[str]
    is_ttf_eligible: bool = False


@router.get("/", response_model=list[ProductOut])
async def list_products(
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Product)
    if category:
        stmt = stmt.where(Product.category == category)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=ProductOut, status_code=201)
async def create_product(body: ProductCreate, db: AsyncSession = Depends(get_db)):
    product = Product(**body.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@router.put("/{ticker}", response_model=ProductOut)
async def update_product(
    ticker: str, body: ProductUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Product).where(Product.ticker == ticker))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    await db.commit()
    await db.refresh(product)
    return product


@router.delete("/{ticker}", status_code=204)
async def delete_product(ticker: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Product).where(Product.ticker == ticker))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    # Check if any transactions reference this product
    tx_count_result = await db.execute(
        select(func.count()).select_from(Transaction).where(Transaction.ticker == ticker)
    )
    tx_count = tx_count_result.scalar_one()
    if tx_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"This product is used in {tx_count} transaction(s) and cannot be deleted.",
        )
    await db.delete(product)
    await db.commit()
