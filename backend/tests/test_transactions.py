"""
Non-regression tests for transaction CRUD endpoints.

Each test creates its own Portfolio + Account + Product so fixtures are
fully isolated. The snapshot-recompute task triggered after mutations is enqueued via
PgQueuer; conftest.py's `client` fixture provides a default no-op get_pgq_queries override
so tests don't need to mock it individually.
"""
import pytest
from datetime import date, timedelta
from sqlalchemy import select

from tests.helpers import create_portfolio, create_broker_id, create_product
from app.models.portfolio_account import PortfolioAccount

_create_portfolio = create_portfolio
_create_account = create_broker_id
_create_product = create_product

_TODAY = date.today().isoformat()
_YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
_LAST_WEEK = (date.today() - timedelta(days=7)).isoformat()
_LAST_MONTH = (date.today() - timedelta(days=30)).isoformat()


def _tx_payload(portfolio_id: int, account_id: int, ticker: str = "CS.PA") -> dict:
    return {
        "portfolio_id": portfolio_id,
        "account_id": account_id,
        "date": "2025-03-15",
        "type": "Actif",
        "ticker": ticker,
        "currency": "EUR",
        "exchange_rate": 1.0,
        "quantity": -10.0,       # sell convention
        "unit_price": 25.50,
    }


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_transaction_computes_derived_fields(client):
    """
    Derived fields (unit_price_eur, total_amount, total_amount_eur) must be
    computed automatically from quantity, unit_price and exchange_rate.
    """
    uid = await _create_portfolio(client, "TX-Create-1")
    aid = await _create_account(client, uid)
    await _create_product(client, "AAPL.TX1")

    payload = {
        "portfolio_id": uid,
        "account_id": aid,
        "date": "2025-04-01",
        "type": "Actif",
        "ticker": "AAPL.TX1",
        "currency": "USD",
        "exchange_rate": 0.92,
        "quantity": -5.0,
        "unit_price": 200.0,
    }

    r = await client.post("/api/transactions/", json=payload)

    assert r.status_code == 201, r.text
    data = r.json()

    assert data["unit_price_eur"] == pytest.approx(200.0 * 0.92)
    assert data["total_amount"] == pytest.approx(-5.0 * 200.0)
    assert data["total_amount_eur"] == pytest.approx(-5.0 * 200.0 * 0.92)


@pytest.mark.asyncio
async def test_create_transaction_eur_defaults(client):
    """For a EUR transaction with exchange_rate=1 all amounts stay consistent."""
    uid = await _create_portfolio(client, "TX-Create-2")
    aid = await _create_account(client, uid)
    await _create_product(client, "BNP.TX2")

    payload = {
        "portfolio_id": uid,
        "account_id": aid,
        "date": "2025-05-10",
        "type": "Actif",
        "ticker": "BNP.TX2",
        "currency": "EUR",
        "exchange_rate": 1.0,
        "quantity": -3.0,
        "unit_price": 50.0,
    }

    r = await client.post("/api/transactions/", json=payload)

    assert r.status_code == 201
    data = r.json()
    assert data["unit_price_eur"] == pytest.approx(50.0)
    assert data["total_amount"] == pytest.approx(-150.0)
    assert data["total_amount_eur"] == pytest.approx(-150.0)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_transactions_filtered_by_user(client):
    """Only transactions belonging to the queried portfolio_id must be returned."""
    uid1 = await _create_portfolio(client, "TX-List-User1")
    uid2 = await _create_portfolio(client, "TX-List-User2")
    aid1 = await _create_account(client, uid1, "AccountU1")
    aid2 = await _create_account(client, uid2, "AccountU2")
    await _create_product(client, "ETF.LIST1")
    await _create_product(client, "ETF.LIST2")

    await client.post("/api/transactions/", json={**_tx_payload(uid1, aid1, "ETF.LIST1"), "date": "2025-01-05"})
    await client.post("/api/transactions/", json={**_tx_payload(uid2, aid2, "ETF.LIST2"), "date": "2025-01-06"})

    r = await client.get(f"/api/transactions/?portfolio_id={uid1}")
    assert r.status_code == 200
    tickers = [t["ticker"] for t in r.json()]
    assert "ETF.LIST1" in tickers
    assert "ETF.LIST2" not in tickers


@pytest.mark.asyncio
async def test_list_transactions_empty_for_new_user(client):
    uid = await _create_portfolio(client, "TX-Empty-User")
    r = await client.get(f"/api/transactions/?portfolio_id={uid}")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_transactions_date_filter(client):
    """date_from / date_to query params must filter correctly."""
    uid = await _create_portfolio(client, "TX-DateFilter")
    aid = await _create_account(client, uid)
    await _create_product(client, "ETF.DATE1")
    await _create_product(client, "ETF.DATE2")

    await client.post("/api/transactions/", json={**_tx_payload(uid, aid, "ETF.DATE1"), "date": "2024-12-01"})
    await client.post("/api/transactions/", json={**_tx_payload(uid, aid, "ETF.DATE2"), "date": "2025-06-15"})

    r = await client.get(f"/api/transactions/?portfolio_id={uid}&date_from=2025-01-01")
    assert r.status_code == 200
    dates = [t["date"] for t in r.json()]
    assert all(d >= "2025-01-01" for d in dates)


