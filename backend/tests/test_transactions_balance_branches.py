# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Branch-coverage-focused tests for create_transaction/update_transaction's balance_eur and
balance_currency logic: the account-not-found early exit, non-EUR-currency edge cases with
and without a previous balance, and the full update_transaction branch matrix (date-changed
vs. not, EUR vs. non-EUR, zero vs. non-zero prior amount) — plus balance_currency
auto-calculation for non-EUR transactions (JPYEUR=X).

Split out of the former test_transactions.py — see test_transactions_crud.py's own header
for the full split rationale and why each split file duplicates its own header.
"""
import pytest
from datetime import date, timedelta

from app.models.portfolio_account import PortfolioAccount

_TODAY = date.today().isoformat()
_LAST_WEEK = (date.today() - timedelta(days=7)).isoformat()


# ---------------------------------------------------------------------------
# Branch coverage — _update_account_cash_balance when account is None (108->exit)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_cash_balance_account_not_found_is_noop(client, db_session):
    """
    Branch 108->exit: _update_account_cash_balance with a non-existent account_id
    must silently do nothing (account is None → skip the update).

    We test this indirectly by deleting a transaction whose account was deleted
    from the DB — _update_account_cash_balance is called with the old account_id
    but the account no longer exists, so it must not raise.

    We achieve this by calling _update_account_cash_balance directly.
    """
    from app.services.transaction_service import _update_account_cash_balance

    # account_id 999988 does not exist in the test DB
    # Calling the helper with a missing account must silently return None (no error)
    result = await _update_account_cash_balance(
        db_session, account_id=999988, portfolio_id=999988, delta=100.0,
        tx_type="Actif", ticker="TEST",
    )
    assert result is None  # function returns None implicitly


# ---------------------------------------------------------------------------
# Branch coverage — create_transaction: non-EUR currency with prev balance
# (178->185 false: tx.currency != "EUR" so balance_currency not set from balance_eur)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_transaction_non_eur_balance_currency_not_auto_set(client, db_session):
    """
    Branch 178->185: when currency != 'EUR', balance_currency is NOT auto-set from balance_eur.

    Scenario: prev balance exists (507.83€), new tx in USD.
    balance_eur = prev_balance + total_amount_eur (auto-calc).
    balance_currency must NOT be set automatically (it's in USD, not the same as balance_eur).
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"NonEurBal-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="IBKR", currency="USD")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="AAPL.NONEUR", name="Apple", category="Actif", currency="USD"))
    db_session.add(Product(ticker="PREV.NONEUR", name="Prev", category="Actif", currency="EUR"))
    await db_session.flush()

    # Pre-existing transaction with a known balance_eur
    prev_tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 1, 1), type="Actif",
        ticker="PREV.NONEUR", currency="EUR", exchange_rate=1.0,
        quantity=-1.0, unit_price=507.83, unit_price_eur=507.83,
        total_amount=-507.83, total_amount_eur=-507.83,
        balance_eur=507.83, balance_currency=507.83,
    )
    db_session.add(prev_tx)
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "AAPL.NONEUR",
        "currency": "USD",   # NOT EUR → branch 178 false
        "exchange_rate": 0.92,
        "quantity": -5.0, "unit_price": 150.0,
    })
    assert r.status_code == 201
    data = r.json()
    # balance_eur was auto-calculated (prev + amount)
    assert data["balance_eur"] is not None
    # balance_currency must NOT be auto-set from balance_eur (non-EUR currency)
    # It should be None since we didn't provide it
    assert data["balance_currency"] is None


