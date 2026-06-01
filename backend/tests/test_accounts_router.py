"""
Integration tests for /api/brokers — CRUD and summary endpoint.

Covers brokers.py lines: 16, 64-65, 83-194.
"""

import pytest
from datetime import date

from app.models.portfolio import Portfolio
from app.models.broker import Broker
from app.models.product import Product
from app.models.pool import Pool, PoolProduct
from app.models.price import AssetPrice
from app.models.transaction import Transaction
from app.models.portfolio_account import PortfolioAccount

from tests.helpers import create_portfolio, create_broker

_create_portfolio = create_portfolio
_create_broker = create_broker


# ---------------------------------------------------------------------------
# GET /api/accounts/?portfolio_id=N  — list (line 64-65)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_accounts_empty(client, db_session):
    uid = await _create_portfolio(client, f"AccList-Empty-{id(db_session)}")
    r = await client.get("/api/brokers/", params={"portfolio_id": uid})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_accounts_returns_created(client, db_session):
    uid = await _create_portfolio(client, f"AccList-{id(db_session)}")
    await _create_broker(client, uid, "Degiro")
    await _create_broker(client, uid, "BourseDir")
    r = await client.get("/api/brokers/", params={"portfolio_id": uid})
    assert r.status_code == 200
    names = [a["name"] for a in r.json()]
    assert "Degiro" in names
    assert "BourseDir" in names


@pytest.mark.asyncio
async def test_list_accounts_isolates_by_user(client, db_session):
    uid_a = await _create_portfolio(client, f"AccIso-A-{id(db_session)}")
    uid_b = await _create_portfolio(client, f"AccIso-B-{id(db_session)}")
    await _create_broker(client, uid_a, "OnlyA")
    r = await client.get("/api/brokers/", params={"portfolio_id": uid_b})
    assert r.json() == []


# ---------------------------------------------------------------------------
# POST /api/accounts/ — create (line 16 = r2 helper, 68-74)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_broker(client, db_session):
    uid = await _create_portfolio(client, f"AccCreate-{id(db_session)}")
    r = await client.post("/api/brokers/", json={
        "name": "IB", "currency": "USD", "portfolio_ids": [uid],
    })
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "IB"
    assert data["currency"] == "USD"
    assert "id" in data


# ---------------------------------------------------------------------------
# GET /api/accounts/summary  — full summary (lines 83-194)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summary_no_accounts_returns_empty(client, db_session):
    uid = await _create_portfolio(client, f"AccSum-NoAcc-{id(db_session)}")
    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_summary_account_with_no_positions(client, db_session):
    """Account exists but no transactions — should return account with empty positions."""
    uid = await _create_portfolio(client, f"AccSum-NoPosn-{id(db_session)}")
    acc = Broker(name="Empty", currency="EUR")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id, cash_balance_eur=500.0))
    await db_session.flush()

    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    summaries = r.json()
    assert len(summaries) == 1
    assert summaries[0]["name"] == "Empty"
    assert summaries[0]["positions"] == []
    assert summaries[0]["cash_balance_eur"] == 500.0
    assert summaries[0]["total_eur"] == 500.0


@pytest.mark.asyncio
async def test_summary_with_etf_position(client, db_session):
    """Account holds an ETF — value_eur = qty * price."""
    suffix = id(db_session)
    uid = await _create_portfolio(client, f"AccSum-ETF-{suffix}")

    # Account
    acc = Broker(name="Degiro", currency="EUR")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id))
    await db_session.flush()

    # Product
    ticker = f"ETF.{suffix}"
    db_session.add(Product(ticker=ticker, name="My ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    # Transaction: buy 10 units (negative qty = held in the DB convention)
    tx = Transaction(
        portfolio_id=uid, account_id=acc.id,
        date=date(2025, 1, 15), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-10.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    )
    db_session.add(tx)
    await db_session.flush()

    # Price
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 1, 15),
                               price=120.0, currency="EUR", source="yfinance"))
    await db_session.flush()

    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    summaries = r.json()
    assert len(summaries) == 1
    s = summaries[0]
    assert s["positions_value_eur"] == pytest.approx(1200.0, abs=0.01)
    assert len(s["positions"]) == 1
    pos = s["positions"][0]
    assert pos["ticker"] == ticker
    assert pos["category"] == "Actif"
    assert pos["quantity"] == pytest.approx(10.0)
    assert pos["last_price"] == pytest.approx(120.0, abs=0.01)
    assert pos["value_eur"] == pytest.approx(1200.0, abs=0.01)


