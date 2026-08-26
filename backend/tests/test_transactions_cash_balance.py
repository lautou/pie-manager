# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for cash_balance_eur auto-update on transaction create/update/delete:
plain cash-affecting transactions (deposits, stock trades, dividends), forex-position
exclusions (JPYEUR=X etc. never touch cash_balance_eur, only a EUR-denominated fee linked to
one does), Attribution's cash-neutral/no-running-balance behavior, and balance_eur/
balance_currency auto-calculation and cross-transaction propagation.

Split out of the former test_transactions.py — see test_transactions_crud.py's own header
for the full split rationale and why each split file duplicates its own header.
"""
import pytest
from datetime import date, timedelta
from sqlalchemy import select

from app.models.portfolio_account import PortfolioAccount

_TODAY = date.today().isoformat()
_LAST_WEEK = (date.today() - timedelta(days=7)).isoformat()


# ---------------------------------------------------------------------------
# cash_balance_eur auto-update — applies to all transaction types
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_transaction_updates_cash_balance(client, db_session):
    """
    Creating ANY transaction updates account.cash_balance_eur by total_amount_eur.
    - LIQUIDITE.EURO deposit (+40€) → cash increases
    - Stock buy (-1500€) → cash decreases
    - Dividend (+40€) → cash increases
    This ensures Comptes + Dashboard liquidity reflect changes immediately.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"CashCreate-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=507.83)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "LIQUIDITE.EURO",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 40.0, "unit_price": 1.0,
    })
    assert r.status_code == 201

    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(507.83 + 40.0, abs=0.01)


@pytest.mark.asyncio
async def test_delete_transaction_restores_cash_balance(client, db_session):
    """Deleting any transaction restores cash_balance_eur (generic, not LIQUIDITE.EURO-specific)."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"LiqDelete-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=200.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    r_create = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "LIQUIDITE.EURO",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 100.0, "unit_price": 1.0,
    })
    assert r_create.status_code == 201
    tx_id = r_create.json()["id"]
    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(300.0, abs=0.01)

    r_del = await client.delete(f"/api/transactions/{tx_id}")
    assert r_del.status_code == 204

    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(200.0, abs=0.01)


@pytest.mark.asyncio
async def test_stock_buy_decreases_cash_balance(client, db_session):
    """Buying a stock (negative total_amount_eur) decreases cash_balance_eur."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"LiqNonLiq-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=1000.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="AAPL.LIQ", name="Apple", category="Actif", currency="USD"))
    await db_session.flush()

    await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "AAPL.LIQ",
        "currency": "USD", "exchange_rate": 0.92,
        "quantity": -5.0, "unit_price": 150.0,
    })

    # total_amount_eur = -5 × 150 × 0.92 = -690 EUR → cash decreases
    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(1000.0 + (-5.0 * 150.0 * 0.92), abs=0.01)


@pytest.mark.asyncio
async def test_multiple_same_day_liquidite_transactions_cumulate(client, db_session):
    """
    Multiple LIQUIDITE.EURO transactions on the same day all update cash_balance_eur.
    Adding +40€ then +160€ → balance increases by 200€ total.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"LiqMulti-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=100.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid, "date": _TODAY,
        "type": "Actif", "ticker": "LIQUIDITE.EURO",
        "currency": "EUR", "exchange_rate": 1.0, "quantity": 40.0, "unit_price": 1.0,
    })
    await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid, "date": _TODAY,
        "type": "Actif", "ticker": "LIQUIDITE.EURO",
        "currency": "EUR", "exchange_rate": 1.0, "quantity": 160.0, "unit_price": 1.0,
    })

    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(300.0, abs=0.01)


# ---------------------------------------------------------------------------
# cash_balance_eur — forex-position transactions (JPYEUR=X etc.) are excluded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_forex_position_buy_does_not_change_cash_balance(client, db_session):
    """
    Buying a currency-pair position (JPYEUR=X) must NOT change cash_balance_eur:
    it's a conversion (EUR wallet -> JPY holding), not a real EUR cash flow. The
    EUR side is captured separately by a manually-entered LIQUIDITE.EUR transaction.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"ForexBuy-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Revolut", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=100.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="JPYEUR=X", name="JPY/EUR", category="Actif", instrument_type="Cash", currency="JPY"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "JPY", "exchange_rate": 0.006102,
        "quantity": 117333.0, "unit_price": 1.0,
    })
    assert r.status_code == 201

    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(100.0, abs=0.01)


@pytest.mark.asyncio
async def test_create_forex_position_sell_does_not_change_cash_balance(client, db_session):
    """Selling a currency-pair position (negative quantity) also leaves cash_balance_eur untouched."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"ForexSell-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Revolut", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=42.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="JPYEUR=X", name="JPY/EUR", category="Actif", instrument_type="Cash", currency="JPY"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "JPY", "exchange_rate": 0.005387,
        "quantity": -10145.0, "unit_price": 1.0,
    })
    assert r.status_code == 201

    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(42.0, abs=0.01)


@pytest.mark.asyncio
async def test_fractional_sibling_forex_position_does_not_change_cash_balance(client, db_session):
    """A fractional sibling execution on a forex-pair order also leaves cash_balance_eur untouched."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"ForexSibling-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Revolut", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=250.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="JPYEUR=X", name="JPY/EUR", category="Actif", instrument_type="Cash", currency="JPY"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "JPY", "exchange_rate": 0.006102,
        "quantity": 50000.0, "unit_price": 1.0,
        "additional_executions": [
            {"date": _TODAY, "quantity": 67333.0, "unit_price": 1.0, "exchange_rate": 0.006105},
        ],
    })
    assert r.status_code == 201

    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(250.0, abs=0.01)


