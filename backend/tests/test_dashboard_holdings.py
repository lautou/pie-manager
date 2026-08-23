# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for GET /api/dashboard/holdings and /holdings/history endpoints."""

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
# GET /api/dashboard/holdings (lines 203-275)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_holdings_empty_no_transactions(client, db_session):
    uid = await async_create_portfolio(client, f"Pos-Empty-{id(db_session)}")
    r = await client.get("/api/dashboard/holdings", params={"portfolio_id": uid})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_holdings_returns_held_assets(client, db_session):
    setup = await _full_setup(db_session, f"poshold-{id(db_session)}")
    uid = setup["portfolio_id"]

    r = await client.get("/api/dashboard/holdings", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    # Filter to non-zero value positions (LIQUIDITE.EURO has no price → value 0)
    valued = [p for p in data if p["value_eur"] > 0]
    tickers = [p["ticker"] for p in valued]
    assert setup["ticker_off"] in tickers
    assert setup["ticker_def"] in tickers


@pytest.mark.asyncio
async def test_holdings_includes_pool_info(client, db_session):
    setup = await _full_setup(db_session, f"pospool-{id(db_session)}")
    uid = setup["portfolio_id"]

    r = await client.get("/api/dashboard/holdings", params={"portfolio_id": uid})
    assert r.status_code == 200
    # Only check positions that have a known pool (ETF positions); LIQUIDITE.EURO has no pool
    valued_positions = [p for p in r.json() if p["value_eur"] > 0]
    assert len(valued_positions) >= 2
    for pos in valued_positions:
        assert pos["pool_id"] is not None
        assert pos["pool_name"] is not None
        assert "category" in pos  # category field must be present for frontend Manuel display


@pytest.mark.asyncio
async def test_holdings_or_physique_instrument_type_exposed(client, db_session):
    """
    instrument_type='Or physique' must appear in the positions response so the
    frontend can hide Quantity and Last Price for assets like physical gold.
    """
    suffix = f"manuel-pos-{id(db_session)}"
    portfolio = Portfolio(name=f"ManPos-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Coffre", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    pool = Pool(portfolio_id=uid, name="Or", strategy="Defensive",
                target_pct=1.0, is_active=True)
    db_session.add(pool)
    await db_session.flush()

    ticker = f"OR.{suffix}"
    db_session.add(Product(ticker=ticker, name="Or Physique", category="Actif", instrument_type="Or physique", currency="EUR"))
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=pool.id, ticker=ticker))
    await db_session.flush()

    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 1, 1), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-1.0, unit_price=30000.0, unit_price_eur=30000.0,
        total_amount=-30000.0, total_amount_eur=-30000.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 1, 1),
                              price=32336.34, currency="EUR", source="manual"))
    await db_session.flush()

    r = await client.get("/api/dashboard/holdings", params={"portfolio_id": uid})
    assert r.status_code == 200
    positions = r.json()
    or_pos = next(p for p in positions if p["ticker"] == ticker)
    assert or_pos["instrument_type"] == "Or physique"
    assert or_pos["value_eur"] == pytest.approx(32336.34, abs=0.01)


