# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, ConfigDict
from typing import Any, Optional
from datetime import date

from app.core.database import get_db
from app.models import Broker, Transaction, Product, AssetPrice, PortfolioAccount
from app.services.price_service import _to_eur, r2, held_quantity, get_forex_fee_adjustments
from app.api.routers.dashboard import _get_spot_rates
from app.api.deps import get_or_404, ensure_unreferenced


router = APIRouter(tags=["brokers"])


async def _broker_out(broker: Broker, db: AsyncSession) -> BrokerOut:
    """Build BrokerOut with portfolio_ids resolved from join table."""
    pa_rows = await db.execute(
        select(PortfolioAccount.portfolio_id).where(PortfolioAccount.broker_id == broker.id)
    )
    portfolio_ids = [r[0] for r in pa_rows.all()]
    data = {c.name: getattr(broker, c.name) for c in broker.__table__.columns}
    return BrokerOut(**data, portfolio_ids=portfolio_ids)


class BrokerCreate(BaseModel):
    name: str
    currency: str = "EUR"
    color: Optional[str] = None
    portfolio_ids: list[int] = []


class BrokerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    currency: str
    commission_schedule: Optional[list[Any]] = None
    allowed_tickers: Optional[list[str]] = None
    withdrawal_fee_eur: float = 0.0
    withdrawal_first_free: bool = False
    commission_profile: Optional[str] = None
    commission_sale_rate: float = 0.0
    include_fees_in_cump: bool = True
    monthly_free_eur: Optional[float] = None
    above_monthly_rate: float = 0.0
    weekend_rate: Optional[float] = None
    color: Optional[str] = None
    portfolio_ids: list[int] = []


class BrokerUpdate(BaseModel):
    name: Optional[str] = None
    currency: Optional[str] = None
    color: Optional[str] = None


class CommissionScheduleUpdate(BaseModel):
    commission_schedule: list[Any]


class AllowedTickersUpdate(BaseModel):
    allowed_tickers: Optional[list[str]] = None


class CommissionSaleRateUpdate(BaseModel):
    commission_sale_rate: float


class IncludeFeesUpdate(BaseModel):
    include_fees_in_cump: bool


class FXCommissionUpdate(BaseModel):
    monthly_free_eur: Optional[float] = None
    above_monthly_rate: float = 0.0
    weekend_rate: Optional[float] = None


class AccountHoldingOut(BaseModel):
    ticker: str
    product_name: str
    category: Optional[str]
    instrument_type: Optional[str] = None
    quantity: float
    last_price: float
    last_price_date: Optional[date]
    last_price_source: str
    value_eur: float
    currency: str


class AccountSummaryOut(BaseModel):
    id: int
    name: str
    currency: str
    cash_balance_eur: float
    positions: list[AccountHoldingOut]
    positions_value_eur: float
    total_eur: float