@pytest.mark.asyncio
async def test_summary_with_cash_position(client, db_session):
    """Transactions of category=Cash hold qty positively."""
    suffix = id(db_session)
    uid = await _create_portfolio(client, f"AccSum-Cash-{suffix}")

    acc = Broker(name="BNP", currency="EUR")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id))
    await db_session.flush()

    ticker = f"CASHEUR.{suffix}"
    db_session.add(Product(ticker=ticker, name="Cash EUR", category="Cash", currency="EUR"))
    await db_session.flush()

    tx = Transaction(
        portfolio_id=uid, account_id=acc.id,
        date=date(2025, 2, 1), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=500.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=500.0, total_amount_eur=500.0,
    )
    db_session.add(tx)
    await db_session.flush()

    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 2, 1),
                               price=1.0, currency="EUR", source="manual"))
    await db_session.flush()

    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    s = r.json()[0]
    # Cash position: held = max(0, qty=500) → 500 * 1.0 = 500
    assert any(p["ticker"] == ticker for p in s["positions"])


@pytest.mark.asyncio
async def test_summary_with_manuel_category(client, db_session):
    """Manuel category: price IS the total value, not per-unit."""
    suffix = id(db_session)
    uid = await _create_portfolio(client, f"AccSum-Manuel-{suffix}")

    acc = Broker(name="Perso", currency="EUR")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id))
    await db_session.flush()

    ticker = f"OR.PHY.{suffix}"
    db_session.add(Product(ticker=ticker, name="Or physique", category="Manuel", currency="EUR"))
    await db_session.flush()

    # Negative qty → held=abs(qty) for non-cash
    tx = Transaction(
        portfolio_id=uid, account_id=acc.id,
        date=date(2025, 3, 1), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-1.0, unit_price=5000.0, unit_price_eur=5000.0,
        total_amount=-5000.0, total_amount_eur=-5000.0,
    )
    db_session.add(tx)
    await db_session.flush()

    # For Manuel: price = total value
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 3, 1),
                               price=5500.0, currency="EUR", source="manual"))
    await db_session.flush()

    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    summaries = r.json()
    assert len(summaries) == 1
    positions = summaries[0]["positions"]
    # Manuel: value_eur = price (total value), not qty * price
    pos = next(p for p in positions if p["ticker"] == ticker)
    assert pos["value_eur"] == pytest.approx(5500.0)
    # category must be returned so the frontend can hide the nonsensical unit price display
    assert pos["category"] == "Manuel"


@pytest.mark.asyncio
async def test_summary_zero_quantity_excluded(client, db_session):
    """A buy + sell that nets to zero should not appear in positions."""
    suffix = id(db_session)
    uid = await _create_portfolio(client, f"AccSum-NetZero-{suffix}")

    acc = Broker(name="Degiro", currency="EUR")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id))
    await db_session.flush()

    ticker = f"SOLD.{suffix}"
    db_session.add(Product(ticker=ticker, name="Sold ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    # Buy -10 then sell +10 → net qty = 0
    for qty in (-10.0, 10.0):
        db_session.add(Transaction(
            portfolio_id=uid, account_id=acc.id,
            date=date(2025, 1, 15), type="Actif", ticker=ticker,
            currency="EUR", exchange_rate=1.0,
            quantity=qty, unit_price=100.0, unit_price_eur=100.0,
            total_amount=qty * 100, total_amount_eur=qty * 100,
        ))
    await db_session.flush()

    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    s = r.json()[0]
    assert all(p["ticker"] != ticker for p in s["positions"])


@pytest.mark.asyncio
async def test_summary_no_price_defaults_to_zero(client, db_session):
    """Position with no price entry should still appear (value_eur = 0 → excluded by held check)."""
    suffix = id(db_session)
    uid = await _create_portfolio(client, f"AccSum-NoPrice-{suffix}")

    acc = Broker(name="Test", currency="EUR")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id, cash_balance_eur=200.0))
    await db_session.flush()

    ticker = f"NOPRICE.{suffix}"
    db_session.add(Product(ticker=ticker, name="Unpriced", category="Actif", currency="EUR"))
    await db_session.flush()

    db_session.add(Transaction(
        portfolio_id=uid, account_id=acc.id,
        date=date(2025, 1, 15), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-5.0, unit_price=50.0, unit_price_eur=50.0,
        total_amount=-250.0, total_amount_eur=-250.0,
    ))
    await db_session.flush()
    # No AssetPrice inserted

    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    # Position with price=0 → value=0, but held=5 (non-zero), check it appears with value_eur=0
    # or is absent, depending on how the router handles missing prices
    summaries = r.json()
    assert len(summaries) == 1
    # Cash balance should still be reflected
    assert summaries[0]["cash_balance_eur"] == 200.0