# ---------------------------------------------------------------------------
# Update (PUT)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_transaction_recalculates_derived_fields(client):
    """
    When quantity or unit_price changes via PUT, derived fields must be
    automatically recomputed.
    """
    uid = await _create_portfolio(client, "TX-Update-1")
    aid = await _create_account(client, uid)
    await _create_product(client, "SAN.UPD1")

    tx_id = (await client.post(
        "/api/transactions/",
        json={**_tx_payload(uid, aid, "SAN.UPD1"), "unit_price": 10.0, "quantity": -5.0},
    )).json()["id"]

    r = await client.put(
        f"/api/transactions/{tx_id}",
        json={"quantity": -10.0, "unit_price": 20.0},
    )

    assert r.status_code == 200
    data = r.json()
    assert data["total_amount"] == pytest.approx(-200.0)
    assert data["unit_price_eur"] == pytest.approx(20.0)  # exchange_rate=1


@pytest.mark.asyncio
async def test_update_transaction_not_found(client):
    r = await client.put("/api/transactions/999999", json={"quantity": -1.0})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_transaction(client):
    uid = await _create_portfolio(client, "TX-Delete-1")
    aid = await _create_account(client, uid)
    await _create_product(client, "MC.DEL1")

    tx_id = (await client.post(
        "/api/transactions/",
        json=_tx_payload(uid, aid, "MC.DEL1"),
    )).json()["id"]

    r = await client.delete(f"/api/transactions/{tx_id}")

    assert r.status_code == 204

    # Confirm gone
    remaining = (await client.get(f"/api/transactions/?portfolio_id={uid}")).json()
    ids = [t["id"] for t in remaining]
    assert tx_id not in ids