# ---------------------------------------------------------------------------
# balance_currency auto-calculation for non-EUR transactions (JPYEUR=X)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_non_eur_transaction_auto_calculates_balance_currency(client, db_session):
    """
    When a non-EUR transaction is created and there is a previous transaction in
    the same currency with a known balance_currency, balance_currency is computed
    as prev_balance_currency + total_amount (in native currency).

    Scenario: JPYEUR=X — first purchase of 117333 JPY recorded with balance_currency
    (total JPY held = 5716779). Adding a withdrawal of 10145 JPY yields 5706634 JPY.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"JpyBal-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Revolut", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="JPYEUR=X", name="JPY/EUR", category="Actif", instrument_type="Cash", currency="JPY"))
    await db_session.flush()

    # Previous JPY purchase with a known balance_currency (5716779 JPY held)
    prev_tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 5, 14), type="Actif",
        ticker="JPYEUR=X", currency="JPY", exchange_rate=0.006102,
        quantity=117333.0, unit_price=1.0, unit_price_eur=0.006102,
        total_amount=117333.0, total_amount_eur=716.0,
        balance_currency=5716779.0, balance_eur=34885.44,
    )
    db_session.add(prev_tx)
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "JPY", "exchange_rate": 0.005387,
        "quantity": -10145.0, "unit_price": 1.0,
    })
    assert r.status_code == 201
    data = r.json()

    # total_amount = -10145 × 1 = -10145 JPY
    # balance_currency = 5716779 + (-10145) = 5706634 JPY
    assert data["balance_currency"] == pytest.approx(5706634.0, abs=0.01)
    # balance_eur should also be computed (34885.44 + (-54.65) ≈ 34830.79)
    assert data["balance_eur"] is not None


@pytest.mark.asyncio
async def test_create_non_eur_transaction_no_prev_currency_balance_leaves_none(client, db_session):
    """
    When no previous transaction of the same currency has a known balance_currency,
    balance_currency stays null — same behaviour as balance_eur with no prior anchor.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"JpyNoPrev-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Revolut2", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
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
    # No prior JPY balance → balance_currency stays null
    assert r.json()["balance_currency"] is None


@pytest.mark.asyncio
async def test_create_non_eur_retroactive_balance_currency_propagation(client, db_session):
    """
    Inserting a non-EUR transaction in the past retroactively updates balance_currency
    for all subsequent same-currency transactions.

    Scenario: later withdrawal of 10145 JPY already has balance_currency=5706634.
    Inserting an earlier withdrawal of 1000 JPY (total_amount=-1000) must shift the
    later balance by -1000 → 5705634.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"JpyRetro-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Revolut3", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="JPYEUR=X", name="JPY/EUR", category="Actif", instrument_type="Cash", currency="JPY"))
    await db_session.flush()

    # Later withdrawal already has a computed balance_currency
    later_tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date.today(), type="Actif",
        ticker="JPYEUR=X", currency="JPY", exchange_rate=0.005387,
        quantity=-10145.0, unit_price=1.0, unit_price_eur=0.005387,
        total_amount=-10145.0, total_amount_eur=-54.65,
        balance_currency=5706634.0, balance_eur=34830.79,
    )
    db_session.add(later_tx)
    await db_session.flush()
    later_id = later_tx.id

    # Insert an earlier transaction — should shift the later balance by -1000
    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _LAST_WEEK, "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "JPY", "exchange_rate": 0.005400,
        "quantity": -1000.0, "unit_price": 1.0,
        # Provide balance_currency explicitly so retroactive propagation is triggered
        "balance_currency": 5707634.0,
    })
    assert r.status_code == 201

    # Verify the later transaction's balance_currency was shifted by -1000
    from app.models.transaction import Transaction as TxModel2
    refreshed = await db_session.get(TxModel2, later_id)
    assert refreshed is not None
    await db_session.refresh(refreshed)
    assert refreshed.balance_currency == pytest.approx(5705634.0, abs=0.01)


@pytest.mark.asyncio
async def test_create_non_eur_with_explicit_balance_currency_skips_elif(client, db_session):
    """
    Branch 215->237: non-EUR transaction where balance_currency is explicitly provided
    by the caller AND a previous balance_eur exists.

    In this case the elif (tx.balance_currency is None) is False, so the auto-computation
    is skipped and execution jumps directly to the retroactive update.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"JpyExplicit-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Revolut4", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="JPYEUR=X", name="JPY/EUR", category="Actif", instrument_type="Cash", currency="JPY"))
    await db_session.flush()

    # Previous transaction with known balance_eur (so prev_balance is not None)
    prev_tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 5, 14), type="Actif",
        ticker="JPYEUR=X", currency="JPY", exchange_rate=0.006102,
        quantity=117333.0, unit_price=1.0, unit_price_eur=0.006102,
        total_amount=117333.0, total_amount_eur=716.0,
        balance_currency=5716779.0, balance_eur=34885.44,
    )
    db_session.add(prev_tx)
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "JPY", "exchange_rate": 0.005387,
        "quantity": -10145.0, "unit_price": 1.0,
        # Caller explicitly provides balance_currency → elif is skipped
        "balance_currency": 5706634.0,
    })
    assert r.status_code == 201
    data = r.json()
    # balance_currency is the explicit value, not auto-computed
    assert data["balance_currency"] == pytest.approx(5706634.0, abs=0.01)
    # balance_eur was still auto-computed from prev
    assert data["balance_eur"] is not None