@router.get("/", response_model=list[BrokerOut])
async def list_brokers(
    portfolio_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if portfolio_id is not None:
        stmt = (
            select(Broker)
            .join(PortfolioAccount, PortfolioAccount.broker_id == Broker.id)
            .where(PortfolioAccount.portfolio_id == portfolio_id)
            .order_by(Broker.id)
        )
    else:
        stmt = select(Broker).order_by(Broker.id)
    result = await db.execute(stmt)
    brokers = result.scalars().all()
    return [await _broker_out(b, db) for b in brokers]


@router.post("/", response_model=BrokerOut, status_code=201)
async def create_broker(body: BrokerCreate, db: AsyncSession = Depends(get_db)):
    broker = Broker(**body.model_dump(exclude={"portfolio_ids"}))
    db.add(broker)
    await db.flush()
    for pid in body.portfolio_ids:
        db.add(PortfolioAccount(portfolio_id=pid, broker_id=broker.id))
    await db.commit()
    await db.refresh(broker)
    return await _broker_out(broker, db)


class PortfolioIdsUpdate(BaseModel):
    portfolio_ids: list[int]


@router.put("/{broker_id}/portfolios", response_model=BrokerOut)
async def update_broker_portfolios(
    broker_id: int,
    body: PortfolioIdsUpdate,
    db: AsyncSession = Depends(get_db),
):
    broker = await get_or_404(db, Broker.id, broker_id, "Broker not found")
    existing = await db.execute(
        select(PortfolioAccount).where(PortfolioAccount.broker_id == broker_id)
    )
    for link in existing.scalars().all():
        await db.delete(link)
    for pid in body.portfolio_ids:
        db.add(PortfolioAccount(portfolio_id=pid, broker_id=broker_id))
    await db.commit()
    await db.refresh(broker)
    return await _broker_out(broker, db)


@router.put("/{broker_id}", response_model=BrokerOut)
async def update_broker(
    broker_id: int,
    body: BrokerUpdate,
    db: AsyncSession = Depends(get_db),
):
    broker = await get_or_404(db, Broker.id, broker_id, "Broker not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(broker, field, value)
    await db.commit()
    await db.refresh(broker)
    return await _broker_out(broker, db)


@router.delete("/{broker_id}", status_code=204)
async def delete_broker(broker_id: int, db: AsyncSession = Depends(get_db)):
    broker = await get_or_404(db, Broker.id, broker_id, "Broker not found")
    await ensure_unreferenced(
        db, Transaction.account_id, broker_id,
        lambda n: f"Cannot delete: {n} transaction(s) are linked to this broker.",
    )
    await db.delete(broker)
    await db.commit()


@router.put("/{broker_id}/commission", response_model=BrokerOut)
async def update_commission_schedule(
    broker_id: int,
    body: CommissionScheduleUpdate,
    db: AsyncSession = Depends(get_db),
):
    broker = await get_or_404(db, Broker.id, broker_id, "Broker not found")
    broker.commission_schedule = body.commission_schedule
    await db.commit()
    await db.refresh(broker)
    return await _broker_out(broker, db)


@router.put("/{broker_id}/sale-rate", response_model=BrokerOut)
async def update_commission_sale_rate(
    broker_id: int,
    body: CommissionSaleRateUpdate,
    db: AsyncSession = Depends(get_db),
):
    broker = await get_or_404(db, Broker.id, broker_id, "Broker not found")
    broker.commission_sale_rate = body.commission_sale_rate
    await db.commit()
    await db.refresh(broker)
    return await _broker_out(broker, db)


@router.put("/{broker_id}/include-fees", response_model=BrokerOut)
async def update_include_fees_in_cump(
    broker_id: int,
    body: IncludeFeesUpdate,
    db: AsyncSession = Depends(get_db),
):
    broker = await get_or_404(db, Broker.id, broker_id, "Broker not found")
    broker.include_fees_in_cump = body.include_fees_in_cump
    await db.commit()
    await db.refresh(broker)
    return await _broker_out(broker, db)


@router.put("/{broker_id}/fx-commission", response_model=BrokerOut)
async def update_fx_commission(
    broker_id: int,
    body: FXCommissionUpdate,
    db: AsyncSession = Depends(get_db),
):
    broker = await get_or_404(db, Broker.id, broker_id, "Broker not found")
    broker.monthly_free_eur = body.monthly_free_eur
    broker.above_monthly_rate = body.above_monthly_rate
    broker.weekend_rate = body.weekend_rate
    await db.commit()
    await db.refresh(broker)
    return await _broker_out(broker, db)


@router.put("/{broker_id}/allowed-tickers", response_model=BrokerOut)
async def update_allowed_tickers(
    broker_id: int,
    body: AllowedTickersUpdate,
    db: AsyncSession = Depends(get_db),
):
    broker = await get_or_404(db, Broker.id, broker_id, "Broker not found")
    broker.allowed_tickers = body.allowed_tickers
    await db.commit()
    await db.refresh(broker)
    return await _broker_out(broker, db)


@router.get("/summary", response_model=list[AccountSummaryOut])
async def get_accounts_summary(
    portfolio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    # 1. Brokers for this portfolio + their cash balances (from portfolio_accounts)
    pa_result = await db.execute(
        select(PortfolioAccount.broker_id, PortfolioAccount.cash_balance_eur)
        .where(PortfolioAccount.portfolio_id == portfolio_id)
    )
    pa_rows = pa_result.all()
    if not pa_rows:
        return []
    cash_by_broker: dict[int, float] = {r.broker_id: r.cash_balance_eur for r in pa_rows}
    broker_ids = list(cash_by_broker.keys())

    brokers_result = await db.execute(
        select(Broker).where(Broker.id.in_(broker_ids)).order_by(Broker.id)
    )
    brokers = brokers_result.scalars().all()

    # 2. Per-broker positions: sum qty by (account_id, ticker) excluding LIQUIDITE.EURO
    qty_result = await db.execute(
        select(
            Transaction.account_id,
            Transaction.ticker,
            func.sum(Transaction.quantity).label("qty"),
        )
        .where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.type == "Actif",
            Transaction.ticker != "LIQUIDITE.EURO",
        )
        .group_by(Transaction.account_id, Transaction.ticker)
        .having(func.sum(Transaction.quantity) != 0)
    )
    raw_positions: dict[int, dict[str, float]] = {}
    for row in qty_result.all():
        raw_positions.setdefault(row.account_id, {})[row.ticker] = float(row.qty)

    # Adjust forex holdings for fees paid in the foreign currency — per account, since a fee
    # incurred on one account must never adjust another account's forex position.
    all_held_tickers = {t for tickers in raw_positions.values() for t in tickers}
    adjustments = await get_forex_fee_adjustments(
        db, portfolio_id, list(all_held_tickers), group_by_account=True,
    )
    for (account_id, ticker), adj in adjustments.items():
        if adj and ticker in raw_positions.get(account_id, {}):
            raw_positions[account_id][ticker] = max(0.0, raw_positions[account_id][ticker] + adj)

    # 3. Product metadata
    all_tickers: set[str] = set()
    for tickers in raw_positions.values():
        all_tickers.update(tickers.keys())

    products_result = await db.execute(
        select(Product.ticker, Product.name, Product.category, Product.instrument_type)
        .where(Product.ticker.in_(all_tickers))
    )
    product_meta: dict[str, tuple[str, str, str]] = {
        r.ticker: (r.name, r.category, r.instrument_type) for r in products_result.all()
    }

    # 4. Latest prices
    if all_tickers:
        subq = (
            select(AssetPrice.ticker, func.max(AssetPrice.date).label("max_date"))
            .where(AssetPrice.ticker.in_(all_tickers))
            .group_by(AssetPrice.ticker)
            .subquery()
        )
        price_rows = await db.execute(
            select(AssetPrice).join(
                subq,
                (AssetPrice.ticker == subq.c.ticker) & (AssetPrice.date == subq.c.max_date),
            )
        )
        price_meta: dict[str, AssetPrice] = {r.ticker: r for r in price_rows.scalars().all()}
    else:
        price_meta = {}

    spot_rates = await _get_spot_rates(db)

    # 5. Build summary per broker
    summaries = []
    for broker in brokers:
        cash_balance = cash_by_broker.get(broker.id, 0.0)
        tickers_in_broker = raw_positions.get(broker.id, {})
        positions_out: list[AccountHoldingOut] = []
        positions_value = 0.0

        for ticker, raw_qty in tickers_in_broker.items():
            pname, category, instrument_type = product_meta.get(ticker, (ticker, "", ""))
            pm = price_meta.get(ticker)
            price = pm.price if pm else 0.0
            currency = pm.currency if pm else "EUR"

            held = held_quantity(raw_qty, instrument_type)

            if held == 0:
                continue

            if instrument_type == "Or physique":
                value_eur = _to_eur(price, currency, spot_rates)
            else:
                value_eur = r2(held * _to_eur(price, currency, spot_rates))

            positions_value += value_eur
            positions_out.append(AccountHoldingOut(
                ticker=ticker,
                product_name=pname,
                category=category or None,
                instrument_type=instrument_type or None,
                quantity=round(held, 6),
                last_price=round(price, 4),
                last_price_date=pm.date if pm else None,
                last_price_source=pm.source if pm else "unknown",
                value_eur=r2(value_eur),
                currency=currency,
            ))

        positions_out.sort(key=lambda p: p.product_name.lower())

        summaries.append(AccountSummaryOut(
            id=broker.id,
            name=broker.name,
            currency=broker.currency,
            cash_balance_eur=cash_balance,
            positions=positions_out,
            positions_value_eur=r2(positions_value),
            total_eur=r2(cash_balance + positions_value),
        ))

    return summaries
