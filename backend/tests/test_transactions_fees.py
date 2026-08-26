# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for Courtage/TTF fee handling on transaction create/update/delete: the
atomic linked-Frais creation on create, recomputation on update, and cascade delete of the
linked Frais rows when their parent transaction is removed.

Split out of the former test_transactions.py — see test_transactions_crud.py's own header
for the full split rationale and why each split file duplicates its own header.
"""
import pytest
from datetime import date

from app.models.portfolio_account import PortfolioAccount

_TODAY = date.today().isoformat()


# ---------------------------------------------------------------------------
# Courtage + TTF: atomic Frais creation and cascade delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_actif_with_courtage_creates_linked_frais(client, db_session):
    """POST with courtage_eur creates 3 transactions: parent Actif + 1 Frais."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"CourtageCreate-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Degiro", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=1000.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="TTE.CTST", name="TTE Test", category="Actif", currency="EUR"))
    db_session.add(Product(ticker="FRAIS.COURTAGE.EUR", name="Frais courtage", category="Frais", currency="EUR", fee_type="Courtage"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "TTE.CTST",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -9.0, "unit_price": 77.42,
        "courtage_eur": 0.99,
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    # Exactly 1 linked Frais should exist
    result = await db_session.execute(
        select(TxModel).where(TxModel.linked_transaction_id == parent_id)
    )
    frais = result.scalars().all()
    assert len(frais) == 1
    f = frais[0]
    assert f.type == "Frais"
    assert f.ticker == "FRAIS.COURTAGE.EUR"
    assert f.total_amount_eur == pytest.approx(-0.99, abs=0.001)

    # cash_balance_eur reduced by buy amount + courtage
    await db_session.refresh(pa)
    expected_balance = 1000.0 + (-9.0 * 77.42) - 0.99
    assert pa.cash_balance_eur == pytest.approx(expected_balance, abs=0.01)


@pytest.mark.asyncio
async def test_create_actif_with_courtage_and_ttf(client, db_session):
    """POST with courtage_eur and ttf_eur creates 3 transactions."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"CourtageAndTTF-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=2000.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="AI.CTST", name="Air Liquide Test", category="Actif",
                           currency="EUR", is_ttf_eligible=True))
    db_session.add(Product(ticker="FRAIS.COURTAGE.EUR", name="Frais courtage", category="Frais", currency="EUR", fee_type="Courtage"))
    db_session.add(Product(ticker="FRAIS.TTF.EUR", name="Taxe sur les Transactions Financières", category="Frais", currency="EUR", fee_type="TTF"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "AI.CTST",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -5.0, "unit_price": 180.0,
        "courtage_eur": 1.90, "ttf_eur": 3.60,
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    # 2 linked Frais (courtage + TTF)
    result = await db_session.execute(
        select(TxModel).where(TxModel.linked_transaction_id == parent_id).order_by(TxModel.id)
    )
    frais = result.scalars().all()
    assert len(frais) == 2
    amounts = sorted([f.total_amount_eur for f in frais])
    assert amounts[0] == pytest.approx(-3.60, abs=0.001)
    assert amounts[1] == pytest.approx(-1.90, abs=0.001)

    # cash balance reduced by all 3 amounts
    await db_session.refresh(pa)
    expected = 2000.0 + (-5.0 * 180.0) - 1.90 - 3.60
    assert pa.cash_balance_eur == pytest.approx(expected, abs=0.01)


@pytest.mark.asyncio
async def test_delete_actif_also_deletes_linked_frais(client, db_session):
    """DELETE of parent Actif removes linked Frais and fully restores cash balance."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"CourtageDelete-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    initial_balance = 5000.0
    account = Broker(name="Degiro", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=initial_balance)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="SU.CTST", name="Schneider Test", category="Actif", currency="EUR"))
    db_session.add(Product(ticker="FRAIS.COURTAGE.EUR", name="Frais courtage", category="Frais", currency="EUR", fee_type="Courtage"))
    db_session.add(Product(ticker="FRAIS.TTF.EUR", name="Taxe sur les Transactions Financières", category="Frais", currency="EUR", fee_type="TTF"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "SU.CTST",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -10.0, "unit_price": 270.0,
        "courtage_eur": 2.90, "ttf_eur": 10.80,
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    # Verify 2 Frais exist
    res = await db_session.execute(
        select(TxModel).where(TxModel.linked_transaction_id == parent_id)
    )
    assert len(res.scalars().all()) == 2

    r_del = await client.delete(f"/api/transactions/{parent_id}")
    assert r_del.status_code == 204

    # Parent should be gone
    gone = await db_session.execute(select(TxModel).where(TxModel.id == parent_id))
    assert gone.scalar_one_or_none() is None

    # Frais should be gone too
    frais_gone = await db_session.execute(
        select(TxModel).where(TxModel.linked_transaction_id == parent_id)
    )
    assert len(frais_gone.scalars().all()) == 0

    # Cash balance should be fully restored
    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(initial_balance, abs=0.01)


@pytest.mark.asyncio
async def test_create_non_actif_with_courtage_ignored(client, db_session):
    """Frais transactions with courtage_eur>0 do not create linked sub-Frais (only Actif triggers it)."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"CourtageFraisIgnore-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Degiro", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="FRAIS.CTST", name="Frais Test", category="Frais", currency="EUR"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Frais", "ticker": "FRAIS.CTST",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -1.0, "unit_price": 5.0,
        "courtage_eur": 9.99,  # should be ignored for non-Actif
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    # No linked Frais should be created
    res = await db_session.execute(
        select(TxModel).where(TxModel.linked_transaction_id == parent_id)
    )
    assert len(res.scalars().all()) == 0


@pytest.mark.asyncio
async def test_update_actif_replaces_linked_frais(client, db_session):
    """PUT with courtage_eur+ttf_eur deletes old linked Frais and creates new ones."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"UpdateFrais-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="MC.UPDATE", name="LVMH Update", category="Actif",
                           currency="EUR", is_ttf_eligible=True))
    db_session.add(Product(ticker="FRAIS.COURTAGE.EUR", name="Frais courtage", category="Frais", currency="EUR", fee_type="Courtage"))
    db_session.add(Product(ticker="FRAIS.TTF.EUR", name="Taxe sur les Transactions Financières", category="Frais", currency="EUR", fee_type="TTF"))
    await db_session.flush()

    # Create with courtage 1.90€ + TTF 3.20€
    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "MC.UPDATE",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -2.0, "unit_price": 400.0,
        "courtage_eur": 1.90, "ttf_eur": 3.20,
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    res = await db_session.execute(
        select(TxModel).where(TxModel.linked_transaction_id == parent_id)
    )
    assert len(res.scalars().all()) == 2

    await db_session.refresh(pa)
    balance_after_create = pa.cash_balance_eur

    # Now update: change courtage to 2.50€, remove TTF (0€)
    r2 = await client.put(f"/api/transactions/{parent_id}", json={
        "courtage_eur": 2.50, "ttf_eur": 0.0,
    })
    assert r2.status_code == 200

    # Only 1 Frais should remain (courtage 2.50€, TTF removed)
    res2 = await db_session.execute(
        select(TxModel).where(TxModel.linked_transaction_id == parent_id)
    )
    frais = res2.scalars().all()
    assert len(frais) == 1
    assert frais[0].total_amount_eur == pytest.approx(-2.50, abs=0.01)

    # cash balance: was reduced by 1.90+3.20=5.10, now reduced by 2.50 → net delta = +2.60
    await db_session.refresh(pa)
    expected = balance_after_create + (1.90 + 3.20) - 2.50  # reverse old, apply new
    assert pa.cash_balance_eur == pytest.approx(expected, abs=0.01)


