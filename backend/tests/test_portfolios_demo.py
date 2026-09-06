# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for POST /api/portfolios/demo — the fictional demo-portfolio generator.
"""
from datetime import date as date_cls

import pytest
from sqlalchemy import select

from app.models.broker import Broker
from app.models.portfolio_account import PortfolioAccount
from app.models.pool import Pool, PoolProduct
from app.models.product import Product
from app.models.price import AssetPrice
from app.models.transaction import Transaction

# Schedules matching this app's own real shapes (confirmed against real brokers this session):
# Degiro-style single flat fee applied regardless of trade amount, and IBKR-style tiered
# schedule (a small amount must skip past the first tier to exercise the loop-continue branch).
FLAT_SCHEDULE = [{"type": "flat", "up_to": None, "value": 3.0}]
TIERED_SCHEDULE = [
    {"type": "flat", "up_to": 100, "value": 1.25},
    {"type": "percent", "up_to": 10_000, "value": 0.00015},
    {"type": "flat", "up_to": None, "value": 29.0},
]


async def _seed_broker_and_products(db_session, commission_schedule=None):
    broker = Broker(name="DemoBroker", currency="EUR", is_cto=True,
                     commission_schedule=commission_schedule)
    db_session.add(broker)
    await db_session.flush()

    etf = Product(ticker="DEMO.ETF", name="Demo ETF", category="Actif",
                   instrument_type="ETF", currency="EUR")
    gold = Product(ticker="DEMO.GOLD", name="Demo Gold", category="Actif",
                    instrument_type="Or physique", currency="EUR")
    # A 3rd, non-ETF/non-gold example so the "regular asset, no sell" branch (only the ETF
    # is the designated with_sell asset) gets real coverage too, not just the two special cases.
    action = Product(ticker="DEMO.ACTION", name="Demo Action", category="Actif",
                      instrument_type="Action", currency="EUR")
    db_session.add_all([etf, gold, action])
    await db_session.flush()
    db_session.add(AssetPrice(ticker="DEMO.ETF", date=date_cls(2026, 1, 1), price=50.0, currency="EUR"))
    await db_session.flush()
    await db_session.commit()
    return broker


@pytest.mark.asyncio
async def test_demo_portfolio_empty_install(client):
    """No brokers, no products at all: still creates a portfolio with 2 pools, no crash."""
    r = await client.post("/api/portfolios/demo")
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Démo"


@pytest.mark.asyncio
async def test_demo_portfolio_links_all_brokers_and_pools(client, db_session):
    broker = await _seed_broker_and_products(db_session)

    r = await client.post("/api/portfolios/demo")
    assert r.status_code == 201
    pid = r.json()["id"]

    links = (await db_session.execute(
        select(PortfolioAccount).where(PortfolioAccount.portfolio_id == pid)
    )).scalars().all()
    assert len(links) == 1
    assert links[0].broker_id == broker.id

    pools = (await db_session.execute(select(Pool).where(Pool.portfolio_id == pid))).scalars().all()
    strategies = {p.strategy for p in pools}
    assert strategies == {"Offensive", "Defensive"}


@pytest.mark.asyncio
async def test_demo_portfolio_seeds_cash_and_example_products(client, db_session):
    broker = await _seed_broker_and_products(db_session)

    r = await client.post("/api/portfolios/demo")
    pid = r.json()["id"]

    account = (await db_session.execute(
        select(PortfolioAccount).where(
            PortfolioAccount.portfolio_id == pid, PortfolioAccount.broker_id == broker.id,
        )
    )).scalar_one()
    assert account.cash_balance_eur < 10_000.0
    assert account.cash_balance_eur > 0  # purchases must not overdraw the demo deposit

    # LIQUIDITE.EURO and FRAIS.COURTAGE.EUR auto-created since this install had neither.
    for ticker in ("LIQUIDITE.EURO", "FRAIS.COURTAGE.EUR"):
        assert (await db_session.execute(
            select(Product).where(Product.ticker == ticker)
        )).scalar_one_or_none() is not None

    # Both example products got linked into a pool.
    tickers = {pp.ticker for pp in (await db_session.execute(
        select(PoolProduct).join(Pool).where(Pool.portfolio_id == pid)
    )).scalars().all()}
    assert tickers == {"DEMO.ETF", "DEMO.GOLD", "DEMO.ACTION"}


@pytest.mark.asyncio
async def test_demo_portfolio_seeds_two_buys_per_asset_and_one_sell(client, db_session):
    """A single buy would make CUMP trivially equal to that one price — this asserts the
    richer sample (2 buys at different prices/dates, plus a partial sell on the ETF) is
    actually there, not just "some transactions exist"."""
    await _seed_broker_and_products(db_session)

    r = await client.post("/api/portfolios/demo")
    pid = r.json()["id"]

    etf_buys = (await db_session.execute(
        select(Transaction).where(
            Transaction.portfolio_id == pid, Transaction.ticker == "DEMO.ETF",
            Transaction.operation == "Achat",
        )
    )).scalars().all()
    assert len(etf_buys) == 2
    assert etf_buys[0].unit_price != etf_buys[1].unit_price  # distinct prices → real CUMP averaging
    assert etf_buys[0].date != etf_buys[1].date

    etf_sells = (await db_session.execute(
        select(Transaction).where(
            Transaction.portfolio_id == pid, Transaction.ticker == "DEMO.ETF",
            Transaction.operation == "Vente",
        )
    )).scalars().all()
    assert len(etf_sells) == 1
    assert etf_sells[0].quantity > 0  # Sell convention: quantity > 0

    gold_buys = (await db_session.execute(
        select(Transaction).where(
            Transaction.portfolio_id == pid, Transaction.ticker == "DEMO.GOLD",
            Transaction.operation == "Achat",
        )
    )).scalars().all()
    assert len(gold_buys) == 2
    # Or physique never sells in this seed (kept simple — only the ETF demonstrates realized PV).
    assert (await db_session.execute(
        select(Transaction).where(
            Transaction.portfolio_id == pid, Transaction.ticker == "DEMO.GOLD",
            Transaction.operation == "Vente",
        )
    )).scalars().all() == []

    # A regular (non-ETF, non-gold) asset: 2 buys, no sell — the "with_sell=False, not
    # Or physique" branch.
    action_buys = (await db_session.execute(
        select(Transaction).where(
            Transaction.portfolio_id == pid, Transaction.ticker == "DEMO.ACTION",
            Transaction.operation == "Achat",
        )
    )).scalars().all()
    assert len(action_buys) == 2
    assert (await db_session.execute(
        select(Transaction).where(
            Transaction.portfolio_id == pid, Transaction.ticker == "DEMO.ACTION",
            Transaction.operation == "Vente",
        )
    )).scalars().all() == []


@pytest.mark.asyncio
async def test_demo_portfolio_creates_linked_courtage_fees_from_real_schedule(client, db_session):
    """Every buy/sell gets a linked courtage Frais transaction sized from the broker's own
    real commission_schedule — a demo isn't exempt from looking realistic."""
    await _seed_broker_and_products(db_session, commission_schedule=FLAT_SCHEDULE)

    r = await client.post("/api/portfolios/demo")
    pid = r.json()["id"]

    fee_txs = (await db_session.execute(
        select(Transaction).where(Transaction.portfolio_id == pid, Transaction.ticker == "FRAIS.COURTAGE.EUR")
    )).scalars().all()
    # 2 buys + 1 sell (ETF, the with_sell asset) + 2 buys (gold) + 2 buys (action) = 7 trades.
    assert len(fee_txs) == 7
    assert all(tx.total_amount_eur == -3.0 for tx in fee_txs)
    assert all(tx.linked_transaction_id is not None for tx in fee_txs)


