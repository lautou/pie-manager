# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for fractional/multi-execution orders (a single logical trade split
into several `additional_executions`, e.g. a broker filling one order across multiple
lots): parent/sibling creation, derived-field computation per execution, and their
interaction with cash_balance_eur/balance_eur/linked fees.

Split out of the former test_transactions.py — see test_transactions_crud.py's own header
for the full split rationale and why each split file duplicates its own header.
"""
import pytest
from datetime import date

from app.models.portfolio_account import PortfolioAccount

_TODAY = date.today().isoformat()


# ---------------------------------------------------------------------------
# Fractional orders
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_fractional_order_creates_siblings(client, db_session):
    """POST with additional_executions creates parent + sibling transactions."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"FractionalCreate-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Degiro", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=10000.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="H411.FRAC", name="H411 Frac Test", category="Actif", currency="EUR"))
    db_session.add(Product(ticker="FRAIS.COURTAGE.EUR", name="Frais courtage", category="Frais", currency="EUR", fee_type="Courtage"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "H411.FRAC",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -84.0, "unit_price": 66.62,
        "courtage_eur": 3.0,
        "additional_executions": [
            {"date": _TODAY, "quantity": -7.0, "unit_price": 66.62},
            {"date": _TODAY, "quantity": -7.0, "unit_price": 66.64},
        ],
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    # 2 siblings with fractional_parent_id = parent_id
    res = await db_session.execute(
        select(TxModel).where(TxModel.fractional_parent_id == parent_id)
    )
    siblings = res.scalars().all()
    assert len(siblings) == 2
    for s in siblings:
        assert s.fractional_parent_id == parent_id
        assert s.type == "Actif"
        assert s.ticker == "H411.FRAC"

    # Cash balance: parent (-84*66.62) + sibling1 (-7*66.62) + sibling2 (-7*66.64) + courtage (-3)
    await db_session.refresh(pa)
    expected = 10000.0 + (-84*66.62) + (-7*66.62) + (-7*66.64) - 3.0
    assert pa.cash_balance_eur == pytest.approx(expected, abs=0.02)


@pytest.mark.asyncio
async def test_delete_parent_deletes_siblings(client, db_session):
    """DELETE of fractional parent also removes all siblings."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"FractionalDelete-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Degiro", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    initial_balance = 5000.0
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=initial_balance)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="QDVF.FRAC", name="QDVF Frac Test", category="Actif", currency="EUR"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "QDVF.FRAC",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -550.0, "unit_price": 10.74,
        "additional_executions": [
            {"date": _TODAY, "quantity": -276.0, "unit_price": 10.74},
        ],
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    # Verify sibling exists
    res = await db_session.execute(
        select(TxModel).where(TxModel.fractional_parent_id == parent_id)
    )
    assert len(res.scalars().all()) == 1

    r_del = await client.delete(f"/api/transactions/{parent_id}")
    assert r_del.status_code == 204

    # Parent gone
    gone = await db_session.execute(select(TxModel).where(TxModel.id == parent_id))
    assert gone.scalar_one_or_none() is None

    # Siblings gone
    no_sibs = await db_session.execute(
        select(TxModel).where(TxModel.fractional_parent_id == parent_id)
    )
    assert len(no_sibs.scalars().all()) == 0

    # Balance restored
    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(initial_balance, abs=0.01)


@pytest.mark.asyncio
async def test_delete_sibling_leaves_parent(client, db_session):
    """DELETE of a fractional sibling leaves parent and other siblings intact."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"FractionalSibling-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="IBKR", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="XJSE.FRAC", name="XJSE Frac Test", category="Actif", currency="EUR"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "XJSE.FRAC",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -352.0, "unit_price": 6.11,
        "additional_executions": [
            {"date": _TODAY, "quantity": -227.0, "unit_price": 6.11},
            {"date": _TODAY, "quantity": -700.0, "unit_price": 6.11},
        ],
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    siblings = (await db_session.execute(
        select(TxModel).where(TxModel.fractional_parent_id == parent_id)
    )).scalars().all()
    assert len(siblings) == 2
    sibling_id = siblings[0].id
    sibling_amount = siblings[0].total_amount_eur

    await db_session.refresh(pa)
    balance_before = pa.cash_balance_eur

    r_del = await client.delete(f"/api/transactions/{sibling_id}")
    assert r_del.status_code == 204

    # Parent still exists
    parent = (await db_session.execute(select(TxModel).where(TxModel.id == parent_id))).scalar_one_or_none()
    assert parent is not None

    # One sibling gone, one remains
    remaining = (await db_session.execute(
        select(TxModel).where(TxModel.fractional_parent_id == parent_id)
    )).scalars().all()
    assert len(remaining) == 1

    # Balance: sibling amount reversed
    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(balance_before - sibling_amount, abs=0.01)


@pytest.mark.asyncio
async def test_fractional_with_courtage_links_to_parent(client, db_session):
    """Courtage Frais is linked to parent execution only; siblings have no linked Frais."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"FractionalCourtage-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Degiro", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="IS0D.FRAC", name="IS0D Frac Test", category="Actif", currency="EUR"))
    db_session.add(Product(ticker="FRAIS.COURTAGE.EUR", name="Frais courtage", category="Frais", currency="EUR", fee_type="Courtage"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "IS0D.FRAC",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -79.0, "unit_price": 20.28,
        "courtage_eur": 1.0,
        "additional_executions": [
            {"date": _TODAY, "quantity": -246.0, "unit_price": 20.31},
        ],
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    # Frais linked to parent
    parent_frais = (await db_session.execute(
        select(TxModel).where(
            TxModel.linked_transaction_id == parent_id,
            TxModel.type == "Frais",
        )
    )).scalars().all()
    assert len(parent_frais) == 1
    assert parent_frais[0].total_amount_eur == pytest.approx(-1.0, abs=0.001)

    # Sibling has no linked Frais
    siblings = (await db_session.execute(
        select(TxModel).where(TxModel.fractional_parent_id == parent_id)
    )).scalars().all()
    assert len(siblings) == 1
    sibling_frais = (await db_session.execute(
        select(TxModel).where(
            TxModel.linked_transaction_id == siblings[0].id,
            TxModel.type == "Frais",
        )
    )).scalars().all()
    assert len(sibling_frais) == 0


@pytest.mark.asyncio
async def test_fractional_siblings_get_balance_eur(client, db_session):
    """Fractional sibling executions get balance_eur calculated."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"FracBalance-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Degiro", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="DBX5.FRAC2", name="DBX5 Frac Balance", category="Actif", currency="EUR"))
    db_session.add(Product(ticker="LIQUIDITE.FBRAC", name="Cash Frac", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    # Create an initial deposit so subsequent transactions get balance_eur
    await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": "2026-01-01", "type": "Actif", "ticker": "LIQUIDITE.FBRAC",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 5000.0, "unit_price": 1.0,
        "balance_eur": 5000.0,  # explicit initial balance
    })

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "DBX5.FRAC2",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -28.0, "unit_price": 127.90,
        "additional_executions": [
            {"date": _TODAY, "quantity": -22.0, "unit_price": 128.18, "exchange_rate": 1.0},
        ],
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    # Parent should have balance_eur (because a prior transaction exists)
    parent = (await db_session.execute(select(TxModel).where(TxModel.id == parent_id))).scalar_one()
    assert parent.balance_eur is not None

    # Sibling should also have balance_eur calculated
    siblings = (await db_session.execute(
        select(TxModel).where(TxModel.fractional_parent_id == parent_id)
    )).scalars().all()
    assert len(siblings) == 1
    assert siblings[0].balance_eur is not None
    # Sibling balance = parent balance + sibling total_amount_eur
    expected_sibling_balance = round(parent.balance_eur + siblings[0].total_amount_eur, 2)
    assert siblings[0].balance_eur == expected_sibling_balance


@pytest.mark.asyncio
async def test_fractional_sibling_non_eur_no_balance_currency(client, db_session):
    """Non-EUR sibling: balance_eur set but balance_currency stays None."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"FracNonEUR-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="IBKR", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="XJSE.FRACTEST", name="XJSE Test", category="Actif", currency="JPY"))
    db_session.add(Product(ticker="LIQUIDITE.FRAC2", name="Cash2", category="Actif", instrument_type="Cash", currency="EUR"))
    await db_session.flush()

    # Seed an initial EUR balance
    await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": "2026-01-01", "type": "Actif", "ticker": "LIQUIDITE.FRAC2",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 10000.0, "unit_price": 1.0, "balance_eur": 10000.0,
    })

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "XJSE.FRACTEST",
        "currency": "JPY", "exchange_rate": 0.006,
        "quantity": -1000.0, "unit_price": 1500.0,
        "additional_executions": [
            {"date": _TODAY, "quantity": -500.0, "unit_price": 1510.0, "exchange_rate": 0.006},
        ],
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    siblings = (await db_session.execute(
        select(TxModel).where(TxModel.fractional_parent_id == parent_id)
    )).scalars().all()
    assert len(siblings) == 1
    # Non-EUR: balance_eur set, balance_currency = None
    assert siblings[0].balance_eur is not None
    assert siblings[0].balance_currency is None


@pytest.mark.asyncio
async def test_auto_frais_get_balance_eur(client, db_session):
    """Auto-created Frais (courtage) get balance_eur calculated."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"FraisBalance-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Degiro", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="QDVF.BTEST", name="QDVF Balance Test", category="Actif", currency="EUR"))
    db_session.add(Product(ticker="LIQUIDITE.BTEST", name="Cash BTest", category="Actif", instrument_type="Cash", currency="EUR"))
    db_session.add(Product(ticker="FRAIS.COURTAGE.EUR", name="Frais courtage", category="Frais", currency="EUR", fee_type="Courtage"))
    await db_session.flush()

    # Seed initial balance
    await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": "2026-01-01", "type": "Actif", "ticker": "LIQUIDITE.BTEST",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 5000.0, "unit_price": 1.0, "balance_eur": 5000.0,
    })

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "QDVF.BTEST",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -100.0, "unit_price": 10.0,
        "courtage_eur": 3.0,
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    # Parent should have balance_eur
    parent = (await db_session.execute(select(TxModel).where(TxModel.id == parent_id))).scalar_one()
    assert parent.balance_eur is not None  # 5000 - 1000 = 4000

    # Auto-created Frais should also have balance_eur
    frais_list = (await db_session.execute(
        select(TxModel).where(TxModel.linked_transaction_id == parent_id, TxModel.type == "Frais")
    )).scalars().all()
    assert len(frais_list) == 1
    frais = frais_list[0]
    assert frais.balance_eur is not None
    # balance = parent.balance_eur - 3
    assert frais.balance_eur == pytest.approx(parent.balance_eur - 3.0, abs=0.01)
    assert frais.balance_currency == frais.balance_eur
