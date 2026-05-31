"""
Capital Gains (Plus-Values) endpoint.

GET /api/pv/?portfolio_id=X[&account_id=Y]

Returns the full CUMP-based capital gains report for a portfolio, with
current market values and unrealized PV filled in from the latest prices.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.dashboard_service import _get_latest_prices, _get_spot_rates
from app.services.price_service import _to_eur, r2
from app.services.pv_service import compute_capital_gains

router = APIRouter(tags=["pv"])


# ── Pydantic response schemas ─────────────────────────────────────────────────

class CapitalGainsEventOut(BaseModel):
    date: date
    ticker: str
    product_name: str
    qty_sold: float
    cump_at_sell: float
    sell_price_eur: float
    realized_pv: float
    account_id: int


class TickerCapitalGainsOut(BaseModel):
    ticker: str
    product_name: str
    cump: float
    qty_held: float
    cost_basis_eur: float
    current_value_eur: float
    unrealized_pv: float
    realized_pv_total: float
    events: list[CapitalGainsEventOut]


class PortfolioCapitalGainsOut(BaseModel):
    portfolio_id: int
    tickers: list[TickerCapitalGainsOut]
    total_unrealized_pv: float
    total_realized_pv: float
    total_pv: float


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=PortfolioCapitalGainsOut)
async def get_capital_gains(
    portfolio_id: int = Query(..., description="Portfolio ID"),
    account_id: Optional[int] = Query(None, description="Filter by account (optional)"),
    db: AsyncSession = Depends(get_db),
) -> PortfolioCapitalGainsOut:
    """
    Return CUMP-based capital gains for the portfolio.

    - Computes realized PV from the full transaction history.
    - Enriches each ticker that still has an open position with the latest
      market price to compute current_value_eur and unrealized_pv.
    - Manuel products (OR.PHYSIQUE, SICAV…) are excluded from the calculation.
    """
    # ── 1. Compute CUMP / realized PV from transactions ───────────────────────
    result = await compute_capital_gains(db, portfolio_id, account_id)

    # ── 2. Fetch latest prices for tickers with an open position ─────────────
    open_tickers = [t.ticker for t in result.tickers if t.qty_held > 0]
    prices = await _get_latest_prices(db, open_tickers) if open_tickers else {}
    spot_rates = await _get_spot_rates(db) if open_tickers else {}

    # ── 3. Fill current_value_eur and unrealized_pv ───────────────────────────
    total_unrealized_pv = 0.0

    tickers_out: list[TickerCapitalGainsOut] = []
    for t in result.tickers:
        current_value_eur = 0.0

        if t.qty_held > 0 and t.ticker in prices:
            native_price, currency = prices[t.ticker]
            price_eur = _to_eur(native_price, currency, spot_rates)
            current_value_eur = r2(t.qty_held * price_eur)

        unrealized_pv = r2(current_value_eur - t.cost_basis_eur) if t.qty_held > 0 else 0.0
        total_unrealized_pv += unrealized_pv

        tickers_out.append(
            TickerCapitalGainsOut(
                ticker=t.ticker,
                product_name=t.product_name,
                cump=t.cump,
                qty_held=t.qty_held,
                cost_basis_eur=t.cost_basis_eur,
                current_value_eur=current_value_eur,
                unrealized_pv=unrealized_pv,
                realized_pv_total=t.realized_pv_total,
                events=[
                    CapitalGainsEventOut(
                        date=e.date,
                        ticker=e.ticker,
                        product_name=e.product_name,
                        qty_sold=e.qty_sold,
                        cump_at_sell=e.cump_at_sell,
                        sell_price_eur=e.sell_price_eur,
                        realized_pv=e.realized_pv,
                        account_id=e.account_id,
                    )
                    for e in t.events
                ],
            )
        )

    total_pv = r2(total_unrealized_pv + result.total_realized_pv)

    return PortfolioCapitalGainsOut(
        portfolio_id=portfolio_id,
        tickers=tickers_out,
        total_unrealized_pv=r2(total_unrealized_pv),
        total_realized_pv=result.total_realized_pv,
        total_pv=total_pv,
    )