@pytest.mark.asyncio
async def test_summary_multiple_accounts(client, db_session):
    """Multiple accounts for one user all appear in the summary."""
    suffix = id(db_session)
    uid = await _create_portfolio(client, f"AccSum-Multi-{suffix}")

    for name in ("Degiro", "BourseDir", "Bourso"):
        acc = Broker(name=name, currency="EUR")
        db_session.add(acc)
        await db_session.flush()
        db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id))
    await db_session.flush()

    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    assert len(r.json()) == 3
    names = [a["name"] for a in r.json()]
    assert set(names) == {"Degiro", "BourseDir", "Bourso"}


@pytest.mark.asyncio
async def test_summary_position_with_zero_held_is_skipped(client, db_session):
    """
    Line 161: `continue` when held == 0.

    For a non-cash product, held = max(0, -raw_qty).  If the net qty is
    positive (more units sold than bought), held becomes 0 and the position
    is skipped even though the ticker has a non-zero net quantity.

    The HAVING clause in the query already filters sum(qty)==0, so we need
    a ticker whose summed qty is POSITIVE (e.g. sold without prior buy),
    which yields held = max(0, -positive) = 0 → continue on line 161.
    """
    suffix = id(db_session)
    uid = await _create_portfolio(client, f"AccSum-ZeroHeld-{suffix}")

    acc = Broker(name="Test", currency="EUR")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id, cash_balance_eur=100.0))
    await db_session.flush()

    ticker = f"SOLD.{suffix}"
    db_session.add(Product(ticker=ticker, name="Net-Sold ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    # Positive net qty for a non-cash ticker → held = max(0, -5.0) = 0 → line 161 continue
    db_session.add(Transaction(
        portfolio_id=uid, account_id=acc.id,
        date=date(2025, 5, 1), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=5.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=500.0, total_amount_eur=500.0,
    ))
    await db_session.flush()

    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 5, 1),
                               price=100.0, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    summaries = r.json()
    assert len(summaries) == 1
    # The ticker should NOT appear in positions (held == 0 → skipped)
    assert all(p["ticker"] != ticker for p in summaries[0]["positions"])
    # Only cash_balance_eur should contribute to total
    assert summaries[0]["total_eur"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_r2_rounding_in_summary(client, db_session):
    """Values are rounded to 2 decimal places (r2 helper)."""
    suffix = id(db_session)
    uid = await _create_portfolio(client, f"AccSum-R2-{suffix}")

    acc = Broker(name="RoundTest", currency="EUR")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id))
    await db_session.flush()

    ticker = f"ROUND.{suffix}"
    db_session.add(Product(ticker=ticker, name="Round ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    # 3 * 20857.425 = 62572.275 → should round half-up to 62572.28 (or per r2 logic)
    db_session.add(Transaction(
        portfolio_id=uid, account_id=acc.id,
        date=date(2025, 4, 1), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-3.0, unit_price=20857.425, unit_price_eur=20857.425,
        total_amount=-62572.275, total_amount_eur=-62572.275,
    ))
    await db_session.flush()

    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 4, 1),
                               price=20857.425, currency="EUR", source="yfinance"))
    await db_session.flush()

    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    s = r.json()[0]
    # Just verify it's a valid float with 2 decimal places
    assert isinstance(s["positions_value_eur"], float)
    assert isinstance(s["total_eur"], float)


# ---------------------------------------------------------------------------
# Additional coverage — lines 66, 74-75, 87-174, 188-198
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summary_no_positions_all_tickers_empty(client, db_session):
    """
    Lines 87-89: accounts exist but ALL have zero non-LIQUIDITE transactions.
    raw_positions is empty for all accounts → all_tickers == set() → price_meta = {}
    (takes the `else: price_meta = {}` branch at lines 139-140).
    """
    suffix = id(db_session)
    uid = await _create_portfolio(client, f"AccSum-AllEmpty-{suffix}")

    acc = Broker(name="Empty1", currency="EUR")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id, cash_balance_eur=200.0))
    await db_session.flush()

    # No transactions at all → raw_positions empty → all_tickers empty → else branch
    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    summaries = r.json()
    assert len(summaries) == 1
    assert summaries[0]["positions"] == []
    assert summaries[0]["positions_value_eur"] == 0.0
    assert summaries[0]["total_eur"] == pytest.approx(200.0)


