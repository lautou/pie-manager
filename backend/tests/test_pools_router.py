"""
Integration tests for /api/pools — CRUD and pool-product association.

Uses the `client` fixture from conftest.py (test DB injected).
"""

import pytest

from tests.helpers import create_portfolio, create_pool, create_product

_create_portfolio = create_portfolio
_create_pool = create_pool
_create_product = create_product


# ---------------------------------------------------------------------------
# List pools (lines 57-58)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pools_empty(client, db_session):
    uid = await _create_portfolio(client, f"PoolTest-{id(db_session)}")
    r = await client.get("/api/pools/", params={"portfolio_id": uid})
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Create pool (lines 63-67)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_pool(client, db_session):
    uid = await _create_portfolio(client, f"PoolCreate-{id(db_session)}")
    r = await client.post("/api/pools/", json={
        "portfolio_id": uid, "name": "Asie", "strategy": "Offensive",
        "target_pct": 0.25, "is_active": True,
    })
    assert r.status_code == 201
    assert r.json()["name"] == "Asie"
    assert r.json()["strategy"] == "Offensive"
    assert r.json()["target_pct"] == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_list_pools_returns_created(client, db_session):
    uid = await _create_portfolio(client, f"PoolList-{id(db_session)}")
    await _create_pool(client, uid, "Or", "Defensive")
    r = await client.get("/api/pools/", params={"portfolio_id": uid})
    assert len(r.json()) == 1
    assert r.json()[0]["name"] == "Or"