@pytest.mark.asyncio
async def test_demo_portfolio_tiered_commission_schedule(client, db_session):
    """A trade amount past the first tier's `up_to` must fall through to the next tier —
    exercises the schedule's loop-continue branch, not just a single-tier match."""
    await _seed_broker_and_products(db_session, commission_schedule=TIERED_SCHEDULE)

    r = await client.post("/api/portfolios/demo")
    pid = r.json()["id"]

    fee_txs = (await db_session.execute(
        select(Transaction).where(Transaction.portfolio_id == pid, Transaction.ticker == "FRAIS.COURTAGE.EUR")
    )).scalars().all()
    assert len(fee_txs) == 7
    # Every seeded trade here is well above the 100€ first tier's cap, so all fall through to
    # the 0.015% percent tier — never the first tier's flat 1.25€ value.
    assert all(tx.total_amount_eur != -1.25 for tx in fee_txs)


@pytest.mark.asyncio
async def test_demo_portfolio_no_fee_transactions_without_a_schedule(client, db_session):
    """A broker with no commission_schedule (e.g. this install's real BNP Paribas/Revolut)
    must not get fabricated fee transactions — _estimate_commission returns 0."""
    await _seed_broker_and_products(db_session, commission_schedule=None)

    r = await client.post("/api/portfolios/demo")
    pid = r.json()["id"]

    fee_txs = (await db_session.execute(
        select(Transaction).where(Transaction.portfolio_id == pid, Transaction.ticker == "FRAIS.COURTAGE.EUR")
    )).scalars().all()
    assert fee_txs == []


@pytest.mark.asyncio
async def test_demo_portfolio_or_physique_convention(client, db_session):
    """Or physique: quantity always -1 per lot, unit_price carries each lot's total value."""
    await _seed_broker_and_products(db_session)

    r = await client.post("/api/portfolios/demo")
    pid = r.json()["id"]

    txs = (await db_session.execute(
        select(Transaction).where(Transaction.portfolio_id == pid, Transaction.ticker == "DEMO.GOLD")
    )).scalars().all()
    assert len(txs) == 2
    assert all(tx.quantity == -1.0 for tx in txs)
    assert {tx.unit_price for tx in txs} == {500.0, 350.0}


@pytest.mark.asyncio
async def test_demo_portfolio_reruns_with_unique_name(client, db_session):
    await _seed_broker_and_products(db_session)

    first = await client.post("/api/portfolios/demo")
    second = await client.post("/api/portfolios/demo")

    assert first.json()["name"] == "Démo"
    assert second.json()["name"] == "Démo (2)"