@pytest.mark.asyncio
async def test_holdings_sorted_by_name_asc(client, db_session):
    """Positions are sorted alphabetically by product_name ascending (case-insensitive)."""
    suffix = f"possorted-{id(db_session)}"
    portfolio = Portfolio(name=f"PosSorted-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    # Insert in reverse alphabetical order (by name) to prove sorting is applied
    for ticker, name, price_val in [
        (f"Z.{suffix}", "Zebra Fund", 500.0),
        (f"A.{suffix}", "Alpha Fund", 50.0),
    ]:
        db_session.add(Product(ticker=ticker, name=name, category="Actif", currency="EUR"))
        await db_session.flush()
        db_session.add(Transaction(
            portfolio_id=uid, account_id=account.id,
            date=date(2025, 1, 1), type="Actif", ticker=ticker,
            currency="EUR", exchange_rate=1.0,
            quantity=-10.0, unit_price=price_val, unit_price_eur=price_val,
            total_amount=-10 * price_val, total_amount_eur=-10 * price_val,
        ))
        db_session.add(AssetPrice(ticker=ticker, date=date(2025, 1, 1),
                                   price=price_val, currency="EUR"))
    await db_session.flush()

    r = await client.get("/api/dashboard/holdings", params={"portfolio_id": uid})
    assert r.status_code == 200
    names = [p["product_name"] for p in r.json()]
    assert names == sorted(names, key=str.lower), f"Expected alphabetical, got {names}"


# ---------------------------------------------------------------------------
# GET /api/dashboard/holdings/history (lines 278-372)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_holdings_history_returns_snapshot(client, db_session):
    setup = await _full_setup(db_session, f"poshist-{id(db_session)}")
    uid = setup["portfolio_id"]

    r = await client.get("/api/dashboard/holdings/history",
                         params={"portfolio_id": uid, "snap_date": "2025-01-10"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_holdings_history_no_transactions(client, db_session):
    uid = await async_create_portfolio(client, f"PosHistEmpty-{id(db_session)}")
    r = await client.get("/api/dashboard/holdings/history",
                         params={"portfolio_id": uid, "snap_date": "2025-01-10"})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_holdings_history_excludes_future_transactions(client, db_session):
    suffix = f"poshist-excl-{id(db_session)}"
    portfolio = Portfolio(name=f"PosHistExcl-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"HIST.{suffix}"
    db_session.add(Product(ticker=ticker, name="HIST ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    # Transaction after snap_date
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 6, 1), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-10.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    await db_session.flush()

    r = await client.get("/api/dashboard/holdings/history",
                         params={"portfolio_id": uid, "snap_date": "2025-01-01"})
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# _get_latest_holdings — Cash branch: held = max(0.0, qty)
# Triggered in GET /api/dashboard/holdings when a Cash product is held.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_holdings_includes_cash_product(client, db_session):
    """
    Line 74: category == "Cash" → held = max(0.0, qty)

    A Cash product (positive qty = held) should appear in /positions.
    """
    suffix = f"cash74-{id(db_session)}"
    portfolio = Portfolio(name=f"DashCash74-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="BNP", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    cash_ticker = f"CASHEUR.{suffix}"
    db_session.add(Product(ticker=cash_ticker, name="EUR Cash",
                            category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    # Positive qty = Cash held
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 3, 3), type="Actif", ticker=cash_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=2000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=2000.0, total_amount_eur=2000.0,
    ))
    await db_session.flush()

    db_session.add(AssetPrice(ticker=cash_ticker, date=date(2025, 3, 3),
                               price=1.0, currency="EUR", source="manual"))
    await db_session.flush()

    r = await client.get("/api/dashboard/holdings", params={"portfolio_id": uid})
    assert r.status_code == 200
    tickers = [p["ticker"] for p in r.json()]
    assert cash_ticker in tickers


# ---------------------------------------------------------------------------
# get_holdings_at_date (holdings/history endpoint)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_holdings_history_cash_category(client, db_session):
    """
    Line 347: category == "Cash" → held = max(0.0, raw_qty) in positions/history.

    A Cash product with positive net qty should appear in the history endpoint.
    """
    suffix = f"histcash-{id(db_session)}"
    portfolio = Portfolio(name=f"HistCash-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    cash_ticker = f"CASHEUR2.{suffix}"
    db_session.add(Product(ticker=cash_ticker, name="EUR Cash", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    snap_date = date(2025, 4, 1)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=snap_date, type="Actif", ticker=cash_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=3000.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=3000.0, total_amount_eur=3000.0,
    ))
    await db_session.flush()

    db_session.add(AssetPrice(ticker=cash_ticker, date=snap_date,
                               price=1.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get("/api/dashboard/holdings/history",
                         params={"portfolio_id": uid, "snap_date": snap_date.isoformat()})
    assert r.status_code == 200
    tickers_in_response = [p["ticker"] for p in r.json()]
    assert cash_ticker in tickers_in_response


@pytest.mark.asyncio
async def test_holdings_history_zero_held_noncash_skipped(client, db_session):
    """
    Line 352: held == 0 and category != "Manuel" → continue.

    Non-cash ticker where net qty is positive (more sold than bought) → held = 0.
    Also tests line 347 indirectly (goes through else branch at 349).
    """
    suffix = f"histzeroheld-{id(db_session)}"
    portfolio = Portfolio(name=f"HistZero-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"NETHELD.{suffix}"
    db_session.add(Product(ticker=ticker, name="Net Sold ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    snap_date = date(2025, 5, 1)
    # Positive net qty for non-cash → held = max(0, -5) = 0 → line 352 continue
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=snap_date, type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=5.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=500.0, total_amount_eur=500.0,
    ))
    await db_session.flush()

    r = await client.get("/api/dashboard/holdings/history",
                         params={"portfolio_id": uid, "snap_date": snap_date.isoformat()})
    assert r.status_code == 200
    assert all(p["ticker"] != ticker for p in r.json())


@pytest.mark.asyncio
async def test_holdings_history_zero_value_eur_skipped(client, db_session):
    """
    Line 356: value_eur <= 0 → continue.

    Non-cash position with held > 0 but no price (price=0) → value_eur=0 → skipped.
    """
    suffix = f"histzeroval-{id(db_session)}"
    portfolio = Portfolio(name=f"HistZeroVal-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"NOPRICE2.{suffix}"
    db_session.add(Product(ticker=ticker, name="Unpriced ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    snap_date = date(2025, 6, 2)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=snap_date, type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-10.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    await db_session.flush()
    # No AssetPrice → price = 0 → value_eur = held * 0 = 0 → line 356 continue

    r = await client.get("/api/dashboard/holdings/history",
                         params={"portfolio_id": uid, "snap_date": snap_date.isoformat()})
    assert r.status_code == 200
    assert all(p["ticker"] != ticker for p in r.json())


# ---------------------------------------------------------------------------
# get_holdings — holdings endpoint with no price info
# (ticker_to_pool missing, product_names missing)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_holdings_no_pool_membership(client, db_session):
    """
    Lines 305-328: ticker held but not assigned to any pool →
    pool_id=None, pool_name=None in response.
    """
    suffix = f"nopool-pos-{id(db_session)}"
    portfolio = Portfolio(name=f"PosNoPool-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"FREE.{suffix}"
    db_session.add(Product(ticker=ticker, name="Free ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    # Transaction exists but ticker not assigned to any pool
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 2, 3), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-8.0, unit_price=50.0, unit_price_eur=50.0,
        total_amount=-400.0, total_amount_eur=-400.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 2, 3),
                               price=55.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get("/api/dashboard/holdings", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    pos = next((p for p in data if p["ticker"] == ticker), None)
    assert pos is not None
    assert pos["pool_id"] is None
    assert pos["pool_name"] is None
    assert pos["value_eur"] == pytest.approx(440.0, rel=0.01)


@pytest.mark.asyncio
async def test_holdings_ticker_no_price(client, db_session):
    """
    Lines 310-312: price_tuple is None → last_price = 0.0, value_eur = 0.
    Position exists but has no AssetPrice entry → appears with value 0.
    """
    suffix = f"noprice-pos-{id(db_session)}"
    portfolio = Portfolio(name=f"PosNoPrice-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"NOPRICE4.{suffix}"
    db_session.add(Product(ticker=ticker, name="Unpriced ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 3, 3), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-5.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    ))
    await db_session.flush()
    # No AssetPrice → price_tuple = None → last_price = 0, value = 0

    r = await client.get("/api/dashboard/holdings", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    pos = next((p for p in data if p["ticker"] == ticker), None)
    assert pos is not None
    assert pos["last_price"] == pytest.approx(0.0)
    assert pos["value_eur"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_holdings_manuel_category_uses_price_as_total(client, db_session):
    """
    Lines 313-316: category == "Manuel" → value_eur = price_eur_unit (not qty × price).
    """
    suffix = f"pos-manuel-{id(db_session)}"
    portfolio = Portfolio(name=f"PosManuel-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"GOLD.{suffix}"
    db_session.add(Product(ticker=ticker, name="Gold", category="Actif", instrument_type="Or physique", currency="EUR"))
    await db_session.flush()

    # Manuel: qty = -1 (buy convention for non-cash), price = total value
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 4, 7), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-1.0, unit_price=7500.0, unit_price_eur=7500.0,
        total_amount=-7500.0, total_amount_eur=-7500.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 4, 7),
                               price=7500.0, currency="EUR", source="manual"))
    await db_session.flush()

    r = await client.get("/api/dashboard/holdings", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    pos = next((p for p in data if p["ticker"] == ticker), None)
    assert pos is not None
    # Manuel: value = price (total), not qty * price
    assert pos["value_eur"] == pytest.approx(7500.0)


# ---------------------------------------------------------------------------
# get_holdings_at_date — Manuel category in history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_holdings_history_manuel_category(client, db_session):
    """
    Lines 395-414: Manuel category in history endpoint.
    value_eur = round(price_eur, 2) not qty × price.
    """
    suffix = f"histmanuel2-{id(db_session)}"
    portfolio = Portfolio(name=f"HistManuel2-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"GOLD2.{suffix}"
    db_session.add(Product(ticker=ticker, name="Gold2", category="Actif", instrument_type="Or physique", currency="EUR"))
    await db_session.flush()

    snap_date = date(2025, 5, 5)
    # Manuel: qty = -1 (non-cash convention), price = total value
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=snap_date, type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-1.0, unit_price=8000.0, unit_price_eur=8000.0,
        total_amount=-8000.0, total_amount_eur=-8000.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date,
                               price=8000.0, currency="EUR", source="manual"))
    await db_session.flush()

    r = await client.get("/api/dashboard/holdings/history",
                         params={"portfolio_id": uid, "snap_date": snap_date.isoformat()})
    assert r.status_code == 200
    data = r.json()
    pos = next((p for p in data if p["ticker"] == ticker), None)
    assert pos is not None
    # Manuel: value = price_eur (total asset value, not qty × price)
    assert pos["value_eur"] == pytest.approx(8000.0)


@pytest.mark.asyncio
async def test_holdings_history_fx_spot_rate(client, db_session):
    """
    Lines 375-377: _get_spot_rates_at_date called for FX conversion in history.
    USD position at historical date uses spot rate at or before snap_date.
    """
    suffix = f"histfx-{id(db_session)}"
    portfolio = Portfolio(name=f"HistFX-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="IBKR", currency="USD")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"MSFT.{suffix}"
    db_session.add(Product(ticker=ticker, name="Microsoft", category="Actif", currency="USD"))

    fx_ticker = f"USDEUR.{suffix}"  # use unique FX ticker to avoid conflicts
    db_session.add(Product(ticker=fx_ticker, name="USD/EUR hist", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    snap_date = date(2025, 6, 2)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=snap_date, type="Actif", ticker=ticker,
        currency="USD", exchange_rate=0.93,
        quantity=-4.0, unit_price=400.0, unit_price_eur=372.0,
        total_amount=-1600.0, total_amount_eur=-1488.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date,
                               price=400.0, currency="USD", source="test"))
    # Historical FX rate - use ticker ending in EUR=X for _get_spot_rates_at_date to pick it up
    # The function looks for tickers LIKE '%EUR=X'. Use "USDEUR=X" but with its own product.
    usd_eur_fx = "USDEUR=X"
    from sqlalchemy import select as sa_select
    existing_fx2 = await db_session.execute(sa_select(Product).where(Product.ticker == usd_eur_fx))
    if not existing_fx2.scalar_one_or_none():
        db_session.add(Product(ticker=usd_eur_fx, name="USD/EUR", category="Actif", instrument_type="Cash", currency="EUR"))
        await db_session.flush()
    db_session.add(AssetPrice(ticker=usd_eur_fx, date=snap_date,
                               price=0.93, currency="EUR", source="ecb"))
    await db_session.flush()

    r = await client.get("/api/dashboard/holdings/history",
                         params={"portfolio_id": uid, "snap_date": snap_date.isoformat()})
    assert r.status_code == 200
    data = r.json()
    pos = next((p for p in data if p["ticker"] == ticker), None)
    assert pos is not None
    # 4 units × 400 USD × 0.93 EUR/USD = 1488 EUR
    assert pos["value_eur"] == pytest.approx(1488.0, rel=0.01)


# ---------------------------------------------------------------------------
# Bug fix: forex positions must deduct fees paid in the foreign currency
# FRAIS.COURTAGE.JPY (type=Frais, currency=JPY, total_amount=-X) reduces JPYEUR=X
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_holdings_forex_deducts_foreign_currency_fees(client, db_session):
    """
    Regression: fees charged in JPY (FRAIS.COURTAGE.JPY) were not deducted
    from the JPYEUR=X held quantity because get_holdings filtered type='Actif'
    only.  total_amount of fee transactions denominated in the foreign currency
    must be summed and subtracted from the matching forex position.
    """
    suffix = f"jpyfee-{id(db_session)}"
    portfolio = Portfolio(name=f"JPYFee-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name=f"Revolut-{suffix}", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    # Products
    jpyeur_ticker = f"JPYEUR=X.{suffix}"
    fee_ticker = f"FRAIS.COURTAGE.JPY.{suffix}"
    db_session.add(Product(ticker=jpyeur_ticker, name="JPY/EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    db_session.add(Product(ticker=fee_ticker, name="Frais JPY", category="Fee", currency="JPY"))
    await db_session.flush()

    # Buy 300,000 JPY
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 6, 1), type="Actif", ticker=jpyeur_ticker,
        currency="JPY", exchange_rate=0.006,
        quantity=300_000.0, unit_price=1.0, unit_price_eur=0.006,
        total_amount=300_000.0, total_amount_eur=1800.0,
    ))
    # Fee 1: 165 JPY brokerage
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 6, 1), type="Frais", ticker=fee_ticker,
        currency="JPY", exchange_rate=0.006,
        quantity=-1.0, unit_price=165.0, unit_price_eur=0.99,
        total_amount=-165.0, total_amount_eur=-0.99,
    ))
    # Fee 2: 20 JPY brokerage
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=date(2025, 6, 2), type="Frais", ticker=fee_ticker,
        currency="JPY", exchange_rate=0.006,
        quantity=-1.0, unit_price=20.0, unit_price_eur=0.12,
        total_amount=-20.0, total_amount_eur=-0.12,
    ))

    db_session.add(AssetPrice(ticker=jpyeur_ticker, date=date(2025, 6, 2),
                               price=0.006, currency="EUR", source="yfinance"))
    await db_session.flush()

    r = await client.get("/api/dashboard/holdings", params={"portfolio_id": uid})
    assert r.status_code == 200
    pos = next((p for p in r.json() if p["ticker"] == jpyeur_ticker), None)
    assert pos is not None
    # 300,000 - 165 - 20 = 299,815 JPY (not 300,000)
    assert pos["quantity"] == pytest.approx(299_815.0, rel=0.001)


# ---------------------------------------------------------------------------
# GET /api/dashboard/holdings/{ticker}/composition
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ticker_composition_404_for_missing_product(client, db_session):
    r = await client.get(f"/api/dashboard/holdings/NOPE.{id(db_session)}/composition")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_ticker_composition_returns_top_holdings_and_sectors(client, db_session):
    from app.services.etf_holdings_service import replace_etf_holdings, replace_sector_weightings

    ticker = f"FLXC.{id(db_session)}"
    db_session.add(Product(ticker=ticker, name="Franklin FTSE China", category="Actif", instrument_type="ETF"))
    await db_session.flush()
    await replace_etf_holdings(db_session, ticker, [
        {"ticker": "0700.HK", "name": "Tencent Holdings Ltd", "weight_pct": 0.1239},
        {"ticker": "9988.HK", "name": "Alibaba Group Holding Ltd", "weight_pct": 0.0783},
    ])
    await replace_sector_weightings(db_session, ticker, {"consumer_cyclical": 0.2149})
    await db_session.flush()

    r = await client.get(f"/api/dashboard/holdings/{ticker}/composition")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == ticker
    assert len(body["top_holdings"]) == 2
    assert body["top_holdings"][0]["ticker"] == "0700.HK"  # sorted by weight desc
    assert body["top_holdings_coverage_pct"] == pytest.approx((0.1239 + 0.0783) * 100, abs=0.01)
    assert body["sector_weightings"] == [{"sector": "consumer_cyclical", "weight_pct": pytest.approx(0.2149)}]
    assert body["bond_duration"] is None
    assert body["holdings_updated_at"] is None


@pytest.mark.asyncio
async def test_ticker_composition_exposes_bond_metrics(client, db_session):
    from app.services.etf_holdings_service import save_etf_fetch_result
    from datetime import datetime, timezone

    ticker = f"XJSE.{id(db_session)}"
    db_session.add(Product(ticker=ticker, name="Japan Govt Bond", category="Actif", instrument_type="Obligation"))
    await db_session.flush()
    await save_etf_fetch_result(
        db_session, ticker, holdings=[], sector_weightings={},
        fetched_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        bond_duration=1.32, bond_maturity=8.57,
    )
    await db_session.flush()

    r = await client.get(f"/api/dashboard/holdings/{ticker}/composition")
    assert r.status_code == 200
    body = r.json()
    assert body["bond_duration"] == pytest.approx(1.32)
    assert body["bond_maturity"] == pytest.approx(8.57)
    assert body["holdings_updated_at"] is not None
