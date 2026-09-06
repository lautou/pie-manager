# SPDX-License-Identifier: AGPL-3.0-or-later
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
from app.api.deps import get_or_404

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
    entry = await get_or_404(db, FiscalCarryForward.id, entry_id, "Entry not found.")
    entry.amount_eur = body.amount_eur
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/carry-forward/{entry_id}", status_code=204)
async def delete_carry_forward(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
):
    entry = await get_or_404(db, FiscalCarryForward.id, entry_id, "Entry not found.")
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


class FiscalLossCandidate(BaseModel):
    account_id: int
    ticker: str
    product_name: str
    qty_held: float
    cump: float
    current_value_eur: float
    unrealized_pv: float


class FiscalCurrentYearPv(BaseModel):
    year: int
    net_realized_pv: float
    details: list[FiscalPvDetail]
    loss_harvesting_candidates: list[FiscalLossCandidate]


async def _get_loss_harvesting_candidates(
    db: AsyncSession,
    portfolio_id: int,
    cto_ids: set[int],
) -> list[FiscalLossCandidate]:
    """
    Currently-held CTO positions (excl. forex) sitting at an unrealized loss right
    now — candidates the user could sell before year-end to realize more offsetting
    moins-values. Reuses compute_capital_gains (CUMP/WACOP) and the same
    price/FX-conversion helpers pv.py's own endpoint uses, scoped per CTO account.

    One row per (account, ticker) — deliberately NOT merged across accounts even
    when the same ticker is held on two different CTO brokers (e.g. Degiro and
    IBKR). A hypothetical sell-to-harvest-a-loss executes on one specific broker,
    whose own commission schedule/fee must be attributable to that exact account —
    a cross-broker blended row would make that impossible downstream.
    """
    from app.services.dashboard_service import _get_latest_prices, _get_spot_rates
    from app.services.price_service import _to_eur, r2
    from app.services.pv_service import compute_capital_gains

    per_account: list[dict] = []
    all_tickers: set[str] = set()
    for cto_id in cto_ids:
        cto_pv = await compute_capital_gains(db, portfolio_id, account_id=cto_id, force_include_fees=True)
        for t in cto_pv.tickers:
            if t.ticker in _FISCAL_EXCLUDED_TICKERS or t.qty_held <= 0:
                continue
            per_account.append({
                "account_id": cto_id,
                "ticker": t.ticker,
                "product_name": t.product_name,
                "qty_held": t.qty_held,
                "cost_basis_eur": t.cost_basis_eur,
            })
            all_tickers.add(t.ticker)

    if not per_account:
        return []

    prices = await _get_latest_prices(db, list(all_tickers))
    spot_rates = await _get_spot_rates(db)

    candidates: list[FiscalLossCandidate] = []
    for entry in per_account:
        ticker = entry["ticker"]
        if ticker not in prices:
            continue
        native_price, currency = prices[ticker]
        price_eur = _to_eur(native_price, currency, spot_rates)
        current_value_eur = r2(entry["qty_held"] * price_eur)
        unrealized_pv = r2(current_value_eur - entry["cost_basis_eur"])
        if unrealized_pv < 0:
            # qty_held > 0 guaranteed by the loop's own skip above — no zero-division risk.
            cump = entry["cost_basis_eur"] / entry["qty_held"]
            candidates.append(FiscalLossCandidate(
                account_id=entry["account_id"],
                ticker=ticker,
                product_name=entry["product_name"],
                qty_held=round(entry["qty_held"], 6),
                cump=round(cump, 6),
                current_value_eur=current_value_eur,
                unrealized_pv=unrealized_pv,
            ))

    candidates.sort(key=lambda c: c.unrealized_pv)
    return candidates


@router.get("/current-year-pv/", response_model=FiscalCurrentYearPv)
async def get_current_year_pv(
    portfolio_id: int,
    year: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns realized net PV for the fiscal year from CTO accounts only,
    excluding JPYEUR=X and other forex tickers (biens meubles regime), plus
    the list of currently-held CTO positions sitting at an unrealized loss
    right now (loss-harvesting candidates for year-end tax optimization).
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
        return FiscalCurrentYearPv(
            year=fiscal_year, net_realized_pv=0.0, details=[], loss_harvesting_candidates=[],
        )

    # Use the PV service — filter events by year and CTO account
    from app.services.pv_service import compute_capital_gains
    pv_data = await compute_capital_gains(db, portfolio_id, force_include_fees=True)

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
    loss_candidates = await _get_loss_harvesting_candidates(db, portfolio_id, cto_ids)
    return FiscalCurrentYearPv(
        year=fiscal_year,
        net_realized_pv=round(net_pv, 2),
        details=details,
        loss_harvesting_candidates=loss_candidates,
    )
