# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Non-regression tests for transaction CRUD endpoints: create, list (incl. filters and
pagination), update, delete, and create/update error paths.

Split out of the former test_transactions.py (3,757 lines) into 5 per-concern files —
this one (CRUD), test_transactions_cash_balance.py (cash_balance_eur auto-update, incl.
forex-position/Attribution exclusions), test_transactions_balance_branches.py (balance_eur/
balance_currency branch-coverage cluster), test_transactions_fees.py (Courtage+TTF cascade),
and test_transactions_fractional.py (fractional/multi-execution orders) — mirroring the same
per-concern split already applied to TransactionsPage.test.tsx/PerformancePage.test.tsx on the
frontend. Every split file duplicates its own small header (imports, `_TODAY`-style date
constants) rather than sharing one via a common module, matching that same frontend
precedent, since each file is meant to be readable standalone. Each test creates its own
Portfolio + Account + Product so fixtures are fully isolated. The snapshot-recompute task
triggered after mutations is enqueued via PgQueuer; conftest.py's `client` fixture provides a
default no-op get_pgq_queries override so tests don't need to mock it individually.
"""
import pytest

from tests.helpers import create_portfolio, create_broker_id, create_product

_create_portfolio = create_portfolio
_create_account = create_broker_id
_create_product = create_product


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