@pytest.mark.asyncio
async def test_fee_linked_to_forex_position_still_changes_cash_balance(client, db_session):
    """
    A EUR-denominated fee (e.g. Revolut FX commission) linked to a JPYEUR=X buy
    is a real cash cost and must still reduce cash_balance_eur, even though the
    parent transaction itself is a forex position (skipped for cash purposes).
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"ForexFee-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Revolut", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=100.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="JPYEUR=X", name="JPY/EUR", category="Actif", instrument_type="Cash", currency="JPY"))
    db_session.add(Product(ticker="FRAIS.COURTAGE.EUR", name="Frais courtage", category="Frais", currency="EUR", fee_type="Courtage"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "JPY", "exchange_rate": 0.006102,
        "quantity": 117333.0, "unit_price": 1.0,
        "courtage_eur": 5.0,
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    result = await db_session.execute(
        select(TxModel).where(TxModel.linked_transaction_id == parent_id)
    )
    frais = result.scalars().all()
    assert len(frais) == 1
    assert frais[0].type == "Frais"
    assert frais[0].ticker == "FRAIS.COURTAGE.EUR"

    # The forex buy itself contributes nothing; only the 5€ fee reduces cash
    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(100.0 - 5.0, abs=0.01)


@pytest.mark.asyncio
async def test_delete_forex_position_transaction_is_noop_on_cash_balance(client, db_session):
    """Deleting a forex-position transaction is symmetric: it never touched cash_balance_eur, so removing it doesn't either."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"ForexDelete-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Revolut", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=0.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="JPYEUR=X", name="JPY/EUR", category="Actif", instrument_type="Cash", currency="JPY"))
    await db_session.flush()

    r_create = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "JPY", "exchange_rate": 0.006102,
        "quantity": 117333.0, "unit_price": 1.0,
    })
    assert r_create.status_code == 201
    tx_id = r_create.json()["id"]
    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(0.0, abs=0.01)

    r_del = await client.delete(f"/api/transactions/{tx_id}")
    assert r_del.status_code == 204

    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(0.0, abs=0.01)


@pytest.mark.asyncio
async def test_update_forex_position_transaction_does_not_change_cash_balance(client, db_session):
    """Changing a forex-position transaction's quantity/rate must not affect cash_balance_eur."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"ForexUpdate-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Revolut", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=17.5)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="JPYEUR=X", name="JPY/EUR", category="Actif", instrument_type="Cash", currency="JPY"))
    await db_session.flush()

    r_create = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "JPY", "exchange_rate": 0.006102,
        "quantity": 100000.0, "unit_price": 1.0,
    })
    assert r_create.status_code == 201
    tx_id = r_create.json()["id"]
    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(17.5, abs=0.01)

    r_update = await client.put(f"/api/transactions/{tx_id}", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "JPY", "exchange_rate": 0.006200,
        "quantity": 150000.0, "unit_price": 1.0,
    })
    assert r_update.status_code == 200

    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(17.5, abs=0.01)


@pytest.mark.asyncio
async def test_create_attribution_does_not_change_cash_balance_or_get_a_running_balance(client, db_session):
    """
    A free share Attribution's total_amount_eur may carry a recorded fair-value
    cost basis (used by WACOP), but no real cash changes hands: it must not touch
    cash_balance_eur, and its own balance_eur/balance_currency must stay null so
    the UI displays "—" instead of a bogus running balance.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"AttribCreate-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="BourseDirect PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=1000.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="MC.ATTRIB", name="LVMH", category="Actif", instrument_type="Action", currency="EUR"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "MC.ATTRIB",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -3.0, "unit_price": 500.0,
        "operation": "Attribution",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["balance_eur"] is None
    assert body["balance_currency"] is None

    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(1000.0, abs=0.01)


@pytest.mark.asyncio
async def test_fractional_sibling_attribution_does_not_get_a_running_balance(client, db_session):
    """A fractional sibling execution under an Attribution parent also stays cash-neutral."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"AttribFrac-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="BourseDirect PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=1000.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="AI.ATTRIB", name="Air Liquide", category="Actif", instrument_type="Action", currency="EUR"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "AI.ATTRIB",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -2.0, "unit_price": 170.0,
        "operation": "Attribution",
        "additional_executions": [
            {"date": _TODAY, "quantity": -1.0, "unit_price": 170.0},
        ],
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    siblings = (await db_session.execute(
        select(TxModel).where(TxModel.fractional_parent_id == parent_id)
    )).scalars().all()
    assert len(siblings) == 1
    assert siblings[0].balance_eur is None
    assert siblings[0].balance_currency is None

    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(1000.0, abs=0.01)


@pytest.mark.asyncio
async def test_delete_attribution_transaction_is_noop_on_cash_balance(client, db_session):
    """Deleting an Attribution never touched cash_balance_eur, so removing it doesn't either."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"AttribDelete-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="BourseDirect PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    initial_balance = 1000.0
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=initial_balance)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="SU.ATTRIB", name="Schneider", category="Actif", instrument_type="Action", currency="EUR"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "SU.ATTRIB",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -5.0, "unit_price": 270.0,
        "operation": "Attribution",
    })
    assert r.status_code == 201
    tx_id = r.json()["id"]

    r_del = await client.delete(f"/api/transactions/{tx_id}")
    assert r_del.status_code == 204

    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(initial_balance, abs=0.01)