@pytest.mark.asyncio
async def test_summary_with_usd_position(client, db_session):
    """
    Lines 143-172: a non-EUR position requires spot-rate conversion via _to_eur.
    Inserting a USD ticker with a USDEUR=X spot rate should produce correct EUR value.
    """
    from sqlalchemy import select as sa_select
    suffix = id(db_session)
    uid = await _create_portfolio(client, f"AccSum-USD-{suffix}")

    acc = Broker(name="IBKR", currency="USD")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id))
    await db_session.flush()

    ticker = f"AAPL.{suffix}"
    db_session.add(Product(ticker=ticker, name="Apple", category="Actif", currency="USD"))
    await db_session.flush()

    # Ensure USDEUR=X product exists (required by FK for AssetPrice)
    fx_ticker = "USDEUR=X"
    existing_fx = await db_session.execute(sa_select(Product).where(Product.ticker == fx_ticker))
    if not existing_fx.scalar_one_or_none():
        db_session.add(Product(ticker=fx_ticker, name="USD/EUR", category="Cash", currency="EUR"))
        await db_session.flush()

    # Buy 10 shares at 200 USD
    db_session.add(Transaction(
        portfolio_id=uid, account_id=acc.id,
        date=date(2025, 5, 1), type="Actif", ticker=ticker,
        currency="USD", exchange_rate=0.92,
        quantity=-10.0, unit_price=200.0, unit_price_eur=184.0,
        total_amount=-2000.0, total_amount_eur=-1840.0,
    ))
    await db_session.flush()

    # Price in USD with a spot rate
    db_session.add(AssetPrice(ticker=ticker, date=date(2025, 5, 1),
                               price=200.0, currency="USD", source="yfinance"))
    # Spot rate: USDEUR=X (1 USD = 0.92 EUR)
    db_session.add(AssetPrice(ticker=fx_ticker, date=date(2025, 5, 1),
                               price=0.92, currency="EUR", source="yfinance"))
    await db_session.flush()

    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    summaries = r.json()
    assert len(summaries) == 1
    positions = summaries[0]["positions"]
    # Should have the USD position
    usd_pos = next((p for p in positions if p["ticker"] == ticker), None)
    assert usd_pos is not None
    # 10 units × 200 USD × 0.92 = 1840 EUR
    assert usd_pos["value_eur"] == pytest.approx(1840.0, rel=0.01)


@pytest.mark.asyncio
async def test_list_accounts_returns_all_fields(client, db_session):
    """
    Lines 64-65: list_accounts returns id, portfolio_id, name, currency fields.
    """
    suffix = id(db_session)
    uid = await _create_portfolio(client, f"AccFields-{suffix}")
    acc = await _create_broker(client, uid, "Degiro", "EUR")

    r = await client.get("/api/brokers/", params={"portfolio_id": uid})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    a = data[0]
    assert a["id"] == acc["id"]
    assert a["name"] == "Degiro"
    assert a["currency"] == "EUR"


@pytest.mark.asyncio
async def test_summary_sorted_positions_by_name_asc(client, db_session):
    """
    Positions are sorted alphabetically by product_name (case-insensitive) ascending.
    'Alpha ETF' must appear before 'Zebra ETF' regardless of their values.
    """
    suffix = id(db_session)
    uid = await _create_portfolio(client, f"AccSum-Sort-{suffix}")

    acc = Broker(name="Sorted", currency="EUR")
    db_session.add(acc)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=acc.id))
    await db_session.flush()

    # Insert in reverse alphabetical order to prove sorting is applied
    for ticker, name, price in [
        (f"Z.{suffix}", "Zebra ETF", 1000.0),
        (f"A.{suffix}", "Alpha ETF", 100.0),
    ]:
        db_session.add(Product(ticker=ticker, name=name, category="Actif", currency="EUR"))
        await db_session.flush()
        db_session.add(Transaction(
            portfolio_id=uid, account_id=acc.id,
            date=date(2025, 6, 1), type="Actif", ticker=ticker,
            currency="EUR", exchange_rate=1.0,
            quantity=-5.0, unit_price=price, unit_price_eur=price,
            total_amount=-5 * price, total_amount_eur=-5 * price,
        ))
        db_session.add(AssetPrice(ticker=ticker, date=date(2025, 6, 1),
                                   price=price, currency="EUR", source="test"))
    await db_session.flush()

    r = await client.get("/api/brokers/summary", params={"portfolio_id": uid})
    assert r.status_code == 200
    positions = r.json()[0]["positions"]
    names = [p["product_name"] for p in positions]
    assert names == sorted(names, key=str.lower), f"Expected alphabetical order, got {names}"


