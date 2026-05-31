"""
Fiscal carry-forward (moins-values reportables) router.

GET    /fiscal/carry-forward/?portfolio_id=X  → list all for a portfolio, ordered by tax_year DESC
POST   /fiscal/carry-forward/                 → create
PUT    /fiscal/carry-forward/{id}             → update amount_eur
DELETE /fiscal/carry-forward/{id}             → delete
"""
from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.fiscal import FiscalCarryForward
from app.models.broker import Broker
from app.models.portfolio_account import PortfolioAccount

router = APIRouter(tags=["fiscal"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CarryForwardCreate(BaseModel):
    portfolio_id: int
    tax_year: int
    amount_eur: float


class CarryForwardUpdate(BaseModel):
    amount_eur: float


class CarryForwardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    portfolio_id: int
    tax_year: int
    amount_eur: float


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/carry-forward/", response_model=list[CarryForwardOut])
async def list_carry_forwards(
    portfolio_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FiscalCarryForward)
        .where(FiscalCarryForward.portfolio_id == portfolio_id)
        .order_by(FiscalCarryForward.tax_year.desc())
    )
    return result.scalars().all()


@router.post("/carry-forward/", response_model=CarryForwardOut, status_code=201)
async def create_carry_forward(
    body: CarryForwardCreate,
    db: AsyncSession = Depends(get_db),
):
    entry = FiscalCarryForward(
        portfolio_id=body.portfolio_id,
        tax_year=body.tax_year,
        amount_eur=body.amount_eur,
    )
    db.add(entry)
    try:
        await db.commit()
        await db.refresh(entry)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"An entry already exists for tax year {body.tax_year} in this portfolio.",
        )
    return entry


@router.put("/carry-forward/{entry_id}", response_model=CarryForwardOut)
async def update_carry_forward(
    entry_id: int,
    body: CarryForwardUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FiscalCarryForward).where(FiscalCarryForward.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")
    entry.amount_eur = body.amount_eur
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/carry-forward/{entry_id}", status_code=204)
async def delete_carry_forward(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FiscalCarryForward).where(FiscalCarryForward.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")
    await db.delete(entry)
    await db.commit()


# ── Current-year realized PV (CTO only, excl. JPYEUR=X) ──────────────────────

# Tickers excluded from fiscal PV computation (movable property, different tax regime)
_FISCAL_EXCLUDED_TICKERS = {"JPYEUR=X", "USDEUR=X", "GBPEUR=X", "CHFEUR=X"}


class FiscalPvDetail(BaseModel):
    date: str
    ticker: str
    product_name: str
    qty_sold: float
    realized_pv: float
    account_id: int


class FiscalCurrentYearPv(BaseModel):
    year: int
    net_realized_pv: float
    details: list[FiscalPvDetail]


@router.get("/current-year-pv/", response_model=FiscalCurrentYearPv)
async def get_current_year_pv(
    portfolio_id: int,
    year: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns realized net PV for the fiscal year from CTO accounts only,
    excluding JPYEUR=X and other forex tickers (biens meubles regime).
    Used to anticipate fiscal impact of current-year sales.
    """
    fiscal_year = year or date.today().year

    # Get CTO account IDs for this portfolio
    cto_result = await db.execute(
        select(Broker.id)
        .join(PortfolioAccount, PortfolioAccount.broker_id == Broker.id)
        .where(
            PortfolioAccount.portfolio_id == portfolio_id,
            Broker.is_cto.is_(True),
        )
    )
    cto_ids = {row[0] for row in cto_result.all()}

    if not cto_ids:
        return FiscalCurrentYearPv(year=fiscal_year, net_realized_pv=0.0, details=[])

    # Use the PV service — filter events by year and CTO account
    from app.services.pv_service import compute_capital_gains
    pv_data = await compute_capital_gains(db, portfolio_id)

    year_str = str(fiscal_year)
    details: list[FiscalPvDetail] = []
    for ticker_data in pv_data.tickers:
        if ticker_data.ticker in _FISCAL_EXCLUDED_TICKERS:
            continue
        for ev in ticker_data.events:
            ev_year = ev.date[:4] if isinstance(ev.date, str) else str(ev.date)[:4]
            if ev_year == year_str and ev.account_id in cto_ids:
                details.append(FiscalPvDetail(
                    date=str(ev.date),
                    ticker=ev.ticker,
                    product_name=ev.product_name,
                    qty_sold=ev.qty_sold,
                    realized_pv=ev.realized_pv,
                    account_id=ev.account_id,
                ))

    details.sort(key=lambda d: d.date, reverse=True)

    net_pv = sum(d.realized_pv for d in details)
    return FiscalCurrentYearPv(year=fiscal_year, net_realized_pv=round(net_pv, 2), details=details)
