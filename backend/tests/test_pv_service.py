# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the Capital Gains (Plus-Values) service — CUMP method.

Covered invariants:
  1. CUMP basic: 2 buys at different prices → correct weighted average.
  2. Realized PV: buy then sell → correct gain/loss.
  3. CUMP reset: full sell then rebuy → CUMP resets, old PV preserved.
  4. Multiple cycles: buy/sell/buy/sell → cumulative PV tracked correctly.
  5. Frais/Revenu ignored: fee transactions don't affect CUMP.
  6. Manuel category excluded: OR.PHYSIQUE skipped.
  7. account_id filter: only returns transactions for that account.
  8. Partial sell does not reset CUMP.
  9. Endpoint GET /api/pv/ returns 200 with correct structure.
 10. Empty portfolio returns zero totals.
 11. Realized PV uses total_amount_eur (exact), not rounded unit_price_eur * qty.
"""
from __future__ import annotations

import pytest
from datetime import date

from app.models.portfolio import Portfolio
from app.models.broker import Broker
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.portfolio_account import PortfolioAccount
from app.services.pv_service import compute_capital_gains


# ---------------------------------------------------------------------------
# Helper — build a minimal Transaction without HTTP (direct DB insert)
# ---------------------------------------------------------------------------

def _tx(
    portfolio_id: int,
    account_id: int,
    ticker: str,
    quantity: float,           # negative = buy, positive = sell
    unit_price_eur: float,
    tx_date: date,
    tx_type: str = "Actif",
    tx_id: int | None = None,
) -> Transaction:
    total_amount_eur = quantity * unit_price_eur
    kwargs = dict(
        portfolio_id=portfolio_id,
        account_id=account_id,
        date=tx_date,
        type=tx_type,
        ticker=ticker,
        currency="EUR",
        exchange_rate=1.0,
        quantity=quantity,
        unit_price=unit_price_eur,
        unit_price_eur=unit_price_eur,
        total_amount=total_amount_eur,
        total_amount_eur=total_amount_eur,
    )
    if tx_id is not None:
        kwargs["id"] = tx_id
    return Transaction(**kwargs)


async def _setup_base(db):
    """Insert a portfolio + account; return (portfolio_id, account_id)."""
    portfolio = Portfolio(name=f"PV-Test-{id(db)}")
    db.add(portfolio)
    await db.flush()

    account = Broker(name="Degiro", currency="EUR")
    db.add(account)
    await db.flush()
    db.add(PortfolioAccount(portfolio_id=portfolio.id, broker_id=account.id))
    await db.flush()
    return portfolio.id, account.id


async def _ensure_product(db, ticker: str, name: str, category: str = "Actif",
                           instrument_type: str | None = None) -> None:
    from sqlalchemy import select
    existing = await db.execute(select(Product).where(Product.ticker == ticker))
    if not existing.scalar_one_or_none():
        db.add(Product(ticker=ticker, name=name, category=category, currency="EUR",
                        instrument_type=instrument_type))
        await db.flush()


# ---------------------------------------------------------------------------
# Test 1: CUMP basic — two buys at different prices
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cump_weighted_average_two_buys(db_session):
    """
    Buy 10 units @ 100 EUR, then 10 units @ 120 EUR.
    Expected CUMP = (10×100 + 10×120) / 20 = 110 EUR.
    """
    pid, aid = await _setup_base(db_session)
    ticker = f"ETF.CUMP.{pid}"
    await _ensure_product(db_session, ticker, "Test ETF CUMP")

    db_session.add(_tx(pid, aid, ticker, -10.0, 100.0, date(2024, 1, 1)))
    db_session.add(_tx(pid, aid, ticker, -10.0, 120.0, date(2024, 2, 1)))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)

    assert len(result.tickers) == 1
    t = result.tickers[0]
    assert t.ticker == ticker
    assert t.qty_held == pytest.approx(20.0, abs=1e-6)
    assert t.cump == pytest.approx(110.0, rel=1e-6)
    assert t.cost_basis_eur == pytest.approx(2200.0, abs=0.01)
    assert result.total_realized_pv == pytest.approx(0.0, abs=0.01)
    assert t.events == []


# ---------------------------------------------------------------------------
# Test 2: Realized PV — buy then sell (gain)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_realized_pv_buy_then_sell_gain(db_session):
    """
    Buy 10 @ 100 EUR, sell 5 @ 130 EUR.
    CUMP = 100. PV per sell = (130 - 100) × 5 = 150 EUR.
    """
    pid, aid = await _setup_base(db_session)
    ticker = f"ETF.GAIN.{pid}"
    await _ensure_product(db_session, ticker, "Test ETF Gain")

    db_session.add(_tx(pid, aid, ticker, -10.0, 100.0, date(2024, 1, 1)))
    db_session.add(_tx(pid, aid, ticker, 5.0, 130.0, date(2024, 3, 1)))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    t = result.tickers[0]

    assert t.qty_held == pytest.approx(5.0, abs=1e-6)
    assert t.cump == pytest.approx(100.0, rel=1e-6)
    assert t.realized_pv_total == pytest.approx(150.0, abs=0.01)
    assert result.total_realized_pv == pytest.approx(150.0, abs=0.01)

    assert len(t.events) == 1
    ev = t.events[0]
    assert ev.realized_pv == pytest.approx(150.0, abs=0.01)
    assert ev.cump_at_sell == pytest.approx(100.0, rel=1e-6)
    assert ev.sell_price_eur == pytest.approx(130.0, rel=1e-6)
    assert ev.qty_sold == pytest.approx(5.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 3: Realized PV — buy then sell (loss)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_realized_pv_buy_then_sell_loss(db_session):
    """
    Buy 10 @ 100 EUR, sell 10 @ 80 EUR.
    CUMP = 100. PV = (80 - 100) × 10 = -200 EUR (loss).
    """
    pid, aid = await _setup_base(db_session)
    ticker = f"ETF.LOSS.{pid}"
    await _ensure_product(db_session, ticker, "Test ETF Loss")

    db_session.add(_tx(pid, aid, ticker, -10.0, 100.0, date(2024, 1, 1)))
    db_session.add(_tx(pid, aid, ticker, 10.0, 80.0, date(2024, 4, 1)))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    t = result.tickers[0]

    assert t.qty_held == pytest.approx(0.0, abs=1e-6)
    assert t.cump == pytest.approx(0.0, abs=1e-6)      # reset after full sell
    assert t.realized_pv_total == pytest.approx(-200.0, abs=0.01)
    assert result.total_realized_pv == pytest.approx(-200.0, abs=0.01)


# ---------------------------------------------------------------------------
# Test 4: CUMP reset — full sell then rebuy → old PV preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cump_reset_after_full_sell(db_session):
    """
    Cycle 1: Buy 10 @ 100, sell 10 @ 120 → PV = 200.
    Cycle 2: Buy 5 @ 150 → new CUMP = 150, old PV still 200.
    """
    pid, aid = await _setup_base(db_session)
    ticker = f"ETF.RESET.{pid}"
    await _ensure_product(db_session, ticker, "Test ETF Reset")

    # Cycle 1
    db_session.add(_tx(pid, aid, ticker, -10.0, 100.0, date(2024, 1, 1)))
    db_session.add(_tx(pid, aid, ticker, 10.0, 120.0, date(2024, 2, 1)))
    # Cycle 2
    db_session.add(_tx(pid, aid, ticker, -5.0, 150.0, date(2024, 3, 1)))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    t = result.tickers[0]

    assert t.qty_held == pytest.approx(5.0, abs=1e-6)
    assert t.cump == pytest.approx(150.0, rel=1e-6)         # reset & new buy
    assert t.realized_pv_total == pytest.approx(200.0, abs=0.01)  # from cycle 1
    assert len(t.events) == 1


# ---------------------------------------------------------------------------
# Test 5: Multiple cycles — cumulative PV tracked correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_cycles_cumulative_pv(db_session):
    """
    Cycle 1: buy 10 @ 100, sell 10 @ 110 → PV1 = 100.
    Cycle 2: buy 8 @ 120, sell 8 @ 115 → PV2 = -40.
    Total realized PV = 60.
    """
    pid, aid = await _setup_base(db_session)
    ticker = f"ETF.MULTI.{pid}"
    await _ensure_product(db_session, ticker, "Test ETF Multi")

    # Cycle 1
    db_session.add(_tx(pid, aid, ticker, -10.0, 100.0, date(2024, 1, 1)))
    db_session.add(_tx(pid, aid, ticker, 10.0, 110.0, date(2024, 2, 1)))
    # Cycle 2
    db_session.add(_tx(pid, aid, ticker, -8.0, 120.0, date(2024, 3, 1)))
    db_session.add(_tx(pid, aid, ticker, 8.0, 115.0, date(2024, 4, 1)))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    t = result.tickers[0]

    assert t.qty_held == pytest.approx(0.0, abs=1e-6)
    assert t.cump == pytest.approx(0.0, abs=1e-6)
    assert t.realized_pv_total == pytest.approx(60.0, abs=0.01)
    assert result.total_realized_pv == pytest.approx(60.0, abs=0.01)
    assert len(t.events) == 2


# ---------------------------------------------------------------------------
# Test 6: Frais/Revenu ignored — fees don't affect CUMP
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_frais_and_revenu_do_not_affect_cump(db_session):
    """
    Buy 10 @ 100 (CUMP = 100).
    Insert a Frais transaction and a Revenu transaction for the same ticker.
    CUMP must remain 100.
    """
    pid, aid = await _setup_base(db_session)
    ticker = f"ETF.FRAIS.{pid}"
    fee_ticker = f"FRAIS.{pid}"
    rev_ticker = f"DIV.{pid}"
    await _ensure_product(db_session, ticker, "Test ETF Frais")
    await _ensure_product(db_session, fee_ticker, "Frais courtage", category="Frais")
    await _ensure_product(db_session, rev_ticker, "Dividende", category="Actif")

    db_session.add(_tx(pid, aid, ticker, -10.0, 100.0, date(2024, 1, 1)))
    # Frais transaction (type=Frais) — must be ignored
    db_session.add(_tx(pid, aid, fee_ticker, 1.0, 5.0, date(2024, 1, 15), tx_type="Frais"))
    # Revenu transaction (dividend, type=Revenu) — must be ignored
    db_session.add(_tx(pid, aid, rev_ticker, 1.0, 2.0, date(2024, 1, 20), tx_type="Revenu"))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)

    # Only the ETF ticker should appear
    tickers_found = {t.ticker for t in result.tickers}
    assert ticker in tickers_found
    assert fee_ticker not in tickers_found
    assert rev_ticker not in tickers_found

    etf = next(t for t in result.tickers if t.ticker == ticker)
    assert etf.cump == pytest.approx(100.0, rel=1e-6)
    assert etf.qty_held == pytest.approx(10.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 7: Manuel category excluded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manuel_category_excluded(db_session):
    """
    OR.PHYSIQUE (category='Manuel') transactions must be excluded from CUMP.
    """
    pid, aid = await _setup_base(db_session)
    gold_ticker = f"OR.PHYS.{pid}"
    etf_ticker = f"ETF.NORM.{pid}"
    await _ensure_product(db_session, gold_ticker, "Or Physique", category="Actif", instrument_type="Or physique")
    await _ensure_product(db_session, etf_ticker, "ETF Normal")

    # Gold — should be ignored
    db_session.add(_tx(pid, aid, gold_ticker, -5.0, 2000.0, date(2024, 1, 1)))
    # Normal ETF — should be included
    db_session.add(_tx(pid, aid, etf_ticker, -10.0, 50.0, date(2024, 1, 1)))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    tickers_found = {t.ticker for t in result.tickers}

    assert gold_ticker not in tickers_found
    assert etf_ticker in tickers_found


# ---------------------------------------------------------------------------
# Test 8: account_id filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_account_id_filter(db_session):
    """
    Two accounts with transactions on the same ticker.
    Filtering by account_id=A should only include account A's transactions.
    """
    pid, aid_a = await _setup_base(db_session)
    account_b = Broker(name="BourseDir", currency="EUR")
    db_session.add(account_b)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=pid, broker_id=account_b.id))
    await db_session.flush()
    aid_b = account_b.id

    ticker = f"ETF.FILTER.{pid}"
    await _ensure_product(db_session, ticker, "Test ETF Filter")

    # Account A: buy 10 @ 100
    db_session.add(_tx(pid, aid_a, ticker, -10.0, 100.0, date(2024, 1, 1)))
    # Account B: buy 5 @ 200 (different price)
    db_session.add(_tx(pid, aid_b, ticker, -5.0, 200.0, date(2024, 1, 2)))
    await db_session.flush()

    # Filter for account A only
    result_a = await compute_capital_gains(db_session, pid, account_id=aid_a)
    assert len(result_a.tickers) == 1
    t_a = result_a.tickers[0]
    assert t_a.qty_held == pytest.approx(10.0, abs=1e-6)
    assert t_a.cump == pytest.approx(100.0, rel=1e-6)

    # Filter for account B only
    result_b = await compute_capital_gains(db_session, pid, account_id=aid_b)
    assert len(result_b.tickers) == 1
    t_b = result_b.tickers[0]
    assert t_b.qty_held == pytest.approx(5.0, abs=1e-6)
    assert t_b.cump == pytest.approx(200.0, rel=1e-6)


# ---------------------------------------------------------------------------
# Test 9: Partial sell does not reset CUMP
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partial_sell_does_not_reset_cump(db_session):
    """
    Buy 10 @ 100, sell 5 @ 130 → qty_held = 5, CUMP stays at 100.
    """
    pid, aid = await _setup_base(db_session)
    ticker = f"ETF.PARTIAL.{pid}"
    await _ensure_product(db_session, ticker, "Test ETF Partial")

    db_session.add(_tx(pid, aid, ticker, -10.0, 100.0, date(2024, 1, 1)))
    db_session.add(_tx(pid, aid, ticker, 5.0, 130.0, date(2024, 3, 1)))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    t = result.tickers[0]

    assert t.qty_held == pytest.approx(5.0, abs=1e-6)
    assert t.cump == pytest.approx(100.0, rel=1e-6)   # NOT reset, position still open


# ---------------------------------------------------------------------------
# Test 10: Endpoint GET /api/pv/ — HTTP integration test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pv_endpoint_returns_200_and_structure(client, db_session):
    """
    GET /api/pv/?portfolio_id=X must return 200 with valid JSON structure
    even when there are no transactions.
    """
    from tests.helpers import create_portfolio
    pid = await create_portfolio(client, f"PV-HTTP-{id(db_session)}")

    r = await client.get("/api/pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    data = r.json()

    assert data["portfolio_id"] == pid
    assert data["tickers"] == []
    assert data["total_unrealized_pv"] == 0.0
    assert data["total_realized_pv"] == 0.0
    assert data["total_pv"] == 0.0


# ---------------------------------------------------------------------------
# Test 11: Endpoint with transactions and current price
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pv_endpoint_fills_current_value_from_prices(client, db_session):
    """
    Buy 10 units @ 100 EUR, insert a latest price of 120 EUR.
    Endpoint should return current_value_eur=1200, unrealized_pv=200.
    """
    from datetime import date as date_cls
    from app.models.price import AssetPrice
    from tests.helpers import create_portfolio, create_broker_id, create_product

    pid = await create_portfolio(client, f"PV-HTTP-Price-{id(db_session)}")
    aid = await create_broker_id(client, pid)
    ticker = f"ETF.HTTP.{pid}"
    await create_product(client, ticker, "Test ETF HTTP Price", category="Actif", currency="EUR")

    # Insert buy transaction directly via DB
    db_session.add(Transaction(
        portfolio_id=pid,
        account_id=aid,
        date=date_cls(2024, 1, 1),
        type="Actif",
        ticker=ticker,
        currency="EUR",
        exchange_rate=1.0,
        quantity=-10.0,
        unit_price=100.0,
        unit_price_eur=100.0,
        total_amount=-1000.0,
        total_amount_eur=-1000.0,
    ))
    # Insert a price
    db_session.add(AssetPrice(
        ticker=ticker,
        date=date_cls(2024, 6, 1),
        price=120.0,
        currency="EUR",
        source="manual",
    ))
    await db_session.flush()

    r = await client.get("/api/pv/", params={"portfolio_id": pid})
    assert r.status_code == 200
    data = r.json()

    assert len(data["tickers"]) == 1
    t = data["tickers"][0]
    assert t["ticker"] == ticker
    assert t["qty_held"] == pytest.approx(10.0, abs=1e-6)
    assert t["cump"] == pytest.approx(100.0, rel=1e-4)
    assert t["cost_basis_eur"] == pytest.approx(1000.0, abs=0.01)
    assert t["current_value_eur"] == pytest.approx(1200.0, abs=0.01)
    assert t["unrealized_pv"] == pytest.approx(200.0, abs=0.01)
    assert data["total_unrealized_pv"] == pytest.approx(200.0, abs=0.01)


# ---------------------------------------------------------------------------
# Test 12: account_id filter via HTTP endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pv_endpoint_account_filter(client, db_session):
    """
    GET /api/pv/?portfolio_id=X&account_id=Y filters transactions by account.
    """
    from datetime import date as date_cls
    from tests.helpers import create_portfolio, create_broker_id, create_broker, create_product

    pid = await create_portfolio(client, f"PV-AccFilt-{id(db_session)}")
    aid_a = await create_broker_id(client, pid, "Degiro")
    aid_b = (await create_broker(client, pid, "BourseDir"))["id"]

    ticker = f"ETF.AFILT.{pid}"
    await create_product(client, ticker, "Test ETF AccFilter", category="Actif", currency="EUR")

    # Account A: buy 20 @ 100
    db_session.add(Transaction(
        portfolio_id=pid, account_id=aid_a,
        date=date_cls(2024, 1, 1), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-20.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=-2000.0, total_amount_eur=-2000.0,
    ))
    # Account B: buy 5 @ 200
    db_session.add(Transaction(
        portfolio_id=pid, account_id=aid_b,
        date=date_cls(2024, 1, 2), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-5.0, unit_price=200.0, unit_price_eur=200.0,
        total_amount=-1000.0, total_amount_eur=-1000.0,
    ))
    await db_session.flush()

    r = await client.get("/api/pv/", params={"portfolio_id": pid, "account_id": aid_a})
    assert r.status_code == 200
    data = r.json()
    assert len(data["tickers"]) == 1
    t = data["tickers"][0]
    assert t["qty_held"] == pytest.approx(20.0, abs=1e-6)
    assert t["cump"] == pytest.approx(100.0, rel=1e-4)

# ---------------------------------------------------------------------------
# Test 12: LIQUIDITE.* tickers are excluded entirely
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_liquidite_tickers_excluded(db_session):
    """
    LIQUIDITE.EURO, LIQUIDITE.USD and similar cash-account tickers must be
    excluded from PV calculation — they are pure cash entries, not assets.
    """
    pid, aid = await _setup_base(db_session)
    await _ensure_product(db_session, "LIQUIDITE.EURO", "Cash EUR", category="Actif", instrument_type="Cash")
    await _ensure_product(db_session, "LIQUIDITE.USD", "Cash USD", category="Actif", instrument_type="Cash")

    # Cash deposit (qty > 0) and withdrawal (qty < 0) — both must be ignored
    db_session.add(_tx(pid, aid, "LIQUIDITE.EURO",  45000.0, 1.0, date(2024, 1, 1)))
    db_session.add(_tx(pid, aid, "LIQUIDITE.EURO", -20000.0, 1.0, date(2024, 6, 1)))
    db_session.add(_tx(pid, aid, "LIQUIDITE.USD",   10000.0, 1.0, date(2024, 3, 1)))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    tickers_found = [t.ticker for t in result.tickers]
    assert "LIQUIDITE.EURO" not in tickers_found
    assert "LIQUIDITE.USD" not in tickers_found
    assert result.total_realized_pv == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# Test 13: Cash forex (JPYEUR=X) uses inverted sign convention
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cash_forex_inverted_sign_convention(db_session):
    """
    For Cash forex products (JPYEUR=X etc.): qty > 0 = BUY (acquiring JPY),
    qty < 0 = SELL (reducing JPY position). This is the opposite of Actif.
    Buy 1 000 000 JPY @ 0.006 EUR, then sell 500 000 JPY @ 0.007 EUR.
    Expected realized PV = (0.007 - 0.006) × 500 000 = 500 EUR.
    """
    pid, aid = await _setup_base(db_session)
    await _ensure_product(db_session, "JPYEUR=X", "JPY/EUR", category="Actif", instrument_type="Cash")

    # Buy 1 000 000 JPY @ 0.006 EUR/JPY (qty > 0 = buy for Cash forex)
    db_session.add(_tx(pid, aid, "JPYEUR=X", 1_000_000.0, 0.006, date(2024, 1, 1)))
    # Sell 500 000 JPY @ 0.007 EUR/JPY (qty < 0 = sell for Cash forex)
    db_session.add(_tx(pid, aid, "JPYEUR=X", -500_000.0, 0.007, date(2024, 6, 1)))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    assert len(result.tickers) == 1
    t = result.tickers[0]
    assert t.ticker == "JPYEUR=X"
    assert t.cump == pytest.approx(0.006, rel=1e-6)
    assert t.qty_held == pytest.approx(500_000.0, abs=1.0)
    assert t.realized_pv_total == pytest.approx(500.0, abs=0.01)
    assert len(t.events) == 1
    assert t.events[0].realized_pv == pytest.approx(500.0, abs=0.01)


# ---------------------------------------------------------------------------
# Test 14: Zero-quantity transactions are silently ignored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zero_quantity_transaction_ignored(db_session):
    """
    A transaction with quantity=0 is neither a buy nor a sell.
    It must be silently skipped (covers the neither-buy-nor-sell branch).
    """
    pid, aid = await _setup_base(db_session)
    await _ensure_product(db_session, "ETF.ZERO", "Zero-qty ETF")

    # Insert a real buy first so the ticker appears in state
    db_session.add(_tx(pid, aid, "ETF.ZERO", -10.0, 100.0, date(2024, 1, 1)))
    # Zero-quantity transaction — must be ignored
    db_session.add(_tx(pid, aid, "ETF.ZERO", 0.0, 100.0, date(2024, 2, 1)))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    assert len(result.tickers) == 1
    t = result.tickers[0]
    # CUMP and qty_held unchanged — zero-qty tx had no effect
    assert t.qty_held == pytest.approx(10.0, abs=1e-6)
    assert t.cump == pytest.approx(100.0, rel=1e-6)
    assert t.realized_pv_total == pytest.approx(0.0, abs=0.01)
    assert len(t.events) == 0


# ---------------------------------------------------------------------------
# Test: CUMP includes linked Frais (courtage + TTF)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cump_includes_linked_frais(db_session):
    """
    Buy 10 units @ 100 EUR with a linked courtage Frais of 1 EUR total.
    Expected CUMP = (10*100 + 1) / 10 = 100.1 EUR.
    """
    pid, aid = await _setup_base(db_session)
    await _ensure_product(db_session, "TST.FRAIS", "Test Frais CUMP", "Actif")

    D = date(2025, 1, 15)

    # Parent buy
    buy = Transaction(
        portfolio_id=pid, account_id=aid,
        date=D, type="Actif", ticker="TST.FRAIS",
        currency="EUR", exchange_rate=1.0,
        quantity=-10.0, unit_price=100.0,
        unit_price_eur=100.0, total_amount=-1000.0, total_amount_eur=-1000.0,
    )
    db_session.add(buy)
    await db_session.flush()

    # Linked Frais (courtage)
    frais = Transaction(
        portfolio_id=pid, account_id=aid,
        date=D, type="Frais", ticker="TST.FRAIS",
        currency="EUR", exchange_rate=1.0,
        quantity=-1.0, unit_price=1.0,
        unit_price_eur=1.0, total_amount=-1.0, total_amount_eur=-1.0,
        linked_transaction_id=buy.id,
    )
    db_session.add(frais)
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    assert len(result.tickers) == 1
    t = result.tickers[0]
    assert t.qty_held == pytest.approx(10.0, abs=1e-6)
    # CUMP = (1000 + 1) / 10 = 100.1
    assert t.cump == pytest.approx(100.1, rel=1e-6)


@pytest.mark.asyncio
async def test_cump_includes_courtage_and_ttf(db_session):
    """
    Buy 5 units @ 180 EUR with courtage 1.90 + TTF 3.60 (total fees 5.50).
    Expected CUMP = (5*180 + 5.50) / 5 = 181.1 EUR.
    """
    pid, aid = await _setup_base(db_session)
    await _ensure_product(db_session, "TST.FRAIS2", "Test Frais CUMP2", "Actif")

    D = date(2025, 2, 10)

    buy = Transaction(
        portfolio_id=pid, account_id=aid,
        date=D, type="Actif", ticker="TST.FRAIS2",
        currency="EUR", exchange_rate=1.0,
        quantity=-5.0, unit_price=180.0,
        unit_price_eur=180.0, total_amount=-900.0, total_amount_eur=-900.0,
    )
    db_session.add(buy)
    await db_session.flush()

    for fee in (1.90, 3.60):
        db_session.add(Transaction(
            portfolio_id=pid, account_id=aid,
            date=D, type="Frais", ticker="TST.FRAIS2",
            currency="EUR", exchange_rate=1.0,
            quantity=-1.0, unit_price=fee,
            unit_price_eur=fee, total_amount=-fee, total_amount_eur=-fee,
            linked_transaction_id=buy.id,
        ))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    t = next(x for x in result.tickers if x.ticker == "TST.FRAIS2")
    assert t.qty_held == pytest.approx(5.0, abs=1e-6)
    assert t.cump == pytest.approx((900.0 + 5.50) / 5.0, rel=1e-6)


@pytest.mark.asyncio
async def test_unlinked_frais_not_included_in_cump(db_session):
    """Frais with linked_transaction_id=None do not affect CUMP."""
    pid, aid = await _setup_base(db_session)
    await _ensure_product(db_session, "TST.FRAIS3", "Test Frais CUMP3", "Actif")

    D = date(2025, 3, 5)

    buy = Transaction(
        portfolio_id=pid, account_id=aid,
        date=D, type="Actif", ticker="TST.FRAIS3",
        currency="EUR", exchange_rate=1.0,
        quantity=-10.0, unit_price=100.0,
        unit_price_eur=100.0, total_amount=-1000.0, total_amount_eur=-1000.0,
    )
    db_session.add(buy)
    await db_session.flush()

    # Unlinked Frais (no linked_transaction_id) — should NOT affect CUMP
    db_session.add(Transaction(
        portfolio_id=pid, account_id=aid,
        date=D, type="Frais", ticker="TST.FRAIS3",
        currency="EUR", exchange_rate=1.0,
        quantity=-1.0, unit_price=5.0,
        unit_price_eur=5.0, total_amount=-5.0, total_amount_eur=-5.0,
        linked_transaction_id=None,
    ))
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    t = next(x for x in result.tickers if x.ticker == "TST.FRAIS3")
    # CUMP unchanged — unlinked Frais not included
    assert t.cump == pytest.approx(100.0, rel=1e-6)


@pytest.mark.asyncio
async def test_realized_pv_uses_total_amount_eur_not_rounded_unit_price(db_session):
    """
    Realized PV must be derived from total_amount_eur (exact), not
    unit_price_eur * qty_sold — unit_price_eur is stored rounded to 2 decimals
    while a real broker execution price can carry more precision (confirmed
    live: a real 380-unit Degiro sale at 6.129 EUR/unit stored as 6.13 EUR/unit,
    producing a 0.38 EUR error when the calculation used the rounded price).
    """
    pid, aid = await _setup_base(db_session)
    ticker = "TST.PRECISION"
    await _ensure_product(db_session, ticker, "Test Precision ETF", "Actif")

    D1, D2 = date(2025, 1, 1), date(2025, 4, 15)

    buy = Transaction(
        portfolio_id=pid, account_id=aid,
        date=D1, type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-1000.0, unit_price=6.15, unit_price_eur=6.15,
        total_amount=-6150.0, total_amount_eur=-6150.0,
    )
    db_session.add(buy)
    await db_session.flush()

    # Real execution price is 6.129 EUR/unit (total_amount_eur = 380 * 6.129 =
    # 2329.02 EUR exactly), but unit_price_eur is stored rounded to 6.13.
    # unit_price_eur * qty would give 2329.40 EUR — a 0.38 EUR overstatement.
    sell = Transaction(
        portfolio_id=pid, account_id=aid,
        date=D2, type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=380.0, unit_price=6.13, unit_price_eur=6.13,
        total_amount=2329.02, total_amount_eur=2329.02,
    )
    db_session.add(sell)
    await db_session.flush()

    result = await compute_capital_gains(db_session, pid)
    t = next(x for x in result.tickers if x.ticker == ticker)

    cump = 6.15
    expected_pv = 2329.02 - cump * 380.0  # proceeds from total_amount_eur
    wrong_pv = (6.13 - cump) * 380.0      # what the old, buggy formula gave

    assert expected_pv != pytest.approx(wrong_pv, abs=0.01)
    assert t.realized_pv_total == pytest.approx(expected_pv, abs=0.001)
    assert t.events[0].realized_pv == pytest.approx(expected_pv, abs=0.001)
    # Display field stays the literal recorded unit price, untouched by the fix.
    assert t.events[0].sell_price_eur == pytest.approx(6.13, rel=1e-6)
