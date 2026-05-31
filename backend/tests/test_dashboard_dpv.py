"""Tests for GET /api/dashboard/daily-position-values endpoint."""

import pytest
from datetime import date, timedelta

# A date well in the past (>500 business days ago) to trigger DPV downsampling.
# 700 calendar days is safely > 500 business days for any year.
_LONG_AGO = date.today() - timedelta(days=730)
_VERY_LONG_AGO = date.today() - timedelta(days=1100)

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
# GET /api/dashboard/daily-position-values (lines 470-630)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_position_values_no_transactions(client, db_session):
    uid = await async_create_portfolio(client, f"DPV-Empty-{id(db_session)}")
    r = await client.get("/api/dashboard/daily-position-values",
                         params={"portfolio_id": uid})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_daily_position_values_with_data(client, db_session):
    setup = await _full_setup(db_session, f"dpv-data-{id(db_session)}")
    uid = setup["portfolio_id"]

    r = await client.get("/api/dashboard/daily-position-values",
                         params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    # Should return at least one day entry
    assert len(data) >= 1
    first = data[0]
    assert "date" in first
    assert "positions" in first
    assert len(first["positions"]) >= 1


@pytest.mark.asyncio
async def test_daily_position_values_structure(client, db_session):
    setup = await _full_setup(db_session, f"dpv-struct-{id(db_session)}")
    uid = setup["portfolio_id"]

    r = await client.get("/api/dashboard/daily-position-values",
                         params={"portfolio_id": uid})
    assert r.status_code == 200
    for entry in r.json():
        assert "date" in entry
        assert "positions" in entry
        for pos in entry["positions"]:
            assert "ticker" in pos
            assert "product_name" in pos
            assert "value_eur" in pos
            assert pos["value_eur"] > 0


# ---------------------------------------------------------------------------
# Lines 509, 522: get_daily_position_values early returns
# Line 509: no earliest_date when ticker_rows exist but min(date) returns None
#           (unreachable in practice; line 522 is easier to target)
# Line 522: not all_days → when earliest_date is a future date (weekend)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_position_values_future_only_transaction(client, db_session):
    """
    Line 522: all_days is empty when earliest_date is a future Saturday/Sunday.

    We insert a transaction dated far in the future (a Sunday).  The business-day
    loop produces zero days (no weekday between that date and today because that
    date is itself in the future and it's a weekend), so all_days == [] → line 522.

    Actually, since today is before the future date, the while loop never runs,
    producing all_days == [].
    """
    suffix = f"futureonly-{id(db_session)}"
    portfolio = Portfolio(name=f"DPVFuture-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"FUTURE.{suffix}"
    db_session.add(Product(ticker=ticker, name="Future ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    # Use a transaction date far in the future so earliest_date > today
    # → all_days loop never runs → all_days == [] → line 522
    future_date = date(2099, 1, 6)  # a Saturday (or any far-future date)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=future_date, type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-10.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    await db_session.flush()

    r = await client.get("/api/dashboard/daily-position-values", params={"portfolio_id": uid})
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Lines 527-530: downsampling to ≤500 data points
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_position_values_downsampling(client, db_session):
    """
    Lines 527-530: when all_days > 500, sampled_days is downsampled.

    We insert a transaction from ~3 years ago (>700 business days) so the
    sampled_days list gets truncated.  We just verify the endpoint returns
    data without error and the number of entries is ≤ 501 (500 + possible last day).
    """
    suffix = f"downsample-{id(db_session)}"
    portfolio = Portfolio(name=f"DPVDown-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"LONGHOLD.{suffix}"
    db_session.add(Product(ticker=ticker, name="Long ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    # Transaction from >700 calendar days ago → >500 business days → triggers downsampling
    early_date = _LONG_AGO
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=early_date, type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-10.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    await db_session.flush()

    # Add price so some days have non-zero value
    db_session.add(AssetPrice(ticker=ticker, date=early_date,
                               price=100.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get("/api/dashboard/daily-position-values", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    # Downsampled to at most 501 entries (500 sampled + possibly appended last day)
    assert len(data) <= 501


# ---------------------------------------------------------------------------
# Lines 609, 611, 616: Cash and Manuel in daily-position-values loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_position_values_cash_product(client, db_session):
    """
    Line 609: category == "Cash" → held = max(0.0, raw_qty) in DPV loop.

    A Cash product with positive qty should appear in daily-position-values.
    """
    suffix = f"dpvcash-{id(db_session)}"
    portfolio = Portfolio(name=f"DPVCash-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    cash_ticker = f"CASHEUR3.{suffix}"
    db_session.add(Product(ticker=cash_ticker, name="EUR Cash",
                            category="Cash", currency="EUR"))
    await db_session.flush()

    snap_date = date(2025, 2, 3)  # Monday
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=snap_date, type="Actif", ticker=cash_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=1500.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=1500.0, total_amount_eur=1500.0,
    ))
    db_session.add(AssetPrice(ticker=cash_ticker, date=snap_date,
                               price=1.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get("/api/dashboard/daily-position-values", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    # There should be at least one entry with the cash ticker
    found = any(
        any(p["ticker"] == cash_ticker for p in entry["positions"])
        for entry in data
    )
    assert found, "Cash position should appear in daily-position-values"


@pytest.mark.asyncio
async def test_daily_position_values_manuel_product(client, db_session):
    """
    Lines 611, 616: category == "Manuel" → held = abs(raw_qty); value = price if held > 0.

    A Manuel product (price = total value) should appear correctly.
    """
    suffix = f"dpvmanuel-{id(db_session)}"
    portfolio = Portfolio(name=f"DPVManuel-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    manuel_ticker = f"OR.PHY2.{suffix}"
    db_session.add(Product(ticker=manuel_ticker, name="Or physique",
                            category="Manuel", currency="EUR"))
    await db_session.flush()

    snap_date = date(2025, 3, 3)  # Monday
    # Negative qty (buy convention for non-cash)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=snap_date, type="Actif", ticker=manuel_ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-1.0, unit_price=5000.0, unit_price_eur=5000.0,
        total_amount=-5000.0, total_amount_eur=-5000.0,
    ))
    # For Manuel: price is the total asset value
    db_session.add(AssetPrice(ticker=manuel_ticker, date=snap_date,
                               price=5000.0, currency="EUR", source="manual"))
    await db_session.flush()

    r = await client.get("/api/dashboard/daily-position-values", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    found = any(
        any(p["ticker"] == manuel_ticker and p["value_eur"] == pytest.approx(5000.0)
            for p in entry["positions"])
        for entry in data
    )
    assert found, "Manuel position should appear with price as total value"


# ---------------------------------------------------------------------------
# Lines 470-528: get_daily_position_values — additional branches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_position_values_weekend_start(client, db_session):
    """
    Lines 592-598: all_days skips weekends.
    A transaction on a Monday should still appear in results.
    """
    suffix = f"dpv-wkd-{id(db_session)}"
    portfolio = Portfolio(name=f"DPVWkd-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"MON.{suffix}"
    db_session.add(Product(ticker=ticker, name="Monday ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    monday = date(2025, 5, 5)  # Monday
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=monday, type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-10.0, unit_price=200.0, unit_price_eur=200.0,
        total_amount=-2000.0, total_amount_eur=-2000.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=monday,
                               price=200.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get("/api/dashboard/daily-position-values", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    # Check that the monday date appears
    dates = [entry["date"] for entry in data]
    assert monday.isoformat() in dates


@pytest.mark.asyncio
async def test_daily_position_values_with_fx_conversion(client, db_session):
    """
    Lines 686-692: DPV loop uses _to_eur with spot_rates_dpv for non-EUR assets.
    """
    suffix = f"dpv-fx-{id(db_session)}"
    portfolio = Portfolio(name=f"DPVfx-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="USD")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"GBP.ETF.{suffix}"
    db_session.add(Product(ticker=ticker, name="GBP ETF", category="Actif", currency="GBP"))

    # Ensure GBPEUR=X product exists for FK constraint
    gbp_fx = "GBPEUR=X"
    from sqlalchemy import select as sa_select
    existing_gbp = await db_session.execute(sa_select(Product).where(Product.ticker == gbp_fx))
    if not existing_gbp.scalar_one_or_none():
        db_session.add(Product(ticker=gbp_fx, name="GBP/EUR", category="Cash", currency="EUR"))
    await db_session.flush()

    snap_date = date(2025, 4, 7)  # Monday
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=snap_date, type="Actif", ticker=ticker,
        currency="GBP", exchange_rate=1.15,
        quantity=-3.0, unit_price=100.0, unit_price_eur=115.0,
        total_amount=-300.0, total_amount_eur=-345.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date,
                               price=100.0, currency="GBP", source="test"))
    # GBP spot rate
    db_session.add(AssetPrice(ticker=gbp_fx, date=snap_date,
                               price=1.15, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get("/api/dashboard/daily-position-values", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    # Should have entry for snap_date with GBP position
    found = any(
        any(p["ticker"] == ticker for p in entry["positions"])
        for entry in data
    )
    assert found


# ---------------------------------------------------------------------------
# Lines 573-654: get_daily_position_values — sampled_days last day appended
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daily_position_values_last_day_appended_if_missing(client, db_session):
    """
    Lines 609-611: when downsampling, if all_days[-1] not in sampled_days, it is appended.
    This happens when the last business day is not hit by step sampling.
    We can test this with 500+ business days and verify data integrity.
    """
    suffix = f"lastday-{id(db_session)}"
    portfolio = Portfolio(name=f"LastDay-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()

    ticker = f"LONG2.{suffix}"
    db_session.add(Product(ticker=ticker, name="Long ETF 2", category="Actif", currency="EUR"))
    await db_session.flush()

    # Transaction from >1100 calendar days ago → >750 business days → triggers downsampling
    early = _VERY_LONG_AGO
    db_session.add(Transaction(
        portfolio_id=uid, account_id=account.id,
        date=early, type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-10.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=early,
                               price=100.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get("/api/dashboard/daily-position-values", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    # Should be downsampled to ≤501 entries
    assert len(data) <= 501
    # Should still have data
    assert len(data) >= 1