@pytest.mark.asyncio
async def test_create_non_eur_fractional_sibling_auto_calculates_balance_currency(client, db_session):
    """
    Line 323: non-EUR fractional sibling gets balance_currency auto-computed from the
    previous same-currency balance (prev_sib_curr_balance is not None path).

    Scenario: JPYEUR=X fractional order — parent + 1 sibling execution.
    A prior JPY transaction has balance_currency=5716779. The parent gets -10000 JPY
    (balance_currency=5706779), the sibling gets -1000 JPY (balance_currency=5705779).
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"JpyFrac-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="Revolut5", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="JPYEUR=X", name="JPY/EUR", category="Actif", instrument_type="Cash", currency="JPY"))
    await db_session.flush()

    # Prior JPY transaction providing the currency balance anchor
    anchor_tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 5, 14), type="Actif",
        ticker="JPYEUR=X", currency="JPY", exchange_rate=0.006102,
        quantity=117333.0, unit_price=1.0, unit_price_eur=0.006102,
        total_amount=117333.0, total_amount_eur=716.0,
        balance_currency=5716779.0, balance_eur=34885.44,
    )
    db_session.add(anchor_tx)
    await db_session.flush()

    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": _TODAY, "type": "Actif", "ticker": "JPYEUR=X",
        "currency": "JPY", "exchange_rate": 0.005387,
        "quantity": -10000.0, "unit_price": 1.0,
        "additional_executions": [
            {"date": _TODAY, "quantity": -1000.0, "unit_price": 1.0, "exchange_rate": 0.005387},
        ],
    })
    assert r.status_code == 201
    parent_id = r.json()["id"]
    # Parent: balance_currency = 5716779 + (-10000) = 5706779
    assert r.json()["balance_currency"] == pytest.approx(5706779.0, abs=0.01)

    # Sibling: balance_currency = 5706779 + (-1000) = 5705779 (line 323 executed)
    from sqlalchemy import select
    sib_res = await db_session.execute(
        select(TxModel).where(TxModel.fractional_parent_id == parent_id)
    )
    sibling = sib_res.scalar_one()
    assert sibling.balance_currency == pytest.approx(5705779.0, abs=0.01)


# ---------------------------------------------------------------------------
# Branch coverage — create_transaction: total_amount_eur == 0 (185->200 false)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_transaction_zero_amount_skips_retroactive_update(client, db_session):
    """
    Branch 185->200: when total_amount_eur == 0, the retroactive balance update
    of subsequent transactions is skipped.

    A transaction with quantity=0 or unit_price=0 yields total_amount_eur=0.
    No downstream balance_eur propagation should occur.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"ZeroAmt-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="ETF.ZERO", name="Zero ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    # Existing tx with a known balance (future tx)
    future_tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 12, 1), type="Actif",
        ticker="ETF.ZERO", currency="EUR", exchange_rate=1.0,
        quantity=-10.0, unit_price=50.0, unit_price_eur=50.0,
        total_amount=-500.0, total_amount_eur=-500.0,
        balance_eur=100.0, balance_currency=100.0,
    )
    db_session.add(future_tx)
    await db_session.flush()

    # Create a tx with total_amount_eur = 0 (quantity=0) → branch 185 false
    r = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": "2025-01-01", "type": "Actif", "ticker": "ETF.ZERO",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": 0.0, "unit_price": 50.0,  # total_amount_eur = 0
    })
    assert r.status_code == 201

    # future_tx balance_eur must be unchanged (no retroactive update)
    await db_session.refresh(future_tx)
    assert future_tx.balance_eur == pytest.approx(100.0, abs=0.01), (
        f"future_tx balance should be unchanged when total_amount_eur=0, got {future_tx.balance_eur}"
    )