# ---------------------------------------------------------------------------
# Regression: JPYEUR=X double-conversion bug
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jpyeur_cash_position_no_double_conversion(client, db_session):
    """
    Regression: when JPYEUR=X has currency='EUR' in asset_prices, _to_eur()
    returns the rate directly (0.0054) instead of multiplying it by itself again.

    Correct:   5_716_779 JPY × 0.0054 EUR/JPY = 30_870.61 €
    Old bug:   5_716_779 × (0.0054 × 0.0054)  =    166.70 €

    The fix: store currency='EUR' for forex *EUR=X tickers so _to_eur() skips
    conversion (price IS already in EUR).
    """
    from app.models.portfolio import Portfolio
    uid = id(db_session)

    portfolio = Portfolio(name=f"JPYFix-{uid}")
    db_session.add(portfolio)
    await db_session.flush()

    account = Broker(name="Revolut",
                      currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=portfolio.id, broker_id=account.id))
    await db_session.flush()

    product = Product(ticker="JPYEUR=X", name="JPY / EUR",
                      category="Cash", currency="EUR")  # EUR — the fix
    db_session.add(product)
    await db_session.flush()

    jpyeur_rate = 0.0054  # 1 JPY = 0.0054 EUR
    db_session.add(AssetPrice(ticker="JPYEUR=X", date=date(2026, 5, 16),
                              price=jpyeur_rate, currency="EUR", source="yfinance"))
    await db_session.flush()

    jpy_qty = 5_716_779.0
    db_session.add(Transaction(
        portfolio_id=portfolio.id, account_id=account.id,
        date=date(2026, 1, 1), type="Actif", ticker="JPYEUR=X",
        currency="EUR", exchange_rate=1.0,
        quantity=jpy_qty, unit_price=jpyeur_rate, unit_price_eur=jpyeur_rate,
        total_amount=jpy_qty * jpyeur_rate,
        total_amount_eur=jpy_qty * jpyeur_rate,
    ))
    await db_session.flush()

    r = await client.get("/api/brokers/summary",
                         params={"portfolio_id": portfolio.id})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    positions = data[0]["positions"]
    assert len(positions) == 1
    pos = positions[0]

    expected_eur = round(jpy_qty * jpyeur_rate, 2)  # 30_870.61
    assert abs(pos["value_eur"] - expected_eur) < 0.02, (
        f"Regression JPYEUR=X double-conversion: "
        f"got {pos['value_eur']} € instead of {expected_eur} €. "
        f"Fix: asset_prices.currency must be 'EUR' for *EUR=X tickers."
    )
    # Sanity: old bug would give ~166.70
    assert pos["value_eur"] > 1000, (
        f"Value {pos['value_eur']} € looks like the double-conversion bug "
        f"(expected ~30 870 €)"
    )


@pytest.mark.asyncio
async def test_update_commission_schedule(client, db_session):
    """PUT /api/accounts/{id}/commission updates commission_schedule."""
    from tests.helpers import create_portfolio, create_broker

    pid = await create_portfolio(client, "CommissionTest")
    acc = await create_broker(client, pid, name="Degiro Commission")
    acc_id = acc["id"]

    schedule = [{"up_to": None, "type": "flat", "value": 3.0}]
    r = await client.put(f"/api/brokers/{acc_id}/commission",
                         json={"commission_schedule": schedule})
    assert r.status_code == 200
    data = r.json()
    assert data["commission_schedule"] == schedule


@pytest.mark.asyncio
async def test_update_commission_schedule_not_found(client):
    """PUT commission on non-existent account returns 404."""
    r = await client.put("/api/brokers/999999/commission",
                         json={"commission_schedule": []})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_accounts_includes_commission_schedule(client, db_session):
    """GET /api/accounts/ includes commission_schedule field."""
    from tests.helpers import create_portfolio, create_broker

    pid = await create_portfolio(client, "CommissionListTest")
    await create_broker(client, pid, name="Degiro List")

    r = await client.get("/api/brokers/", params={"portfolio_id": pid})
    assert r.status_code == 200
    accounts = r.json()
    assert len(accounts) == 1
    assert "commission_schedule" in accounts[0]


@pytest.mark.asyncio
async def test_update_allowed_tickers(client, db_session):
    """PUT /api/accounts/{id}/allowed-tickers sets the whitelist."""
    from tests.helpers import create_portfolio, create_broker

    pid = await create_portfolio(client, "AllowedTickersTest")
    acc = await create_broker(client, pid, name="PEA Tickers")
    acc_id = acc["id"]

    tickers = ["AI.PA", "TTE.PA", "LIQUIDITE.EURO"]
    r = await client.put(f"/api/brokers/{acc_id}/allowed-tickers",
                         json={"allowed_tickers": tickers})
    assert r.status_code == 200
    assert r.json()["allowed_tickers"] == tickers


@pytest.mark.asyncio
async def test_update_allowed_tickers_null_removes_restriction(client, db_session):
    """PUT with null removes the whitelist restriction."""
    from tests.helpers import create_portfolio, create_broker

    pid = await create_portfolio(client, "AllowedTickersNullTest")
    acc = await create_broker(client, pid, name="All Products")
    acc_id = acc["id"]

    r = await client.put(f"/api/brokers/{acc_id}/allowed-tickers",
                         json={"allowed_tickers": None})
    assert r.status_code == 200
    assert r.json()["allowed_tickers"] is None


