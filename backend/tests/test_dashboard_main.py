# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for GET /api/dashboard/ — main dashboard endpoint."""

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
# GET /api/dashboard/?portfolio_id=N (lines 97-187)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard_no_pools_returns_empty(client, db_session):
    uid = await (async_create_portfolio(client, f"Dash-NoPools-{id(db_session)}"))
    r = await client.get("/api/dashboard/", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert data["total_eur"] == 0.0
    assert data["pools"] == []
    assert data["liquidity_eur"] == 0.0
    assert data["last_updated"] is None


@pytest.mark.asyncio
async def test_dashboard_with_pools_and_prices(client, db_session):
    setup = await _full_setup(db_session, str(id(db_session)))
    uid = setup["portfolio_id"]

    r = await client.get("/api/dashboard/", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert data["total_eur"] > 0
    assert len(data["pools"]) == 2
    # 10 units × 110 EUR = 1100 each, + 1000 liquidity = 3200 total
    assert data["total_eur"] == pytest.approx(3200.0, abs=1.0)
    assert data["liquidity_eur"] == pytest.approx(1000.0)


@pytest.mark.asyncio
async def test_dashboard_pool_current_pct(client, db_session):
    setup = await _full_setup(db_session, f"pct-{id(db_session)}")
    uid = setup["portfolio_id"]

    r = await client.get("/api/dashboard/", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    # Both pools have ~same value, check pcts are reasonable
    for pool in data["pools"]:
        assert 0.0 <= pool["current_pct"] <= 100.0
        assert isinstance(pool["gap_pct"], float)


@pytest.mark.asyncio
async def test_dashboard_last_updated_from_snapshot(client, db_session):
    setup = await _full_setup(db_session, f"lastup-{id(db_session)}")
    uid = setup["portfolio_id"]

    r = await client.get("/api/dashboard/", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert data["last_updated"] == "2025-01-10"


@pytest.mark.asyncio
async def test_dashboard_no_snapshot_last_updated_none(client, db_session):
    """If no DailySnapshot exists, last_updated should be null."""
    suffix = f"nosnap-{id(db_session)}"
    portfolio = Portfolio(name=f"DashNoSnap-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    ticker = f"NS.{suffix}"
    db_session.add(Product(ticker=ticker, name="ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    pool = Pool(portfolio_id=uid, name="Pool", strategy="Offensive",
                target_pct=1.0, is_active=True)
    db_session.add(pool)
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=pool.id, ticker=ticker))
    await db_session.flush()

    r = await client.get("/api/dashboard/", params={"portfolio_id": uid})
    assert r.status_code == 200
    assert r.json()["last_updated"] is None


@pytest.mark.asyncio
async def test_dashboard_offensive_defensive_split(client, db_session):
    setup = await _full_setup(db_session, f"offdef-{id(db_session)}")
    uid = setup["portfolio_id"]

    r = await client.get("/api/dashboard/", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert data["offensive_eur"] == pytest.approx(1100.0, abs=1.0)
    assert data["defensive_eur"] == pytest.approx(1100.0, abs=1.0)


@pytest.mark.asyncio
async def test_dashboard_manuel_category_pool(client, db_session):
    """Manuel products: price IS the total value (not per unit)."""
    suffix = f"manuel-{id(db_session)}"
    portfolio = Portfolio(name=f"DashManuel-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Perso", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"OR.{suffix}"
    db_session.add(Product(ticker=ticker, name="Or", category="Actif", instrument_type="Or physique", currency="EUR"))
    await db_session.flush()

    pool = Pool(portfolio_id=uid, name="Or Pool", strategy="Defensive",
                target_pct=1.0, is_active=True)
    db_session.add(pool)
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=pool.id, ticker=ticker))
    await db_session.flush()

    # For Manuel, price = total value
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 1, 15),
                               price=5000.0, currency="EUR", source="manual"))
    await db_session.flush()

    r = await client.get("/api/dashboard/", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert data["total_eur"] == pytest.approx(5000.0, abs=1.0)


# ===========================================================================
# NEW TESTS — targeting missing coverage lines
# ===========================================================================

# ---------------------------------------------------------------------------
# Line 40: _get_latest_prices returns {} when called with empty tickers list.
# Triggered in GET /api/dashboard/ when active pools exist but have no products.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard_pools_with_no_products_uses_empty_prices(client, db_session):
    """
    Line 40: _get_latest_prices(db, []) → return {}

    Create a user with an active pool but attach zero products to it.
    The dashboard still runs; all_tickers is empty, so _get_latest_prices
    is called with [] and immediately returns {}.
    """
    suffix = f"noprod-{id(db_session)}"
    portfolio = Portfolio(name=f"DashNoProd-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=500.0))
    await db_session.flush()

    # Ensure LIQUIDITE.EURO product exists and add a cash deposit transaction
    liq_ticker = "LIQUIDITE.EURO"
    from sqlalchemy import select as sa_select
    existing_liq = await db_session.execute(sa_select(Product).where(Product.ticker == liq_ticker))
    if not existing_liq.scalar_one_or_none():
        db_session.add(Product(ticker=liq_ticker, name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
        await db_session.flush()
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 1, 1), type="Actif", ticker=liq_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=500.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=500.0, total_amount_eur=500.0,
    ))

    # Pool with no products attached
    pool = Pool(portfolio_id=uid, name="EmptyPool", strategy="Offensive",
                target_pct=1.0, is_active=True)
    db_session.add(pool)
    await db_session.flush()
    # No PoolProduct rows → all_tickers == set() → _get_latest_prices([]) → line 40

    r = await client.get("/api/dashboard/", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    # One pool, no value from products, only liquidity
    assert len(data["pools"]) == 1
    assert data["pools"][0]["current_value_eur"] == pytest.approx(0.0)
    assert data["liquidity_eur"] == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Line 146: dashboard / get_dashboard — LIQUIDITE.EURO in pool products is skipped.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard_liquidite_euro_in_pool_is_skipped(client, db_session):
    """
    Line 146: ticker == "LIQUIDITE.EURO" → continue (skipped in pool value calc).

    Assign LIQUIDITE.EURO as a PoolProduct.  The dashboard should compute
    pool_val for that pool as 0 (only liquidity is tracked separately).
    """
    suffix = f"liqpool-{id(db_session)}"
    portfolio = Portfolio(name=f"DashLiq-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=1000.0))
    await db_session.flush()

    liq_ticker = "LIQUIDITE.EURO"
    from sqlalchemy import select as sa_select
    existing = await db_session.execute(sa_select(Product).where(Product.ticker == liq_ticker))
    if not existing.scalar_one_or_none():
        db_session.add(Product(ticker=liq_ticker, name="Cash EUR",
                                category="Actif", instrument_type="Cash", currency="EUR"))
        await db_session.flush()

    # Add a cash deposit so _get_liquidity_eur returns 1000
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 1, 1), type="Actif", ticker=liq_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=1000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=1000.0, total_amount_eur=1000.0,
    ))
    await db_session.flush()

    pool = Pool(portfolio_id=uid, name="LiqPool", strategy="Offensive",
                target_pct=1.0, is_active=True)
    db_session.add(pool)
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=pool.id, ticker=liq_ticker))
    await db_session.flush()

    r = await client.get("/api/dashboard/", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    # Pool value should be 0 because LIQUIDITE.EURO is skipped (line 146)
    assert data["pools"][0]["current_value_eur"] == pytest.approx(0.0)
    # Liquidity is tracked separately
    assert data["liquidity_eur"] == pytest.approx(1000.0)


# ===========================================================================
# ADDITIONAL COVERAGE TESTS — targeting remaining missing lines
# ===========================================================================

# ---------------------------------------------------------------------------
# Lines 150-209 (dashboard): pool value computation with FX / non-EUR ticker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard_non_eur_ticker_with_spot_rate(client, db_session):
    """
    Dashboard pool value calculation with a non-EUR asset requiring _to_eur conversion.
    Covers the spot_rates path in pool value computation (lines 150-209).
    """
    suffix = f"fxpool-{id(db_session)}"
    portfolio = Portfolio(name=f"DashFX-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="IBKR", currency="USD")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    from sqlalchemy import select as sa_select
    liq_ticker = "LIQUIDITE.EURO"
    existing = await db_session.execute(sa_select(Product).where(Product.ticker == liq_ticker))
    if not existing.scalar_one_or_none():
        db_session.add(Product(ticker=liq_ticker, name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
        await db_session.flush()

    # USD-priced ETF
    ticker = f"AAPL.FX.{suffix}"
    db_session.add(Product(ticker=ticker, name="Apple", category="Actif", currency="USD"))
    await db_session.flush()

    pool = Pool(portfolio_id=uid, name="US Stocks", strategy="Offensive",
                target_pct=1.0, is_active=True)
    db_session.add(pool)
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=pool.id, ticker=ticker))
    await db_session.flush()

    # Buy 5 shares
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 3, 3), type="Actif", ticker=ticker,
        currency="USD", exchange_rate=0.92,
        quantity=-5.0, unit_price=200.0, unit_price_eur=184.0,
        total_amount=-1000.0, total_amount_eur=-920.0,
    ))
    await db_session.flush()

    # Ensure USDEUR=X product exists (required by FK constraint on asset_prices.ticker)
    fx_ticker = "USDEUR=X"
    existing_fx = await db_session.execute(sa_select(Product).where(Product.ticker == fx_ticker))
    if not existing_fx.scalar_one_or_none():
        db_session.add(Product(ticker=fx_ticker, name="USD/EUR", category="Actif", instrument_type="Cash", currency="EUR"))
        await db_session.flush()

    # Asset price in USD
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 3, 3),
                               price=200.0, currency="USD", source="yfinance"))
    # Spot rate USDEUR=X
    db_session.add(AssetPrice(ticker=fx_ticker, date=date(2025, 3, 3),
                               price=0.92, currency="EUR", source="yfinance"))
    await db_session.flush()

    r = await client.get("/api/dashboard/", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data["pools"]) == 1
    # 5 units × 200 USD × 0.92 EUR/USD = 920 EUR
    assert data["pools"][0]["current_value_eur"] == pytest.approx(920.0, rel=0.01)