# ---------------------------------------------------------------------------
# Branch coverage — update_transaction date_changed: old_total_eur == 0 (243->258 false)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_transaction_date_changed_zero_old_amount_skips_undo(client, db_session):
    """
    Branch 243->258: when old_total_eur == 0, the undo step is skipped.
    Moving a tx with total_amount_eur=0 to a new date: no undo propagation.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"ZeroOldAmt-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="ETF.ZEROOLD", name="Zero Old ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    # tx with total_amount_eur=0
    tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 2, 3), type="Actif",
        ticker="ETF.ZEROOLD", currency="EUR", exchange_rate=1.0,
        quantity=0.0, unit_price=50.0, unit_price_eur=50.0,
        total_amount=0.0, total_amount_eur=0.0,
        balance_eur=100.0, balance_currency=100.0,
    )
    db_session.add(tx)

    # A subsequent tx with known balance (should NOT be changed)
    subsequent = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 3, 3), type="Actif",
        ticker="ETF.ZEROOLD", currency="EUR", exchange_rate=1.0,
        quantity=-5.0, unit_price=50.0, unit_price_eur=50.0,
        total_amount=-250.0, total_amount_eur=-250.0,
        balance_eur=200.0, balance_currency=200.0,
    )
    db_session.add(subsequent)
    await db_session.flush()

    # Move tx to a new date → date_changed=True, old_total_eur=0 → branch 243 false
    r = await client.put(f"/api/transactions/{tx.id}", json={"date": "2025-01-01"})
    assert r.status_code == 200

    # subsequent balance must remain unchanged (no undo propagation)
    await db_session.refresh(subsequent)
    assert subsequent.balance_eur == pytest.approx(200.0, abs=0.01)


@pytest.mark.asyncio
async def test_update_transaction_date_change_with_amount_change_updates_cash_balance(client, db_session):
    """
    Changing BOTH date and amount (quantity/unit_price/exchange_rate) in the same
    edit takes the date_changed branch, which must still apply the amount delta
    to cash_balance_eur — it used to be silently dropped there (only the non-date-
    move branch called _update_account_cash_balance).
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product

    portfolio = Portfolio(name=f"DateAndAmount-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    pa = PortfolioAccount(portfolio_id=uid, broker_id=account.id, cash_balance_eur=500.0)
    db_session.add(pa)
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="ETF.DATEAMT", name="Date+Amount ETF", category="Actif", currency="EUR"))
    await db_session.flush()

    r_create = await client.post("/api/transactions/", json={
        "portfolio_id": uid, "account_id": aid,
        "date": "2025-02-03", "type": "Actif", "ticker": "ETF.DATEAMT",
        "currency": "EUR", "exchange_rate": 1.0,
        "quantity": -5.0, "unit_price": 50.0,
    })
    assert r_create.status_code == 201
    tx_id = r_create.json()["id"]

    # total_amount_eur was -250 (5*50); cash_balance_eur = 500 - 250 = 250
    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(250.0, abs=0.01)

    # Change both the date AND the quantity in the same PUT
    r_update = await client.put(f"/api/transactions/{tx_id}", json={
        "date": "2025-03-10", "quantity": -8.0,
    })
    assert r_update.status_code == 200

    # New total_amount_eur = -8*50 = -400; delta = -400 - (-250) = -150
    # cash_balance_eur must reflect the delta: 250 + (-150) = 100
    await db_session.refresh(pa)
    assert pa.cash_balance_eur == pytest.approx(100.0, abs=0.01)


# ---------------------------------------------------------------------------
# Branch coverage — update date_changed: prev_balance is None after move (273->282 else)
# ---------------------------------------------------------------------------
# This branch is already covered by test_update_transaction_date_change_recalculates_balance_eur
# which moves T2 before T1 resulting in balance_eur=None.
# Let's add a more targeted test focusing on the EUR currency branch within date_changed.