@pytest.mark.asyncio
async def test_update_attribution_amount_does_not_change_cash_balance(client, db_session):
    """Changing an Attribution's price (same date) must not touch cash_balance_eur
    or propagate any running-balance delta to other transactions."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"AttribUpdateAmount-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="BourseDirect PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=1000.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="TTE.ATTRIB", name="TotalEnergies", category="Actif", instrument_type="Action", currency="EUR"))
    await db_session.flush()

    r_create = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "TTE.ATTRIB",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -4.0, "unit_price": 60.0,
        "operation": "Attribution",
    })
    assert r_create.status_code == 201
    tx_id = r_create.json()["id"]

    r_update = await client.put(f"/api/transactions/{tx_id}", json={"unit_price": 65.0})
    assert r_update.status_code == 200
    assert r_update.json()["balance_eur"] is None

    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(1000.0, abs=0.01)


@pytest.mark.asyncio
async def test_update_attribution_date_does_not_recompute_or_propagate_balance(client, db_session):
    """Moving an Attribution to a new date must not give it a running balance or
    shift any other transaction's balance_eur (date_changed branch)."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"AttribUpdateDate-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="BourseDirect PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=1000.0))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="MC.ATTRIBDATE", name="LVMH", category="Actif", instrument_type="Action", currency="EUR"))
    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    # A later real cash transaction with a known balance, so we can prove it's untouched
    later_cash = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2026, 12, 31), type="Actif",
        ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
        quantity=200.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=200.0, total_amount_eur=200.0,
        balance_eur=1200.0, balance_currency=1200.0,
    )
    db_session.add(later_cash)
    await db_session.flush()

    r_create = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": "2026-01-01", "type": "Actif", "ticker": "MC.ATTRIBDATE",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -2.0, "unit_price": 500.0,
        "operation": "Attribution",
    })
    assert r_create.status_code == 201
    tx_id = r_create.json()["id"]

    r_update = await client.put(f"/api/transactions/{tx_id}", json={"date": "2026-06-15"})
    assert r_update.status_code == 200
    assert r_update.json()["balance_eur"] is None

    await db_session.refresh(later_cash)
    assert later_cash.balance_eur == pytest.approx(1200.0, abs=0.01)


@pytest.mark.asyncio
async def test_create_transaction_auto_calculates_balance_eur(client, db_session):
    """
    When balance_eur is not provided, the backend auto-calculates it from the
    most recent known balance for the same account + total_amount_eur.

    Scenario: BourseDirect PEA last known balance = 507.83€ (from SU.PA dividend).
    Adding +40€ LIQUIDITE.EURO → balance_eur = 507.83 + 40 = 547.83€.
    This populates the 'Contrevaleur solde EUR' column in the transactions list.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"BalEur-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=507.83))
    await db_session.flush()
    aid = account.id

    # Previous transaction with a known balance (e.g. imported from Sheets)
    db_session.add(Product(ticker="SU.PA.BAL", name="Schneider", category="Actif", currency="EUR"))
    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    # First transaction: a Revenu with known balance_eur
    r1 = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _LAST_WEEK, "type": "Revenu", "ticker": "SU.PA.BAL",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 27.0, "unit_price": 4.2,
        "balance_currency": 507.83, "balance_eur": 507.83,
    })
    assert r1.status_code == 201

    # New transaction: balance_eur not provided → must be auto-calculated
    r2 = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "LIQUIDITE.EURO",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 40.0, "unit_price": 1.0,
    })
    assert r2.status_code == 201
    data = r2.json()

    # total_amount_eur = 40 × 1 × 1 = 40€ → balance_eur = 507.83 + 40 = 547.83
    assert data["balance_eur"] == pytest.approx(507.83 + 40.0, abs=0.01), (
        f"Expected balance_eur=547.83, got {data['balance_eur']}. "
        "Auto-calculation of Contrevaleur solde EUR failed."
    )
    assert data["balance_currency"] == pytest.approx(547.83, abs=0.01)


@pytest.mark.asyncio
async def test_create_transaction_balance_eur_scoped_per_portfolio_shared_broker(client, db_session):
    """
    Regression test: a broker (account_id) shared by two portfolios must NOT
    leak balance_eur between them when computing the running balance.

    Scenario (real bug): Degiro used by both Portfolio 1 and Portfolio 2.
    Portfolio 1's most recent transaction has balance_eur=35.56€.
    Portfolio 2's own last known balance is 0.94€. Depositing 2210€ into
    Portfolio 2's Degiro account must yield 0.94 + 2210 = 2210.94€ — NOT
    35.56 + 2210 = 2245.56€ (Portfolio 1's balance leaking into Portfolio 2).
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio_a = Portfolio(name=f"SharedBrokerA-{id(db_session)}")
    portfolio_b = Portfolio(name=f"SharedBrokerB-{id(db_session)}")
    db_session.add_all([portfolio_a, portfolio_b])
    await db_session.flush()
    pid_a, pid_b = portfolio_a.id, portfolio_b.id

    # Single broker shared by both portfolios (matches the Broker/Compte model)
    broker = Broker(name="SharedDegiro", currency="EUR")
    db_session.add(broker)
    await db_session.flush()
    aid = broker.id
    db_session.add(PortfolioAccount(portfolio_id=pid_a, broker_id=aid))
    db_session.add(PortfolioAccount(portfolio_id=pid_b, broker_id=aid))
    await db_session.flush()

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    db_session.add(Product(ticker="FRAIS.COURTAGE.EUR", name="Frais courtage", category="Frais", currency="EUR"))
    await db_session.flush()

    # Portfolio A (Portfolio-1-like): larger, more recent balance on the shared broker
    db_session.add(TxModel(
        portfolio_id=pid_a, account_id=aid, date=date(2026, 6, 3), type="Frais",
        ticker="FRAIS.COURTAGE.EUR", currency="EUR", exchange_rate=1.0,
        quantity=-1, unit_price=3.0, unit_price_eur=3.0,
        total_amount=-3.0, total_amount_eur=-3.0,
        balance_eur=35.56, balance_currency=35.56,
    ))
    # Portfolio B (Portfolio-2-like): smaller, older balance on the SAME broker
    db_session.add(TxModel(
        portfolio_id=pid_b, account_id=aid, date=date(2026, 3, 16), type="Frais",
        ticker="FRAIS.COURTAGE.EUR", currency="EUR", exchange_rate=1.0,
        quantity=-1, unit_price=3.0, unit_price_eur=3.0,
        total_amount=-3.0, total_amount_eur=-3.0,
        balance_eur=0.94, balance_currency=0.94,
    ))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": pid_b, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "LIQUIDITE.EURO",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 2210.0, "unit_price": 1.0,
    })
    assert r.status_code == 201
    data = r.json()

    # Must use portfolio B's own 0.94€ baseline, not portfolio A's 35.56€
    assert data["balance_eur"] == pytest.approx(2210.94, abs=0.01), (
        f"Expected balance_eur=2210.94 (0.94 + 2210, scoped to portfolio B), "
        f"got {data['balance_eur']} — balance_eur is leaking across portfolios "
        f"sharing the same broker."
    )