@pytest.mark.asyncio
async def test_update_actif_recreated_frais_get_balance_eur(client, db_session):
    """
    Regression test: editing an Actif transaction (e.g. fixing a wrong unit_price)
    while leaving courtage/ttf unchanged deletes and recreates the linked Frais
    transactions. Those recreated Frais must get balance_eur/balance_currency
    computed from the parent's updated balance — otherwise they stay null and,
    since they get the highest id for that day, mask the parent's correct
    balance in the UI (only the highest id per date+currency displays a balance).
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"UpdateFraisBal-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="BourseDirect", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="TTE.BALFIX", name="TotalEnergies", category="Actif", currency="EUR"))
    db_session.add(Product(ticker="LIQUIDITE.EURO", name="Cash EUR", category="Actif", instrument_type="Cash", currency="EUR"))
    db_session.add(Product(ticker="FRAIS.COURTAGE.EUR", name="Frais courtage", category="Frais", currency="EUR", fee_type="Courtage"))
    db_session.add(Product(ticker="FRAIS.TTF.EUR", name="Taxe sur les Transactions Financières", category="Frais", currency="EUR", fee_type="TTF"))
    await db_session.flush()

    # Anchor transaction with a known balance_eur (prior cash position)
    anchor = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2026, 7, 5), type="Actif",
        ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
        quantity=30.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=30.0, total_amount_eur=30.0,
        balance_eur=206.25, balance_currency=206.25,
    )
    db_session.add(anchor)
    await db_session.flush()

    # Create with a wrong unit_price (typo: 66.67 instead of 67.66)
    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "TTE.BALFIX",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -3.0, "unit_price": 66.67,
        "courtage_eur": 0.80, "ttf_eur": 0.99,
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    # Correct the unit_price, leaving courtage/ttf unchanged (frontend always sends them)
    r2 = await client.put(f"/api/transactions/{parent_id}", json={
        "unit_price": 67.66,
        "courtage_eur": 0.80, "ttf_eur": 0.99,
    })
    assert r2.status_code == 200
    # Parent balance_eur = 206.25 - 3*67.66 = 3.27
    assert r2.json()["balance_eur"] == pytest.approx(3.27, abs=0.01)

    # Recreated Frais must each have a computed balance_eur, chained from the parent
    res = await db_session.execute(
        select(TxModel).where(TxModel.linked_transaction_id == parent_id).order_by(TxModel.id)
    )
    frais = res.scalars().all()
    assert len(frais) == 2
    for f in frais:
        assert f.balance_eur is not None, f"Frais {f.ticker} ({f.total_amount_eur}€) has no balance_eur"
    # courtage (0.80) applied first: 3.27 - 0.80 = 2.47; then ttf (0.99): 2.47 - 0.99 = 1.48
    assert frais[0].balance_eur == pytest.approx(2.47, abs=0.01)
    assert frais[1].balance_eur == pytest.approx(1.48, abs=0.01)


@pytest.mark.asyncio
async def test_update_without_frais_fields_leaves_linked_frais_unchanged(client, db_session):
    """PUT without courtage_eur/ttf_eur leaves linked Frais untouched."""
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel
    from sqlalchemy import select

    portfolio = Portfolio(name=f"UpdateNoFrais-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA2", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="SU.UPDATE", name="SE Update", category="Actif", currency="EUR"))
    db_session.add(Product(ticker="FRAIS.COURTAGE.EUR", name="Frais courtage", category="Frais", currency="EUR", fee_type="Courtage"))
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "SU.UPDATE",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -3.0, "unit_price": 270.0,
        "courtage_eur": 1.90,
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]

    # Update price only — no courtage_eur/ttf_eur → linked Frais must stay
    await client.put(f"/api/transactions/{parent_id}", json={"unit_price": 275.0})

    res = await db_session.execute(
        select(TxModel).where(TxModel.linked_transaction_id == parent_id)
    )
    frais = res.scalars().all()
    assert len(frais) == 1
    assert frais[0].total_amount_eur == pytest.approx(-1.90, abs=0.01)