@pytest.mark.asyncio
async def test_update_transaction_date_changed_eur_currency_sets_balance_currency(client, db_session):
    """
    Branch 273->282 true: when prev_balance is not None AND currency == 'EUR',
    both balance_eur and balance_currency get set.

    Move a EUR tx to a new position where a prior balance exists.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"DateEurBal-{id(db_session)}")
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

    # T1 (Jan, +100, bal=100)
    t1 = make_tx(date(2025, 1, 1), 100.0, 100.0)
    # T2 (Mar, +200, bal=300) — will be moved to Feb
    t2 = make_tx(date(2025, 3, 1), 200.0, 300.0)
    # T3 (Apr, +50, bal=350)
    t3 = make_tx(date(2025, 4, 1), 50.0, 350.0)
    db_session.add_all([t1, t2, t3])
    await db_session.flush()

    # Move T2 to Feb (between T1 and original Mar position)
    # After move: T2 at Feb, prior = T1 (bal=100), so T2.balance_eur = 100+200=300
    # And currency="EUR" → balance_currency also set to 300
    r = await client.put(f"/api/transactions/{t2.id}", json={"date": "2025-02-01"})
    assert r.status_code == 200
    data = r.json()

    # balance_eur should be 100 (T1 bal) + 200 (T2 amount) = 300
    assert data["balance_eur"] == pytest.approx(300.0, abs=0.01)
    # currency == EUR → balance_currency must also be set
    assert data["balance_currency"] == pytest.approx(300.0, abs=0.01)


# ---------------------------------------------------------------------------
# Branch coverage — update date_changed: tx.total_amount_eur == 0 (282->340 false)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_transaction_date_changed_zero_new_amount_skips_apply(client, db_session):
    """
    Branch 282->340: when tx.total_amount_eur == 0 after date change,
    the 'apply at new position' propagation is skipped.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"ZeroNewAmt-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="PEA", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="ETF.ZERONEW", name="Zero New", category="Actif", currency="EUR"))
    await db_session.flush()

    # tx with total_amount_eur=0 (no financial impact)
    tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 3, 3), type="Actif",
        ticker="ETF.ZERONEW", currency="EUR", exchange_rate=1.0,
        quantity=0.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=0.0, total_amount_eur=0.0,
        balance_eur=50.0, balance_currency=50.0,
    )
    db_session.add(tx)

    # A subsequent tx
    future_tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 5, 1), type="Actif",
        ticker="ETF.ZERONEW", currency="EUR", exchange_rate=1.0,
        quantity=-2.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=-200.0, total_amount_eur=-200.0,
        balance_eur=75.0, balance_currency=75.0,
    )
    db_session.add(future_tx)
    await db_session.flush()

    # Move tx to new date (date_changed=True), total_amount_eur still 0
    r = await client.put(f"/api/transactions/{tx.id}", json={"date": "2025-01-01"})
    assert r.status_code == 200

    # future_tx balance must be unchanged (no apply propagation when total=0)
    await db_session.refresh(future_tx)
    assert future_tx.balance_eur == pytest.approx(75.0, abs=0.01)


