# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations
from datetime import date as Date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pgqueuer import Queries
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from pydantic import BaseModel, ConfigDict, field_serializer

from app.core.database import get_db
from app.core.pgq import get_pgq_queries
from app.models import Portfolio, Broker, PortfolioAccount, Pool, PoolProduct, Product
from app.models.price import AssetPrice
from app.utils.datetime_utils import to_utc_iso
from app.api.deps import get_or_404
from app.services.transaction_service import TransactionCreate, create_transaction_core, trigger_snapshot_recompute

router = APIRouter(tags=["portfolios"])

CASH_TICKER = "LIQUIDITE.EURO"
DEMO_DEPOSIT_EUR = 10_000.0
DEMO_PURCHASE_TARGET_EUR = 3_000.0
# Or physique's own convention (see the root CLAUDE.md's "Transaction conventions"): quantity
# is always 1 (one purchase lot) and unit_price carries the *total* value, not a per-unit price.
DEMO_OR_PHYSIQUE_LOT_EUR = 500.0


class PortfolioCreate(BaseModel):
    name: str


class PortfolioRename(BaseModel):
    name: str


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: Optional[datetime] = None

    @field_serializer("created_at")
    def _serialize_created_at(self, dt: Optional[datetime]) -> Optional[str]:
        return to_utc_iso(dt)


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


async def _unique_demo_name(db: AsyncSession) -> str:
    """"Démo" first, then "Démo (2)", "Démo (3)"... so the generator is safely re-runnable."""
    base_name = "Démo"
    name = base_name
    suffix = 2
    while (await db.execute(select(Portfolio).where(Portfolio.name == name))).scalar_one_or_none():
        name = f"{base_name} ({suffix})"
        suffix += 1
    return name


async def _get_or_create_product(db: AsyncSession, ticker: str, name: str, category: str, **fields) -> None:
    """Neither LIQUIDITE.EUR nor FRAIS.COURTAGE.EUR is seeded by any migration — a real
    install only gets them the first time a user manually creates one (via the Products UI)
    or enters a transaction that needs it. A brand-new install (zero real transactions yet)
    may have neither, but the demo's deposit/fee transactions need them to exist first."""
    existing = await db.execute(select(Product).where(Product.ticker == ticker))
    if existing.scalar_one_or_none() is None:
        db.add(Product(ticker=ticker, name=name, category=category, **fields))
        await db.flush()


async def _pick_example_products(db: AsyncSession) -> list[Product]:
    """One already-existing product per instrument_type present in this install's own
    catalogue (excluding Cash, which is funding plumbing, not an investment example) — reusing
    real tickers means they already have real Yahoo-synced price history, so the demo
    portfolio's valuation/PV is genuinely functional instead of showing "prix inconnu"."""
    types = await db.execute(
        select(Product.instrument_type)
        .where(Product.category == "Actif", Product.instrument_type.isnot(None),
               Product.instrument_type != "Cash")
        .distinct()
    )
    products: list[Product] = []
    for (instrument_type,) in types.all():
        row = await db.execute(
            select(Product)
            .where(Product.category == "Actif", Product.instrument_type == instrument_type)
            .order_by(Product.ticker)
            .limit(1)
        )
        products.append(row.scalar_one())
    return products


async def _latest_price(db: AsyncSession, ticker: str) -> float | None:
    row = await db.execute(
        select(AssetPrice.price).where(AssetPrice.ticker == ticker).order_by(AssetPrice.date.desc()).limit(1)
    )
    return row.scalar_one_or_none()


def _estimate_commission(broker: Broker, amount_eur: float) -> float:
    """Real per-broker tiered schedule already stored on Broker.commission_schedule — a list
    of {type: "flat"|"percent", up_to: float|None, value: float} tiers ordered by `up_to`
    ascending (None = last, uncapped tier). Confirmed shape against this install's own real
    brokers this session (e.g. Degiro: a single flat 3€ tier; IBKR: 3 amount-based tiers).
    Mirrors the intent of the frontend's commission.ts without duplicating its full surface —
    this only needs "estimate a fee for one seed trade", not the full manual-entry UI logic."""
    for tier in broker.commission_schedule or []:
        if tier["up_to"] is None or amount_eur <= tier["up_to"]:
            return round(amount_eur * tier["value"], 2) if tier["type"] == "percent" else round(tier["value"], 2)
    return 0.0