@pytest.mark.asyncio
async def test_create_transaction_no_prev_balance_leaves_balance_eur_none(client, db_session):
    """
    When no previous transaction has a known balance_eur, balance_eur stays null.
    This is expected for the first transaction of a new account.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"NoPrevBal-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="New Account", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "LIQUIDITE.EURO",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 100.0, "unit_price": 1.0,
    })
    assert r.status_code == 201
    # No previous balance known → balance_eur stays null (shown as '—')
    assert r.json()["balance_eur"] is None


@pytest.mark.asyncio
async def test_update_transaction_auto_calculates_balance_eur_when_null(client, db_session):
    """
    Editing and re-saving a transaction with balance_eur=null triggers auto-calculation.
    This fixes existing transactions created before the auto-calc feature was added.
    User workflow: click pencil → save without changes → balance_eur appears.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"UpdBalEur-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=507.83))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="SU.PA.UPD", name="Schneider", category="Actif", currency="EUR"))
    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    # Previous transaction with known balance_eur (imported from Sheets)
    await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _LAST_WEEK, "type": "Revenu", "ticker": "SU.PA.UPD",
        "currency": "EUR", "exchange_rate": 1.0, "quantity": 27.0, "unit_price": 4.2,
        "balance_eur": 507.83, "balance_currency": 507.83,
    })

    # Transaction created with balance_eur=null (before the auto-calc fix)
    r_old = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "LIQUIDITE.EURO",
        "currency": "EUR", "exchange_rate": 1.0, "quantity": 40.0, "unit_price": 1.0,
    })
    assert r_old.status_code == 201
    tx_id = r_old.json()["id"]

    # Force balance_eur back to null to simulate a pre-fix transaction
    from app.models.transaction import Transaction as TxModel
    tx_obj_result = await db_session.execute(
        select(TxModel).where(TxModel.id == tx_id)
    )
    tx_obj = tx_obj_result.scalar_one()
    tx_obj.balance_eur = None
    tx_obj.balance_currency = None
    await db_session.flush()

    # User clicks pencil + save without changes → PUT triggers auto-calc
    r_update = await client.put(f"/api/transactions/{tx_id}", json={})
    assert r_update.status_code == 200
    data = r_update.json()

    # balance_eur should now be calculated: 507.83 + 40 = 547.83
    assert data["balance_eur"] == pytest.approx(547.83, abs=0.01), (
        f"Expected balance_eur=547.83 after edit-save, got {data['balance_eur']}"
    )


