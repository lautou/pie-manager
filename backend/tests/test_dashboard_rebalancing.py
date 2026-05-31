"""Tests for POST /api/dashboard/rebalancing endpoint."""

import pytest
from datetime import date

from app.models.portfolio import Portfolio
from app.models.broker import Broker
from app.models.product import Product
from app.models.pool import Pool, PoolProduct
from app.models.price import AssetPrice
from app.models.transaction import Transaction
from app.models.snapshot import DailySnapshot, MonthlySnapshot
from app.models.portfolio_account import PortfolioAccount

from tests.helpers import create_portfolio as async_create_portfolio, full_dashboard_setup as _full_setup


# ---------------------------------------------------------------------------
# POST /api/dashboard/rebalancing (lines 402-456)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebalancing_no_pools_returns_404(client, db_session):
    uid = await async_create_portfolio(client, f"Reb-NoPools-{id(db_session)}")
    r = await client.post("/api/dashboard/rebalancing",
                          json={"portfolio_id": uid, "external_injection": 0.0})
    assert r.status_code == 404
    assert "No active pools" in r.json()["detail"]


@pytest.mark.asyncio
async def test_rebalancing_basic(client, db_session):
    setup = await _full_setup(db_session, f"reb-basic-{id(db_session)}")
    uid = setup["portfolio_id"]

    r = await client.post("/api/dashboard/rebalancing",
                          json={"portfolio_id": uid, "external_injection": 0.0})
    assert r.status_code == 200
    data = r.json()
    assert "total_current" in data
    assert "pools" in data
    assert len(data["pools"]) == 2
    assert data["liquidity_available"] == pytest.approx(1000.0)


@pytest.mark.asyncio
async def test_rebalancing_with_injection(client, db_session):
    setup = await _full_setup(db_session, f"reb-inject-{id(db_session)}")
    uid = setup["portfolio_id"]

    injection = 5000.0
    r = await client.post("/api/dashboard/rebalancing",
                          json={"portfolio_id": uid, "external_injection": injection})
    assert r.status_code == 200
    data = r.json()
    assert data["external_injection"] == pytest.approx(injection)
    assert data["total_apport"] == pytest.approx(1000.0 + injection, abs=1.0)
    assert data["total_after"] == pytest.approx(data["total_current"] + data["total_apport"], abs=1.0)


@pytest.mark.asyncio
async def test_rebalancing_injection_amounts_sum_correctly(client, db_session):
    setup = await _full_setup(db_session, f"reb-sum-{id(db_session)}")
    uid = setup["portfolio_id"]

    r = await client.post("/api/dashboard/rebalancing",
                          json={"portfolio_id": uid, "external_injection": 10000.0})
    assert r.status_code == 200
    data = r.json()
    total_injection = sum(p["injection_amount"] for p in data["pools"])
    assert total_injection == pytest.approx(data["total_apport"], abs=1.0)


# ---------------------------------------------------------------------------
# Rebalancing: missing price → ticker skipped (line 488-489)
# and Manuel asset → price IS total value (lines 493-495)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebalancing_ticker_with_no_price_is_skipped(client, db_session):
    """
    A pool with two tickers: one has no price (line 488 guard triggers continue),
    one has a price. Pool value = only the priced ticker's contribution.
    """
    uid = await async_create_portfolio(client, f"reb-noprice-{id(db_session)}")
    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker_nopr = f"NO.PRICE.{uid}"
    ticker_priced = f"PRICED.{uid}"
    db_session.add(Product(ticker=ticker_nopr, name="No Price ETF", category="Actif", currency="EUR"))
    db_session.add(Product(ticker=ticker_priced, name="Priced ETF", category="Actif", currency="EUR"))

    pool = Pool(portfolio_id=uid, name="TestPool", strategy="Offensive", target_pct=1.0, is_active=True)
    db_session.add(pool)
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=pool.id, ticker=ticker_nopr))
    db_session.add(PoolProduct(pool_id=pool.id, ticker=ticker_priced))

    for ticker in (ticker_nopr, ticker_priced):
        db_session.add(Transaction(
            portfolio_id=uid, account_id=account.id, date=date(2025, 3, 1),
            type="Actif", ticker=ticker, currency="EUR", exchange_rate=1.0,
            quantity=-10.0, unit_price=50.0, unit_price_eur=50.0,
            total_amount=-500.0, total_amount_eur=-500.0,
        ))
    # Only ticker_priced has a price → ticker_nopr is skipped (line 488-489)
    db_session.add(AssetPrice(ticker=ticker_priced, date=date(2025, 3, 1),
                              price=55.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.post("/api/dashboard/rebalancing",
                          json={"portfolio_id": uid, "external_injection": 0.0})
    assert r.status_code == 200
    data = r.json()
    # Pool value = 10 × 55 = 550€ (no-price ticker skipped)
    assert len(data["pools"]) == 1
    assert data["pools"][0]["current_value"] == pytest.approx(550.0, rel=1e-2)


@pytest.mark.asyncio
async def test_rebalancing_manuel_asset_uses_price_as_total_value(client, db_session):
    """
    Manuel category assets (OR.PHYSIQUE): price in asset_prices IS the total
    portfolio value, not a per-unit price. Lines 493-495: val += price_eur.
    """
    uid = await async_create_portfolio(client, f"reb-manuel-{id(db_session)}")
    account = Broker(name="Test", currency="EUR")
    db_session.add(account)

    ticker = f"OR.PHYS.{uid}"
    db_session.add(Product(ticker=ticker, name="Or physique", category="Manuel", currency="EUR"))

    pool = Pool(portfolio_id=uid, name="Or", strategy="Defensive", target_pct=1.0, is_active=True)
    db_session.add(pool)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    db_session.add(PoolProduct(pool_id=pool.id, ticker=ticker))

    # Manuel: price = total value (e.g. 8000€ worth of gold)
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 4, 1),
                              price=8000.0, currency="EUR", source="manual"))
    await db_session.flush()

    r = await client.post("/api/dashboard/rebalancing",
                          json={"portfolio_id": uid, "external_injection": 0.0})
    assert r.status_code == 200
    data = r.json()
    # Manuel: current_value = 8000€ (price directly, not qty × price)
    assert data["pools"][0]["current_value"] == pytest.approx(8000.0, rel=1e-2)