# ---------------------------------------------------------------------------
# Lines 213-232: dashboard pool_dashboards computation with total_eur == 0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard_total_zero_gives_zero_current_pct(client, db_session):
    """
    Line 217: if total_eur == 0 → current_pct = 0.0 (edge case when no price data).
    Pool with a product but no prices → pool_val = 0, total_eur = 0.
    """
    suffix = f"zero-total-{id(db_session)}"
    portfolio = Portfolio(name=f"DashZero-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"NOPRICE3.{suffix}"
    db_session.add(Product(ticker=ticker, name="Unpriced", category="Actif", currency="EUR"))
    await db_session.flush()

    pool = Pool(portfolio_id=uid, name="Pool", strategy="Offensive",
                target_pct=1.0, is_active=True)
    db_session.add(pool)
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=pool.id, ticker=ticker))
    await db_session.flush()

    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 4, 1), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-10.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    await db_session.flush()
    # No AssetPrice → pool_val = 0 → total_eur = 0 → current_pct = 0 (line 217)

    r = await client.get("/api/dashboard/", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert data["total_eur"] == pytest.approx(0.0)
    assert data["pools"][0]["current_pct"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _get_liquidity_eur regression — must use cash_balance_eur, not LIQUIDITE.EURO
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_liquidity_uses_account_cash_balance_not_liquidite_transactions(client, db_session):
    """
    Regression: the old _get_liquidity_eur() summed LIQUIDITE.EURO transactions,
    returning all historical deposits (~209 k€) instead of the real current
    cash balance (~547 €).

    The fix uses SUM(account.cash_balance_eur) which is the same source as the
    Comptes page.  This test verifies:
    - liquidity_eur = SUM(cash_balance_eur) across accounts
    - NOT the sum of LIQUIDITE.EURO transactions
    """
    uid = id(db_session)
    portfolio = Portfolio(name=f"LiqFix-{uid}")
    db_session.add(portfolio)
    await db_session.flush()

    # Two accounts with known cash balances (total = 547.49 €)
    acc1 = Broker(name="IBKR", currency="EUR")
    acc2 = Broker(name="Degiro", currency="EUR")
    db_session.add_all([acc1, acc2])
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=portfolio.id, broker_id=acc1.id, cash_balance_eur=500.00))
    db_session.add(PortfolioAccount(portfolio_id=portfolio.id, broker_id=acc2.id, cash_balance_eur=47.49))
    await db_session.flush()

    # Add a pool so the dashboard endpoint doesn't return early
    pool = Pool(portfolio_id=portfolio.id, name="Asie", strategy="Offensive",
                target_pct=1.0, is_active=True)
    db_session.add(pool)
    await db_session.flush()

    # Add LIQUIDITE.EURO transactions with a MUCH larger sum (the old bug)
    # Historical deposits: 100 000 € deposited over time...
    fake_liq = Product(ticker=f"LIQUIDITE.EURO", name="Cash",
                       category="Actif", instrument_type="Cash", currency="EUR")
    db_session.add(fake_liq)
    await db_session.flush()
    db_session.add(Transaction(
        portfolio_id=portfolio.id, account_id=acc1.id,
        date=date(2024, 1, 1), type="Actif", ticker="LIQUIDITE.EURO",
        currency="EUR", exchange_rate=1.0,
        quantity=100000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=100000.0, total_amount_eur=100000.0,
    ))
    await db_session.flush()

    r = await client.get("/api/dashboard/", params={"portfolio_id": portfolio.id})
    assert r.status_code == 200
    data = r.json()

    # Must reflect cash_balance_eur total (547.49), NOT the LIQUIDITE.EURO sum (100 000)
    assert abs(data["liquidity_eur"] - 547.49) < 0.01, (
        f"Expected ~547.49 (sum of cash_balance_eur) but got {data['liquidity_eur']}. "
        "Regression: _get_liquidity_eur must use account.cash_balance_eur, "
        "not LIQUIDITE.EURO transaction sum."
    )