@pytest.mark.asyncio
async def test_delete_transaction_not_found(client):
    r = await client.delete("/api/transactions/999999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Filter by account_id (line 91), ticker (line 93), date_to (line 97)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_transactions_filter_by_account_id(client):
    """account_id filter returns only transactions for that account."""
    uid = await _create_portfolio(client, "TX-AccFilter")
    aid1 = await _create_account(client, uid, "Degiro")
    aid2 = await _create_account(client, uid, "IBKR")
    await _create_product(client, "ETF.ACC1")
    await _create_product(client, "ETF.ACC2")

    await client.post("/api/transactions/", json={**_tx_payload(uid, aid1, "ETF.ACC1")})
    await client.post("/api/transactions/", json={**_tx_payload(uid, aid2, "ETF.ACC2")})

    r = await client.get(f"/api/transactions/?portfolio_id={uid}&account_id={aid1}")
    assert r.status_code == 200
    assert all(t["account_id"] == aid1 for t in r.json())
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_list_transactions_filter_by_ticker(client):
    """ticker filter uses case-insensitive substring (ilike) matching."""
    uid = await _create_portfolio(client, "TX-TickFilter")
    aid = await _create_account(client, uid)
    await _create_product(client, "AAA.TICK")
    await _create_product(client, "BBB.TICK")

    await client.post("/api/transactions/", json={**_tx_payload(uid, aid, "AAA.TICK")})
    await client.post("/api/transactions/", json={**_tx_payload(uid, aid, "BBB.TICK")})

    # Exact match still works
    r = await client.get(f"/api/transactions/?portfolio_id={uid}&ticker=AAA.TICK")
    assert r.status_code == 200
    assert all(t["ticker"] == "AAA.TICK" for t in r.json())
    assert len(r.json()) == 1

    # Substring match: partial prefix returns the matching ticker
    r = await client.get(f"/api/transactions/?portfolio_id={uid}&ticker=AAA")
    assert r.status_code == 200
    tickers = [t["ticker"] for t in r.json()]
    assert "AAA.TICK" in tickers
    assert "BBB.TICK" not in tickers

    # Case-insensitive match: lowercase should match uppercase stored ticker
    r = await client.get(f"/api/transactions/?portfolio_id={uid}&ticker=aaa.tick")
    assert r.status_code == 200
    assert all(t["ticker"] == "AAA.TICK" for t in r.json())
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_list_transactions_filter_by_currency(client):
    """currency filter uses case-insensitive substring (ilike) matching."""
    uid = await _create_portfolio(client, "TX-CurrFilter")
    aid = await _create_account(client, uid)
    await _create_product(client, "ETF.EUR.CURR")
    await _create_product(client, "ETF.USD.CURR")

    await client.post("/api/transactions/", json={
        **_tx_payload(uid, aid, "ETF.EUR.CURR"),
        "currency": "EUR",
    })
    await client.post("/api/transactions/", json={
        **_tx_payload(uid, aid, "ETF.USD.CURR"),
        "currency": "USD",
        "exchange_rate": 0.92,
    })

    # Exact match
    r = await client.get(f"/api/transactions/?portfolio_id={uid}&currency=EUR")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["currency"] == "EUR"

    # Other currency
    r = await client.get(f"/api/transactions/?portfolio_id={uid}&currency=USD")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["currency"] == "USD"

    # Case-insensitive match: lowercase "eur" should match "EUR"
    r = await client.get(f"/api/transactions/?portfolio_id={uid}&currency=eur")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["currency"] == "EUR"

    # No currency filter: both returned
    r = await client.get(f"/api/transactions/?portfolio_id={uid}")
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_list_transactions_filter_date_to(client):
    """date_to filter excludes transactions after the given date."""
    uid = await _create_portfolio(client, "TX-DateTo")
    aid = await _create_account(client, uid)
    await _create_product(client, "ETF.DT1")
    await _create_product(client, "ETF.DT2")

    await client.post("/api/transactions/", json={**_tx_payload(uid, aid, "ETF.DT1"), "date": "2024-03-01"})
    await client.post("/api/transactions/", json={**_tx_payload(uid, aid, "ETF.DT2"), "date": "2025-09-15"})

    r = await client.get(f"/api/transactions/?portfolio_id={uid}&date_to=2024-12-31")
    assert r.status_code == 200
    dates = [t["date"] for t in r.json()]
    assert all(d <= "2024-12-31" for d in dates)
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# Create — error paths (lines 102-116)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_transaction_account_not_found(client):
    """POST with non-existent account_id → 400."""
    uid = await _create_portfolio(client, "TX-AccNotFound")
    await _create_product(client, "ETF.ACCNF")
    payload = {
        "portfolio_id": uid,
        "account_id": 999999,  # non-existent
        "date": "2025-01-10",
        "type": "Actif",
        "ticker": "ETF.ACCNF",
        "currency": "EUR",
        "exchange_rate": 1.0,
        "quantity": -5.0,
        "unit_price": 100.0,
    }
    r = await client.post("/api/transactions/", json=payload)
    assert r.status_code == 400
    assert "Broker not found" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_transaction_portfolio_mismatch(client):
    """POST with account belonging to a different portfolio → 400 (lines 112-116)."""
    uid_a = await _create_portfolio(client, "TX-MismatchA")
    uid_b = await _create_portfolio(client, "TX-MismatchB")
    # Account belongs to portfolio B
    r_acc = await client.post("/api/brokers/", json={
        "name": "AccB", "currency": "EUR", "portfolio_ids": [uid_b],
    })
    assert r_acc.status_code == 201
    aid_b = r_acc.json()["id"]

    await _create_product(client, "ETF.MISMATCH")
    payload = {
        "portfolio_id": uid_a,  # wrong portfolio
        "account_id": aid_b,
        "date": "2025-02-01",
        "type": "Actif",
        "ticker": "ETF.MISMATCH",
        "currency": "EUR",
        "exchange_rate": 1.0,
        "quantity": -3.0,
        "unit_price": 50.0,
    }
    r = await client.post("/api/transactions/", json=payload)
    assert r.status_code == 400
    assert "does not belong to the specified portfolio" in r.json()["detail"]


@pytest.mark.asyncio
async def test_update_transaction_only_non_price_fields(client):
    """
    PUT updating only non-price/qty/rate fields (e.g. ticker, type) should NOT
    recompute derived fields — covers the else branch of the `if any(...)` check
    at lines 142-145.
    """
    uid = await _create_portfolio(client, "TX-UpdateNonPrice")
    aid = await _create_account(client, uid)
    await _create_product(client, "ETF.NONPRICE")
    await _create_product(client, "ETF.NONPRICE2")

    tx = (await client.post("/api/transactions/", json={
        **_tx_payload(uid, aid, "ETF.NONPRICE"),
        "quantity": -2.0,
        "unit_price": 30.0,
        "exchange_rate": 1.0,
    })).json()
    tx_id = tx["id"]
    original_total = tx["total_amount"]

    # Update only the ticker (no price/qty/rate change) → else branch, no recompute
    r = await client.put(f"/api/transactions/{tx_id}", json={"ticker": "ETF.NONPRICE2"})

    assert r.status_code == 200
    data = r.json()
    # Derived fields unchanged (total_amount stays at original)
    assert data["total_amount"] == pytest.approx(original_total)
    assert data["ticker"] == "ETF.NONPRICE2"


@pytest.mark.asyncio
async def test_list_transactions_skip_and_limit(client):
    """skip and limit params control pagination (lines 97-101)."""
    uid = await _create_portfolio(client, "TX-Paginate")
    aid = await _create_account(client, uid)
    await _create_product(client, "ETF.PAGE")

    for i in range(5):
        await client.post("/api/transactions/", json={
            **_tx_payload(uid, aid, "ETF.PAGE"),
            "date": f"2025-0{i+1}-15",
        })

    r_all = await client.get(f"/api/transactions/?portfolio_id={uid}")
    assert len(r_all.json()) == 5

    r_paged = await client.get(f"/api/transactions/?portfolio_id={uid}&skip=2&limit=2")
    assert r_paged.status_code == 200
    assert len(r_paged.json()) == 2


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
    from datetime import date as _date
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
    from sqlalchemy import select

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
    from sqlalchemy import select

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
    from app.api.routers.transactions import _update_account_cash_balance

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
