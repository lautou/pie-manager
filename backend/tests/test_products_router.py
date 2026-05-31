"""
Integration tests for /api/products — full coverage of all four endpoints.

  41-50: list_products (no filter + category filter)
  53-59: create_product (success + all optional fields)
  62-74: update_product (including 404)
  77-85: delete_product (including 404)
  delete_product_blocked: 400 when transactions reference the product

Uses the `client` fixture from conftest.py (test DB injected).
"""

import pytest
from datetime import date as _date
from app.models.transaction import Transaction
from app.models.broker import Broker
from app.models.portfolio import Portfolio
from app.models.portfolio_account import PortfolioAccount
from tests.helpers import create_product


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create(client, ticker: str, category: str = "Actif") -> dict:
    r = await client.post("/api/products/", json={
        "ticker": ticker, "name": f"Name-{ticker}",
        "category": category, "currency": "EUR",
    })
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# list_products with category filter (lines 47-51)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_products_category_filter(client, db_session):
    """GET /api/products?category=X returns only products of that category."""
    suffix = str(id(db_session))
    await _create(client, f"ACT.{suffix}", "Actif")
    await _create(client, f"MAN.{suffix}", "Manuel")
    r = await client.get("/api/products/", params={"category": "Manuel"})
    assert r.status_code == 200
    tickers = [p["ticker"] for p in r.json()]
    assert f"MAN.{suffix}" in tickers
    assert f"ACT.{suffix}" not in tickers


# ---------------------------------------------------------------------------
# update_product (lines 67-75)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_product_name(client, db_session):
    ticker = f"UPD.{id(db_session)}"
    await _create(client, ticker)
    r = await client.put(f"/api/products/{ticker}", json={"name": "Updated Name"})
    assert r.status_code == 200
    assert r.json()["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_update_product_category(client, db_session):
    ticker = f"CATUPD.{id(db_session)}"
    await _create(client, ticker, "Actif")
    r = await client.put(f"/api/products/{ticker}", json={"category": "Manuel"})
    assert r.status_code == 200
    assert r.json()["category"] == "Manuel"


@pytest.mark.asyncio
async def test_update_product_not_found(client):
    r = await client.put("/api/products/MISSING.XX", json={"name": "X"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# delete_product (lines 80-85)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_product(client, db_session):
    ticker = f"DEL.{id(db_session)}"
    await _create(client, ticker)
    r = await client.delete(f"/api/products/{ticker}")
    assert r.status_code == 204
    r_list = await client.get("/api/products/")
    assert not any(p["ticker"] == ticker for p in r_list.json())


@pytest.mark.asyncio
async def test_delete_product_not_found(client):
    r = await client.delete("/api/products/GHOST.XX")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_product_blocked_by_transaction(client, db_session):
    """DELETE /api/products/{ticker} returns 400 when transactions reference the product."""
    suffix = str(id(db_session))
    ticker = f"BLKD.{suffix}"
    await _create(client, ticker, "Actif")

    # Create a minimal portfolio + account + transaction that references this product
    portfolio = Portfolio(name=f"BlockedTest-{suffix}")
    db_session.add(portfolio)
    await db_session.flush()

    account = Broker(name="Test", currency="EUR")
    db_session.add(account)
    await db_session.flush()
    db_session.add(PortfolioAccount(portfolio_id=portfolio.id, broker_id=account.id))
    await db_session.flush()

    tx = Transaction(
        portfolio_id=portfolio.id,
        account_id=account.id,
        date=_date(2025, 1, 1),
        type="Actif",
        ticker=ticker,
        currency="EUR",
        exchange_rate=1.0,
        quantity=-5.0,
        unit_price=100.0,
        unit_price_eur=100.0,
        total_amount=-500.0,
        total_amount_eur=-500.0,
    )
    db_session.add(tx)
    await db_session.flush()

    r = await client.delete(f"/api/products/{ticker}")
    assert r.status_code == 400
    assert "transaction" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# create_product — explicit coverage (lines 53-59)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_product_minimal(client, db_session):
    """POST with ticker, name and category → 201, unspecified isin/notes remain None."""
    ticker = f"MIN.{id(db_session)}"
    r = await client.post("/api/products/", json={
        "ticker": ticker, "name": "Minimal", "category": "Actif",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["ticker"] == ticker
    assert data["name"] == "Minimal"
    assert data["category"] == "Actif"
    assert data["isin"] is None
    assert data["notes"] is None


@pytest.mark.asyncio
async def test_create_product_all_fields(client, db_session):
    """POST with all optional fields populated → 201, all fields returned."""
    ticker = f"FULL.{id(db_session)}"
    payload = {
        "ticker": ticker,
        "name": "Full Product",
        "category": "Actif",
        "currency": "USD",
        "isin": "FR0000000001",
        "notes": "Test note",
    }
    r = await client.post("/api/products/", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["isin"] == "FR0000000001"
    assert data["notes"] == "Test note"
    assert data["currency"] == "USD"


# ---------------------------------------------------------------------------
# list_products — no filter (lines 41-50)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_products_no_filter_returns_all(client, db_session):
    """GET /api/products/ without filter returns all products (includes created ones)."""
    suffix = str(id(db_session))
    ticker_a = f"LST.A.{suffix}"
    ticker_b = f"LST.B.{suffix}"
    await _create(client, ticker_a, "Actif")
    await _create(client, ticker_b, "Manuel")

    r = await client.get("/api/products/")
    assert r.status_code == 200
    tickers = [p["ticker"] for p in r.json()]
    assert ticker_a in tickers
    assert ticker_b in tickers


@pytest.mark.asyncio
async def test_update_product_is_ttf_eligible(client):
    """PUT /api/products/{ticker} can set is_ttf_eligible."""
    await create_product(client, "TTF.TEST", name="TTF Test", category="Actif")

    r = await client.put("/api/products/TTF.TEST", json={"is_ttf_eligible": True})
    assert r.status_code == 200
    assert r.json()["is_ttf_eligible"] is True

    # Reset to False
    r2 = await client.put("/api/products/TTF.TEST", json={"is_ttf_eligible": False})
    assert r2.status_code == 200
    assert r2.json()["is_ttf_eligible"] is False


@pytest.mark.asyncio
async def test_list_products_includes_is_ttf_eligible(client):
    """GET /api/products/ includes is_ttf_eligible field."""
    await create_product(client, "TTF.LIST", name="TTF List", category="Actif")
    r = await client.get("/api/products/")
    assert r.status_code == 200
    found = next((p for p in r.json() if p["ticker"] == "TTF.LIST"), None)
    assert found is not None
    assert "is_ttf_eligible" in found
    assert found["is_ttf_eligible"] is False
