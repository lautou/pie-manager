# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for GET /api/holdings/daily-holding-values (lines 240-396 of holdings.py).

Covers:
  - Empty result when no transactions
  - Single holding on a single date
  - No price → no entry
  - Quantity accumulation across multiple transactions
  - Response structure: date + holdings list with ticker/product_name/value_eur/unit_price
  - Downsampling to ≤500 data points (>500 business days)
  - Last day always appended when downsampling
  - Cash category (held = max(0, qty))
  - Manuel category (held = abs(qty), value = price)
  - FX conversion for non-EUR currencies
  - Weekend exclusion
  - Future-only transaction → empty result
"""
import pytest
from datetime import date, timedelta

from app.models.portfolio import Portfolio
from app.models.broker import Broker
from app.models.product import Product
from app.models.price import AssetPrice
from app.models.transaction import Transaction
from app.models.portfolio_account import PortfolioAccount


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_portfolio(db) -> tuple[int, int]:
    """Returns (portfolio_id, broker_id)."""
    p = Portfolio(name=f"DHV-{id(db)}")
    db.add(p)
    await db.flush()
    b = Broker(name="Test", currency="EUR")
    db.add(b)
    await db.flush()
    db.add(PortfolioAccount(portfolio_id=p.id, broker_id=b.id))
    await db.flush()
    return p.id, b.id


async def _add_product(db, ticker: str, name: str = "ETF", category: str = "Actif",
                        currency: str = "EUR", instrument_type: str | None = None) -> None:
    from sqlalchemy import select
    ex = await db.execute(select(Product).where(Product.ticker == ticker))
    if not ex.scalar_one_or_none():
        db.add(Product(ticker=ticker, name=name, category=category, currency=currency,
                        instrument_type=instrument_type))
        await db.flush()


URL = "/api/dashboard/daily-holding-values"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dhv_empty_when_no_transactions(client, db_session):
    uid, _ = await _make_portfolio(db_session)
    r = await client.get(URL, params={"portfolio_id": uid})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_dhv_single_holding_single_date(client, db_session):
    uid, aid = await _make_portfolio(db_session)
    ticker = f"DHV.SINGLE.{uid}"
    snap_date = date(2025, 6, 2)  # Monday

    await _add_product(db_session, ticker)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=50.0, unit_price_eur=50.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date, price=50.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get(URL, params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1

    entry = next((d for d in data if d["date"] == snap_date.isoformat()), None)
    assert entry is not None, f"No entry for {snap_date}"
    assert "holdings" in entry
    h = next((h for h in entry["holdings"] if h["ticker"] == ticker), None)
    assert h is not None
    assert abs(h["value_eur"] - 500.0) < 1.0
    assert "unit_price" in h
    assert "product_name" in h


@pytest.mark.asyncio
async def test_dhv_no_price_means_no_entry(client, db_session):
    uid, aid = await _make_portfolio(db_session)
    ticker = f"DHV.NOPRICE.{uid}"
    snap_date = date(2025, 7, 7)  # Monday

    await _add_product(db_session, ticker)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-5.0,
        unit_price=100.0, unit_price_eur=100.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    ))
    # No AssetPrice added
    await db_session.flush()

    r = await client.get(URL, params={"portfolio_id": uid})
    assert r.status_code == 200
    for entry in r.json():
        for h in entry["holdings"]:
            assert h["ticker"] != ticker


@pytest.mark.asyncio
async def test_dhv_quantities_accumulate(client, db_session):
    uid, aid = await _make_portfolio(db_session)
    ticker = f"DHV.ACCUM.{uid}"
    date1 = date(2025, 8, 4)   # Monday
    date2 = date(2025, 8, 11)  # Monday

    await _add_product(db_session, ticker)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=date1,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=50.0, unit_price_eur=50.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    ))
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=date2,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=4.0,
        unit_price=55.0, unit_price_eur=55.0,
        total_amount=220.0, total_amount_eur=220.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=date1, price=50.0, currency="EUR", source="test"))
    db_session.add(AssetPrice(ticker=ticker, date=date2, price=55.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get(URL, params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()

    entry2 = next((d for d in data if d["date"] == date2.isoformat()), None)
    assert entry2 is not None
    h = next((h for h in entry2["holdings"] if h["ticker"] == ticker), None)
    assert h is not None
    # net = 10 - 4 = 6 units at 55€ = 330€
    assert abs(h["value_eur"] - 330.0) < 1.0


@pytest.mark.asyncio
async def test_dhv_response_structure(client, db_session):
    uid, aid = await _make_portfolio(db_session)
    ticker = f"DHV.STRUCT.{uid}"
    snap_date = date(2025, 9, 1)  # Monday

    await _add_product(db_session, ticker, name="My ETF")
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-3.0,
        unit_price=100.0, unit_price_eur=100.0,
        total_amount=-300.0, total_amount_eur=-300.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date, price=100.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get(URL, params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) > 0

    first = data[0]
    assert "date" in first
    assert "holdings" in first
    assert isinstance(first["holdings"], list)

    h = first["holdings"][0]
    assert "ticker" in h
    assert "product_name" in h
    assert "value_eur" in h
    assert "unit_price" in h
    assert h["product_name"] == "My ETF"


@pytest.mark.asyncio
async def test_dhv_downsampling(client, db_session):
    """Lines 286-290: >500 business days → sampled to ≤501 entries."""
    uid, aid = await _make_portfolio(db_session)
    ticker = f"DHV.DSAMP.{uid}"
    early_date = date.today() - timedelta(days=730)  # ~700 business days

    await _add_product(db_session, ticker, name="Long ETF")
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=early_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=early_date, price=100.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get(URL, params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) <= 501


@pytest.mark.asyncio
async def test_dhv_last_day_always_included(client, db_session):
    """Lines 289-290: last day appended when not in sampled_days."""
    uid, aid = await _make_portfolio(db_session)
    ticker = f"DHV.LASTDAY.{uid}"
    today = date.today()
    early = today - timedelta(days=1100)  # >750 business days

    await _add_product(db_session, ticker, name="Long ETF 2")
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=early,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=early, price=100.0, currency="EUR", source="test"))
    db_session.add(AssetPrice(ticker=ticker, date=today, price=110.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get(URL, params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) <= 501
    assert len(data) >= 1
    last_date = date.fromisoformat(data[-1]["date"])
    assert last_date >= today - timedelta(days=7)


@pytest.mark.asyncio
async def test_dhv_cash_category(client, db_session):
    """Line 373-374: Cash category → held = max(0.0, raw_qty)."""
    uid, aid = await _make_portfolio(db_session)
    ticker = f"DHV.CASH.{uid}"
    snap_date = date(2025, 2, 3)  # Monday

    await _add_product(db_session, ticker, name="EUR Cash", category="Actif", instrument_type="Cash")
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=1500.0,
        unit_price=1.0, unit_price_eur=1.0,
        total_amount=1500.0, total_amount_eur=1500.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date, price=1.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get(URL, params={"portfolio_id": uid})
    assert r.status_code == 200
    found = any(
        any(h["ticker"] == ticker for h in entry["holdings"])
        for entry in r.json()
    )
    assert found


@pytest.mark.asyncio
async def test_dhv_manuel_category(client, db_session):
    """Lines 375-376, 380-381: Manuel category → held = abs(qty), value = price."""
    uid, aid = await _make_portfolio(db_session)
    ticker = f"DHV.MANUEL.{uid}"
    snap_date = date(2025, 3, 3)  # Monday

    await _add_product(db_session, ticker, name="Or physique", category="Actif", instrument_type="Or physique")
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-1.0,
        unit_price=5000.0, unit_price_eur=5000.0,
        total_amount=-5000.0, total_amount_eur=-5000.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date, price=5000.0, currency="EUR", source="manual"))
    await db_session.flush()

    r = await client.get(URL, params={"portfolio_id": uid})
    assert r.status_code == 200
    found = any(
        any(h["ticker"] == ticker and abs(h["value_eur"] - 5000.0) < 1.0
            for h in entry["holdings"])
        for entry in r.json()
    )
    assert found


@pytest.mark.asyncio
async def test_dhv_future_transaction_returns_empty(client, db_session):
    """Lines 281-282: all_days empty when earliest_date is in the future."""
    uid, aid = await _make_portfolio(db_session)
    ticker = f"DHV.FUTURE.{uid}"

    await _add_product(db_session, ticker)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=date(2099, 1, 6),
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    await db_session.flush()

    r = await client.get(URL, params={"portfolio_id": uid})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_dhv_weekend_dates_excluded(client, db_session):
    """Lines 276-279: weekends are skipped in all_days."""
    uid, aid = await _make_portfolio(db_session)
    ticker = f"DHV.WKD.{uid}"
    monday = date(2025, 5, 5)  # Monday

    await _add_product(db_session, ticker, name="Monday ETF")
    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=monday,
        type="Actif", ticker=ticker, currency="EUR",
        exchange_rate=1.0, quantity=-10.0,
        unit_price=200.0, unit_price_eur=200.0,
        total_amount=-2000.0, total_amount_eur=-2000.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=monday, price=200.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get(URL, params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    # Verify no weekend dates appear
    for entry in data:
        d = date.fromisoformat(entry["date"])
        assert d.weekday() < 5, f"Weekend date {d} appeared in response"
    assert monday.isoformat() in [e["date"] for e in data]


@pytest.mark.asyncio
async def test_dhv_fx_conversion(client, db_session):
    """Lines 370-371: non-EUR price converted via spot rates."""
    uid, aid = await _make_portfolio(db_session)
    ticker = f"DHV.FX.{uid}"
    gbp_fx = "GBPEUR=X"
    snap_date = date(2025, 4, 7)  # Monday

    await _add_product(db_session, ticker, name="GBP ETF", currency="GBP")
    from sqlalchemy import select as sa_select
    ex = await db_session.execute(sa_select(Product).where(Product.ticker == gbp_fx))
    if not ex.scalar_one_or_none():
        db_session.add(Product(ticker=gbp_fx, name="GBP/EUR", category="Actif", instrument_type="Cash", currency="EUR"))
        await db_session.flush()

    db_session.add(Transaction(
        portfolio_id=uid, account_id=aid, date=snap_date,
        type="Actif", ticker=ticker, currency="GBP",
        exchange_rate=1.15, quantity=-3.0,
        unit_price=100.0, unit_price_eur=115.0,
        total_amount=-300.0, total_amount_eur=-345.0,
    ))
    db_session.add(AssetPrice(ticker=ticker, date=snap_date, price=100.0, currency="GBP", source="test"))
    db_session.add(AssetPrice(ticker=gbp_fx, date=snap_date, price=1.15, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get(URL, params={"portfolio_id": uid})
    assert r.status_code == 200
    found = any(
        any(h["ticker"] == ticker for h in entry["holdings"])
        for entry in r.json()
    )
    assert found