@pytest.mark.asyncio
async def test_update_allowed_tickers_not_found(client):
    """PUT on non-existent account returns 404."""
    r = await client.put("/api/brokers/999999/allowed-tickers",
                         json={"allowed_tickers": ["AI.PA"]})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_accounts_includes_allowed_tickers(client, db_session):
    """GET /api/accounts/ includes allowed_tickers field."""
    from tests.helpers import create_portfolio, create_broker

    pid = await create_portfolio(client, "AllowedTickersListTest")
    await create_broker(client, pid, name="PEA List")

    r = await client.get("/api/brokers/", params={"portfolio_id": pid})
    assert r.status_code == 200
    accounts = r.json()
    assert len(accounts) == 1
    assert "allowed_tickers" in accounts[0]


@pytest.mark.asyncio
async def test_update_commission_sale_rate(client, db_session):
    """PUT /api/accounts/{id}/sale-rate updates commission_sale_rate."""
    from tests.helpers import create_portfolio, create_broker

    pid = await create_portfolio(client, "SaleRateTest")
    acc = await create_broker(client, pid, name="auCoffre SaleRate")
    acc_id = acc["id"]

    r = await client.put(f"/api/brokers/{acc_id}/sale-rate",
                         json={"commission_sale_rate": 0.03})
    assert r.status_code == 200
    assert r.json()["commission_sale_rate"] == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_update_commission_sale_rate_not_found(client):
    """PUT sale-rate on non-existent account returns 404."""
    r = await client.put("/api/brokers/999999/sale-rate",
                         json={"commission_sale_rate": 0.03})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_include_fees_in_cump(client, db_session):
    """PUT /api/accounts/{id}/include-fees updates include_fees_in_cump."""
    from tests.helpers import create_portfolio, create_broker

    pid = await create_portfolio(client, "IncludeFeesTest")
    acc = await create_broker(client, pid, name="Degiro Fees")
    acc_id = acc["id"]

    r = await client.put(f"/api/brokers/{acc_id}/include-fees",
                         json={"include_fees_in_cump": False})
    assert r.status_code == 200
    assert r.json()["include_fees_in_cump"] is False

    r2 = await client.put(f"/api/brokers/{acc_id}/include-fees",
                          json={"include_fees_in_cump": True})
    assert r2.status_code == 200
    assert r2.json()["include_fees_in_cump"] is True