@pytest.mark.asyncio
async def test_update_non_eur_transaction_auto_calculates_balance_currency(client, db_session):
    """
    Editing and re-saving a non-EUR transaction with balance_currency=null triggers
    auto-calculation from the previous same-currency balance.

    User workflow: click pencil on JPYEUR=X transaction → save without changes
    → balance_currency (Solde compte devise) appears.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"JpyUpdBal-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Revolut6", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="JPYEUR=X", name="JPY/EUR", category="Actif", instrument_type="Cash", currency="JPY"))
    await db_session.flush()

    # Anchor: first JPY purchase with known balance_currency
    anchor = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 5, 14), type="Actif",
        ticker="JPYEUR=X", currency="JPY", exchange_rate=0.006102,
        quantity=117333.0, unit_price=1.0, unit_price_eur=0.006102,
        total_amount=117333.0, total_amount_eur=716.0,
        balance_currency=5716779.0, balance_eur=34885.44,
    )
    db_session.add(anchor)
    await db_session.flush()

    # Later withdrawal — balance_currency was null (created before the fix)
    withdrawal = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2026, 5, 25), type="Actif",
        ticker="JPYEUR=X", currency="JPY", exchange_rate=0.005387,
        quantity=-10145.0, unit_price=1.0, unit_price_eur=0.005387,
        total_amount=-10145.0, total_amount_eur=-54.65,
        balance_currency=None, balance_eur=34830.79,
    )
    db_session.add(withdrawal)
    await db_session.flush()
    tx_id = withdrawal.id

    # User clicks pencil → save without changes → PUT with same values
    r = await client.put(f"/api/transactions/{tx_id}", json={
        "portfolio_id": uid, "account_id": aid,
        "date": "2026-05-25", "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "JPY", "exchange_rate": 0.005387,
        "quantity": -10145.0, "unit_price": 1.0,
    })
    assert r.status_code == 200

    # balance_currency = 5716779 + (-10145) = 5706634 JPY
    assert r.json()["balance_currency"] == pytest.approx(5706634.0, abs=0.01)


@pytest.mark.asyncio
async def test_update_transaction_propagates_balance_eur_to_subsequent(client, db_session):
    """
    When a transaction's amount changes, balance_eur of all SUBSEQUENT
    transactions for the same account must be updated by the same delta.

    Scenario:
      T1 (2025-01-01): +100€, balance_eur = 100€
      T2 (2025-02-01): +200€, balance_eur = 300€  ← should become 350€ after T1 changed
      T3 (2025-03-01): +50€,  balance_eur = 350€  ← should become 400€

    Change T1 from +100€ to +150€ (delta = +50€):
      T1 balance_eur = 150€
      T2 balance_eur = 350€ (300 + 50)
      T3 balance_eur = 400€ (350 + 50)
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from datetime import date as _date
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"RetroBalance-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    def make_tx(d, qty, bal):
        return TxModel(
            portfolio_id=uid, account_id=aid, date=d, type="Actif",
            ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
            quantity=qty, unit_price=1.0, unit_price_eur=1.0,
            total_amount=qty, total_amount_eur=qty,
            balance_eur=bal, balance_currency=bal,
        )

    t1 = make_tx(_date(2025, 1, 1), 100.0, 100.0)
    t2 = make_tx(_date(2025, 2, 1), 200.0, 300.0)
    t3 = make_tx(_date(2025, 3, 1),  50.0, 350.0)
    db_session.add_all([t1, t2, t3])
    await db_session.flush()

    # Change T1 from qty=100 to qty=150 (delta = +50)
    r = await client.put(f"/api/transactions/{t1.id}", json={"quantity": 150.0})
    assert r.status_code == 200
    assert r.json()["balance_eur"] == pytest.approx(150.0, abs=0.01)

    # T2 and T3 must be updated retroactively (+50€ delta)
    await db_session.refresh(t2)
    await db_session.refresh(t3)
    assert t2.balance_eur == pytest.approx(350.0, abs=0.01), f"T2: {t2.balance_eur}"
    assert t3.balance_eur == pytest.approx(400.0, abs=0.01), f"T3: {t3.balance_eur}"