# ---------------------------------------------------------------------------
# Branch coverage — update no date change: currency == EUR sets balance_currency (313->316)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_transaction_no_date_change_eur_auto_calc_sets_balance_currency(client, db_session):
    """
    Branch 313->316: in the else branch (no date change), when balance_eur is None
    and prev_balance is found AND currency == 'EUR', balance_currency is also set.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"ElseEurBal-{id(db_session)}")
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

    # Prev tx with known balance
    prev_tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 1, 1), type="Actif",
        ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
        quantity=200.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=200.0, total_amount_eur=200.0,
        balance_eur=200.0, balance_currency=200.0,
    )
    db_session.add(prev_tx)
    await db_session.flush()

    # Current tx with balance_eur=None, currency=EUR → on edit, auto-calc fills both
    curr_tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 2, 1), type="Actif",
        ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
        quantity=50.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=50.0, total_amount_eur=50.0,
        balance_eur=None, balance_currency=None,  # simulating pre-fix transaction
    )
    db_session.add(curr_tx)
    await db_session.flush()

    # Edit without changing date (no date_changed → else branch) → triggers auto-calc
    r = await client.put(f"/api/transactions/{curr_tx.id}", json={})
    assert r.status_code == 200
    data = r.json()

    # balance_eur = prev (200) + amount (50) = 250
    assert data["balance_eur"] == pytest.approx(250.0, abs=0.01)
    # currency == EUR → balance_currency also set
    assert data["balance_currency"] == pytest.approx(250.0, abs=0.01)


# ---------------------------------------------------------------------------
# Branch coverage — update no date change: delta != 0, currency == EUR (322->326)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_transaction_no_date_change_delta_eur_sets_balance_currency(client, db_session):
    """
    Branch 322->326: in the else branch (no date change), when delta != 0
    AND balance_eur is not None AND currency == 'EUR', balance_currency is set.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"DeltaEurBal-{id(db_session)}")
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

    # tx with known balance_eur and currency=EUR
    tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 3, 3), type="Actif",
        ticker="LIQUIDITE.EURO", currency="EUR", exchange_rate=1.0,
        quantity=100.0, unit_price=1.0, unit_price_eur=1.0,
        total_amount=100.0, total_amount_eur=100.0,
        balance_eur=100.0, balance_currency=100.0,
    )
    db_session.add(tx)
    await db_session.flush()

    # Change quantity (no date change) → delta != 0, currency=EUR → branch 322 true
    r = await client.put(f"/api/transactions/{tx.id}", json={"quantity": 150.0})
    assert r.status_code == 200
    data = r.json()

    # total_amount_eur was 100, now 150 → delta = 50
    # balance_eur was 100, now 100 + 50 = 150
    assert data["balance_eur"] == pytest.approx(150.0, abs=0.01)
    # currency == EUR → balance_currency also updated
    assert data["balance_currency"] == pytest.approx(150.0, abs=0.01)


# ---------------------------------------------------------------------------
# Branch coverage — update date_changed: prev_balance found, currency != EUR (273->282 false)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_transaction_date_changed_non_eur_balance_currency_not_set(client, db_session):
    """
    Branch 273->282 false: when prev_balance is not None AND currency != 'EUR',
    balance_eur is set but balance_currency is NOT auto-set.

    Move a USD (non-EUR) tx to a position where a prior EUR balance exists.
    balance_eur is computed; balance_currency should remain None (not copied from balance_eur).
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"DateNonEurBal-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="IBKR", currency="USD")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="PREV.DNEUB", name="Prev EUR", category="Actif", currency="EUR"))
    db_session.add(Product(ticker="AAPL.DNEUB", name="Apple DNEUB", category="Actif", currency="USD"))
    await db_session.flush()

    # Anchor tx: provides a prior balance_eur
    anchor = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 1, 1), type="Actif",
        ticker="PREV.DNEUB", currency="EUR", exchange_rate=1.0,
        quantity=-1.0, unit_price=500.0, unit_price_eur=500.0,
        total_amount=-500.0, total_amount_eur=-500.0,
        balance_eur=500.0, balance_currency=500.0,
    )
    db_session.add(anchor)
    await db_session.flush()

    # USD tx at Feb — will be moved to Feb (just a date change to trigger the date_changed branch)
    # We move it from Mar to Feb to get it after the anchor (Jan) so prior balance is found
    tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 3, 1), type="Actif",
        ticker="AAPL.DNEUB", currency="USD", exchange_rate=0.92,
        quantity=-5.0, unit_price=200.0, unit_price_eur=184.0,
        total_amount=-1000.0, total_amount_eur=-920.0,
        balance_eur=None, balance_currency=None,
    )
    db_session.add(tx)
    await db_session.flush()

    # Move tx from Mar to Feb (between anchor at Jan and old position at Mar)
    # date_changed=True; after move, prior balance = anchor's balance_eur (500.0)
    # currency = "USD" (non-EUR) → branch 273->282 false → balance_currency NOT set
    r = await client.put(f"/api/transactions/{tx.id}", json={"date": "2025-02-01"})
    assert r.status_code == 200
    data = r.json()

    # balance_eur should be computed: anchor_balance (500) + total_amount_eur (-920) = -420
    assert data["balance_eur"] == pytest.approx(500.0 + (-920.0), abs=0.01)
    # currency != EUR → balance_currency NOT auto-set → stays None
    assert data["balance_currency"] is None


# ---------------------------------------------------------------------------
# Branch coverage — update no date change: auto-calc non-EUR currency (313->316 false)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_transaction_no_date_change_non_eur_auto_calc_no_balance_currency(client, db_session):
    """
    Branch 313->316 false: in the else branch (no date change), when balance_eur is None
    and prev_balance is found AND currency != 'EUR', balance_currency is NOT set.

    Tests the false path of `if tx.currency == "EUR" and tx.balance_currency is None`.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"ElseNonEurBal-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="IBKR", currency="USD")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="PREV.NEUB2", name="Prev EUR", category="Actif", currency="EUR"))
    db_session.add(Product(ticker="AAPL.NEUB2", name="Apple NEUB2", category="Actif", currency="USD"))
    await db_session.flush()

    # Prev tx with known balance
    prev_tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 1, 1), type="Actif",
        ticker="PREV.NEUB2", currency="EUR", exchange_rate=1.0,
        quantity=-1.0, unit_price=300.0, unit_price_eur=300.0,
        total_amount=-300.0, total_amount_eur=-300.0,
        balance_eur=300.0, balance_currency=300.0,
    )
    db_session.add(prev_tx)
    await db_session.flush()

    # Current USD tx with balance_eur=None → on edit (no date change), auto-calc fills balance_eur
    # but NOT balance_currency (currency != EUR)
    curr_tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 2, 1), type="Actif",
        ticker="AAPL.NEUB2", currency="USD", exchange_rate=0.92,
        quantity=-10.0, unit_price=100.0, unit_price_eur=92.0,
        total_amount=-1000.0, total_amount_eur=-920.0,
        balance_eur=None, balance_currency=None,
    )
    db_session.add(curr_tx)
    await db_session.flush()

    # Edit without changing date → else branch, balance_eur=None, currency=USD → 313->316 false
    r = await client.put(f"/api/transactions/{curr_tx.id}", json={})
    assert r.status_code == 200
    data = r.json()

    # balance_eur = prev (300) + total_amount_eur (-920) = -620
    assert data["balance_eur"] == pytest.approx(300.0 + (-920.0), abs=0.01)
    # currency != EUR → balance_currency NOT auto-set → stays None
    assert data["balance_currency"] is None