async def _seed_asset_transactions(
    db: AsyncSession, portfolio_id: int, broker: Broker, product: Product, with_sell: bool,
) -> None:
    """A small, fixed, deterministic sample per asset — not a rich history: 2 buys at
    different dates/prices (so CUMP/WACOP averaging is actually visible, unlike a single buy
    which trivially makes CUMP equal to that one price), and for the one designated
    `with_sell` asset, a partial sell afterward so the Capital Gains page's "Historique des
    cessions"/realized-PV feature has something real to show too, not just latent positions.
    Every linked courtage fee is estimated from the broker's own real schedule, same as any
    other transaction in this DB — a demo isn't exempt from looking realistic."""
    today = Date.today()

    if product.instrument_type == "Or physique":
        # Its own convention (root CLAUDE.md "Transaction conventions"): quantity is always
        # ±1 per lot, unit_price carries that lot's *total* value, never a per-unit price.
        for days_ago, lot_eur in ((90, DEMO_OR_PHYSIQUE_LOT_EUR), (45, DEMO_OR_PHYSIQUE_LOT_EUR * 0.7)):
            await create_transaction_core(TransactionCreate(
                portfolio_id=portfolio_id, account_id=broker.id, date=today - timedelta(days=days_ago),
                type="Actif", operation="Achat", ticker=product.ticker, currency=product.currency,
                exchange_rate=1.0, quantity=-1.0, unit_price=lot_eur,
                courtage_eur=_estimate_commission(broker, lot_eur),
            ), db)
        return

    latest_price = await _latest_price(db, product.ticker) or 100.0
    buy1_price, buy2_price = round(latest_price * 0.95, 4), round(latest_price * 0.98, 4)
    buy1_amount, buy2_amount = DEMO_PURCHASE_TARGET_EUR * 0.6, DEMO_PURCHASE_TARGET_EUR * 0.4
    buy1_qty = max(1.0, round(buy1_amount / buy1_price, 4))
    buy2_qty = max(1.0, round(buy2_amount / buy2_price, 4))

    for days_ago, qty, price in ((90, buy1_qty, buy1_price), (45, buy2_qty, buy2_price)):
        amount = qty * price
        await create_transaction_core(TransactionCreate(
            portfolio_id=portfolio_id, account_id=broker.id, date=today - timedelta(days=days_ago),
            type="Actif", operation="Achat", ticker=product.ticker, currency=product.currency,
            exchange_rate=1.0, quantity=-qty, unit_price=price,
            courtage_eur=_estimate_commission(broker, amount),
        ), db)

    if with_sell:
        sell_price = round(latest_price * 1.02, 4)
        sell_qty = round((buy1_qty + buy2_qty) * 0.3, 4)
        await create_transaction_core(TransactionCreate(
            portfolio_id=portfolio_id, account_id=broker.id, date=today - timedelta(days=15),
            type="Actif", operation="Vente", ticker=product.ticker, currency=product.currency,
            exchange_rate=1.0, quantity=sell_qty, unit_price=sell_price,
            courtage_eur=_estimate_commission(broker, sell_qty * sell_price),
        ), db)


@router.post("/demo", response_model=PortfolioOut, status_code=201)
async def create_demo_portfolio(
    db: AsyncSession = Depends(get_db),
    queries: Queries = Depends(get_pgq_queries),
):
    """Generate a small, fictional portfolio mirroring this install's own real structure
    (same brokers, same pool strategy, one example asset per instrument category already in
    the catalogue, each with a small realistic transaction sample) — lets a user (or a new
    visitor to this open-source app) explore the app's features without entering real
    financial data. Every transaction goes through create_transaction_core, same as any real
    one (WACOP/cash-balance/fee logic), per this project's "all data entry funnels through the
    same create-transaction path" rule.
    """
    portfolio = Portfolio(name=await _unique_demo_name(db))
    db.add(portfolio)
    await db.flush()

    offensive = Pool(portfolio_id=portfolio.id, name="Offensif", strategy="Offensive", target_pct=0.6)
    defensive = Pool(portfolio_id=portfolio.id, name="Défensif", strategy="Defensive", target_pct=0.4)
    db.add_all([offensive, defensive])

    brokers = (await db.execute(select(Broker).order_by(Broker.id))).scalars().all()
    for broker in brokers:
        db.add(PortfolioAccount(portfolio_id=portfolio.id, broker_id=broker.id))
    await db.flush()

    if brokers:
        await _get_or_create_product(db, CASH_TICKER, "Liquidités EUR", "Actif", instrument_type="Cash", currency="EUR")
        await _get_or_create_product(db, "FRAIS.COURTAGE.EUR", "Frais de courtage EUR", "Frais", fee_type="Courtage")
        deposit_date = Date.today() - timedelta(days=120)
        for broker in brokers:
            await create_transaction_core(TransactionCreate(
                portfolio_id=portfolio.id, account_id=broker.id, date=deposit_date,
                type="Actif", operation="Achat", ticker=CASH_TICKER, currency="EUR",
                exchange_rate=1.0, quantity=DEMO_DEPOSIT_EUR, unit_price=1.0,
            ), db)

        example_products = await _pick_example_products(db)
        # The one example asset that also gets a partial sell, to demonstrate realized PV —
        # an ETF if one was picked (most realistic case for an active sale), else the first
        # non-physical-gold example (Or physique keeps its own lot-only seeding above).
        sell_idx = next(
            (i for i, p in enumerate(example_products) if p.instrument_type == "ETF"),
            next((i for i, p in enumerate(example_products) if p.instrument_type != "Or physique"), None),
        )
        for i, product in enumerate(example_products):
            broker = brokers[i % len(brokers)]
            pool = offensive if i % 2 == 0 else defensive
            await _seed_asset_transactions(db, portfolio.id, broker, product, with_sell=(i == sell_idx))
            db.add(PoolProduct(pool_id=pool.id, ticker=product.ticker))

    await db.commit()
    await db.refresh(portfolio)
    await trigger_snapshot_recompute(portfolio.id, Date.today() - timedelta(days=120), queries)
    return portfolio


@router.get("/{portfolio_id}", response_model=PortfolioOut)
async def get_portfolio(portfolio_id: int, db: AsyncSession = Depends(get_db)):
    return await get_or_404(db, Portfolio.id, portfolio_id, "Portfolio not found")


@router.put("/{portfolio_id}", response_model=PortfolioOut)
async def rename_portfolio(portfolio_id: int, body: PortfolioRename, db: AsyncSession = Depends(get_db)):
    portfolio = await get_or_404(db, Portfolio.id, portfolio_id, "Portfolio not found")
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
    portfolio = await get_or_404(db, Portfolio.id, portfolio_id, "Portfolio not found")

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