@pytest.mark.asyncio
async def test_create_transaction_propagates_balance_eur_to_subsequent(client, db_session):
    """
    Creating a transaction on a past date propagates total_amount_eur to all
    SUBSEQUENT transactions for the same account (same logic as UPDATE).

    Use case: adding a missing fee from the Sheets import.
    The subsequent balance_eur values must shift by the same delta.

    T_existing (2025-01-01): balance_eur = 100€
    ADD fee on 2024-12-01 (-50€) → T_existing.balance_eur must become 50€.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from datetime import date as _date

    portfolio = Portfolio(name=f"RetroCreate-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    db_session.add(Product(ticker="FRAIS.TEST", name="Frais test", category="Frais", currency="EUR"))
    await db_session.flush()

    # Pre-existing transaction with a known balance (simulating a Sheets-imported value)
    existing = TxModel(
        portfolio_id=uid, account_id=aid, date=_date(2025, 1, 1), type="Actif",
        ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
        quantity=100.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=100.0, total_amount_eur=100.0, balance_eur=100.0,
    )
    db_session.add(existing)
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": "2024-12-01", "type": "Frais", "ticker": "FRAIS.TEST",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -1.0, "unit_price": 50.0,
    })
    assert r.status_code == 201, r.text

    # Reload existing tx — balance_eur must have decreased by 50
    await db_session.refresh(existing)
    assert existing.balance_eur == pytest.approx(50.0, abs=0.01), (
        f"Expected 50.0 (100 - 50 fee delta), got {existing.balance_eur}"
    )


@pytest.mark.asyncio
async def test_create_transaction_uses_prior_balance_not_future(client, db_session):
    """
    Regression: when a transaction is inserted at a PAST date, balance_eur must be
    calculated from the most recent PRIOR balance (date < new_tx.date), NOT from
    a more-recent balance that happens to exist in the DB.

    Scenario:
      T1 (2025-01-01): balance_eur = 0€  ← prior balance
      T2 (2025-03-01): balance_eur = 100€ ← FUTURE, must NOT be used
      INSERT new tx on 2025-02-01 with amount -50€
      → new balance must be 0 + (-50) = -50€, NOT 100 + (-50) = 50€
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from datetime import date as _date

    portfolio = Portfolio(name=f"PriorBal-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    db_session.add(Product(ticker="FRAIS.TEST.B", name="Frais test B", category="Frais", currency="EUR"))
    await db_session.flush()

    # T1 — prior balance = 0
    t1 = TxModel(
        portfolio_id=uid, account_id=aid, date=_date(2025, 1, 1), type="Actif",
        ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
        quantity=100.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=100.0, total_amount_eur=100.0, balance_eur=0.0,
    )
    # T2 — future balance (must NOT be used as prior reference)
    t2 = TxModel(
        portfolio_id=uid, account_id=aid, date=_date(2025, 3, 1), type="Actif",
        ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
        quantity=50.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=50.0, total_amount_eur=50.0, balance_eur=100.0,
    )
    db_session.add_all([t1, t2])
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": "2025-02-01", "type": "Frais", "ticker": "FRAIS.TEST.B",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -1.0, "unit_price": 50.0,
    })
    assert r.status_code == 201, r.text
    data = r.json()

    # balance_eur must use T1's balance (0) + (-50) = -50, NOT T2's balance (100) + (-50) = 50
    assert data["balance_eur"] == pytest.approx(-50.0, abs=0.01), (
        f"Bug: used future balance instead of prior balance. Got {data['balance_eur']}"
    )

    # T2's balance must be updated by the delta: 100 + (-50) = 50
    await db_session.refresh(t2)
    assert t2.balance_eur == pytest.approx(50.0, abs=0.01)