# ---------------------------------------------------------------------------
# Branch coverage — update no date change: delta != 0, currency != EUR (322->326 false)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_transaction_no_date_change_delta_non_eur_no_balance_currency(client, db_session):
    """
    Branch 322->326 false: in the else branch (no date change), when delta != 0
    AND balance_eur is not None AND currency != 'EUR', balance_currency is NOT set.
    """
    from app.models.portfolio import Portfolio
    from app.models.broker import Broker
    from app.models.product import Product
    from app.models.transaction import Transaction as TxModel

    portfolio = Portfolio(name=f"DeltaNonEurBal-{id(db_session)}")
    db_session.add(portfolio)
    await db_session.flush()
    uid = portfolio.id

    account = Broker(name="IBKR", currency="USD")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=uid, broker_id=account.id))
    await db_session.flush()
    aid = account.id

    db_session.add(Product(ticker="AAPL.DNEUB2", name="Apple DNEUB2", category="Actif", currency="USD"))
    await db_session.flush()

    # USD tx with known balance_eur (in EUR) — currency is USD, not EUR
    tx = TxModel(
        portfolio_id=uid, account_id=aid, date=date(2025, 3, 3), type="Actif",
        ticker="AAPL.DNEUB2", currency="USD", exchange_rate=0.92,
        quantity=-100.0, unit_price=10.0, unit_price_eur=9.2,
        total_amount=-1000.0, total_amount_eur=-920.0,
        balance_eur=-920.0, balance_currency=None,  # balance_currency is null (USD qty)
    )
    db_session.add(tx)
    await db_session.flush()

    # Change quantity (no date change) → delta != 0, currency=USD → branch 322 false
    r = await client.put(f"/api/transactions/{tx.id}", json={"quantity": -150.0})
    assert r.status_code == 200
    data = r.json()

    # total_amount_eur was -920, now -150 * 10 * 0.92 = -1380 → delta = -460
    # balance_eur was -920, now -920 + (-460) = -1380
    assert data["balance_eur"] == pytest.approx(-920.0 + (-460.0), abs=0.01)
    # currency != EUR → balance_currency NOT updated (stays None)
    assert data["balance_currency"] is None