# ---------------------------------------------------------------------------
# Update pool (lines 76-84)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_pool(client, db_session):
    uid = await _create_portfolio(client, f"PoolUpd-{id(db_session)}")
    pool = await _create_pool(client, uid, "Yen")
    r = await client.put(f"/api/pools/{pool['id']}", json={"name": "Yen-2", "target_pct": 0.30})
    assert r.status_code == 200
    assert r.json()["name"] == "Yen-2"
    assert r.json()["target_pct"] == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_update_pool_not_found(client):
    r = await client.put("/api/pools/99999", json={"name": "X"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Delete pool (lines 89-94)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_pool(client, db_session):
    uid = await _create_portfolio(client, f"PoolDel-{id(db_session)}")
    pool = await _create_pool(client, uid, "ToDelete")
    r = await client.delete(f"/api/pools/{pool['id']}")
    assert r.status_code == 204
    assert (await client.get("/api/pools/", params={"portfolio_id": uid})).json() == []


@pytest.mark.asyncio
async def test_delete_pool_not_found(client):
    r = await client.delete("/api/pools/99999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Pool products — list (lines 99-102)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pool_products_empty(client, db_session):
    uid = await _create_portfolio(client, f"PP-Empty-{id(db_session)}")
    pool = await _create_pool(client, uid)
    r = await client.get(f"/api/pools/{pool['id']}/products")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Pool products — add (lines 111-128)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_product_to_pool(client, db_session):
    uid = await _create_portfolio(client, f"PP-Add-{id(db_session)}")
    ticker = f"TEST.P.{id(db_session)}"
    pool = await _create_pool(client, uid)
    await _create_product(client, ticker)
    r = await client.post(f"/api/pools/{pool['id']}/products", json={"ticker": ticker})
    assert r.status_code == 201
    products = (await client.get(f"/api/pools/{pool['id']}/products")).json()
    assert any(p["ticker"] == ticker for p in products)


@pytest.mark.asyncio
async def test_add_product_pool_not_found(client):
    r = await client.post("/api/pools/99999/products", json={"ticker": "X.PA"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_add_duplicate_product_rejected(client, db_session):
    uid = await _create_portfolio(client, f"PP-Dup-{id(db_session)}")
    ticker = f"DUP.P.{id(db_session)}"
    pool = await _create_pool(client, uid)
    await _create_product(client, ticker)
    await client.post(f"/api/pools/{pool['id']}/products", json={"ticker": ticker})
    r = await client.post(f"/api/pools/{pool['id']}/products", json={"ticker": ticker})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Pool products — remove (lines 137-146)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_product_from_pool(client, db_session):
    uid = await _create_portfolio(client, f"PP-Rem-{id(db_session)}")
    ticker = f"REM.P.{id(db_session)}"
    pool = await _create_pool(client, uid)
    await _create_product(client, ticker)
    await client.post(f"/api/pools/{pool['id']}/products", json={"ticker": ticker})
    r = await client.delete(f"/api/pools/{pool['id']}/products/{ticker}")
    assert r.status_code == 204
    assert (await client.get(f"/api/pools/{pool['id']}/products")).json() == []


@pytest.mark.asyncio
async def test_remove_product_not_found(client, db_session):
    uid = await _create_portfolio(client, f"PP-RemNF-{id(db_session)}")
    pool = await _create_pool(client, uid)
    r = await client.delete(f"/api/pools/{pool['id']}/products/MISSING.PA")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Business rule: one ticker → at most one pool per portfolio
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ticker_cannot_belong_to_two_pools(client, db_session):
    """Assigning the same ticker to a second pool in the same portfolio must return 409."""
    uid = await _create_portfolio(client, f"PP-OnePool-{id(db_session)}")
    ticker = f"EXCL.{id(db_session)}"
    pool_a = await _create_pool(client, uid, "PoolA")
    pool_b = await _create_pool(client, uid, "PoolB")
    await _create_product(client, ticker)

    r1 = await client.post(f"/api/pools/{pool_a['id']}/products", json={"ticker": ticker})
    assert r1.status_code == 201

    r2 = await client.post(f"/api/pools/{pool_b['id']}/products", json={"ticker": ticker})
    assert r2.status_code == 409
    assert "already assigned" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_ticker_can_belong_to_different_portfolios(client, db_session):
    """The same ticker CAN appear in pools of different portfolios."""
    uid_a = await _create_portfolio(client, f"PP-MultiA-{id(db_session)}")
    uid_b = await _create_portfolio(client, f"PP-MultiB-{id(db_session)}")
    ticker = f"SHARED.{id(db_session)}"
    pool_a = await _create_pool(client, uid_a, "PA")
    pool_b = await _create_pool(client, uid_b, "PB")
    await _create_product(client, ticker)

    r1 = await client.post(f"/api/pools/{pool_a['id']}/products", json={"ticker": ticker})
    assert r1.status_code == 201

    r2 = await client.post(f"/api/pools/{pool_b['id']}/products", json={"ticker": ticker})
    assert r2.status_code == 201


# ---------------------------------------------------------------------------
# Additional coverage: list_pool_products returns items (line 100)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pool_products_returns_added_product(client, db_session):
    """GET /{pool_id}/products returns the products after add (line 99-100)."""
    uid = await _create_portfolio(client, f"PP-List-{id(db_session)}")
    ticker1 = f"AA.P.{id(db_session)}"
    ticker2 = f"BB.P.{id(db_session)}"
    pool = await _create_pool(client, uid)
    await _create_product(client, ticker1)
    await _create_product(client, ticker2)

    await client.post(f"/api/pools/{pool['id']}/products", json={"ticker": ticker1})
    await client.post(f"/api/pools/{pool['id']}/products", json={"ticker": ticker2})

    r = await client.get(f"/api/pools/{pool['id']}/products")
    assert r.status_code == 200
    tickers = [p["ticker"] for p in r.json()]
    assert ticker1 in tickers
    assert ticker2 in tickers


@pytest.mark.asyncio
async def test_update_pool_strategy_and_active(client, db_session):
    """Update strategy and is_active fields (covers more of lines 75-82)."""
    uid = await _create_portfolio(client, f"PoolUpd2-{id(db_session)}")
    pool = await _create_pool(client, uid, "Energy", "Offensive")

    r = await client.put(f"/api/pools/{pool['id']}", json={
        "strategy": "Defensive", "is_active": False
    })
    assert r.status_code == 200
    data = r.json()
    assert data["strategy"] == "Defensive"
    assert data["is_active"] is False


@pytest.mark.asyncio
async def test_create_pool_inactive(client, db_session):
    """Create a pool with is_active=False (line 62 variant)."""
    uid = await _create_portfolio(client, f"PoolInactive-{id(db_session)}")
    r = await client.post("/api/pools/", json={
        "portfolio_id": uid,
        "name": "LegacyPool",
        "strategy": "Defensive",
        "target_pct": 0.10,
        "is_active": False,
    })
    assert r.status_code == 201
    assert r.json()["is_active"] is False