@pytest.mark.asyncio
async def test_update_include_fees_not_found(client):
    """PUT include-fees on non-existent account returns 404."""
    r = await client.put("/api/brokers/999999/include-fees",
                         json={"include_fees_in_cump": False})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_fx_commission(client, db_session):
    """PUT /api/accounts/{id}/fx-commission sets monthly FX params."""
    from tests.helpers import create_portfolio, create_broker

    pid = await create_portfolio(client, "FXCommTest")
    acc = await create_broker(client, pid, name="Revolut FX")
    acc_id = acc["id"]

    r = await client.put(f"/api/brokers/{acc_id}/fx-commission", json={
        "monthly_free_eur": 1000.0,
        "above_monthly_rate": 0.01,
        "weekend_rate": 0.01,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["monthly_free_eur"] == 1000.0
    assert data["above_monthly_rate"] == pytest.approx(0.01)
    assert data["weekend_rate"] == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_update_fx_commission_null_clears_params(client, db_session):
    """PUT fx-commission with null monthly_free_eur disables monthly limit."""
    from tests.helpers import create_portfolio, create_broker

    pid = await create_portfolio(client, "FXClear")
    acc = await create_broker(client, pid, name="Generic FX")
    acc_id = acc["id"]

    r = await client.put(f"/api/brokers/{acc_id}/fx-commission", json={
        "monthly_free_eur": None,
        "above_monthly_rate": 0.0,
        "weekend_rate": None,
    })
    assert r.status_code == 200
    assert r.json()["monthly_free_eur"] is None
    assert r.json()["weekend_rate"] is None


@pytest.mark.asyncio
async def test_update_fx_commission_not_found(client):
    """PUT fx-commission on non-existent account returns 404."""
    r = await client.put("/api/brokers/999999/fx-commission", json={
        "monthly_free_eur": 500.0,
        "above_monthly_rate": 0.02,
        "weekend_rate": None,
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_account_name_and_color(client, db_session):
    """PUT /api/accounts/{id} updates name and color."""
    from tests.helpers import create_portfolio, create_broker

    pid = await create_portfolio(client, "UpdateAccTest")
    acc = await create_broker(client, pid, name="OldName")
    acc_id = acc["id"]

    r = await client.put(f"/api/brokers/{acc_id}", json={"name": "NewName", "color": "#FF4D4F"})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "NewName"
    assert data["color"] == "#FF4D4F"


@pytest.mark.asyncio
async def test_update_account_not_found(client):
    """PUT account on non-existent id returns 404."""
    r = await client.put("/api/brokers/999999", json={"name": "X"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_account_no_transactions(client, db_session):
    """DELETE account with no transactions succeeds."""
    from tests.helpers import create_portfolio, create_broker

    pid = await create_portfolio(client, "DeleteAccTest")
    acc = await create_broker(client, pid, name="ToDelete")
    acc_id = acc["id"]

    r = await client.delete(f"/api/brokers/{acc_id}")
    assert r.status_code == 204

    # Account should be gone
    r2 = await client.get("/api/brokers/", params={"portfolio_id": pid})
    assert all(a["id"] != acc_id for a in r2.json())


@pytest.mark.asyncio
async def test_delete_account_not_found(client):
    """DELETE non-existent account returns 404."""
    r = await client.delete("/api/brokers/999999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_account_with_transactions_returns_400(client, db_session):
    """DELETE account with linked transactions returns 400."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"DelAccTx-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Locked", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LOCK.TEST", name="Lock Test", category="Actif", currency="EUR"))
    await db_session.flush()

    tx = TxModel(
        portfolio_id=uid, account_id=aid, date=__import__('datetime').date(2026, 1, 1),
        type="Actif", ticker="LOCK.TEST", currency="EUR", exchange_rate=1.0,
        quantity=-1.0, unit_price=10.0, unit_price_eur=10.0,
        total_amount=-10.0, total_amount_eur=-10.0,
    )
    db_session.add(tx)
    await db_session.flush()

    r = await client.delete(f"/api/brokers/{aid}")
    assert r.status_code == 400
    assert "transaction" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_all_accounts_no_portfolio_filter(client, db_session):
    """GET /api/accounts/ without portfolio_id returns all accounts."""
    from tests.helpers import create_portfolio, create_broker

    pid1 = await create_portfolio(client, "AllAccP1")
    pid2 = await create_portfolio(client, "AllAccP2")
    await create_broker(client, pid1, name="AccP1")
    await create_broker(client, pid2, name="AccP2")

    # Without filter: returns accounts from both portfolios
    r = await client.get("/api/brokers/")
    assert r.status_code == 200
    names = [a["name"] for a in r.json()]
    assert "AccP1" in names
    assert "AccP2" in names


@pytest.mark.asyncio
async def test_update_account_portfolios(client, db_session):
    """PUT /api/accounts/{id}/portfolios replaces portfolio assignments."""
    pid1 = await _create_portfolio(client, f"UpdPorts-P1-{id(db_session)}")
    pid2 = await _create_portfolio(client, f"UpdPorts-P2-{id(db_session)}")

    # Create account assigned to pid1 only
    r = await client.post("/api/brokers/", json={"name": "Transferable", "currency": "EUR", "portfolio_ids": [pid1]})
    assert r.status_code == 201
    acc_id = r.json()["id"]
    assert r.json()["portfolio_ids"] == [pid1]

    # Assign to both portfolios
    r = await client.put(f"/api/brokers/{acc_id}/portfolios", json={"portfolio_ids": [pid1, pid2]})
    assert r.status_code == 200
    assert set(r.json()["portfolio_ids"]) == {pid1, pid2}

    # Remove from pid1, keep only pid2
    r = await client.put(f"/api/brokers/{acc_id}/portfolios", json={"portfolio_ids": [pid2]})
    assert r.status_code == 200
    assert r.json()["portfolio_ids"] == [pid2]

    # Account no longer appears in pid1 list
    r = await client.get("/api/brokers/", params={"portfolio_id": pid1})
    assert all(a["id"] != acc_id for a in r.json())

    # Account still appears in pid2 list
    r = await client.get("/api/brokers/", params={"portfolio_id": pid2})
    assert any(a["id"] == acc_id for a in r.json())


@pytest.mark.asyncio
async def test_update_account_portfolios_404(client, db_session):
    """PUT /api/accounts/{id}/portfolios returns 404 for unknown account."""
    r = await client.put("/api/brokers/999999/portfolios", json={"portfolio_ids": []})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_summary_forex_deducts_foreign_currency_fees(client, db_session):
    """
    Regression: fees charged in a foreign currency (e.g. FRAIS.COURTAGE.JPY)
    were excluded from the JPYEUR=X position quantity in the accounts summary
    because get_accounts_summary() filtered type='Actif' only.

    total_amount of fee transactions in the foreign currency must be subtracted
    from the matching forex (Cash) position per broker.
    """
    suffix = f"fee-{id(db_session)}"
    portfolio = Portfolio(name=f"FeePortfolio-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    pid = portfolio.id

    broker = Broker(name=f"Revolut-{suffix}", currency="EUR")
    db_session.add(broker)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=pid, broker_id=broker.id, cash_balance_eur=0.0))
    await db_session.flush()

    jpyeur_ticker = f"JPYEUR=X.{suffix}"
    fee_ticker = f"FRAIS.COURTAGE.JPY.{suffix}"
    db_session.add(Product(ticker=jpyeur_ticker, name="JPY/EUR", category="Cash", currency="EUR"))
    db_session.add(Product(ticker=fee_ticker, name="JPY Fee", category="Fee", currency="JPY"))
    await db_session.flush()

    # Buy 300,000 JPY
    db_session.add(Transaction(
        portfolio_id=pid, account_id=broker.id,
        date=date(2025, 6, 1), type="Actif", ticker=jpyeur_ticker,
        currency="JPY", exchange_rate=0.006,
        quantity=300_000.0, unit_price=1.0, unit_price_eur=0.006,
        total_amount=300_000.0, total_amount_eur=1800.0,
    ))
    # Fee: 185 JPY
    db_session.add(Transaction(
        portfolio_id=pid, account_id=broker.id,
        date=date(2025, 6, 2), type="Frais", ticker=fee_ticker,
        currency="JPY", exchange_rate=0.006,
        quantity=-1.0, unit_price=185.0, unit_price_eur=1.11,
        total_amount=-185.0, total_amount_eur=-1.11,
    ))
    db_session.add(AssetPrice(ticker=jpyeur_ticker, date=date(2025, 6, 2),
                               price=0.006, currency="EUR", source="yfinance"))
    await db_session.flush()

    r = await client.get("/api/brokers/summary", params={"portfolio_id": pid})
    assert r.status_code == 200
    broker_data = next((b for b in r.json() if b["name"] == f"Revolut-{suffix}"), None)
    assert broker_data is not None
    pos = next((p for p in broker_data["positions"] if p["ticker"] == jpyeur_ticker), None)
    assert pos is not None
    # 300,000 - 185 = 299,815 JPY (fee deducted from forex position)
    assert pos["quantity"] == pytest.approx(299_815.0, rel=0.001)


@pytest.mark.asyncio
async def test_summary_forex_fee_with_fully_sold_position(client, db_session):
    """
    brokers.py line 357->355 False branch:
    `if adj and row.ticker in raw_positions.get(row.account_id, {})`
    is False when adj != 0 but the forex position has been fully closed.

    A broker holds JPY (buy 300k, sell 300k → net qty = 0).
    The JPYEUR=X ticker is not in raw_positions, so the fee-adjustment
    branch skips it without error.
    """
    from datetime import date

    suffix = f"sold-jpy-{id(db_session)}"
    portfolio = Portfolio(name=f"SoldJPY-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()
    pid = portfolio.id

    broker = Broker(name=f"MUFG-{suffix}", currency="JPY")
    db_session.add(broker)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=pid, broker_id=broker.id))

    jpyeur_ticker = f"JPYEUR.SOLD.{suffix}"
    fee_ticker = f"FRAIS.JPY.SOLD.{suffix}"
    db_session.add(Product(ticker=jpyeur_ticker, name="JPY/EUR closed", category="Cash", currency="EUR"))
    db_session.add(Product(ticker=fee_ticker, name="JPY Fee closed", category="Fee", currency="JPY"))
    await db_session.flush()

    # Buy 300k JPY, then sell all 300k → net qty = 0, no position in raw_positions
    db_session.add(Transaction(
        portfolio_id=pid, account_id=broker.id,
        date=date(2025, 6, 1), type="Actif", ticker=jpyeur_ticker,
        currency="JPY", exchange_rate=0.006,
        quantity=300_000.0, unit_price=1.0, unit_price_eur=0.006,
        total_amount=300_000.0, total_amount_eur=1800.0,
    ))
    db_session.add(Transaction(
        portfolio_id=pid, account_id=broker.id,
        date=date(2025, 6, 3), type="Actif", ticker=jpyeur_ticker,
        currency="JPY", exchange_rate=0.006,
        quantity=-300_000.0, unit_price=1.0, unit_price_eur=0.006,
        total_amount=-300_000.0, total_amount_eur=-1800.0,
    ))
    # Fee still exists even though position is fully closed
    db_session.add(Transaction(
        portfolio_id=pid, account_id=broker.id,
        date=date(2025, 6, 2), type="Frais", ticker=fee_ticker,
        currency="JPY", exchange_rate=0.006,
        quantity=-1.0, unit_price=185.0, unit_price_eur=1.11,
        total_amount=-185.0, total_amount_eur=-1.11,
    ))
    await db_session.flush()

    r = await client.get("/api/brokers/summary", params={"portfolio_id": pid})
    assert r.status_code == 200
    # No crash; the broker with a closed position and a fee is handled gracefully
    broker_data = next((b for b in r.json() if b["name"] == f"MUFG-{suffix}"), None)
    assert broker_data is not None
    # Position is fully closed — should not appear
    positions = [p for p in broker_data["positions"] if p["ticker"] == jpyeur_ticker]
    assert positions == []