@pytest.mark.asyncio
async def test_update_transaction_date_change_recalculates_balance_eur(client, db_session):
    """
    Moving T2 backward (Feb→Dec) undoes its effect from subsequent txs at old position
    and applies it to subsequent txs at the new position.

    Before: T1(Jan, +100, bal=100), T2(Feb, +50, bal=150), T3(Mar, +200, bal=350)
    Move T2 → 2024-12-01 (before T1):
      Undo at old pos: T3 -= 50 → 300
      T2 at Dec: no prior → balance_eur = None
      Apply at new pos: T1 += 50 → 150; T3 += 50 → 350
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from datetime import date as _date

    portfolio = Portfolio(name=f"DateMove-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    def make_tx(d, qty, bal):
        return TxModel(
            portfolio_id=uid, account_id=aid, date=d, type="Actif",
            ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
            quantity=qty, unit_price=1.0, unit_price_eur=1.0,
            total_amount=qty, total_amount_eur=qty,
            balance_eur=bal, balance_currency=bal,
        )

    # Chain: T1(Jan) balance=100, T2(Feb) balance=150 (+50), T3(Mar) balance=350 (+200)
    t1 = make_tx(_date(2025, 1, 1), 100.0, 100.0)
    t2 = make_tx(_date(2025, 2, 1),  50.0, 150.0)
    t3 = make_tx(_date(2025, 3, 1), 200.0, 350.0)
    db_session.add_all([t1, t2, t3])
    await db_session.flush()

    # Move T2 from 2025-02-01 → 2025-01-15 (still between T1 and T3, but T1 is 2025-01-01)
    # New chain after move:
    #   T1 (Jan-01): balance=100, +100 → 100
    #   T2 (Jan-15): balance = 100 + 50 = 150  (prior is T1)
    #   T3 (Mar-01): old was 350 after T2 was at Feb. After undo: 350-50=300. After apply: 300+50=350.
    # Net: T1=100, T2=150, T3=350 (same totals since T2 is still between T1 and T3)
    # Let's move T2 BEFORE T1 to make the test more illustrative.
    # Move T2 → 2024-12-01 (before T1):
    #   Undo at old pos: T3 -= 50 → 300
    #   Recalc T2 at 2024-12-01: no prior → balance_eur = None
    #   Apply at new pos: T1 += 50 → 150; T3 += 50 → 350
    # Final: T2.balance_eur=None, T1=150, T3=350

    r = await client.put(f"/api/transactions/{t2.id}", json={"date": "2024-12-01"})
    assert r.status_code == 200, r.text
    data = r.json()

    # T2 has no prior transaction at 2024-12-01 → balance_eur stays None
    assert data["balance_eur"] is None, f"Expected None (no prior), got {data['balance_eur']}"

    # T1 (Jan-01) must now include T2's amount: 100 + 50 = 150
    await db_session.refresh(t1)
    assert t1.balance_eur == pytest.approx(150.0, abs=0.01), (
        f"T1 after date move: expected 150, got {t1.balance_eur}"
    )

    # T3 (Mar-01) net change: undo gave 300, apply gave 350 → back to original 350
    await db_session.refresh(t3)
    assert t3.balance_eur == pytest.approx(350.0, abs=0.01), (
        f"T3 after date move: expected 350, got {t3.balance_eur}"
    )


@pytest.mark.asyncio
async def test_balance_eur_no_negative_zero_after_date_move(client, db_session):
    """
    Regression: moving a transaction whose undo+apply on a downstream balance
    cancel exactly (0.0 - delta + delta) must never yield -0.0 in the response.

    Scenario:
      T1 (Jan, +100, bal=100) → T2 (Mar, +50, bal=150)
    Move T2 Feb→Apr then move it back. LIQUIDITE.balance at Mar must be 0.00 not -0.00.

    Simpler: create a transaction whose bulk-update path produces IEEE 754 -0.
    This is guaranteed when the downstream balance is 0.0 and the undo/apply
    delta is the same value.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from datetime import date as _date

    portfolio = Portfolio(name=f"NegZeroBulk-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="BNP", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    # T_SELL (Feb, total=+6290.09) — no balance set; T_LIQ (Feb, highest id, balance=0.0)
    t_sell = TxModel(
        portfolio_id=uid, account_id=aid, date=_date(2026, 3, 5), type="Actif",
        ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
        quantity=6290.09, unit_price=1.0, unit_price_eur=1.0,
        total_amount=6290.09, total_amount_eur=6290.09,
        balance_eur=None,
    )
    db_session.add(t_sell)
    await db_session.flush()

    t_liq = TxModel(
        portfolio_id=uid, account_id=aid, date=_date(2026, 3, 5), type="Actif",
        ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
        quantity=-6290.09, unit_price=1.0, unit_price_eur=1.0,
        total_amount=-6290.09, total_amount_eur=-6290.09,
        balance_eur=0.0, balance_currency=0.0,
    )
    db_session.add(t_liq)
    await db_session.flush()

    # Move t_sell to Jan-01: undo subtracts 6290.09 from t_liq (0.0 → -6290.09),
    # apply adds 6290.09 back (-6290.09 + 6290.09 → ±0.0 — must not be -0.0)
    r = await client.put(f"/api/transactions/{t_sell.id}", json={"date": "2026-01-01"})
    assert r.status_code == 200

    # Re-fetch t_liq via list endpoint
    lst = await client.get(f"/api/transactions/?portfolio_id={uid}&account_id={aid}")
    liq = next(t for t in lst.json() if t["id"] == t_liq.id)
    bal = liq["balance_eur"]

    import math
    assert bal is None or math.copysign(1.0, bal) >= 0, (
        f"balance_eur must not be -0.0, got {bal!r}"
    )


@pytest.mark.asyncio
async def test_balance_eur_never_negative_zero(client, db_session):
    """
    Regression: balance_eur must never be -0.0.
    Occurs when prev_balance + total_amount_eur is a tiny negative float
    that rounds to -0.00 (IEEE 754 negative zero).
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from datetime import date as _date

    portfolio = Portfolio(name=f"NegZero-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    # A buy that creates a specific prev balance
    t1 = TxModel(
        portfolio_id=uid, account_id=aid, date=_date(2024, 1, 1), type="Actif",
        ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
        quantity=-45285.637088, unit_price=1.0, unit_price_eur=1.0,
        total_amount=-45285.637088, total_amount_eur=-45285.637088,
        balance_eur=-45285.637088, balance_currency=-45285.637088,
    )
    db_session.add(t1)
    await db_session.flush()

    # A deposit that nearly exactly cancels the buy → balance should be 0.0, not -0.0
    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": "2024-01-01", "type": "Actif", "ticker": "LIQUIDITE.EURO",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 45285.63, "unit_price": 1.0,
    })
    assert r.status_code == 201
    bal = r.json()["balance_eur"]
    # Must not be negative zero (import math; math.copysign(1, -0.0) == -1)
    import math
    assert bal is None or math.copysign(1.0, bal) == 1.0 or bal != 0.0, (
        f"balance_eur must not be -0.0, got {bal!r}"
    )


@pytest.mark.asyncio
async def test_update_transaction_date_change_backward_propagates_to_lower_id(client, db_session):
    """
    Regression: moving a manually-added tx (higher id) backward must propagate
    to an imported tx (lower id) that was at the SAME old date.

    Real-world case: FRAIS.TAXE.EUR (id=high) added after LIQUIDITE.EURO (id=low),
    both at Oct-15. Moving FRAIS to Oct-06: LIQUIDITE at Oct-15 must receive the
    fee's impact (it becomes "after" FRAIS chronologically).

    Before:
      T_IMPORT (id=low,  date=Feb, total=-20000, balance=-500)   ← bank-imported
      T_MANUAL (id=high, date=Feb, total=-200,   balance=-700)   ← manually added
      T_FUTURE (id=any,  date=Mar, total=+100,   balance=-600)

    Move T_MANUAL Feb→Jan (before T_IMPORT):
      Undo at Feb: T_MANUAL was after T_IMPORT (higher id) → only T_FUTURE -= (-200) → -600-(-200)=-400
      Recalc T_MANUAL at Jan: no prior → balance=None
      Apply at Jan: T_IMPORT (Feb>Jan) += -200 → -500+(-200)=-700
                    T_FUTURE (Mar>Jan) += -200 → -400+(-200)=-600  (net 0 vs original)
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from datetime import date as _date

    portfolio = Portfolio(name=f"DateMoveLowId-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="BNP", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    db_session.add(Product(ticker="FRAIS.TEST.LOW", name="Frais", category="Frais", currency="EUR"))
    await db_session.flush()

    def make_tx(ticker, d, qty, price, bal):
        return TxModel(
            portfolio_id=uid, account_id=aid, date=d, type="Actif",
            ticker=ticker, currency="EUR", exchange_rate=1.0,
            quantity=qty, unit_price=price, unit_price_eur=price,
            total_amount=qty * price, total_amount_eur=qty * price,
            balance_eur=bal, balance_currency=bal,
        )

    # T_IMPORT: bank-imported, lower id, date=Feb, balance from bank statement
    t_import = make_tx("LIQUIDITE.EURO", _date(2025, 2, 1), -20000.0, 1.0, -500.0)
    db_session.add(t_import)
    await db_session.flush()

    # T_MANUAL: added manually AFTER import → higher id, same date=Feb
    # Chain at Feb: t_import (id=low) → t_manual (id=high)
    # t_manual.balance = -500 + (-200) = -700
    t_manual = make_tx("FRAIS.TEST.LOW", _date(2025, 2, 1), -1.0, 200.0, -700.0)
    db_session.add(t_manual)
    await db_session.flush()

    # T_FUTURE: date=Mar, balance=-600 (after +100 on top of t_manual's -700)
    t_future = make_tx("LIQUIDITE.EURO", _date(2025, 3, 1), 100.0, 1.0, -600.0)
    db_session.add(t_future)
    await db_session.flush()

    assert t_import.id < t_manual.id, "t_import must have lower id than t_manual"

    # Move T_MANUAL from Feb-01 → Jan-01 (before T_IMPORT)
    r = await client.put(f"/api/transactions/{t_manual.id}", json={"date": "2025-01-01"})
    assert r.status_code == 200, r.text

    # T_MANUAL at Jan: no prior tx before Jan → balance_eur = None
    assert r.json()["balance_eur"] is None, (
        f"T_MANUAL moved to Jan has no prior → expected None, got {r.json()['balance_eur']}"
    )

    # T_IMPORT (Feb): T_MANUAL is now before it chronologically → gets -200 applied
    # -500 + (-200) = -700
    await db_session.refresh(t_import)
    assert t_import.balance_eur == pytest.approx(-700.0, abs=0.01), (
        f"T_IMPORT at Feb: expected -700 (propagation from moved FRAIS), got {t_import.balance_eur}"
    )

    # T_FUTURE (Mar): undo removed (-200) → -400, apply added (-200) → -600 (net 0)
    await db_session.refresh(t_future)
    assert t_future.balance_eur == pytest.approx(-600.0, abs=0.01), (
        f"T_FUTURE at Mar: expected -600 (net zero change), got {t_future.balance_eur}"
    )


@pytest.mark.asyncio
async def test_update_transaction_date_change_forward_recalculates(client, db_session):
    """
    Moving a transaction FORWARD in time (from Jan to Mar):
    removes it from between T1 and T2, inserting it after T3.

    Before: T1(Jan, +100, bal=100), T2(Feb, +200, bal=300), T3(Mar, +50, bal=350)
    Move T1 → Apr:
      Undo: T2 -= 100 → 200; T3 -= 100 → 250
      Recalc T1 at Apr: prior is T3 at Mar (bal=250) → T1.balance = 250+100=350
      Apply: no tx after Apr → nothing to propagate
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from datetime import date as _date

    portfolio = Portfolio(name=f"DateFwd-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    def make_tx(d, qty, bal):
        return TxModel(
            portfolio_id=uid, account_id=aid, date=d, type="Actif",
            ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
            quantity=qty, unit_price=1.0, unit_price_eur=1.0,
            total_amount=qty, total_amount_eur=qty,
            balance_eur=bal, balance_currency=bal,
        )

    t1 = make_tx(_date(2025, 1, 1), 100.0, 100.0)
    t2 = make_tx(_date(2025, 2, 1), 200.0, 300.0)
    t3 = make_tx(_date(2025, 3, 1),  50.0, 350.0)
    db_session.add_all([t1, t2, t3])
    await db_session.flush()

    # Move T1 → 2025-04-01 (after T3)
    r = await client.put(f"/api/transactions/{t1.id}", json={"date": "2025-04-01"})
    assert r.status_code == 200, r.text
    data = r.json()

    # T1 moved to Apr: prior is T3 (bal=250 after undo), T1.balance = 250 + 100 = 350
    assert data["balance_eur"] == pytest.approx(350.0, abs=0.01), (
        f"T1 (moved to Apr): expected 350, got {data['balance_eur']}"
    )

    # T2 (Feb): was 300, undo removed T1's +100 → 200
    await db_session.refresh(t2)
    assert t2.balance_eur == pytest.approx(200.0, abs=0.01), (
        f"T2 after T1 moved forward: expected 200, got {t2.balance_eur}"
    )

    # T3 (Mar): was 350, undo removed T1's +100 → 250
    await db_session.refresh(t3)
    assert t3.balance_eur == pytest.approx(250.0, abs=0.01), (
        f"T3 after T1 moved forward: expected 250, got {t3.balance_eur}"
    )
